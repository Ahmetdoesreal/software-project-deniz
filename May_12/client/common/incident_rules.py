import hashlib
import os
from copy import deepcopy

from common import protocol
from common.process_definitions import normalize_actions, process_name_matches_any
from common.text_safety import normalize_for_match, sanitize_window_title


INCIDENT_RULES_RULE_ID = "incident_rules"
INCIDENT_RULE_STATUSES = {"unknown", "whitelist", "warning", "blacklist"}
INCIDENT_RULE_MATCH_MODES = {"contains", "exact"}
DEFAULT_BROWSER_PROCESS_NAMES = (
    "chrome.exe",
    "msedge.exe",
    "msedgewebview2.exe",
    "yandex.exe",
    "browser.exe",
)
DEFAULT_NEW_TAB_PATTERNS = (
    "New Tab",
    "Yeni Sekme",
    "Yeni sekme",
)


def _string_list(values) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = normalize_for_match(text)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def _process_name(value: str | None) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    return os.path.basename(clean).lower()


def normalize_status(value: str | None) -> str:
    status = str(value or "unknown").strip().lower()
    if status not in INCIDENT_RULE_STATUSES:
        return "unknown"
    return status


def normalize_match_mode(value: str | None) -> str:
    mode = str(value or "contains").strip().lower()
    if mode not in INCIDENT_RULE_MATCH_MODES:
        return "contains"
    return mode


def stable_incident_rule_key(rule: dict | None) -> str:
    if not isinstance(rule, dict):
        rule = {}
    parts = [
        str(rule.get("rule_id", "") or "").strip(),
        str(rule.get("event_type", "") or "").strip(),
        str(rule.get("source", "") or "").strip(),
        normalize_match_mode(rule.get("match_mode")),
        "|".join(normalize_for_match(value) for value in _string_list(rule.get("process_names", []))),
        "|".join(normalize_for_match(value) for value in _string_list(rule.get("browser_process_names", []))),
        "|".join(normalize_for_match(value) for value in _string_list(rule.get("window_title_patterns", []))),
    ]
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return digest[:24]


def normalize_incident_rule(raw: dict | None, *, now: str | None = None) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    now = now or protocol.now_iso()
    process_names = _string_list(raw.get("process_names", []))
    if not process_names and raw.get("process_name"):
        process_names = _string_list([raw.get("process_name")])
    window_patterns = _string_list(raw.get("window_title_patterns", []))
    if not window_patterns and raw.get("window_title"):
        window_patterns = _string_list([raw.get("window_title")])
    browser_process_names = _string_list(raw.get("browser_process_names", []))
    actions = normalize_actions(raw.get("actions") or raw.get("saved_actions"))
    normalized = {
        "definition_id": str(raw.get("definition_id") or raw.get("id") or "").strip(),
        "rule_key": "",
        "name": str(raw.get("name") or raw.get("rule_name") or "").strip(),
        "status": normalize_status(raw.get("status")),
        "actions": actions,
        "rule_id": str(raw.get("rule_id") or "").strip(),
        "event_type": str(raw.get("event_type") or "").strip(),
        "source": str(raw.get("source") or "").strip(),
        "process_names": process_names,
        "browser_process_names": browser_process_names,
        "window_title_patterns": window_patterns,
        "match_mode": normalize_match_mode(raw.get("match_mode")),
        "priority": int(raw.get("priority", 0) or 0),
        "source_incident_id": str(raw.get("source_incident_id") or "").strip(),
        "matching_history": [
            dict(entry) for entry in raw.get("matching_history", []) if isinstance(entry, dict)
        ] if isinstance(raw.get("matching_history", []), list) else [],
        "previous_matching_entries": [
            dict(entry) for entry in raw.get("previous_matching_entries", []) if isinstance(entry, dict)
        ] if isinstance(raw.get("previous_matching_entries", []), list) else [],
        "created_at": str(raw.get("created_at") or now),
        "updated_at": str(raw.get("updated_at") or now),
        "decided_at": str(raw.get("decided_at") or ""),
        "decided_by": str(raw.get("decided_by") or ""),
        "decision_reason": str(raw.get("decision_reason") or ""),
    }
    normalized["rule_key"] = stable_incident_rule_key(normalized)
    if not normalized["definition_id"]:
        normalized["definition_id"] = normalized["rule_key"]
    if not normalized["name"]:
        normalized["name"] = incident_rule_display_name(normalized)
    return normalized


