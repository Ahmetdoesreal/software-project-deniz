import copy
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common import protocol
from common.process_definitions import (
    PROCESS_DEFINITION_ACTIONS,
    PROCESS_INCIDENT_RULE_IDS,
    build_google_search_url,
    definition_from_incident,
    find_matching_definitions,
    incident_matches_definition,
    normalize_actions,
    normalize_definition,
    normalize_definitions,
    process_incident_identity,
    stable_process_key,
)
from common.incident_rules import (
    INCIDENT_RULES_RULE_ID,
    incident_history_entry,
    incident_matches_rule,
    incident_rule_from_incident,
    normalize_incident_rule,
    normalize_incident_rules,
)

from . import session_state


LIST_ACTIONS = {"add", "remove", "replace"}


@dataclass
class SettingsResult:
    ok: bool
    changed: bool = False
    message: str = ""
    settings: dict = field(default_factory=dict)
    changed_paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def get_settings_snapshot(state, app=None) -> dict:
    policy = state.current_exam_policy()
    snapshot = {
        "exam_policy": copy.deepcopy(state._policy_without_process_definitions()),
        "current_exam_policy": policy,
        "policy_version": policy.get("policy_version", ""),
        "process_blacklist": list(state.process_blacklist),
        "process_blacklist_version": state.process_blacklist_version,
        "process_definitions_version": state.process_definitions_version,
        "incident_rules": list(state.rule_config(INCIDENT_RULES_RULE_ID).get("definitions", [])),
        "incident_rules_version": state.incident_rules_version,
        "operator_defaults": state.operator_defaults(),
        "session": state.session_policy(),
    }
    if app is not None:
        snapshot["runtime"] = {
            "exam_duration": app.get("exam_duration"),
            "exam_files": app.get("exam_files"),
        }
    return snapshot


def update_exam_policy(state, patch: dict, *, actor="admin", _audit_action="update_exam_policy") -> SettingsResult:
    if not isinstance(patch, dict):
        return _error_result("Exam policy patch must be an object.", state)

    before_config = copy.deepcopy(state.exam_policy_config)
    before_version = state.current_exam_policy().get("policy_version", "")
    merged = _deep_merge(copy.deepcopy(before_config), patch)
    normalized = state._normalize_exam_policy_config(merged)
    merged_rules = merged.get("rules", {}) if isinstance(merged.get("rules"), dict) else {}
    merged_process_definitions = (
        merged_rules.get("process_definitions", {})
        if isinstance(merged_rules.get("process_definitions"), dict)
        else {}
    )
    merged_incident_rules = (
        merged_rules.get(INCIDENT_RULES_RULE_ID, {})
        if isinstance(merged_rules.get(INCIDENT_RULES_RULE_ID), dict)
        else {}
    )
    has_definition_payload = "definitions" in merged_process_definitions
    has_incident_rule_payload = "definitions" in merged_incident_rules
    next_definitions = process_definitions(state)
    next_incident_rules = incident_rules(state)
    definitions_changed = False
    incident_rules_changed = False
    if has_definition_payload:
        before_definitions = process_definitions(state)
        next_definitions = normalize_definitions(merged_process_definitions.get("definitions", []))
        definitions_changed = before_definitions != next_definitions
        normalized_rules = normalized.get("rules", {}) if isinstance(normalized.get("rules"), dict) else {}
        normalized_process_definitions = (
            normalized_rules.get("process_definitions", {})
            if isinstance(normalized_rules.get("process_definitions"), dict)
            else {}
        )
        normalized_process_definitions.pop("definitions", None)
    if has_incident_rule_payload:
        before_incident_rules = incident_rules(state)
        next_incident_rules = normalize_incident_rules(merged_incident_rules.get("definitions", []))
        incident_rules_changed = before_incident_rules != next_incident_rules
        normalized_rules = normalized.get("rules", {}) if isinstance(normalized.get("rules"), dict) else {}
        normalized_incident_rules = (
            normalized_rules.get(INCIDENT_RULES_RULE_ID, {})
            if isinstance(normalized_rules.get(INCIDENT_RULES_RULE_ID), dict)
            else {}
        )
        normalized_incident_rules.pop("definitions", None)

    changed_paths = _changed_paths(before_config, normalized)
    if definitions_changed and "process_definitions" not in changed_paths:
        changed_paths.append("process_definitions")
    if incident_rules_changed and INCIDENT_RULES_RULE_ID not in changed_paths:
        changed_paths.append(INCIDENT_RULES_RULE_ID)

    if not changed_paths:
        return SettingsResult(
            ok=True,
            changed=False,
            message="No exam policy changes.",
            settings=get_settings_snapshot(state),
            changed_paths=[],
            errors=[],
        )

    state.exam_policy_config = normalized
    if has_definition_payload:
        state.process_definitions = next_definitions
        state.save_process_definitions()
    if has_incident_rule_payload:
        state.incident_rules = next_incident_rules
        state.save_incident_rules()
    state.save_exam_policy()
    after_version = state.current_exam_policy().get("policy_version", "")
    _append_audit(
        state,
        actor=actor,
        action=_audit_action,
        changed_paths=changed_paths,
        before={"policy_version": before_version},
        after={"policy_version": after_version},
    )
    return SettingsResult(
        ok=True,
        changed=True,
        message="Exam policy updated.",
        settings=get_settings_snapshot(state),
        changed_paths=changed_paths,
        errors=[],
    )


