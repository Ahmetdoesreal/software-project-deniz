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


def build_incident_rule_decision_payload(
    row: dict,
    *,
    status: str,
    actions: dict,
    save_policy: bool,
    priority: int | None = None,
) -> dict:
    definition = {
        "definition_id": row.get("definition_id", ""),
        "rule_key": row.get("rule_key", ""),
        "name": row.get("name", ""),
        "status": status,
        "actions": {
            "ban": bool(actions.get("ban", False)),
            "kick": bool(actions.get("kick", False)),
            "pause_exam": bool(actions.get("pause_exam", False)),
            "kill_pid": bool(actions.get("kill_pid", False)),
        },
        "rule_id": row.get("rule_id", ""),
        "event_type": row.get("event_type", ""),
        "source": row.get("source", ""),
        "process_names": list(row.get("process_names", [])),
        "browser_process_names": list(row.get("browser_process_names", [])),
        "window_title_patterns": list(row.get("window_title_patterns", [])),
        "match_mode": row.get("match_mode", "contains"),
        "priority": int(priority if priority is not None else row.get("priority", 0) or 0),
        "source_incident_id": row.get("source_incident_id", ""),
        "matching_history": list(row.get("matching_history", [])),
        "previous_matching_entries": list(row.get("previous_matching_entries", [])),
    }
    return {
        "cmd": "apply_incident_rule_decision",
        "definition": definition,
        "status": status,
        "actions": definition["actions"],
        "priority": definition["priority"],
        "save_policy": bool(save_policy),
    }
