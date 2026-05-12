import os
import re
import uuid
from datetime import datetime, timezone
from collections import deque
from dataclasses import dataclass

from common import protocol
from common.text_safety import normalize_display_text, normalize_for_match, sanitize_window_title
from common.process_definitions import (
    PROCESS_DEFINITIONS_RULE_ID,
    PROCESS_PATH_CLARIFICATION_RULE_ID,
    find_matching_definitions,
    find_saved_definition_for_path,
    normalize_actions,
    normalize_definitions,
    process_name_matches,
    process_name_matches_any,
)
from common.incident_rules import (
    INCIDENT_RULES_RULE_ID,
    apply_incident_rule_to_incident,
    best_incident_rule,
    incident_rule_summary,
    normalize_incident_rules,
)
from common.process_users import current_process_usernames, normalize_process_username


ProcessEntry = (
    tuple[int, str]
    | tuple[int, str, str | None]
    | tuple[int, str, str | None, str | None]
)
RAPID_SWITCH_DEFAULT_MAX_SWITCHES = 10
RAPID_SWITCH_DEFAULT_WINDOW_SECONDS = 60.0


def _string_list(values) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _normalize_name(value: str | None) -> str:
    return normalize_for_match(value)


def _normalize_process_name(value: str | None) -> str:
    return _normalize_name(os.path.basename(str(value or "").strip()))


def _expand_path_vars(value: str) -> str:
    def replace_percent_var(match):
        name = match.group(1)
        return os.environ.get(name, match.group(0))

    return os.path.expandvars(re.sub(r"%([^%]+)%", replace_percent_var, value))


def _normalize_path(value: str | None) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    return os.path.normcase(os.path.normpath(os.path.expanduser(_expand_path_vars(clean))))


def _is_path_under_directory(process_path: str | None, directory_path: str | None) -> bool:
    normalized_path = _normalize_path(process_path)
    normalized_dir = _normalize_path(directory_path)
    if not normalized_path or not normalized_dir:
        return False
    if normalized_path == normalized_dir:
        return True
    prefix = normalized_dir if normalized_dir.endswith(os.sep) else normalized_dir + os.sep
    return normalized_path.startswith(prefix)


def _title_matches_any(window_title: str, entries: list[str], match_mode: str) -> bool:
    title = normalize_for_match(window_title)
    clean_entries = [normalize_for_match(entry) for entry in entries if normalize_for_match(entry)]
    if match_mode == "exact":
        return title in clean_entries
    return any(entry in title for entry in clean_entries)


def _process_dir(process_path: str | None) -> str:
    if not process_path:
        return ""
    return os.path.dirname(str(process_path))


def _process_parts(process: ProcessEntry) -> tuple[int, str, str | None, str | None]:
    pid = int(process[0])
    name = str(process[1])
    username = str(process[2]) if len(process) > 2 and process[2] else None
    process_path = str(process[3]) if len(process) > 3 and process[3] else None
    return pid, name, username, process_path


def _client_definition_summary(definition: dict) -> dict:
    return {
        "definition_id": str(definition.get("definition_id", "") or ""),
        "process_key": str(definition.get("process_key", "") or ""),
        "process_name": str(definition.get("process_name", "") or ""),
        "normalized_process_name": str(definition.get("normalized_process_name", "") or ""),
        "process_path": str(definition.get("process_path", "") or ""),
        "process_dir": str(definition.get("process_dir", "") or ""),
        "match_scope": str(definition.get("match_scope", "") or ""),
        "status": str(definition.get("status", "") or ""),
        "actions": normalize_actions(definition.get("actions", {})),
    }


@dataclass
class _FocusState:
    subject_key: tuple[str, str] | None = None
    out_of_policy_count: int = 0
    in_policy_count: int = 0
    open_incident_id: str = ""


@dataclass
class _RapidSwitchState:
    last_subject_key: tuple[str, str] | None = None
    changes: deque | None = None
    open_incident_id: str = ""

    def __post_init__(self):
        if self.changes is None:
            self.changes = deque()


