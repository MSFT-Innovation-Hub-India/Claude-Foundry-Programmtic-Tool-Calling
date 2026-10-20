"""Builds data/patient_grievances.json by resolving the Jira issue ids (the 'unique ID') for the demo tickets
and validating the claim ids against the Azure SQL claims table.

Run:  python -m scripts.build_mapping
"""
import json

from core import backends
from core.config import Config

# Jira key -> (service type of the denied claim it is about)
TICKET_TO_DENIED_CLAIM_SERVICE = {
    "DEMO-17": "Consultation",  # already assigned to a person
    "DEMO-16": "Dental Care",   # still unassigned
}


def main() -> None:
    claims = backends.query_claims(Config.patient_name)
    denied = {c["Service_Type"]: c for c in claims if c["Claim_Status"] == "Denied"}

    grievances = []
    for key, service in TICKET_TO_DENIED_CLAIM_SERVICE.items():
        issue = backends.get_jira_issue(key)
        grievances.append({
            "Grievance_ID": issue["id"],
            "Grievance_Key": issue["key"],
            "Claim_ID": denied[service]["Claim_ID"],
        })

    doc = {
        "_comment": "Dummy demo data. Grievance_ID is the Jira issue id; Claim_ID is from dbo.Health_Insurance_Claims.",
        "patients": [{"Patient_Name": Config.patient_name, "Grievances": grievances}],
    }
    Config.data_file.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(json.dumps(doc, indent=2))


if __name__ == "__main__":
    main()