def update_process_blacklist(state, action: str, entries: list[str], *, actor="admin") -> SettingsResult:
    action = str(action or "").strip().lower()
    if action not in LIST_ACTIONS:
        return _error_result(f"Unsupported process blacklist action: {action}", state)
    if not isinstance(entries, list):
        return _error_result("Process blacklist entries must be a list.", state)

    before_entries = list(state.process_blacklist)
    before_version = state.process_blacklist_version
    incoming = _dedupe_strings(entries)

    if action == "replace":
        next_entries = incoming
    elif action == "add":
        next_entries = _dedupe_strings(before_entries + incoming)
    else:
        remove_keys = {_key(entry) for entry in incoming}
        next_entries = [entry for entry in before_entries if _key(entry) not in remove_keys]

    if [_key(entry) for entry in next_entries] == [_key(entry) for entry in before_entries]:
        return SettingsResult(
            ok=True,
            changed=False,
            message="No process blacklist changes.",
            settings=get_settings_snapshot(state),
            changed_paths=[],
            errors=[],
        )

    state.process_blacklist = next_entries
    state.save_process_blacklist()
    _append_audit(
        state,
        actor=actor,
        action=f"process_blacklist_{action}",
        changed_paths=["process_blacklist"],
        before={"process_blacklist_version": before_version, "entries": before_entries},
        after={"process_blacklist_version": state.process_blacklist_version, "entries": next_entries},
    )
    return SettingsResult(
        ok=True,
        changed=True,
        message="Process blacklist updated.",
        settings=get_settings_snapshot(state),
        changed_paths=["process_blacklist"],
        errors=[],
    )


def update_known_processes(state, action: str, process_names: list[str], *, actor="admin") -> SettingsResult:
    return _update_policy_list(
        state,
        action,
        process_names,
        path=("rules", "unexpected_process", "known_process_names"),
        changed_path="rules.unexpected_process.known_process_names",
        normalizer=_normalize_process_name,
        actor=actor,
        action_name="known_processes",
    )


def update_known_directories(state, action: str, directory_paths: list[str], *, actor="admin") -> SettingsResult:
    return _update_policy_list(
        state,
        action,
        directory_paths,
        path=("rules", "unexpected_process", "known_directory_paths"),
        changed_path="rules.unexpected_process.known_directory_paths",
        normalizer=_normalize_directory_path,
        actor=actor,
        action_name="known_directories",
    )


def update_focused_window_rules(state, patch: dict, *, actor="admin") -> SettingsResult:
    if not isinstance(patch, dict):
        return _error_result("Focused-window rule patch must be an object.", state)
    return update_exam_policy(
        state,
        {"rules": {"focused_window": patch}},
        actor=actor,
        _audit_action="update_focused_window_rules",
    )


def apply_incident_policy_action(state, incident: dict, action: str, *, actor="admin") -> SettingsResult:
    if not isinstance(incident, dict):
        return _error_result("Incident must be an object.", state)

    action = str(action or "").strip().lower()
    process_name = _incident_process_name(incident)
    if action == "mark_known_process":
        if not process_name:
            return _error_result("Incident does not include a process name.", state)
        return update_known_processes(state, "add", [process_name], actor=actor)

    if action == "mark_known_directory":
        directory = _incident_process_directory(incident)
        if not directory:
            return _error_result("Incident does not include a process path or directory.", state)
        return update_known_directories(state, "add", [directory], actor=actor)

    if action == "add_process_blacklist":
        if not process_name:
            return _error_result("Incident does not include a process name.", state)
        return update_process_blacklist(state, "add", [process_name], actor=actor)

    return _error_result(f"Unsupported incident policy action: {action}", state)


def process_definitions(state) -> list[dict]:
    return normalize_definitions(state.rule_config("process_definitions").get("definitions", []))


def incident_rules(state) -> list[dict]:
    return normalize_incident_rules(state.rule_config(INCIDENT_RULES_RULE_ID).get("definitions", []))


def update_process_definitions(
    state,
    definitions: list[dict],
    *,
    actor="admin",
    _audit_action="update_process_definitions",
) -> SettingsResult:
    if not isinstance(definitions, list):
        return _error_result("Process definitions must be a JSON list.", state)

    before_entries = process_definitions(state)
    before_version = state.process_definitions_version
    before_policy_version = state.current_exam_policy().get("policy_version", "")
    next_entries = normalize_definitions(definitions)

    if before_entries == next_entries:
        return SettingsResult(
            ok=True,
            changed=False,
            message="No process definition changes.",
            settings=get_settings_snapshot(state),
            changed_paths=[],
            errors=[],
        )

    state.process_definitions = next_entries
    state.save_process_definitions()
    _append_audit(
        state,
        actor=actor,
        action=_audit_action,
        changed_paths=["process_definitions"],
        before={
            "process_definitions_version": before_version,
            "policy_version": before_policy_version,
        },
        after={
            "process_definitions_version": state.process_definitions_version,
            "policy_version": state.current_exam_policy().get("policy_version", ""),
        },
    )
    return SettingsResult(
        ok=True,
        changed=True,
        message="Process definitions updated.",
        settings=get_settings_snapshot(state),
        changed_paths=["process_definitions"],
        errors=[],
    )


def upsert_process_definition(state, definition: dict, *, actor="admin") -> SettingsResult:
    normalized = normalize_definition(definition)
    if not normalized.get("normalized_process_name"):
        return _error_result("Process definition requires an executable name.", state)

    current = process_definitions(state)
    updated: list[dict] = []
    replaced = False
    for existing in current:
        same_id = existing.get("definition_id") == normalized.get("definition_id")
        same_key = existing.get("process_key") == normalized.get("process_key")
        if same_id or same_key:
            merged = {
                **existing,
                **normalized,
                "created_at": existing.get("created_at") or normalized.get("created_at"),
            }
            updated.append(normalize_definition(merged))
            replaced = True
        else:
            updated.append(existing)
    if not replaced:
        updated.append(normalized)

    return update_process_definitions(
        state,
        updated,
        actor=actor,
        _audit_action="upsert_process_definition",
    )


def update_incident_rules(
    state,
    definitions: list[dict],
    *,
    actor="admin",
    _audit_action="update_incident_rules",
) -> SettingsResult:
    if not isinstance(definitions, list):
        return _error_result("Incident rules must be a JSON list.", state)

    before_entries = incident_rules(state)
    before_version = state.incident_rules_version
    before_policy_version = state.current_exam_policy().get("policy_version", "")
    next_entries = normalize_incident_rules(definitions)

    if before_entries == next_entries:
        return SettingsResult(
            ok=True,
            changed=False,
            message="No incident rule changes.",
            settings=get_settings_snapshot(state),
            changed_paths=[],
            errors=[],
        )

    state.incident_rules = next_entries
    state.save_incident_rules()
    _append_audit(
        state,
        actor=actor,
        action=_audit_action,
        changed_paths=[INCIDENT_RULES_RULE_ID],
        before={
            "incident_rules_version": before_version,
            "policy_version": before_policy_version,
        },
        after={
            "incident_rules_version": state.incident_rules_version,
            "policy_version": state.current_exam_policy().get("policy_version", ""),
        },
    )
    return SettingsResult(
        ok=True,
        changed=True,
        message="Incident rules updated.",
        settings=get_settings_snapshot(state),
        changed_paths=[INCIDENT_RULES_RULE_ID],
        errors=[],
    )


