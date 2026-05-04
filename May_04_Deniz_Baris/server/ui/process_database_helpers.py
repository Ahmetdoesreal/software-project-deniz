"""Shared process-database UI helpers used by Tk and Qt dashboards."""

from common.process_definitions import build_google_search_url


def build_process_decision_payload(
    row: dict,
    *,
    status: str,
    match_scope: str,
    actions: dict,
    save_policy: bool,
) -> dict:
    return {
        "cmd": "apply_process_decision",
        "definition": {
            "definition_id": row.get("definition_id", ""),
            "process_key": row.get("process_key", ""),
            "process_name": row.get("process_name", ""),
            "normalized_process_name": row.get("normalized_process_name", ""),
            "process_path": row.get("process_path", ""),
            "normalized_process_path": row.get("normalized_process_path", ""),
            "process_dir": row.get("process_dir", ""),
            "normalized_process_dir": row.get("normalized_process_dir", ""),
            "match_scope": match_scope,
            "status": status,
            "actions": {
                "ban": bool(actions.get("ban", False)),
                "kick": bool(actions.get("kick", False)),
                "pause_exam": bool(actions.get("pause_exam", False)),
                "kill_pid": bool(actions.get("kill_pid", False)),
            },
            "source_incident_id": row.get("source_incident_id", ""),
            "matching_history": list(row.get("matching_history", [])),
            "previous_matching_entries": list(row.get("previous_matching_entries", [])),
        },
        "status": status,
        "match_scope": match_scope,
        "actions": {
            "ban": bool(actions.get("ban", False)),
            "kick": bool(actions.get("kick", False)),
            "pause_exam": bool(actions.get("pause_exam", False)),
            "kill_pid": bool(actions.get("kill_pid", False)),
        },
        "save_policy": bool(save_policy),
    }


def process_row_google_search_url(row: dict) -> str:
    return build_google_search_url(row.get("process_name", ""), row.get("process_path", ""))