def normalize_incident_rules(values) -> list[dict]:
    if not isinstance(values, list):
        return []
    normalized = []
    seen = set()
    for value in values:
        rule = normalize_incident_rule(value)
        key = str(rule.get("definition_id") or rule.get("rule_key") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(rule)
    return normalized


def default_incident_rules() -> list[dict]:
    return normalize_incident_rules(
        [
            {
                "name": "Browser New Tab whitelist",
                "status": "whitelist",
                "rule_id": "focused_window_policy",
                "event_type": "focused_window_policy",
                "source": "focused_window",
                "browser_process_names": list(DEFAULT_BROWSER_PROCESS_NAMES),
                "window_title_patterns": list(DEFAULT_NEW_TAB_PATTERNS),
                "match_mode": "contains",
                "priority": 100,
            }
        ]
    )


def _matches_text(value: str, patterns: list[str], mode: str) -> bool:
    clean_value = normalize_for_match(value)
    clean_patterns = [normalize_for_match(pattern) for pattern in patterns if normalize_for_match(pattern)]
    if not clean_patterns:
        return True
    if mode == "exact":
        return clean_value in clean_patterns
    return any(pattern in clean_value for pattern in clean_patterns)


def incident_matches_rule(incident: dict, raw_rule: dict) -> bool:
    rule = normalize_incident_rule(raw_rule)
    configured = False
    for key in ("rule_id", "event_type", "source"):
        expected = str(rule.get(key, "") or "").strip()
        if not expected:
            continue
        configured = True
        if str(incident.get(key, "") or "").strip() != expected:
            return False

    process_names = rule.get("process_names", [])
    if process_names:
        configured = True
        process_name = _process_name(incident.get("process_name"))
        if not process_name_matches_any(process_name, process_names):
            return False

    browser_names = rule.get("browser_process_names", [])
    if browser_names:
        configured = True
        process_name = _process_name(incident.get("process_name"))
        if not process_name_matches_any(process_name, browser_names):
            return False

    window_patterns = rule.get("window_title_patterns", [])
    if window_patterns:
        configured = True
        title = sanitize_window_title(incident.get("window_title"))
        if not _matches_text(title, window_patterns, str(rule.get("match_mode", "contains"))):
            return False

    return configured


def matching_incident_rules(definitions: list[dict], incident: dict) -> list[dict]:
    matches = [
        normalize_incident_rule(rule)
        for rule in normalize_incident_rules(definitions)
        if incident_matches_rule(incident, rule)
    ]
    return sorted(
        matches,
        key=lambda rule: (
            1 if rule.get("status") == "whitelist" else 0,
            int(rule.get("priority", 0) or 0),
            str(rule.get("updated_at", "")),
        ),
        reverse=True,
    )


def best_incident_rule(definitions: list[dict], incident: dict) -> dict | None:
    matches = matching_incident_rules(definitions, incident)
    return matches[0] if matches else None


def apply_incident_rule_to_incident(definitions: list[dict], incident: dict) -> dict | None:
    if str(incident.get("status", "") or "") not in {"opened", "escalated"}:
        return incident
    rule = best_incident_rule(definitions, incident)
    if not rule:
        return incident
    status = str(rule.get("status") or "unknown")
    if status == "whitelist":
        return None
    if status in {"warning", "blacklist"}:
        updated = dict(incident)
        updated["severity"] = "violation" if status == "blacklist" else "warning"
        updated["matched_incident_rule"] = incident_rule_summary(rule)
        updated["matched_incident_rule_id"] = str(rule.get("definition_id", "") or "")
        updated["configured_actions"] = normalize_actions(rule.get("actions", {}))
        return updated
    return incident


def incident_rule_summary(rule: dict) -> dict:
    normalized = normalize_incident_rule(rule)
    return {
        "definition_id": normalized.get("definition_id", ""),
        "rule_key": normalized.get("rule_key", ""),
        "name": normalized.get("name", ""),
        "status": normalized.get("status", "unknown"),
        "actions": normalize_actions(normalized.get("actions", {})),
        "rule_id": normalized.get("rule_id", ""),
        "event_type": normalized.get("event_type", ""),
        "source": normalized.get("source", ""),
        "process_names": list(normalized.get("process_names", [])),
        "browser_process_names": list(normalized.get("browser_process_names", [])),
        "window_title_patterns": list(normalized.get("window_title_patterns", [])),
        "match_mode": normalized.get("match_mode", "contains"),
        "priority": int(normalized.get("priority", 0) or 0),
    }


def incident_rule_display_name(rule: dict) -> str:
    parts = []
    if rule.get("rule_id"):
        parts.append(str(rule.get("rule_id")))
    if rule.get("event_type") and rule.get("event_type") != rule.get("rule_id"):
        parts.append(str(rule.get("event_type")))
    titles = _string_list(rule.get("window_title_patterns", []))
    if titles:
        parts.append("title " + ", ".join(titles[:2]))
    processes = _string_list(rule.get("process_names", [])) or _string_list(rule.get("browser_process_names", []))
    if processes:
        parts.append("process " + ", ".join(processes[:2]))
    return " / ".join(parts) if parts else "Incident rule"


def incident_rule_from_incident(incident: dict, *, status: str = "unknown", actions: dict | None = None) -> dict:
    process_name = str(incident.get("process_name") or "").strip()
    window_title = sanitize_window_title(incident.get("window_title"))
    payload = {
        "name": incident_rule_display_name(incident),
        "status": status,
        "actions": normalize_actions(actions or {}),
        "rule_id": str(incident.get("rule_id") or "").strip(),
        "event_type": str(incident.get("event_type") or incident.get("rule_id") or "").strip(),
        "source": str(incident.get("source") or "").strip(),
        "process_names": [process_name] if process_name else [],
        "window_title_patterns": [window_title] if window_title else [],
        "match_mode": "contains" if window_title else "exact",
        "priority": 0,
        "source_incident_id": str(incident.get("incident_id") or "").strip(),
    }
    return normalize_incident_rule(payload)


def incident_history_entry(incident: dict, *, active: bool = False) -> dict:
    return {
        "incident_id": str(incident.get("incident_id", "") or ""),
        "client_id": str(incident.get("client_id", "") or ""),
        "login_id": str(incident.get("login_id", "") or ""),
        "status": str(incident.get("status", "") or ""),
        "severity": str(incident.get("severity", "") or ""),
        "rule_id": str(incident.get("rule_id", "") or ""),
        "event_type": str(incident.get("event_type", "") or ""),
        "source": str(incident.get("source", "") or ""),
        "event_at": str(
            incident.get("server_received_at")
            or incident.get("reported_at")
            or incident.get("event_at")
            or incident.get("timestamp")
            or ""
        ),
        "pid": int(incident.get("pid", 0) or 0),
        "process_name": str(incident.get("process_name", "") or ""),
        "window_title": sanitize_window_title(incident.get("window_title")),
        "active": bool(active),
        "summary": str(incident.get("summary", "") or ""),
    }


def incident_rule_patch(rule: dict) -> dict:
    return {
        "rules": {
            INCIDENT_RULES_RULE_ID: {
                "definitions": [deepcopy(normalize_incident_rule(rule))],
            }
        }
    }