def upsert_incident_rule(state, definition: dict, *, actor="admin") -> SettingsResult:
    normalized = normalize_incident_rule(definition)
    if not any(
        normalized.get(key)
        for key in ("rule_id", "event_type", "source", "process_names", "browser_process_names", "window_title_patterns")
    ):
        return _error_result("Incident rule requires at least one match field.", state)

    current = incident_rules(state)
    updated: list[dict] = []
    replaced = False
    for existing in current:
        same_id = existing.get("definition_id") == normalized.get("definition_id")
        same_key = existing.get("rule_key") == normalized.get("rule_key")
        if same_id or same_key:
            merged = {
                **existing,
                **normalized,
                "created_at": existing.get("created_at") or normalized.get("created_at"),
            }
            updated.append(normalize_incident_rule(merged))
            replaced = True
        else:
            updated.append(existing)
    if not replaced:
        updated.append(normalized)

    return update_incident_rules(
        state,
        updated,
        actor=actor,
        _audit_action="upsert_incident_rule",
    )


def matching_process_incidents(state, definition: dict) -> list[dict]:
    normalized = normalize_definition(definition)
    matches = []
    for incident in state.incidents:
        if not isinstance(incident, dict):
            continue
        if str(incident.get("rule_id", "") or "") not in PROCESS_INCIDENT_RULE_IDS:
            continue
        if incident_matches_definition(incident, normalized):
            matches.append(incident)
    return matches


def process_history_entry(incident: dict, *, active: bool = False) -> dict:
    identity = process_incident_identity(incident)
    return {
        "incident_id": str(incident.get("incident_id", "") or ""),
        "client_id": str(incident.get("client_id", "") or ""),
        "login_id": str(incident.get("login_id", "") or ""),
        "status": str(incident.get("status", "") or ""),
        "severity": str(incident.get("severity", "") or ""),
        "rule_id": str(incident.get("rule_id", "") or ""),
        "event_at": str(
            incident.get("server_received_at")
            or incident.get("reported_at")
            or incident.get("event_at")
            or incident.get("timestamp")
            or ""
        ),
        "pid": int(incident.get("pid", 0) or 0),
        "process_name": identity.get("process_name") or str(incident.get("process_name", "") or ""),
        "process_path": identity.get("process_path") or str(incident.get("process_path", "") or ""),
        "process_dir": identity.get("process_dir") or str(incident.get("process_dir", "") or ""),
        "active": bool(active),
        "summary": str(incident.get("summary", "") or ""),
    }


def build_action_states(state, history: list[dict]) -> list[dict]:
    latest_by_login: dict[str, dict] = {}
    fallback_entries: list[dict] = []
    for entry in history:
        login_id = str(entry.get("login_id", "") or "")
        if not login_id:
            fallback_entries.append(entry)
            continue
        current = latest_by_login.get(login_id)
        if current is None or str(entry.get("event_at", "")) >= str(current.get("event_at", "")):
            latest_by_login[login_id] = entry

    entries = list(latest_by_login.values()) + fallback_entries
    return [_action_state_for_entry(state, entry) for entry in sorted(entries, key=lambda item: str(item.get("login_id") or item.get("client_id") or ""))]


def build_process_database(state) -> list[dict]:
    definitions = process_definitions(state)
    rows: dict[str, dict] = {}

    for definition in definitions:
        row = _empty_process_row(definition)
        row["source"] = "policy"
        rows[row["process_key"]] = row

    for incident in state.incidents:
        if not isinstance(incident, dict):
            continue
        if str(incident.get("rule_id", "") or "") not in PROCESS_INCIDENT_RULE_IDS:
            continue
        identity = process_incident_identity(incident)
        if not identity.get("normalized_process_name"):
            continue
        matching = find_matching_definitions(
            definitions,
            identity.get("normalized_process_name"),
            identity.get("normalized_process_path"),
        )
        if matching:
            definition = matching[0]
        else:
            status = _status_from_incident(incident)
            definition = definition_from_incident(incident, status=status)
        process_key = definition.get("process_key") or stable_process_key(
            identity.get("normalized_process_name"),
            identity.get("normalized_process_path"),
            definition.get("match_scope"),
        )
        row = rows.setdefault(process_key, _empty_process_row(definition))
        incident_id = str(incident.get("incident_id", "") or "")
        active = bool(incident_id and incident_id in state.active_incidents)
        row["matching_history"].append(process_history_entry(incident, active=active))
        row["active"] = bool(row["active"] or active)
        if str(incident.get("status", "") or "") == "resolved":
            row["resolved"] = True
        event_at = str(
            incident.get("server_received_at")
            or incident.get("reported_at")
            or incident.get("event_at")
            or incident.get("timestamp")
            or ""
        )
        if event_at and event_at > str(row.get("last_seen", "")):
            row["last_seen"] = event_at

    for row in rows.values():
        history = row["matching_history"]
        students = sorted({str(entry.get("login_id") or entry.get("client_id") or "") for entry in history if str(entry.get("login_id") or entry.get("client_id") or "")})
        opened_students = sorted({str(entry.get("login_id") or entry.get("client_id") or "") for entry in history if str(entry.get("status", "") or "") == "opened" and str(entry.get("login_id") or entry.get("client_id") or "")})
        resolved_students = sorted({str(entry.get("login_id") or entry.get("client_id") or "") for entry in history if str(entry.get("status", "") or "") == "resolved" and str(entry.get("login_id") or entry.get("client_id") or "")})
        row["match_count"] = len(history)
        row["affected_students"] = students
        row["affected_student_count"] = len(students)
        row["opened_students"] = opened_students
        row["resolved_students"] = resolved_students
        row["closed_students"] = resolved_students
        row["saved_action_labels"] = _action_labels(row.get("actions", {}))
        row["action_states"] = build_action_states(state, history)
        row["action_availability"] = _summarize_action_states(row["action_states"])
        row["previous_matching_entries"] = _previous_matching_definitions(row, definitions)
        row["warning"] = row.get("status") == "warning"
        if not row.get("last_seen") and row.get("updated_at"):
            row["last_seen"] = row["updated_at"]

    return sorted(
        rows.values(),
        key=lambda row: (
            bool(row.get("active")),
            str(row.get("last_seen", "")),
            str(row.get("process_name", "")),
        ),
        reverse=True,
    )


