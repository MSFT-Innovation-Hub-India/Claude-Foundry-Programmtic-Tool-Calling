"""Back-end integrations: local JSON, Jira, Azure SQL (Entra ID) and WorkIQ e-mail."""
from __future__ import annotations

import json
import shutil
import struct
import subprocess
import time
from contextlib import closing
from pathlib import Path

import pyodbc
import requests
from azure.identity import DefaultAzureCredential

from .config import Config

# ----------------------------------------------------------------------------------------------
# 1) Local JSON (patient -> grievance ids -> claim ids)
# ----------------------------------------------------------------------------------------------


def read_patient_grievances(patient_name: str) -> dict:
    records = json.loads(Config.data_file.read_text(encoding="utf-8"))["patients"]
    for rec in records:
        if rec["Patient_Name"].lower() == patient_name.lower():
            return rec
    return {"Patient_Name": patient_name, "Grievances": []}


# ----------------------------------------------------------------------------------------------
# 2) Jira
# ----------------------------------------------------------------------------------------------


def _jira_get(path: str, **params) -> dict:
    resp = requests.get(
        f"{Config.atlassian_url}{path}",
        params=params,
        auth=(Config.atlassian_user_name, Config.atlassian_api_key),
        headers={"Accept": "application/json"},
        timeout=30,
    )
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()
    return resp.json()


def _adf_to_text(node) -> str:
    """Jira Cloud returns rich text as Atlassian Document Format."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_to_text(n) for n in node)
    if node.get("type") == "text":
        return node.get("text", "")
    text = _adf_to_text(node.get("content"))
    return text + "\n" if node.get("type") in ("paragraph", "heading", "listItem") else text


def get_jira_issue(issue_id_or_key: str) -> dict:
    """Returns a compact view of a Jira issue, or {} when it does not exist."""
    data = _jira_get(
        f"/rest/api/3/issue/{issue_id_or_key}",
        fields="summary,status,assignee,created,description,project",
    )
    if not data:
        return {}
    f = data["fields"]
    assignee = f.get("assignee")
    return {
        "id": data["id"],
        "key": data["key"],
        "project": f["project"]["key"],
        "summary": f.get("summary"),
        "description": _adf_to_text(f.get("description")).strip(),
        "status": f["status"]["name"],
        "assignee": assignee["displayName"] if assignee else None,
        "created": f["created"],
    }


# ----------------------------------------------------------------------------------------------
# 3) Azure SQL with the signed-in Entra identity (az login)
# ----------------------------------------------------------------------------------------------

_SQL_COPT_SS_ACCESS_TOKEN = 1256
_credential = DefaultAzureCredential()


def _sql_connection() -> pyodbc.Connection:
    conn_str = (
        f"Driver={{{Config.az_db_driver}}};Server=tcp:{Config.az_db_server},1433;"
        f"Database={Config.az_db_database};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )
    last = None
    for attempt in range(3):
        token = _credential.get_token("https://database.windows.net/.default").token.encode("utf-16-le")
        token_struct = struct.pack(f"<I{len(token)}s", len(token), token)
        try:
            return pyodbc.connect(conn_str, attrs_before={_SQL_COPT_SS_ACCESS_TOKEN: token_struct}, timeout=30)
        except pyodbc.Error as exc:  # serverless databases can need a few seconds to resume
            last = exc
            time.sleep(2 ** (attempt + 1))
    raise last


def query_claims(patient_name: str) -> list[dict]:
    sql = """
        SELECT Claim_ID, Provider_ID, Date_of_Service, Date_Submitted, Service_Type,
               Claim_Amount, Paid_Amount, Claim_Status, Reason_for_Denial, Patient_Name
        FROM dbo.Health_Insurance_Claims
        WHERE Patient_Name = ?
        ORDER BY Date_Submitted
    """
    with closing(_sql_connection()) as conn:
        cur = conn.cursor()
        cur.execute(sql, patient_name)
        cols = [c[0] for c in cur.description]
        rows = []
        for r in cur.fetchall():
            rows.append({c: (str(v) if v is not None and not isinstance(v, (int, float)) else v) for c, v in zip(cols, r)})
        return rows


# ----------------------------------------------------------------------------------------------
# 4) E-mail through WorkIQ (uses the CLI's signed-in account)
# ----------------------------------------------------------------------------------------------


def _workiq_command() -> list[str]:
    exe = shutil.which("workiq")
    if not exe:
        raise RuntimeError("The WorkIQ CLI ('workiq') was not found on PATH.")
    # Launch node directly so the JSON body is passed without cmd.exe quote mangling.
    js = Path(exe).parent / "node_modules" / "@microsoft" / "workiq" / "bin" / "workiq.js"
    node = shutil.which("node")
    if js.exists() and node:
        return [node, str(js)]
    return [exe]


def send_mail_via_workiq(to: str, subject: str, body: str, mode: str = "send") -> dict:
    if mode != "send":
        return {"sent": True, "mode": "dry_run", "to": to, "subject": subject,
                "note": "Demo dry run: the e-mail was recorded but not delivered. Do not retry."}

    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        "saveToSentItems": True,
    }
    proc = subprocess.run(
        [*_workiq_command(), "do-action", "-u", "/me/sendMail", "-b", json.dumps(payload)],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"workiq sendMail failed: {(proc.stderr or proc.stdout).strip()[:500]}")
    return {"sent": True, "mode": "send", "to": to, "subject": subject}
