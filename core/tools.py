"""The four tools exposed to Claude, plus their JSON schemas and a dispatcher.

The very same implementations back both demo paths. Only the schema differs:
 * traditional path  -> plain tools (Claude calls them directly, one model round trip each)
 * programmatic path -> tools carry ``allowed_callers`` so they can be awaited from the
                        code-execution sandbox as async Python functions.
"""
from __future__ import annotations

import json

from . import backends
from .config import Config, RunOptions

TOOL_DESCRIPTIONS = {
    "get_patient_grievance_mappings": (
        "Reads the local JSON document and returns the grievances raised by a patient. "
        "Returns a JSON object: {\"Patient_Name\": str, \"Grievances\": [{\"Grievance_ID\": str (Jira issue id), "
                "\"Grievance_Key\": str, \"Claim_ID\": str (GUID of the claim in the claims database)}]}."
    ),
    "get_jira_grievance_status": (
        "Looks up ONE grievance (Jira ticket) by its Jira issue id. Call it once per grievance. "
        "Returns a JSON object: {\"id\": str, \"key\": str (e.g. DEMO-16), \"summary\": str, \"description\": str, "
        "\"status\": str, \"assigned\": bool, \"assignee\": str|null (null when unassigned), "
        "\"created\": str (ISO-8601 timestamp)}, or {\"error\": str} when not found."
    ),
    "get_patient_claims": (
        "Queries the claims database and returns ALL claims of a patient as a JSON object: "
        "{\"claims\": [{\"Claim_ID\": str (GUID), \"Provider_ID\": str, \"Date_of_Service\": str, \"Date_Submitted\": str, "
        "\"Service_Type\": str, \"Claim_Amount\": number, \"Paid_Amount\": number, "
        "\"Claim_Status\": str (Paid | Pending | Denied), \"Reason_for_Denial\": str|null, \"Patient_Name\": str}]}."
    ),
    "escalate_unassigned_grievance": (
        "Sends an e-mail (via WorkIQ) to the claims escalation contact asking a person to intervene on a grievance that "
        "is still unassigned. "
        "Returns a JSON object: {\"sent\": bool, \"mode\": str, \"to\": str, \"subject\": str}."
    ),
}

_SCHEMAS = {
    "get_patient_grievance_mappings": {
        "type": "object",
        "properties": {"patient_name": {"type": "string", "description": "Patient name, e.g. Srikantan"}},
        "required": ["patient_name"],
    },
    "get_jira_grievance_status": {
        "type": "object",
        "properties": {"grievance_id": {"type": "string", "description": "Jira issue id from Grievance_ID"}},
        "required": ["grievance_id"],
    },
    "get_patient_claims": {
        "type": "object",
        "properties": {"patient_name": {"type": "string", "description": "Patient name, e.g. Srikantan"}},
        "required": ["patient_name"],
    },
    "escalate_unassigned_grievance": {
        "type": "object",
        "properties": {
            "grievance_key": {"type": "string", "description": "Jira key, e.g. DEMO-16"},
            "grievance_summary": {"type": "string"},
            "grievance_created": {"type": "string", "description": "Created timestamp from Jira"},
            "patient_name": {"type": "string"},
            "claim_id": {"type": "string", "description": "Claim ID (GUID) the grievance relates to"},
            "claim_details": {"type": "string", "description": "Short text: service type, amount, denial reason"},
        },
        "required": ["grievance_key", "grievance_summary", "grievance_created", "patient_name", "claim_id"],
    },
}


def _jira_description(jira_payload: str) -> str:
    if jira_payload == "raw":
        return (
            "Looks up ONE grievance (Jira ticket) by its Jira issue id. Call it once per grievance. "
            "Returns the raw Jira Cloud REST v3 issue JSON: {\"id\": str, \"key\": str (e.g. DEMO-16), \"fields\": "
            "{\"summary\": str, \"status\": {\"name\": str}, \"assignee\": {\"displayName\": str}|null (null = unassigned), "
            "\"created\": str (ISO-8601), \"description\": Atlassian Document Format, ...many other Jira fields}}, "
            "or {\"error\": str} when not found."
        )
    return TOOL_DESCRIPTIONS["get_jira_grievance_status"]


def tool_definitions(programmatic: bool, options: RunOptions) -> list[dict]:
    defs = []
    for name, schema in _SCHEMAS.items():
        description = (
            _jira_description(options.jira_payload) if name == "get_jira_grievance_status" else TOOL_DESCRIPTIONS[name]
        )
        d = {"name": name, "description": description, "input_schema": schema}
        if programmatic:
            d["allowed_callers"] = [Config.code_execution_tool_version]
        defs.append(d)
    return defs


# ------------------------------------------------------------------ implementations


def _grievance_status(grievance_id: str, options: RunOptions) -> dict:
    if options.jira_payload == "raw":
        # The unfiltered Jira REST response, as a real integration would return it.
        raw = backends._jira_get(f"/rest/api/3/issue/{grievance_id}")
        if not raw or raw["fields"]["project"]["key"] != Config.grievance_project_key:
            return {"error": f"No grievance found with id {grievance_id}"}
        return raw
    issue = backends.get_jira_issue(str(grievance_id))
    if not issue or issue["project"] != Config.grievance_project_key:
        return {"error": f"No grievance found with id {grievance_id}"}
    return {
        "id": issue["id"],
        "key": issue["key"],
        "summary": issue["summary"],
        "description": issue["description"],
        "status": issue["status"],
        "assigned": issue["assignee"] is not None,
        "assignee": issue["assignee"],
        "created": issue["created"],
    }


def _escalate(a: dict, options: RunOptions) -> dict:
    subject = f"[Action needed] Unassigned grievance {a['grievance_key']} - claim {a['claim_id']}"
    body = (
        f"Hello,\n\n"
        f"A grievance raised by patient {a['patient_name']} is still UNASSIGNED and needs a person to intervene.\n\n"
        f"  Grievance key : {a['grievance_key']}\n"
        f"  Summary       : {a['grievance_summary']}\n"
        f"  Created       : {a['grievance_created']}\n"
        f"  Status        : Open - unassigned\n"
        f"  Patient       : {a['patient_name']}\n"
        f"  Claim ID      : {a['claim_id']}\n"
        f"  Claim details : {a.get('claim_details', 'n/a')}\n\n"
        f"Please assign an owner and follow up with the patient at the earliest.\n\n"
        f"Thank you,\nContoso Insurance Claims Assistant"
    )
    return backends.send_mail_via_workiq(Config.escalation_email, subject, body, options.email_mode)


def execute_tool(name: str, args: dict, options: RunOptions) -> str:
    """Runs a tool and returns the text that is handed back to Claude."""
    # The patient is always the signed-in user - the model cannot ask for somebody else's data.
    try:
        if name == "get_patient_grievance_mappings":
            result = backends.read_patient_grievances(Config.patient_name)
        elif name == "get_jira_grievance_status":
            result = _grievance_status(args["grievance_id"], options)
        elif name == "get_patient_claims":
            result = {"claims": backends.query_claims(Config.patient_name)}
        elif name == "escalate_unassigned_grievance":
            result = _escalate({**args, "patient_name": Config.patient_name}, options)
        else:
            result = {"error": f"Unknown tool {name}"}
    except Exception as exc:  # surfaced to the model so it can explain the failure
        result = {"error": f"{type(exc).__name__}: {exc}"}
    return json.dumps(result, default=str)