def matching_incident_rule_incidents(state, definition: dict) -> list[dict]:
    normalized = normalize_incident_rule(definition)
    matches = []
    for incident in state.incidents:
        if not isinstance(incident, dict):
            continue
        if incident_matches_rule(incident, normalized):
            matches.append(incident)
    return matches


def build_incident_rules_database(state) -> list[dict]:
    definitions = incident_rules(state)
    rows: dict[str, dict] = {}

    for definition in definitions:
        row = _empty_incident_rule_row(definition)
        row["source"] = "policy"
        rows[row["rule_key"]] = row

    for incident in state.incidents:
        if not isinstance(incident, dict):
            continue
        matching = [
            definition
            for definition in definitions
            if incident_matches_rule(incident, definition)
        ]
        if matching:
            definition = matching[0]
        else:
            definition = incident_rule_from_incident(
                incident,
                status=_incident_rule_status_from_incident(incident),
            )
        rule_key = str(definition.get("rule_key", "") or "")
        if not rule_key:
            continue
        row = rows.setdefault(rule_key, _empty_incident_rule_row(definition))
        incident_id = str(incident.get("incident_id", "") or "")
        active = bool(incident_id and incident_id in state.active_incidents)
        row["matching_history"].append(incident_history_entry(incident, active=active))
        row["active"] = bool(row["active"] or active)
        if str(incident.get("status", "") or "") == "resolved":
            row["resolved"] = True
        event_at = str(
            incident.get("server_received_at")
            or incident.get("reported_at")
            or incident.get("event_at")
            or incident.get("timestamp")
            or ""
        )
        if event_at and event_at > str(row.get("last_seen", "")):
            row["last_seen"] = event_at

    for row in rows.values():
        history = row["matching_history"]
        students = sorted({str(entry.get("login_id") or entry.get("client_id") or "") for entry in history if str(entry.get("login_id") or entry.get("client_id") or "")})
        opened_students = sorted({str(entry.get("login_id") or entry.get("client_id") or "") for entry in history if str(entry.get("status", "") or "") == "opened" and str(entry.get("login_id") or entry.get("client_id") or "")})
        resolved_students = sorted({str(entry.get("login_id") or entry.get("client_id") or "") for entry in history if str(entry.get("status", "") or "") == "resolved" and str(entry.get("login_id") or entry.get("client_id") or "")})
        row["match_count"] = len(history)
        row["affected_students"] = students
        row["affected_student_count"] = len(students)
        row["opened_students"] = opened_students
        row["resolved_students"] = resolved_students
        row["closed_students"] = resolved_students
        row["saved_action_labels"] = _action_labels(row.get("actions", {}))
        row["action_states"] = build_action_states(state, history)
        row["action_availability"] = _summarize_action_states(row["action_states"])
        row["previous_matching_entries"] = _previous_matching_incident_rules(row, definitions)
        row["warning"] = row.get("status") == "warning"
        if not row.get("last_seen") and row.get("updated_at"):
            row["last_seen"] = row["updated_at"]

    return sorted(
        rows.values(),
        key=lambda row: (
            bool(row.get("active")),
            str(row.get("last_seen", "")),
            str(row.get("name", "")),
        ),
        reverse=True,
    )


def apply_incident_rule_decision(state, decision: dict, *, actor="admin") -> dict:
    if not isinstance(decision, dict):
        return {"ok": False, "message": "Incident rule decision must be an object.", "errors": ["Incident rule decision must be an object."]}

    raw_definition = dict(decision.get("definition") or {})
    if not raw_definition and isinstance(decision.get("incident"), dict):
        raw_definition = incident_rule_from_incident(decision.get("incident"), status=str(decision.get("status") or "unknown"))
    raw_definition["status"] = str(decision.get("status") or raw_definition.get("status") or "unknown")
    raw_definition["actions"] = normalize_actions(decision.get("actions") or raw_definition.get("actions"))
    if "priority" in decision:
        raw_definition["priority"] = int(decision.get("priority", 0) or 0)
    now = protocol.now_iso()
    raw_definition["updated_at"] = now
    raw_definition["decided_at"] = now
    raw_definition["decided_by"] = str(actor or "admin")
    if decision.get("reason"):
        raw_definition["decision_reason"] = str(decision.get("reason") or "")

    definition = normalize_incident_rule(raw_definition, now=now)
    if not any(
        definition.get(key)
        for key in ("rule_id", "event_type", "source", "process_names", "browser_process_names", "window_title_patterns")
    ):
        return {"ok": False, "message": "Decision requires at least one incident match field.", "errors": ["Decision requires at least one incident match field."]}

    matches = matching_incident_rule_incidents(state, definition)
    history = [
        incident_history_entry(
            incident,
            active=str(incident.get("incident_id", "") or "") in state.active_incidents,
        )
        for incident in matches
    ]
    definition["matching_history"] = history
    definition["previous_matching_entries"] = _previous_matching_incident_rules(definition, incident_rules(state))

    saved_to_policy = bool(decision.get("save_policy", False))
    settings_result = None
    if saved_to_policy:
        settings_result = upsert_incident_rule(state, definition, actor=actor)
        if not settings_result.ok:
            return {
                "ok": False,
                "message": settings_result.message,
                "errors": settings_result.errors,
                "definition": definition,
            }

    for incident in matches:
        incident["incident_rule_decision"] = {
            "definition_id": definition.get("definition_id"),
            "rule_key": definition.get("rule_key"),
            "status": definition.get("status"),
            "actions": dict(definition.get("actions", {})),
            "saved_to_policy": saved_to_policy,
            "decided_at": now,
            "decided_by": str(actor or "admin"),
        }
    if matches and hasattr(state, "save_incidents"):
        state.save_incidents()

    action_results = []
    banned_login_ids = []
    if definition.get("actions", {}).get("ban"):
        for login_id in sorted({entry.get("login_id", "") for entry in history if entry.get("login_id")}):
            user = state.users_db.get(login_id)
            if not user:
                action_results.append(_action_result(login_id, "ban", "not_possible", "unknown user"))
                continue
            if user.get("banned") or session_state.derive_state(user) == session_state.BANNED:
                action_results.append(_action_result(login_id, "ban", "applied", "already banned"))
                continue
            session_state.set_state(user, session_state.BANNED, reason=f"Incident rule decision: {definition.get('name')}")
            user["kick_count"] = int(user.get("kick_count", 0)) + 1
            user["last_action"] = f"Incident rule decision ban: {definition.get('name') or definition.get('rule_key')}"
            banned_login_ids.append(login_id)
            action_results.append(_action_result(login_id, "ban", "applied", "banned"))
        if banned_login_ids:
            state.save_users()

    if hasattr(state, "append_audit"):
        state.append_audit(
            {
                "timestamp": now,
                "actor": str(actor or "admin"),
                "action": "apply_incident_rule_decision",
                "definition_id": definition.get("definition_id"),
                "rule_key": definition.get("rule_key"),
                "status": definition.get("status"),
                "actions": definition.get("actions", {}),
                "saved_to_policy": saved_to_policy,
                "matching_incident_ids": [entry.get("incident_id") for entry in history],
                "banned_login_ids": banned_login_ids,
            }
        )

    return {
        "ok": True,
        "changed": bool(saved_to_policy and settings_result and settings_result.changed) or bool(matches) or bool(banned_login_ids),
        "message": "Incident rule decision applied.",
        "definition": definition,
        "matching_history": history,
        "matching_incident_ids": [entry.get("incident_id") for entry in history],
        "action_states": build_action_states(state, history),
        "action_results": action_results,
        "banned_login_ids": banned_login_ids,
        "saved_to_policy": saved_to_policy,
    }


