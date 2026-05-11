"""Shared process-database UI helpers used by Tk and Qt dashboards."""

from __future__ import annotations

import re

from common.process_definitions import build_google_search_url
from common.text_safety import normalize_for_match, sanitize_window_title


_TITLE_SEPARATOR_RE = re.compile(r"\s+(?:-|--|\u2013|\u2014|\||\u00b7|\u2022)\s+")
_BROWSER_SUFFIX_RE = re.compile(
    r"(?:\s*(?:-|--|\u2013|\u2014|\||\u00b7|\u2022)\s*)?"
    r"(?:Microsoft Edge|Google Chrome|Yandex Browser|Mozilla Firefox|Firefox|Brave|Opera|Chromium|Chrome|Yandex)"
    r"\s*$",
    re.IGNORECASE,
)
_PROFILE_SUFFIX_RE = re.compile(
    r"(?:\s*(?:-|--|\u2013|\u2014|\||\u00b7|\u2022)\s*)?(?:Profile|Profil)\s+\d+\s*$",
    re.IGNORECASE,
)


def split_multiline_values(text: str, *, split_commas: bool = False) -> list[str]:
    separators = r"[\n\r,]+" if split_commas else r"[\n\r]+"
    values = []
    seen = set()
    for value in re.split(separators, str(text or "")):
        clean = value.strip()
        if not clean:
            continue
        key = normalize_for_match(clean)
        if key in seen:
            continue
        seen.add(key)
        values.append(clean)
    return values


def _line_text(values) -> str:
    if not isinstance(values, list):
        return ""
    return "\n".join(str(value).strip() for value in values if str(value).strip())


def incident_rule_field_text(row: dict, key: str) -> str:
    return _line_text(row.get(key, []))


def _text_matches(value: str, pattern: str, mode: str) -> bool:
    clean_value = normalize_for_match(value)
    clean_pattern = normalize_for_match(pattern)
    if not clean_value or not clean_pattern:
        return False
    if str(mode or "contains").strip().lower() == "exact":
        return clean_value == clean_pattern
    return clean_pattern in clean_value


def _focused_window_config(settings_snapshot: dict | None) -> dict:
    if not isinstance(settings_snapshot, dict):
        return {}
    exam_policy = settings_snapshot.get("exam_policy", {})
    if isinstance(exam_policy, dict):
        rules = exam_policy.get("rules", {})
        if isinstance(rules, dict) and isinstance(rules.get("focused_window"), dict):
            return rules["focused_window"]
    current_policy = settings_snapshot.get("current_exam_policy", {})
    if isinstance(current_policy, dict):
        for rule in current_policy.get("rules", []):
            if isinstance(rule, dict) and rule.get("rule_id") == "focused_window_policy":
                return rule
    return {}


def _matching_legacy_title_pattern(window_title: str, settings_snapshot: dict | None) -> str:
    focused_window = _focused_window_config(settings_snapshot)
    mode = str(focused_window.get("window_title_match_mode") or "contains").strip().lower()
    for key in ("blocked_window_titles", "allowed_window_titles"):
        values = focused_window.get(key, [])
        if not isinstance(values, list):
            continue
        for value in values:
            pattern = str(value or "").strip()
            if pattern and _text_matches(window_title, pattern, mode):
                return pattern
    return ""


def _strip_browser_suffixes(value: str) -> str:
    clean = str(value or "").strip()
    while clean:
        updated = _BROWSER_SUFFIX_RE.sub("", clean).strip()
        updated = _PROFILE_SUFFIX_RE.sub("", updated).strip()
        if not updated or updated == clean:
            return clean
        clean = updated
    return clean


def suggest_title_patterns(window_title: str, settings_snapshot: dict | None = None) -> list[str]:
    title = sanitize_window_title(window_title)
    if not title:
        return []

    legacy_pattern = _matching_legacy_title_pattern(title, settings_snapshot)
    if legacy_pattern:
        return [legacy_pattern]

    candidate = _strip_browser_suffixes(title)
    parts = [part.strip() for part in _TITLE_SEPARATOR_RE.split(candidate) if part.strip()]
    if len(parts) > 1:
        candidate = parts[0]
    candidate = _strip_browser_suffixes(candidate).strip()
    return [candidate or title]


def incident_rule_observed_window_title(row: dict) -> str:
    title = sanitize_window_title(row.get("observed_window_title") or row.get("window_title"))
    if title:
        return title
    for entry in row.get("matching_history", []):
        if isinstance(entry, dict):
            title = sanitize_window_title(entry.get("window_title"))
            if title:
                return title
    return ""


def incident_rule_row_from_incident(incident: dict, settings_snapshot: dict | None = None) -> dict:
    details = incident.get("details", {})
    if not isinstance(details, dict):
        details = {}
    window_title = sanitize_window_title(incident.get("window_title") or details.get("window_title"))
    title_patterns = suggest_title_patterns(window_title, settings_snapshot)
    process_name = str(incident.get("process_name") or "").strip()
    rule_name = str(incident.get("rule_name") or incident.get("rule_id") or "Incident rule")
    if title_patterns:
        name = f"{rule_name} / title {', '.join(title_patterns[:2])}"
    else:
        name = rule_name
    return {
        "rule_key": "",
        "definition_id": "",
        "name": name,
        "status": "unknown",
        "actions": {},
        "rule_id": str(incident.get("rule_id") or ""),
        "event_type": str(incident.get("event_type") or incident.get("rule_id") or ""),
        "source": str(incident.get("source") or ""),
        "process_names": [] if title_patterns else ([process_name] if process_name else []),
        "browser_process_names": [],
        "window_title_patterns": title_patterns,
        "match_mode": "contains" if title_patterns else "exact",
        "priority": 0,
        "source_incident_id": str(incident.get("incident_id") or ""),
        "observed_window_title": window_title,
        "matching_history": [incident],
        "previous_matching_entries": [],
        "action_states": [],
    }


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
    process_names: list[str] | None = None,
    browser_process_names: list[str] | None = None,
    window_title_patterns: list[str] | None = None,
    match_mode: str | None = None,
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
        "process_names": list(process_names if process_names is not None else row.get("process_names", [])),
        "browser_process_names": list(
            browser_process_names if browser_process_names is not None else row.get("browser_process_names", [])
        ),
        "window_title_patterns": list(
            window_title_patterns if window_title_patterns is not None else row.get("window_title_patterns", [])
        ),
        "match_mode": match_mode or row.get("match_mode", "contains"),
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
