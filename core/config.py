"""Central configuration, loaded from .env (see .env.example).

``Config`` holds process-wide settings and the *defaults* of the per-run switches. The switches themselves travel in a
``RunOptions`` object that is passed explicitly into every run, so two runs never share mutable global state.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _flag(name: str, default: bool) -> bool:
    return _get(name, "on" if default else "off").strip().lower() in ("1", "true", "on", "yes")


class Config:
    patient_name = _get("PATIENT_NAME", "Srikantan")
    escalation_email = _get("ESCALATION_EMAIL", "kishorep@onemtc.net")

    foundry_resource = _get("FOUNDRY_RESOURCE", "sansri-claude-model-pro-resource")
    code_execution_tool_version = _get("CODE_EXECUTION_TOOL_VERSION", "code_execution_20260120")

    # ---- defaults of the per-run switches (changeable in the UI)
    default_deployment = _get("CLAUDE_DEPLOYMENT", "claude-haiku-5-5")
    default_email_mode = _get("EMAIL_MODE", "send")            # send | dry_run
    default_jira_payload = _get("JIRA_PAYLOAD", "raw")         # raw | compact
    default_prompt_caching = _flag("PROMPT_CACHING", True)
    default_cold_cache = _flag("COLD_CACHE_PER_RUN", False)

    # ---- price model used for the "cost index" (relative to 1 uncached input token). Assumptions, not a bill.
    cache_read_multiplier = float(_get("CACHE_READ_MULTIPLIER", "0.1"))
    cache_write_multiplier = float(_get("CACHE_WRITE_MULTIPLIER", "1.25"))   # 5-minute cache
    output_multiplier = float(_get("OUTPUT_PRICE_MULTIPLIER", "5"))

    atlassian_api_key = _get("ATLASSIAN_API_KEY")
    atlassian_user_name = _get("ATLASSIAN_USER_NAME")
    atlassian_url = _get("ATLASSIAN_URL").rstrip("/")
    grievance_project_key = _get("GRIEVANCE_PROJECT_KEY", "DEMO")
    grievance_type = _get("GRIEVANCE_TYPE", "Task")
    grievance_project_name = _get("GRIEVANCE_PROJECT_NAME", "Demo service space")

    az_db_server = _get("AZ_DB_SERVER", "az-sqldb-common.database.windows.net")
    az_db_database = _get("AZ_DB_DATABASE", "cdcsampledb")
    az_db_driver = _get("AZ_DB_DRIVER", "ODBC Driver 18 for SQL Server")

    data_file = ROOT / "data" / "patient_grievances.json"
    history_file = ROOT / "runs" / "history.jsonl"


@dataclass(frozen=True)
class RunOptions:
    """Everything that can differ between two runs of the demo."""

    deployment: str = Config.default_deployment
    jira_payload: str = Config.default_jira_payload      # raw | compact
    prompt_caching: bool = Config.default_prompt_caching
    cold_cache: bool = Config.default_cold_cache         # unique prefix per run, so no cache is inherited from an earlier run
    email_mode: str = Config.default_email_mode          # send | dry_run

    @property
    def label(self) -> str:
        """Short configuration label used to group runs in the history view."""
        return "Raw Jira payload" if self.jira_payload == "raw" else "Trimmed Jira payload"