def apply_process_decision(state, decision: dict, *, actor="admin") -> dict:
    if not isinstance(decision, dict):
        return {"ok": False, "message": "Process decision must be an object.", "errors": ["Process decision must be an object."]}

    raw_definition = dict(decision.get("definition") or {})
    if not raw_definition and decision.get("process"):
        raw_definition = dict(decision.get("process") or {})
    raw_definition["status"] = str(decision.get("status") or raw_definition.get("status") or "unknown")
    raw_definition["match_scope"] = str(decision.get("match_scope") or raw_definition.get("match_scope") or "")
    raw_definition["actions"] = normalize_actions(decision.get("actions") or raw_definition.get("actions"))
    now = protocol.now_iso()
    raw_definition["updated_at"] = now
    raw_definition["decided_at"] = now
    raw_definition["decided_by"] = str(actor or "admin")
    if decision.get("reason"):
        raw_definition["decision_reason"] = str(decision.get("reason") or "")

    definition = normalize_definition(raw_definition, now=now)
    if not definition.get("normalized_process_name"):
        return {"ok": False, "message": "Decision requires an executable name.", "errors": ["Decision requires an executable name."]}

    matches = matching_process_incidents(state, definition)
    history = [process_history_entry(incident, active=str(incident.get("incident_id", "") or "") in state.active_incidents) for incident in matches]
    definition["matching_history"] = history
    definition["previous_matching_entries"] = _previous_matching_definitions(definition, process_definitions(state))

    saved_to_policy = bool(decision.get("save_policy", False))
    settings_result = None
    if saved_to_policy:
        settings_result = upsert_process_definition(state, definition, actor=actor)
        if not settings_result.ok:
            return {
                "ok": False,
                "message": settings_result.message,
                "errors": settings_result.errors,
                "definition": definition,
            }

    for incident in matches:
        incident["process_decision"] = {
            "definition_id": definition.get("definition_id"),
            "process_key": definition.get("process_key"),
            "status": definition.get("status"),
            "actions": dict(definition.get("actions", {})),
            "saved_to_policy": saved_to_policy,
            "decided_at": now,
            "decided_by": str(actor or "admin"),
        }
    if matches and hasattr(state, "save_incidents"):
        state.save_incidents()

    action_results = []
    banned_login_ids = []
    if definition.get("actions", {}).get("ban"):
        for login_id in sorted({entry.get("login_id", "") for entry in history if entry.get("login_id")}):
            user = state.users_db.get(login_id)
            if not user:
                action_results.append(_action_result(login_id, "ban", "not_possible", "unknown user"))
                continue
            if user.get("banned") or session_state.derive_state(user) == session_state.BANNED:
                action_results.append(_action_result(login_id, "ban", "applied", "already banned"))
                continue
            session_state.set_state(user, session_state.BANNED, reason=f"Process policy decision: {definition.get('process_name')}")
            user["kick_count"] = int(user.get("kick_count", 0)) + 1
            user["last_action"] = f"Process decision ban: {definition.get('process_name') or definition.get('normalized_process_name')}"
            banned_login_ids.append(login_id)
            action_results.append(_action_result(login_id, "ban", "applied", "banned"))
        if banned_login_ids:
            state.save_users()

    if hasattr(state, "append_audit"):
        state.append_audit(
            {
                "timestamp": now,
                "actor": str(actor or "admin"),
                "action": "apply_process_decision",
                "definition_id": definition.get("definition_id"),
                "process_key": definition.get("process_key"),
                "status": definition.get("status"),
                "actions": definition.get("actions", {}),
                "saved_to_policy": saved_to_policy,
                "matching_incident_ids": [entry.get("incident_id") for entry in history],
                "banned_login_ids": banned_login_ids,
            }
        )

    return {
        "ok": True,
        "changed": bool(saved_to_policy and settings_result and settings_result.changed) or bool(matches) or bool(banned_login_ids),
        "message": "Process decision applied.",
        "definition": definition,
        "matching_history": history,
        "matching_incident_ids": [entry.get("incident_id") for entry in history],
        "action_states": build_action_states(state, history),
        "action_results": action_results,
        "banned_login_ids": banned_login_ids,
        "saved_to_policy": saved_to_policy,
    }


