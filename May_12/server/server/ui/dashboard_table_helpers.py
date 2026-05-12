CLIENT_FILTERS = (
    "All",
    "Connected",
    "Disconnected",
    "Running",
    "Paused",
    "Needs Attention",
    "Submitted/Finished",
    "Banned",
)

INCIDENT_FILTERS = (
    "All",
    "Active",
    "Resolved",
    "Violation",
    "Warning",
    "Info",
    "Blocking",
    "Has PID",
)

PROCESS_DATABASE_FILTERS = (
    "All",
    "Unknown",
    "Whitelist",
    "Blacklist",
    "Warning",
    "Active",
    "Resolved",
)

INCIDENT_RULE_FILTERS = PROCESS_DATABASE_FILTERS

CLIENT_COLUMNS = (
    ("login_id", "Login ID"),
    ("status", "Status"),
    ("remaining", "Remaining"),
    ("window_title", "Window Title"),
    ("ip", "IP"),
    ("uuid", "UUID"),
)

PROCESS_COLUMNS = (
    ("process_key", "Process Key"),
    ("executable", "Executable"),
    ("status", "Status"),
    ("path", "Path / Directory"),
    ("scope", "Scope"),
    ("matches", "Matches"),
    ("students", "Affected Students"),
    ("last_seen", "Last Seen"),
    ("actions", "Saved Actions"),
    ("availability", "Action Availability"),
)

INCIDENT_RULE_COLUMNS = (
    ("rule_key", "Rule Key"),
    ("name", "Name"),
    ("status", "Status"),
    ("match", "Match"),
    ("matches", "Matches"),
    ("students", "Affected Students"),
    ("last_seen", "Last Seen"),
    ("actions", "Saved Actions"),
    ("availability", "Action Availability"),
)


def active_filter_names(filter_states: dict[str, bool] | set[str] | list[str] | tuple[str, ...]) -> set[str]:
    if isinstance(filter_states, dict):
        names = {name for name, enabled in filter_states.items() if enabled}
    else:
        names = {str(name) for name in filter_states}
    if not names or "All" in names:
        return set()
    return names


def client_matches_filters(data: dict, filters: set[str]) -> bool:
    active = active_filter_names(filters)
    if not active:
        return True
    return any(_client_matches_filter(data, label) for label in active)


def incident_matches_filters(incident: dict, filters: set[str]) -> bool:
    active = active_filter_names(filters)
    if not active:
        return True
    return any(_incident_matches_filter(incident, label) for label in active)


def process_row_matches_filter(row: dict, filter_name: str) -> bool:
    return _process_matches_filter(row, str(filter_name or "All"))


def incident_rule_row_matches_filter(row: dict, filter_name: str) -> bool:
    return _process_matches_filter(row, str(filter_name or "All"))


def process_row_matches_filters(row: dict, filters: set[str]) -> bool:
    active = active_filter_names(filters)
    if not active:
        return True
    return any(_process_matches_filter(row, label) for label in active)


def incident_rule_row_matches_filters(row: dict, filters: set[str]) -> bool:
    active = active_filter_names(filters)
    if not active:
        return True
    return any(_process_matches_filter(row, label) for label in active)


def sorted_client_items(
    clients: dict[str, dict],
    filters: set[str],
    sort_column: str,
    descending: bool,
) -> list[tuple[str, dict]]:
    items = [
        (client_id, data)
        for client_id, data in clients.items()
        if client_matches_filters(data, filters)
    ]
    return sorted(
        items,
        key=lambda item: (_client_sort_value(item[0], item[1], sort_column), _text(item[1].get("login_id")), item[0]),
        reverse=descending,
    )


def sorted_incidents(
    incidents: list[dict],
    filters: set[str],
    sort_column: str,
    descending: bool,
) -> list[dict]:
    rows = [incident for incident in incidents if incident_matches_filters(incident, filters)]
    return sorted(
        rows,
        key=lambda incident: (_incident_sort_value(incident, sort_column), _text(incident.get("incident_id"))),
        reverse=descending,
    )


def sorted_process_rows(
    rows: list[dict],
    filters: set[str],
    sort_column: str,
    descending: bool,
) -> list[dict]:
    filtered = [row for row in rows if process_row_matches_filters(row, filters)]
    return sorted(
        filtered,
        key=lambda row: (_process_sort_value(row, sort_column), _text(row.get("process_key"))),
        reverse=descending,
    )


def sorted_incident_rule_rows(
    rows: list[dict],
    filters: set[str],
    sort_column: str,
    descending: bool,
) -> list[dict]:
    filtered = [row for row in rows if incident_rule_row_matches_filters(row, filters)]
    return sorted(
        filtered,
        key=lambda row: (_incident_rule_sort_value(row, sort_column), _text(row.get("rule_key"))),
        reverse=descending,
    )


def client_window_title(data: dict) -> str:
    return str(data.get("last_focus_window") or "").strip()


def process_path_display(row: dict) -> str:
    return str(
        row.get("process_path")
        or row.get("process_dir")
        or row.get("normalized_process_path")
        or row.get("normalized_process_dir")
        or "-"
    )


def affected_students_display(row: dict, limit: int = 4) -> str:
    students = [str(student) for student in row.get("affected_students", []) if str(student)]
    text = ", ".join(students[:limit])
    if len(students) > limit:
        text += " ..."
    return text or "-"