class ClientIncidentEngine:
    def __init__(self):
        self.policy_version = ""
        self._rules_by_id: dict[str, dict] = {}
        self._open_process_incidents: dict[tuple[str, int, str], dict] = {}
        self._known_processes: set[str] = set()
        self._process_definitions: list[dict] = []
        self._incident_rules: list[dict] = []
        self._unexpected_seen_identities: set[str] = set()
        self._unexpected_baseline_ready = False
        self._open_unexpected_process_incidents: dict[str, dict] = {}
        self._focus_state = _FocusState()
        self._rapid_switch_state = _RapidSwitchState()
        self._idle_incident_id: str = ""
        self._idle_level: str = "none"  # "none" | "warn" | "critical"

    def apply_policy(self, policy: dict) -> tuple[bool, str]:
        if not isinstance(policy, dict):
            return False, "policy must be an object"

        policy_version = str(policy.get("policy_version", "")).strip()
        rules = policy.get("rules", [])
        if not policy_version:
            return False, "policy_version is required"
        if not isinstance(rules, list):
            return False, "rules must be a list"

        normalized_rules = {}
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            rule_id = str(rule.get("rule_id", "")).strip()
            if not rule_id:
                continue
            normalized_rules[rule_id] = rule

        self.policy_version = policy_version
        self._rules_by_id = normalized_rules
        self._process_definitions = normalize_definitions(
            normalized_rules.get(PROCESS_DEFINITIONS_RULE_ID, {}).get("definitions", [])
        )
        incident_rules_config = normalized_rules.get(INCIDENT_RULES_RULE_ID, {})
        self._incident_rules = normalize_incident_rules(
            incident_rules_config.get("definitions", [])
            if incident_rules_config.get("enabled", True)
            else []
        )
        self._unexpected_seen_identities = set()
        self._unexpected_baseline_ready = False
        self._focus_state = _FocusState()
        self._rapid_switch_state = _RapidSwitchState()
        self._idle_incident_id = ""
        self._idle_level = "none"
        self._known_processes = {
            _normalize_process_name(entry)
            for rule in normalized_rules.values()
            for entry in _string_list(rule.get("known_process_names", []))
        }
        self._known_processes.update(
            _normalize_process_name(entry)
            for rule in normalized_rules.values()
            for entry in _string_list(rule.get("entries", []))
        )
        return True, ""

    def observe_processes(self, processes: set[ProcessEntry]) -> list[dict]:
        incidents, suppressed_identities = self._observe_process_definitions(processes)
        blacklist_incidents, blacklist_identities = self._observe_blacklisted_processes(processes)
        incidents.extend(blacklist_incidents)
        suppressed_identities.update(blacklist_identities)
        incidents.extend(
            self._observe_unexpected_processes(
                processes,
                suppressed_identities=suppressed_identities,
            )
        )
        return incidents

    def _observe_blacklisted_processes(self, processes: set[ProcessEntry]) -> tuple[list[dict], set[str]]:
        rule = self._rules_by_id.get("process_blacklist", {})
        if not rule or not rule.get("enabled", True):
            return (
                self._resolve_process_incidents_for_rules({"process_blacklist", PROCESS_PATH_CLARIFICATION_RULE_ID}),
                set(),
            )

        blacklist = [_normalize_process_name(entry) for entry in rule.get("entries", []) if _normalize_process_name(entry)]
        monitored_usernames = current_process_usernames(_string_list(rule.get("process_usernames", [])))
        current_matches = {}
        suppressed_identities: set[str] = set()
        for process in sorted(processes, key=lambda item: (str(item[1]).lower(), int(item[0]))):
            pid, name, username, process_path = _process_parts(process)
            normalized = _normalize_process_name(name)
            if not process_name_matches_any(normalized, blacklist):
                continue
            if self._is_whitelisted_process(name, process_path):
                continue
            normalized_username = normalize_process_username(username)
            if normalized_username and normalized_username not in monitored_usernames:
                continue
            saved_definition = find_saved_definition_for_path(self._process_definitions, name, process_path)
            if saved_definition:
                continue
            identity = _normalize_path(process_path) or normalized
            if process_path:
                key = (PROCESS_PATH_CLARIFICATION_RULE_ID, int(pid), identity)
                current_matches[key] = {
                    "rule": self._path_clarification_rule(),
                    "pid": int(pid),
                    "process_name": str(name),
                    "process_username": username,
                    "process_path": process_path,
                    "process_dir": _process_dir(process_path),
                    "normalized_process_name": normalized,
                    "summary": f"Blacklisted executable needs path clarification: {name} (pid {pid})",
                    "event_type": "process_path_clarification",
                    "known_definition_candidates": [
                        _client_definition_summary(definition)
                        for definition in self._process_definitions
                        if process_name_matches(definition.get("normalized_process_name"), normalized)
                    ],
                }
            else:
                key = ("process_blacklist", int(pid), normalized)
                current_matches[key] = {
                    "rule": rule,
                    "pid": int(pid),
                    "process_name": str(name),
                    "process_username": username,
                    "process_path": process_path,
                    "process_dir": _process_dir(process_path),
                    "normalized_process_name": normalized,
                    "summary": f"Blacklisted process detected: {name} (pid {pid})",
                    "event_type": "process_blacklist",
                }
            suppressed_identities.add(identity)

        incidents = []
        for key, details in current_matches.items():
            if key in self._open_process_incidents:
                continue
            incident = self._new_incident(details["rule"], status="opened", summary=details["summary"])
            incident["process_name"] = details["process_name"]
            incident["pid"] = details["pid"]
            incident["process_username"] = details["process_username"]
            incident["process_path"] = details["process_path"]
            incident["process_dir"] = details["process_dir"]
            incident["normalized_process_name"] = details["normalized_process_name"]
            incident["event_type"] = details["event_type"]
            if details.get("known_definition_candidates"):
                incident["known_definition_candidates"] = details["known_definition_candidates"]
            incident = self._finalize_candidate_incident(incident)
            if incident is None:
                continue
            self._open_process_incidents[key] = incident
            incidents.append(dict(incident))

        for key, incident in list(self._open_process_incidents.items()):
            rule_id = str(incident.get("rule_id", "") or key[0])
            if rule_id not in {"process_blacklist", PROCESS_PATH_CLARIFICATION_RULE_ID}:
                continue
            if key in current_matches:
                continue
            now = protocol.now_iso()
            resolved = dict(incident)
            resolved["status"] = "resolved"
            resolved["resolved_at"] = now
            resolved["event_at"] = now
            resolved["timestamp"] = now
            resolved["summary"] = f"Process no longer detected: {incident.get('process_name', 'unknown')}"
            incidents.append(resolved)
            self._open_process_incidents.pop(key, None)

        return incidents, suppressed_identities

    def observe_focused_window(self, snapshot: dict) -> list[dict]:
        incidents = self._observe_rapid_application_switching(snapshot)

        rule = self._rules_by_id.get("focused_window_policy", {})
        if not rule or not rule.get("enabled", False):
            incidents.extend(self._resolve_focus_if_open("Focused-window policy disabled."))
            return incidents

        subject_key = (
            _normalize_name(snapshot.get("process_name")),
            _normalize_name(snapshot.get("window_title")),
        )
        out_of_policy, effective_rule = self._focus_policy_decision(rule, snapshot)
        if out_of_policy:
            incidents.extend(self._handle_focus_violation(effective_rule, snapshot, subject_key))
        else:
            incidents.extend(self._handle_focus_clear(rule, subject_key))
        return incidents

    def observe_idle(self, snapshot: dict) -> list[dict]:
        """
        Evaluate idle time against the server-configured idle_policy rule.

        Rule fields (all optional, with defaults):
          enabled                  bool   (default False)
          warn_threshold_seconds   float  (default 80)
          critical_threshold_seconds float (default 150)

        Opens an incident when the student crosses a threshold, resolves it
        when they become active again.
        """
        rule = self._rules_by_id.get("idle_policy", {})
        if not rule or not rule.get("enabled", False):
            incidents = self._resolve_idle_if_open("Idle policy disabled.")
            self._idle_level = "none"
            return incidents

        idle_seconds = float(snapshot.get("idle_seconds", -1))
        if idle_seconds < 0:
            return []

        warn_threshold = float(rule.get("warn_threshold_seconds", 80))
        critical_threshold = float(rule.get("critical_threshold_seconds", 150))

        if idle_seconds >= critical_threshold:
            new_level = "critical"
        elif idle_seconds >= warn_threshold:
            new_level = "warn"
        else:
            new_level = "none"

        incidents: list[dict] = []

        if new_level == "none":
            incidents.extend(self._resolve_idle_if_open("Student is active again."))
            self._idle_level = "none"
            return incidents

        # escalate: warn -> critical opens a fresh incident
        if new_level == "critical" and self._idle_level == "warn" and self._idle_incident_id:
            incidents.extend(self._resolve_idle_if_open(
                f"Escalating idle incident to critical ({idle_seconds:.0f}s)."
            ))
            self._idle_level = "none"

        if not self._idle_incident_id:
            severity = "violation" if new_level == "critical" else "warning"
            incident_rule = {
                **rule,
                "rule_id": "idle_policy",
                "rule_name": rule.get("rule_name", "idle_policy"),
                "source": "idle_monitor",
                "severity": severity,
            }
            summary = (
                f"Student idle for {idle_seconds:.0f}s "
                f"({'critical' if new_level == 'critical' else 'warning'} threshold "
                f"{critical_threshold if new_level == 'critical' else warn_threshold:.0f}s)"
            )
            incident = self._new_incident(incident_rule, status="opened", summary=summary)
            incident["idle_seconds"] = idle_seconds
            incident["event_type"] = f"idle_{new_level}"
            incident = self._finalize_candidate_incident(incident)
            if incident is None:
                self._idle_level = "none"
                return incidents
            self._idle_incident_id = incident["incident_id"]
            self._idle_level = new_level
            incidents.append(incident)

        return incidents

    def _resolve_idle_if_open(self, summary: str) -> list[dict]:
        if not self._idle_incident_id:
            return []
        now = protocol.now_iso()
        resolved = {
            "incident_id": self._idle_incident_id,
            "policy_version": self.policy_version,
            "rule_id": "idle_policy",
            "rule_name": "idle_policy",
            "source": "idle_monitor",
            "severity": "warning",
            "status": "resolved",
            "summary": summary,
            "event_type": "idle_resolved",
            "event_at": now,
            "timestamp": now,
            "resolved_at": now,
            "needs_evidence": False,
        }
        self._idle_incident_id = ""
        self._idle_level = "none"
        return [resolved]

    def incident_for_id(self, incident_id: str) -> dict | None:
        for incident in self._open_process_incidents.values():
            if incident.get("incident_id") == incident_id:
                return incident
        for incident in self._open_unexpected_process_incidents.values():
            if incident.get("incident_id") == incident_id:
                return incident
        if self._focus_state.open_incident_id:
            return {
                "incident_id": self._focus_state.open_incident_id,
                "rule_id": "focused_window_policy",
            }
        return None

    def _resolve_all_process_incidents(self) -> list[dict]:
        incidents = []
        for incident in list(self._open_process_incidents.values()):
            now = protocol.now_iso()
            resolved = dict(incident)
            resolved["status"] = "resolved"
            resolved["resolved_at"] = now
            resolved["event_at"] = now
            resolved["timestamp"] = now
            resolved["summary"] = f"Policy disabled while incident was open: {incident.get('process_name', 'unknown')}"
            incidents.append(resolved)
        self._open_process_incidents = {}
        return incidents

    def _resolve_process_incidents_for_rules(self, rule_ids: set[str]) -> list[dict]:
        incidents = []
        normalized_rule_ids = {str(rule_id) for rule_id in rule_ids}
        for key, incident in list(self._open_process_incidents.items()):
            if str(incident.get("rule_id", "") or key[0]) not in normalized_rule_ids:
                continue
            now = protocol.now_iso()
            resolved = dict(incident)
            resolved["status"] = "resolved"
            resolved["resolved_at"] = now
            resolved["event_at"] = now
            resolved["timestamp"] = now
            resolved["summary"] = f"Policy disabled while incident was open: {incident.get('process_name', 'unknown')}"
            resolved["needs_evidence"] = False
            incidents.append(resolved)
            self._open_process_incidents.pop(key, None)
        return incidents

    def _new_incident(self, rule: dict, *, status: str, summary: str) -> dict:
        timestamp = protocol.now_iso()
        rule_id = str(rule.get("rule_id", ""))
        return {
            "incident_id": str(uuid.uuid4()),
            "policy_version": self.policy_version,
            "rule_id": rule_id,
            "rule_name": str(rule.get("rule_name") or rule_id),
            "source": str(rule.get("source", "")),
            "severity": str(rule.get("severity", "warning")),
            "status": status,
            "summary": summary,
            "event_type": rule_id or str(rule.get("type", "")) or "policy_incident",
            "event_at": timestamp,
            "timestamp": timestamp,
            "needs_evidence": status in {"opened", "escalated"},
        }

    def _finalize_candidate_incident(self, incident: dict) -> dict | None:
        return apply_incident_rule_to_incident(self._incident_rules, incident)

    def _observe_process_definitions(self, processes: set[ProcessEntry]) -> tuple[list[dict], set[str]]:
        rule = self._rules_by_id.get(PROCESS_DEFINITIONS_RULE_ID, {})
        if not rule or not rule.get("enabled", True):
            return self._resolve_process_incidents_for_rules({PROCESS_DEFINITIONS_RULE_ID}), set()

        incidents: list[dict] = []
        suppressed_identities: set[str] = set()
        current_keys = set()
        for process in sorted(processes, key=lambda item: (str(item[1]).lower(), int(item[0]))):
            pid, name, username, process_path = _process_parts(process)
            identity = _normalize_path(process_path) or _normalize_process_name(name)
            matches = find_matching_definitions(self._process_definitions, name, process_path)
            if not matches:
                continue
            definition = matches[0]
            status = str(definition.get("status", "unknown") or "unknown").lower()
            if status == "whitelist":
                suppressed_identities.add(identity)
                continue
            severity = "violation" if status == "blacklist" else "warning"
            incident_rule = {
                **rule,
                "rule_id": PROCESS_DEFINITIONS_RULE_ID,
                "rule_name": PROCESS_DEFINITIONS_RULE_ID,
                "source": "process_monitor",
                "severity": severity,
                "allow_remote_kill": True,
            }
            key = (PROCESS_DEFINITIONS_RULE_ID, int(pid), f"{definition.get('definition_id')}:{identity}")
            current_keys.add(key)
            suppressed_identities.add(identity)
            if key in self._open_process_incidents:
                continue
            incident = self._new_incident(
                incident_rule,
                status="opened",
                summary=f"Process definition matched ({status}): {name} (pid {pid})",
            )
            incident.update(
                {
                    "event_type": "process_definition_match",
                    "pid": int(pid),
                    "process_name": str(name),
                    "process_username": username,
                    "process_path": process_path,
                    "process_dir": _process_dir(process_path),
                    "normalized_process_name": _normalize_process_name(name),
                    "matched_definition_id": definition.get("definition_id", ""),
                    "matched_definition": _client_definition_summary(definition),
                    "configured_actions": normalize_actions(definition.get("actions", {})),
                }
            )
            incident = self._finalize_candidate_incident(incident)
            if incident is None:
                continue
            self._open_process_incidents[key] = incident
            incidents.append(dict(incident))

        for key, incident in list(self._open_process_incidents.items()):
            if str(incident.get("rule_id", "") or "") != PROCESS_DEFINITIONS_RULE_ID:
                continue
            if key in current_keys:
                continue
            now = protocol.now_iso()
            resolved = dict(incident)
            resolved["status"] = "resolved"
            resolved["resolved_at"] = now
            resolved["event_at"] = now
            resolved["timestamp"] = now
            resolved["summary"] = f"Process definition no longer matched: {incident.get('process_name', 'unknown')}"
            resolved["needs_evidence"] = False
            incidents.append(resolved)
            self._open_process_incidents.pop(key, None)

        return incidents, suppressed_identities

    def _observe_unexpected_processes(
        self,
        processes: set[ProcessEntry],
        *,
        suppressed_identities: set[str] | None = None,
    ) -> list[dict]:
        rule = self._unexpected_process_rule()
        if not rule:
            self._open_unexpected_process_incidents = {}
            self._unexpected_seen_identities = set()
            self._unexpected_baseline_ready = False
            return []
        suppressed_identities = suppressed_identities or set()
        baseline_existing = bool(rule.get("baseline_existing_processes", False))

        allowed = [_normalize_process_name(entry) for entry in _string_list(rule.get("allowed_process_names", []))]
        known = [entry for entry in self._known_processes if entry]
        known.extend(_normalize_process_name(entry) for entry in _string_list(rule.get("known_process_names", [])))
        known.extend(allowed)
        known_directories = _string_list(rule.get("known_directory_paths", []))

        current_names = {
            _normalize_process_name(name)
            for _pid, name, _username, _process_path in (_process_parts(process) for process in processes)
            if str(name).strip()
        }
        current_identities = set()
        raw_processes = [
            {
                "pid": int(raw_pid),
                "process_name": str(raw_name),
                "process_username": raw_username,
                "process_path": raw_process_path,
            }
            for raw_pid, raw_name, raw_username, raw_process_path in (
                _process_parts(process)
                for process in sorted(processes, key=lambda item: (str(item[1]).lower(), int(item[0])))
            )
        ]
        incidents = []
        candidate_identities: set[str] = set()

        for process in sorted(processes, key=lambda item: (str(item[1]).lower(), int(item[0]))):
            pid, name, username, process_path = _process_parts(process)
            normalized = _normalize_process_name(name)
            normalized_path = _normalize_path(process_path)
            identity = normalized_path or normalized
            if identity in suppressed_identities:
                continue
            if self._is_whitelisted_process(name, process_path):
                continue
            if not normalized or process_name_matches_any(normalized, known):
                continue
            if any(_is_path_under_directory(process_path, directory) for directory in known_directories):
                continue
            current_identities.add(identity)
            candidate_identities.add(identity)
            if (
                baseline_existing
                and not self._unexpected_baseline_ready
            ):
                self._unexpected_seen_identities.add(identity)
                continue
            if identity in self._unexpected_seen_identities and identity not in self._open_unexpected_process_incidents:
                continue
            if identity in self._open_unexpected_process_incidents:
                continue

            incident = self._new_incident(
                rule,
                status="opened",
                summary=f"Unexpected process detected: {name} (pid {pid})",
            )
            incident.update(
                {
                    "event_type": "unexpected_process",
                    "pid": int(pid),
                    "process_name": str(name),
                    "process_username": username,
                    "process_path": process_path,
                    "process_dir": _process_dir(process_path),
                    "normalized_process_name": normalized,
                    "raw_processes": raw_processes,
                }
            )
            incident = self._finalize_candidate_incident(incident)
            if incident is None:
                self._unexpected_seen_identities.add(identity)
                continue
            self._open_unexpected_process_incidents[identity] = incident
            self._unexpected_seen_identities.add(identity)
            incidents.append(dict(incident))

        self._unexpected_baseline_ready = True

        for identity, incident in list(self._open_unexpected_process_incidents.items()):
            if identity in current_identities or identity in current_names:
                continue
            now = protocol.now_iso()
            resolved = dict(incident)
            resolved["status"] = "resolved"
            resolved["resolved_at"] = now
            resolved["event_at"] = now
            resolved["timestamp"] = now
            resolved["summary"] = f"Unexpected process no longer detected: {incident.get('process_name', 'unknown')}"
            resolved["needs_evidence"] = False
            incidents.append(resolved)
            self._open_unexpected_process_incidents.pop(identity, None)
            self._unexpected_seen_identities.discard(identity)

        self._unexpected_seen_identities.intersection_update(candidate_identities | set(self._open_unexpected_process_incidents))

        return incidents

    def _unexpected_process_rule(self) -> dict:
        rule = self._rules_by_id.get("unexpected_process", {})
        if rule and rule.get("enabled", False):
            return rule
        definition_rule = self._rules_by_id.get(PROCESS_DEFINITIONS_RULE_ID, {})
        if not definition_rule or not definition_rule.get("enabled", True):
            return {}
        if not definition_rule.get("detect_unknown_processes", True):
            return {}
        return {
            "rule_id": "unexpected_process",
            "rule_name": "unexpected_process",
            "source": "process_monitor",
            "type": "unexpected_process",
            "enabled": True,
            "severity": str(definition_rule.get("unknown_severity", "warning") or "warning"),
            "known_process_names": list(rule.get("known_process_names", [])) if isinstance(rule, dict) else [],
            "known_directory_paths": list(rule.get("known_directory_paths", [])) if isinstance(rule, dict) else [],
            "allowed_process_names": list(rule.get("allowed_process_names", [])) if isinstance(rule, dict) else [],
            "auto_violation_pause": False,
            "baseline_existing_processes": bool(definition_rule.get("baseline_existing_processes", True)),
        }

    def _is_whitelisted_process(self, process_name: str | None, process_path: str | None = None) -> bool:
        return bool(
            find_matching_definitions(
                self._process_definitions,
                process_name,
                process_path,
                statuses={"whitelist"},
            )
        )

    def _path_clarification_rule(self) -> dict:
        rule = self._rules_by_id.get(PROCESS_PATH_CLARIFICATION_RULE_ID, {})
        if rule:
            return rule
        return {
            "rule_id": PROCESS_PATH_CLARIFICATION_RULE_ID,
            "rule_name": PROCESS_PATH_CLARIFICATION_RULE_ID,
            "source": "process_monitor",
            "type": "process_path_clarification",
            "enabled": True,
            "severity": "warning",
        }

    def _observe_rapid_application_switching(self, snapshot: dict) -> list[dict]:
        rule = self._rules_by_id.get("rapid_application_switching", {})
        if not rule or not rule.get("enabled", False):
            self._rapid_switch_state = _RapidSwitchState()
            return []

        if "window_seconds" in rule:
            max_switches = max(
                1,
                int(rule.get("max_switches", RAPID_SWITCH_DEFAULT_MAX_SWITCHES) or RAPID_SWITCH_DEFAULT_MAX_SWITCHES),
            )
            window_seconds = float(rule.get("window_seconds", RAPID_SWITCH_DEFAULT_WINDOW_SECONDS) or RAPID_SWITCH_DEFAULT_WINDOW_SECONDS)
        else:
            # Legacy policies used window_observations-based thresholds. Default to
            # the new time-window model when window_seconds is not provided.
            max_switches = RAPID_SWITCH_DEFAULT_MAX_SWITCHES
            window_seconds = RAPID_SWITCH_DEFAULT_WINDOW_SECONDS
        if window_seconds <= 0:
            window_seconds = RAPID_SWITCH_DEFAULT_WINDOW_SECONDS

        process_name = str(snapshot.get("process_name") or "")
        window_title = sanitize_window_title(snapshot.get("window_title"))
        subject_key = (_normalize_name(process_name), normalize_for_match(window_title))
        if not any(subject_key):
            return []

        state = self._rapid_switch_state
        timestamp = str(snapshot.get("timestamp") or snapshot.get("event_at") or protocol.now_iso())
        now_epoch = _iso_to_epoch_seconds(timestamp)
        if state.last_subject_key is None:
            state.last_subject_key = subject_key
        elif state.last_subject_key != subject_key:
            state.last_subject_key = subject_key
            state.changes.append(
                {
                    "process_name": process_name,
                    "window_title": window_title,
                    "timestamp": timestamp,
                    "_epoch": now_epoch,
                }
            )

        cutoff = now_epoch - window_seconds
        while state.changes and float(state.changes[0].get("_epoch", 0.0)) < cutoff:
            state.changes.popleft()

        recent_switches = []
        for change in state.changes:
            rendered = dict(change)
            rendered.pop("_epoch", None)
            recent_switches.append(rendered)

        incidents: list[dict] = []
        if state.open_incident_id and len(recent_switches) < max_switches:
            now = protocol.now_iso()
            incidents.append(
                {
                    "incident_id": state.open_incident_id,
                    "policy_version": self.policy_version,
                    "rule_id": "rapid_application_switching",
                    "rule_name": "rapid_application_switching",
                    "source": "focused_window",
                    "severity": str(rule.get("severity", "warning")),
                    "status": "resolved",
                    "summary": (
                        f"Rapid switching returned below threshold: "
                        f"{len(recent_switches)} changes in last {int(window_seconds)} seconds"
                    ),
                    "event_type": "rapid_application_switching",
                    "switch_count": len(recent_switches),
                    "threshold": max_switches,
                    "window_seconds": int(window_seconds),
                    "recent_switches": recent_switches,
                    "event_at": now,
                    "timestamp": now,
                    "resolved_at": now,
                    "needs_evidence": False,
                }
            )
            state.open_incident_id = ""

        if state.open_incident_id or len(recent_switches) < max_switches:
            return incidents

        incident = self._new_incident(
            rule,
            status="opened",
            summary=(
                f"Rapid application switching detected: "
                f"{len(recent_switches)} changes in last {int(window_seconds)} seconds"
            ),
        )
        incident.update(
            {
                "event_type": "rapid_application_switching",
                "switch_count": len(recent_switches),
                "threshold": max_switches,
                "window_seconds": int(window_seconds),
                "recent_switches": recent_switches,
            }
        )
        incident = self._finalize_candidate_incident(incident)
        if incident is None:
            return incidents
        state.open_incident_id = incident["incident_id"]
        incidents.append(incident)
        return incidents

    def _focus_policy_decision(self, rule: dict, snapshot: dict) -> tuple[bool, dict]:
        process_name = normalize_display_text(snapshot.get("process_name")) or ""
        window_title = sanitize_window_title(snapshot.get("window_title")) or ""
        candidate = {
            "rule_id": "focused_window_policy",
            "rule_name": "focused_window_policy",
            "source": "focused_window",
            "event_type": "focused_window_policy",
            "status": "opened",
            "severity": str(rule.get("severity", "warning") or "warning"),
            "process_name": process_name,
            "window_title": window_title,
        }
        matched_rule = best_incident_rule(self._incident_rules, candidate)
        if matched_rule:
            status = str(matched_rule.get("status", "unknown") or "unknown")
            if status == "whitelist":
                return False, rule
            if status in {"warning", "blacklist"}:
                effective_rule = {
                    **rule,
                    "severity": "violation" if status == "blacklist" else "warning",
                    "_matched_incident_rule": incident_rule_summary(matched_rule),
                    "configured_actions": normalize_actions(matched_rule.get("actions", {})),
                }
                return True, effective_rule
        return self._is_focus_out_of_policy(rule, snapshot), rule

    def _is_focus_out_of_policy(self, rule: dict, snapshot: dict) -> bool:
        process_name = _normalize_process_name(snapshot.get("process_name"))
        window_title = _normalize_name(snapshot.get("window_title"))
        blocked_process_names = [_normalize_process_name(value) for value in rule.get("blocked_process_names", [])]
        blocked_window_titles = [_normalize_name(value) for value in rule.get("blocked_window_titles", [])]
        allowed_process_names = [_normalize_process_name(value) for value in rule.get("allowed_process_names", [])]
        allowed_window_titles = [_normalize_name(value) for value in rule.get("allowed_window_titles", [])]
        window_title_match_mode = str(rule.get("window_title_match_mode", "contains") or "contains").strip().lower()

        if process_name and process_name_matches_any(process_name, blocked_process_names):
            return True
        if window_title and _title_matches_any(window_title, blocked_window_titles, window_title_match_mode):
            return True
        if allowed_process_names and not process_name_matches_any(process_name, allowed_process_names):
            return True
        if allowed_window_titles and not _title_matches_any(window_title, allowed_window_titles, window_title_match_mode):
            return True
        return False

    def _handle_focus_violation(
        self,
        rule: dict,
        snapshot: dict,
        subject_key: tuple[str, str],
    ) -> list[dict]:
        incidents = []
        state = self._focus_state
        if state.subject_key != subject_key:
            incidents.extend(self._resolve_focus_if_open("Focused window changed to a new violating window."))
            state = self._focus_state
            state.subject_key = subject_key
            state.out_of_policy_count = 0
            state.in_policy_count = 0

        state.out_of_policy_count += 1
        state.in_policy_count = 0
        open_after = max(1, int(rule.get("open_after_consecutive", 3) or 3))
        if state.open_incident_id or state.out_of_policy_count < open_after:
            return incidents

        process_name = str(snapshot.get("process_name") or "unknown")
        window_title = sanitize_window_title(snapshot.get("window_title")) or "unknown"
        process_name = normalize_display_text(process_name) or "unknown"
        incident = self._new_incident(
            rule,
            status="opened",
            summary=f"Focused window out of policy: {process_name} / {window_title}",
        )
        incident["process_name"] = process_name
        incident["window_title"] = window_title
        incident["pid"] = int(snapshot.get("process_id") or 0) or None
        if rule.get("_matched_incident_rule"):
            incident["matched_incident_rule"] = dict(rule.get("_matched_incident_rule") or {})
            incident["matched_incident_rule_id"] = str(incident["matched_incident_rule"].get("definition_id", "") or "")
            incident["configured_actions"] = normalize_actions(rule.get("configured_actions", {}))
        incident = self._finalize_candidate_incident(incident)
        if incident is None:
            return incidents
        state.open_incident_id = incident["incident_id"]
        incidents.append(incident)
        return incidents

    def _handle_focus_clear(self, rule: dict, subject_key: tuple[str, str]) -> list[dict]:
        state = self._focus_state
        state.subject_key = subject_key
        state.out_of_policy_count = 0
        if not state.open_incident_id:
            state.in_policy_count = 0
            return []

        state.in_policy_count += 1
        resolve_after = max(1, int(rule.get("resolve_after_consecutive", 2) or 2))
        if state.in_policy_count < resolve_after:
            return []
        return self._resolve_focus_if_open("Focused window returned to an allowed state.")

    def _resolve_focus_if_open(self, summary: str) -> list[dict]:
        state = self._focus_state
        if not state.open_incident_id:
            return []

        now = protocol.now_iso()
        resolved = {
            "incident_id": state.open_incident_id,
            "policy_version": self.policy_version,
            "rule_id": "focused_window_policy",
            "rule_name": "focused_window_policy",
            "source": "focused_window",
            "severity": "warning",
            "status": "resolved",
            "summary": summary,
            "event_type": "focused_window_policy",
            "event_at": now,
            "timestamp": now,
            "resolved_at": now,
            "needs_evidence": False,
        }
        self._focus_state = _FocusState()
        return [resolved]


def _iso_to_epoch_seconds(value: str) -> float:
    normalized = str(value or "").strip().replace("Z", "+00:00")
    if not normalized:
        return datetime.now(timezone.utc).timestamp()
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return datetime.now(timezone.utc).timestamp()