def process_google_search_url(process_name: str, process_path: str = "") -> str:
    return build_google_search_url(process_name, process_path)


def update_operator_defaults(state, patch: dict, *, actor="admin") -> SettingsResult:
    if not isinstance(patch, dict):
        return _error_result("Operator defaults patch must be an object.", state)
    return update_exam_policy(
        state,
        {"operator_defaults": patch},
        actor=actor,
        _audit_action="update_operator_defaults",
    )


def update_session_settings(state, patch: dict, *, actor="admin") -> SettingsResult:
    if not isinstance(patch, dict):
        return _error_result("Session settings patch must be an object.", state)
    return update_exam_policy(
        state,
        {"session": patch},
        actor=actor,
        _audit_action="update_session_settings",
    )


def update_runtime_settings(app, patch: dict, *, actor="admin") -> SettingsResult:
    if app is None:
        return SettingsResult(ok=False, message="Runtime app is required.", errors=["Runtime app is required."])
    if not isinstance(patch, dict):
        return SettingsResult(ok=False, message="Runtime patch must be an object.", errors=["Runtime patch must be an object."])

    errors: list[str] = []
    updates: dict[str, Any] = {}
    if "exam_duration" in patch:
        try:
            exam_duration = int(patch["exam_duration"])
        except (TypeError, ValueError):
            errors.append("exam_duration must be a positive integer.")
        else:
            if exam_duration <= 0:
                errors.append("exam_duration must be greater than 0.")
            else:
                updates["exam_duration"] = exam_duration

    if "exam_files" in patch:
        exam_files = patch.get("exam_files")
        if exam_files in {None, ""}:
            updates["exam_files"] = None
        else:
            exam_file = Path(str(exam_files)).expanduser()
            if exam_file.suffix.lower() != ".zip":
                errors.append("exam_files must be a .zip file.")
            elif not exam_file.exists() or not exam_file.is_file():
                errors.append(f"exam_files does not exist: {exam_file}")
            else:
                updates["exam_files"] = str(exam_file)

    unsupported = sorted(set(patch) - {"exam_duration", "exam_files"})
    if unsupported:
        errors.append(f"Unsupported runtime setting(s): {', '.join(unsupported)}")

    state = app.get("settings_state") or app.get("state")
    if errors:
        return SettingsResult(
            ok=False,
            changed=False,
            message="Runtime settings were not updated.",
            settings=get_settings_snapshot(state, app) if state else {"runtime": _runtime_snapshot(app)},
            errors=errors,
        )

    before = _runtime_snapshot(app)
    changed_paths = []
    for key, value in updates.items():
        if app.get(key) != value:
            app[key] = value
            changed_paths.append(f"runtime.{key}")

    if changed_paths and state:
        _append_audit(
            state,
            actor=actor,
            action="update_runtime_settings",
            changed_paths=changed_paths,
            before=before,
            after=_runtime_snapshot(app),
        )

    return SettingsResult(
        ok=True,
        changed=bool(changed_paths),
        message="Runtime settings updated." if changed_paths else "No runtime settings changes.",
        settings=get_settings_snapshot(state, app) if state else {"runtime": _runtime_snapshot(app)},
        changed_paths=changed_paths,
        errors=[],
    )


def _empty_process_row(definition: dict) -> dict:
    normalized = normalize_definition(definition)
    return {
        "process_key": normalized.get("process_key", ""),
        "definition_id": normalized.get("definition_id", ""),
        "process_name": normalized.get("process_name") or normalized.get("normalized_process_name", ""),
        "normalized_process_name": normalized.get("normalized_process_name", ""),
        "process_path": normalized.get("process_path", ""),
        "normalized_process_path": normalized.get("normalized_process_path", ""),
        "process_dir": normalized.get("process_dir", ""),
        "normalized_process_dir": normalized.get("normalized_process_dir", ""),
        "match_scope": normalized.get("match_scope", "path"),
        "status": normalized.get("status", "unknown"),
        "actions": normalize_actions(normalized.get("actions", {})),
        "source_incident_id": normalized.get("source_incident_id", ""),
        "matching_history": [],
        "previous_matching_entries": list(normalized.get("previous_matching_entries", [])),
        "match_count": 0,
        "affected_students": [],
        "affected_student_count": 0,
        "opened_students": [],
        "resolved_students": [],
        "closed_students": [],
        "last_seen": "",
        "active": False,
        "resolved": False,
        "warning": normalized.get("status") == "warning",
        "source": normalized.get("source", ""),
        "created_at": normalized.get("created_at", ""),
        "updated_at": normalized.get("updated_at", ""),
        "decided_at": normalized.get("decided_at", ""),
        "decided_by": normalized.get("decided_by", ""),
    }


def _empty_incident_rule_row(definition: dict) -> dict:
    normalized = normalize_incident_rule(definition)
    return {
        "rule_key": normalized.get("rule_key", ""),
        "definition_id": normalized.get("definition_id", ""),
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
        "source_incident_id": normalized.get("source_incident_id", ""),
        "matching_history": [],
        "previous_matching_entries": list(normalized.get("previous_matching_entries", [])),
        "match_count": 0,
        "affected_students": [],
        "affected_student_count": 0,
        "opened_students": [],
        "resolved_students": [],
        "closed_students": [],
        "last_seen": "",
        "active": False,
        "resolved": False,
        "warning": normalized.get("status") == "warning",
        "created_at": normalized.get("created_at", ""),
        "updated_at": normalized.get("updated_at", ""),
        "decided_at": normalized.get("decided_at", ""),
        "decided_by": normalized.get("decided_by", ""),
        "match_summary": _incident_rule_match_summary(normalized),
    }


def _status_from_incident(incident: dict) -> str:
    rule_id = str(incident.get("rule_id", "") or "")
    if rule_id == "process_blacklist":
        return "blacklist"
    if rule_id == "process_path_clarification":
        return "warning"
    matched = incident.get("matched_definition")
    if isinstance(matched, dict) and matched.get("status"):
        return str(matched.get("status"))
    return "unknown"