def incident_rule_match_display(row: dict) -> str:
    return str(row.get("match_summary") or "-")


def _client_matches_filter(data: dict, label: str) -> bool:
    label = str(label or "").strip().lower()
    connection = str(data.get("connection_status") or "").strip().lower()
    exam_state = str(data.get("exam_state") or "").strip().lower()
    session_state = str(data.get("session_state") or "").strip().lower()
    latest_status = str(data.get("latest_incident_status") or "").strip().lower()
    latest_severity = str(data.get("latest_incident_severity") or "").strip().lower()
    if label == "connected":
        return connection == "connected"
    if label == "disconnected":
        return connection != "connected"
    if label == "running":
        return exam_state == "running" or session_state == "running"
    if label == "paused":
        return bool(data.get("admin_paused")) or "paused" in exam_state or "paused" in session_state
    if label == "needs attention":
        return bool(data.get("blocking_incident_id")) or latest_status in {"opened", "active"} or latest_severity in {"warning", "violation"}
    if label == "submitted/finished":
        return bool(data.get("exam_finished") or data.get("submitted_at")) or exam_state in {"submitted", "finished"}
    if label == "banned":
        return bool(data.get("banned")) or exam_state == "banned"
    return True


def _incident_matches_filter(incident: dict, label: str) -> bool:
    label = str(label or "").strip().lower()
    severity = str(incident.get("severity") or "").strip().lower()
    status = str(incident.get("status") or "").strip().lower()
    if label == "active":
        return bool(incident.get("active"))
    if label == "resolved":
        return status == "resolved" or (bool(incident.get("resolved")) and not bool(incident.get("active")))
    if label in {"violation", "warning", "info"}:
        return severity == label
    if label == "blocking":
        return bool(incident.get("blocking"))
    if label == "has pid":
        return _number(incident.get("pid")) > 0
    return True


def _process_matches_filter(row: dict, label: str) -> bool:
    label = str(label or "All").strip().lower()
    status = str(row.get("status", "") or "").strip().lower()
    if label == "all":
        return True
    if label in {"warning", "warnings"}:
        return status == "warning" or bool(row.get("warning"))
    if label == "active":
        return bool(row.get("active"))
    if label == "resolved":
        return bool(row.get("resolved")) and not bool(row.get("active"))
    return status == label


def _client_sort_value(client_id: str, data: dict, column: str):
    if column == "login_id":
        return _text(data.get("login_id"))
    if column == "status":
        return _text(data.get("status_label"))
    if column == "remaining":
        return _number(data.get("remaining"))
    if column == "window_title":
        return _text(data.get("last_focus_window"))
    if column == "ip":
        return _text(data.get("ip"))
    if column == "uuid":
        return _text(client_id)
    return _text(data.get("login_id"))


def _incident_sort_value(incident: dict, column: str):
    if column == "incident_id":
        return _text(incident.get("incident_id"))
    if column == "time":
        return _text(incident.get("event_at"))
    if column == "user":
        return _text(incident.get("login_id"))
    if column == "severity":
        return _severity_rank(incident.get("severity"))
    if column == "rule":
        return _text(incident.get("rule_name") or incident.get("rule_id"))
    if column == "source":
        return _text(incident.get("source"))
    if column == "process":
        return _text(incident.get("process_name"))
    if column == "pid":
        return _number(incident.get("pid"))
    if column == "auto_action":
        return _text(incident.get("auto_action_state_label") or incident.get("auto_action_state"))
    if column == "status":
        return _text(incident.get("status"))
    return _text(incident.get("event_at"))


def _process_sort_value(row: dict, column: str):
    if column == "process_key":
        return _text(row.get("process_key"))
    if column == "executable":
        return _text(row.get("process_name") or row.get("normalized_process_name"))
    if column == "status":
        return _text(row.get("status"))
    if column == "path":
        return _text(process_path_display(row))
    if column == "scope":
        return _text(row.get("match_scope"))
    if column == "matches":
        return _number(row.get("match_count"))
    if column == "students":
        return _number(row.get("affected_student_count") or len(row.get("affected_students", [])))
    if column == "last_seen":
        return _text(row.get("last_seen"))
    if column == "actions":
        return _text(row.get("saved_action_labels"))
    if column == "availability":
        return _text(row.get("action_availability") or "")
    return _text(row.get("process_name") or row.get("normalized_process_name"))


def _incident_rule_sort_value(row: dict, column: str):
    if column == "rule_key":
        return _text(row.get("rule_key"))
    if column == "name":
        return _text(row.get("name"))
    if column == "status":
        return _text(row.get("status"))
    if column == "match":
        return _text(row.get("match_summary"))
    if column == "matches":
        return _number(row.get("match_count"))
    if column == "students":
        return _number(row.get("affected_student_count") or len(row.get("affected_students", [])))
    if column == "last_seen":
        return _text(row.get("last_seen"))
    if column == "actions":
        return _text(row.get("saved_action_labels"))
    if column == "availability":
        return _text(row.get("action_availability") or "")
    return _text(row.get("name"))


def _text(value) -> str:
    return str(value or "").strip().lower()


def _number(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _severity_rank(value) -> int:
    severity = _text(value)
    order = {"info": 0, "warning": 1, "violation": 2}
    return order.get(severity, 99)