def _incident_rule_status_from_incident(incident: dict) -> str:
    severity = str(incident.get("severity", "") or "").strip().lower()
    if severity == "violation":
        return "blacklist"
    if severity == "warning":
        return "warning"
    return "unknown"


def _incident_rule_match_summary(rule: dict) -> str:
    normalized = normalize_incident_rule(rule)
    parts = []
    for key, label in (
        ("rule_id", "rule"),
        ("event_type", "event"),
        ("source", "source"),
    ):
        value = str(normalized.get(key, "") or "")
        if value:
            parts.append(f"{label}={value}")
    if normalized.get("process_names"):
        parts.append("process=" + ", ".join(normalized.get("process_names", [])[:3]))
    if normalized.get("browser_process_names"):
        parts.append("browser=" + ", ".join(normalized.get("browser_process_names", [])[:3]))
    if normalized.get("window_title_patterns"):
        parts.append("title=" + ", ".join(normalized.get("window_title_patterns", [])[:3]))
    return "; ".join(parts) if parts else "-"


def _previous_matching_definitions(row_or_definition: dict, definitions: list[dict]) -> list[dict]:
    normalized_name = str(row_or_definition.get("normalized_process_name", "") or "")
    current_id = str(row_or_definition.get("definition_id", "") or "")
    current_key = str(row_or_definition.get("process_key", "") or "")
    previous = []
    for definition in definitions:
        normalized = normalize_definition(definition)
        if normalized.get("normalized_process_name") != normalized_name:
            continue
        if normalized.get("definition_id") == current_id or normalized.get("process_key") == current_key:
            continue
        previous.append(
            {
                "definition_id": normalized.get("definition_id", ""),
                "process_key": normalized.get("process_key", ""),
                "status": normalized.get("status", ""),
                "match_scope": normalized.get("match_scope", ""),
                "process_path": normalized.get("process_path", ""),
                "process_dir": normalized.get("process_dir", ""),
                "actions": normalize_actions(normalized.get("actions", {})),
                "updated_at": normalized.get("updated_at", ""),
                "decided_at": normalized.get("decided_at", ""),
                "decided_by": normalized.get("decided_by", ""),
            }
        )
    return previous


def _previous_matching_incident_rules(row_or_definition: dict, definitions: list[dict]) -> list[dict]:
    current_id = str(row_or_definition.get("definition_id", "") or "")
    current_key = str(row_or_definition.get("rule_key", "") or "")
    previous = []
    reference = normalize_incident_rule(row_or_definition)
    for definition in definitions:
        normalized = normalize_incident_rule(definition)
        if normalized.get("definition_id") == current_id or normalized.get("rule_key") == current_key:
            continue
        probe = {
            "rule_id": reference.get("rule_id", ""),
            "event_type": reference.get("event_type", ""),
            "source": reference.get("source", ""),
            "process_name": (reference.get("process_names") or reference.get("browser_process_names") or [""])[0],
            "window_title": (reference.get("window_title_patterns") or [""])[0],
        }
        if not incident_matches_rule(probe, normalized):
            continue
        previous.append(
            {
                "definition_id": normalized.get("definition_id", ""),
                "rule_key": normalized.get("rule_key", ""),
                "status": normalized.get("status", ""),
                "match_summary": _incident_rule_match_summary(normalized),
                "actions": normalize_actions(normalized.get("actions", {})),
                "updated_at": normalized.get("updated_at", ""),
                "decided_at": normalized.get("decided_at", ""),
                "decided_by": normalized.get("decided_by", ""),
            }
        )
    return previous


def _action_state_for_entry(state, entry: dict) -> dict:
    login_id = str(entry.get("login_id", "") or "")
    client_id = str(entry.get("client_id", "") or "")
    user = state.users_db.get(login_id) if login_id else None
    if not user and client_id:
        login_id, user = state.find_user_by_uuid(client_id)
        login_id = login_id or ""
    if user and not client_id:
        client_id = str(user.get("uuid", "") or "")

    connected = bool(client_id and client_id in state.clients)
    session_name = session_state.derive_state(user) if user else ""
    submitted = bool(user and (user.get("submitted_at") or session_name == session_state.SUBMITTED))
    finished = bool(user and (session_name == session_state.AWAITING_SUBMISSION or (user.get("exam_finished") and not submitted)))
    banned = bool(user and (user.get("banned") or session_name == session_state.BANNED))
    pid = int(entry.get("pid", 0) or 0)
    active = bool(entry.get("active", False))

    action_states = {
        "ban": _availability("possible"),
        "kick": _availability("possible"),
        "pause_exam": _availability("possible"),
        "kill_pid": _availability("possible"),
    }

    if not user:
        for action in PROCESS_DEFINITION_ACTIONS:
            action_states[action] = _availability("not_possible", "unknown user")
    elif banned:
        action_states["ban"] = _availability("applied", "already banned")
        action_states["kick"] = _availability("not_possible", "already banned")
        action_states["pause_exam"] = _availability("not_possible", "already banned")
        action_states["kill_pid"] = _availability("not_possible", "already banned")
    else:
        action_states["ban"] = _availability("possible")

        if submitted:
            action_states["kick"] = _availability("not_possible", "submitted")
            action_states["pause_exam"] = _availability("not_possible", "submitted")
        elif finished:
            action_states["kick"] = _availability("not_possible", "already finished")
            action_states["pause_exam"] = _availability("not_possible", "already finished")
        elif not connected:
            action_states["kick"] = _availability("not_possible", "disconnected")
        else:
            action_states["kick"] = _availability("possible")

        if not submitted and not finished:
            if session_name == session_state.RUNNING:
                action_states["pause_exam"] = _availability("possible")
            elif not connected:
                action_states["pause_exam"] = _availability("not_possible", "disconnected")
            else:
                action_states["pause_exam"] = _availability("not_possible", "exam not running")

        if submitted:
            action_states["kill_pid"] = _availability("not_possible", "submitted")
        elif finished:
            action_states["kill_pid"] = _availability("not_possible", "already finished")
        elif not connected:
            action_states["kill_pid"] = _availability("not_possible", "disconnected")
        elif pid <= 0 or not active:
            action_states["kill_pid"] = _availability("not_possible", "no live PID")
        else:
            action_states["kill_pid"] = _availability("possible")

    return {
        "login_id": login_id,
        "client_id": client_id,
        "incident_id": str(entry.get("incident_id", "") or ""),
        "process_name": str(entry.get("process_name", "") or ""),
        "process_path": str(entry.get("process_path", "") or ""),
        "pid": pid,
        "active": active,
        "session_state": session_name,
        "connected": connected,
        "actions": action_states,
    }


def _availability(state: str, reason: str = "") -> dict:
    payload = {"state": state}
    if reason:
        payload["reason"] = reason
    return payload


def _summarize_action_states(action_states: list[dict]) -> dict:
    summary = {
        action: {"possible": 0, "applied": 0, "not_possible": 0, "reasons": []}
        for action in PROCESS_DEFINITION_ACTIONS
    }
    for student_state in action_states:
        for action, action_state in student_state.get("actions", {}).items():
            bucket = summary.setdefault(action, {"possible": 0, "applied": 0, "not_possible": 0, "reasons": []})
            state_name = str(action_state.get("state", "not_possible") or "not_possible")
            if state_name not in {"possible", "applied", "not_possible"}:
                state_name = "not_possible"
            bucket[state_name] += 1
            reason = str(action_state.get("reason", "") or "")
            if reason and reason not in bucket["reasons"]:
                bucket["reasons"].append(reason)
    return summary


def _action_labels(actions: dict) -> str:
    labels = [name.replace("_", " ") for name, enabled in normalize_actions(actions).items() if enabled]
    return ", ".join(labels) if labels else "-"


def _action_result(login_id: str, action: str, state_name: str, reason: str) -> dict:
    return {
        "login_id": login_id,
        "action": action,
        "state": state_name,
        "reason": reason,
    }


def _update_policy_list(
    state,
    action: str,
    values: list[str],
    *,
    path: tuple[str, ...],
    changed_path: str,
    normalizer,
    actor: str,
    action_name: str,
) -> SettingsResult:
    action = str(action or "").strip().lower()
    if action not in LIST_ACTIONS:
        return _error_result(f"Unsupported {action_name} action: {action}", state)
    if not isinstance(values, list):
        return _error_result(f"{action_name} values must be a list.", state)

    config = copy.deepcopy(state.exam_policy_config)
    current = list(_get_nested(config, path, []))
    incoming = [normalizer(value) for value in values]
    incoming = [value for value in incoming if value]

    if action == "replace":
        updated = _dedupe_strings(incoming)
    elif action == "add":
        updated = _dedupe_strings(current + incoming)
    else:
        remove_keys = {_key(value) for value in incoming}
        updated = [value for value in current if _key(value) not in remove_keys]

    _set_nested(config, path, updated)
    result = update_exam_policy(
        state,
        config,
        actor=actor,
        _audit_action=f"{action_name}_{action}",
    )
    if result.changed:
        result.message = f"{action_name.replace('_', ' ').title()} updated."
        result.changed_paths = [changed_path if item == changed_path or item.startswith(changed_path) else item for item in result.changed_paths]
        if changed_path not in result.changed_paths:
            result.changed_paths.append(changed_path)
    return result


def _error_result(message: str, state=None) -> SettingsResult:
    return SettingsResult(
        ok=False,
        changed=False,
        message=message,
        settings=get_settings_snapshot(state) if state else {},
        changed_paths=[],
        errors=[message],
    )


def _append_audit(state, *, actor: str, action: str, changed_paths: list[str], before: dict, after: dict):
    if not hasattr(state, "append_audit"):
        return
    state.append_audit(
        {
            "timestamp": protocol.now_iso(),
            "actor": str(actor or "admin"),
            "action": action,
            "changed_paths": list(changed_paths),
            "before": before,
            "after": after,
        }
    )


def _deep_merge(base: dict, patch: dict) -> dict:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(dict(base[key]), value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _changed_paths(before, after, prefix: str = "") -> list[str]:
    if before == after:
        return []
    if not isinstance(before, dict) or not isinstance(after, dict):
        return [prefix or "settings"]
    paths = []
    for key in sorted(set(before) | set(after)):
        child_prefix = f"{prefix}.{key}" if prefix else str(key)
        paths.extend(_changed_paths(before.get(key), after.get(key), child_prefix))
    return paths


def _get_nested(config: dict, path: tuple[str, ...], default):
    current = config
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _set_nested(config: dict, path: tuple[str, ...], value):
    current = config
    for part in path[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[path[-1]] = value


def _dedupe_strings(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        clean = str(value or "").strip()
        if not clean:
            continue
        key = _key(clean)
        if key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result


def _normalize_process_name(value: str) -> str:
    clean = os.path.basename(str(value or "").strip())
    return clean.lower()


def _normalize_directory_path(value: str) -> str:
    clean = _expand_path_vars(str(value or "").strip())
    if not clean:
        return ""
    return os.path.normcase(os.path.normpath(os.path.expanduser(clean)))


def _expand_path_vars(value: str) -> str:
    def replace_percent_var(match):
        name = match.group(1)
        return os.environ.get(name, match.group(0))

    return os.path.expandvars(re.sub(r"%([^%]+)%", replace_percent_var, value))


def _incident_process_name(incident: dict) -> str:
    process_name = str(incident.get("normalized_process_name") or incident.get("process_name") or "").strip()
    if not process_name and incident.get("process_path"):
        process_name = os.path.basename(str(incident.get("process_path")))
    return _normalize_process_name(process_name)


def _incident_process_directory(incident: dict) -> str:
    process_dir = str(incident.get("process_dir") or "").strip()
    if process_dir:
        return _normalize_directory_path(process_dir)
    process_path = str(incident.get("process_path") or "").strip()
    if not process_path:
        return ""
    return _normalize_directory_path(os.path.dirname(process_path))


def _runtime_snapshot(app) -> dict:
    return {
        "exam_duration": app.get("exam_duration"),
        "exam_files": app.get("exam_files"),
    }


def _key(value: str) -> str:
    return str(value or "").strip().lower()
