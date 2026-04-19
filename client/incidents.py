import uuid
from collections import deque
from dataclasses import dataclass

from common import protocol
from common.process_users import current_process_usernames, normalize_process_username


ProcessEntry = tuple[int, str] | tuple[int, str, str | None]


def _string_list(values) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _normalize_name(value: str | None) -> str:
    return str(value or "").strip().lower()


def _process_parts(process: ProcessEntry) -> tuple[int, str, str | None]:
    pid = int(process[0])
    name = str(process[1])
    username = str(process[2]) if len(process) > 2 and process[2] else None
    return pid, name, username


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
        self._open_unexpected_process_incidents: dict[str, dict] = {}
        self._focus_state = _FocusState()
        self._rapid_switch_state = _RapidSwitchState()

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
        self._focus_state = _FocusState()
        self._rapid_switch_state = _RapidSwitchState()
        self._known_processes = {
            _normalize_name(entry)
            for rule in normalized_rules.values()
            for entry in _string_list(rule.get("known_process_names", []))
        }
        self._known_processes.update(
            _normalize_name(entry)
            for rule in normalized_rules.values()
            for entry in _string_list(rule.get("entries", []))
        )
        return True, ""

    def observe_processes(self, processes: set[ProcessEntry]) -> list[dict]:
        incidents = self._observe_unexpected_processes(processes)

        rule = self._rules_by_id.get("process_blacklist", {})
        if not rule or not rule.get("enabled", True):
            incidents.extend(self._resolve_all_process_incidents())
            return incidents

        blacklist = {_normalize_name(entry) for entry in rule.get("entries", [])}
        monitored_usernames = current_process_usernames(_string_list(rule.get("process_usernames", [])))
        current_matches = {}
        for process in sorted(processes, key=lambda item: (str(item[1]).lower(), int(item[0]))):
            pid, name, username = _process_parts(process)
            normalized = _normalize_name(name.split("/")[-1].split("\\")[-1])
            if normalized not in blacklist:
                continue
            normalized_username = normalize_process_username(username)
            if normalized_username and normalized_username not in monitored_usernames:
                continue
            key = ("process_blacklist", int(pid), normalized)
            current_matches[key] = {
                "pid": int(pid),
                "process_name": str(name),
                "process_username": username,
                "summary": f"Blacklisted process detected: {name} (pid {pid})",
            }

        for key, details in current_matches.items():
            if key in self._open_process_incidents:
                continue
            incident = self._new_incident(rule, status="opened", summary=details["summary"])
            incident["process_name"] = details["process_name"]
            incident["pid"] = details["pid"]
            incident["process_username"] = details["process_username"]
            self._open_process_incidents[key] = incident
            incidents.append(dict(incident))

        for key, incident in list(self._open_process_incidents.items()):
            if key in current_matches:
                continue
            resolved = dict(incident)
            resolved["status"] = "resolved"
            resolved["resolved_at"] = protocol.now_iso()
            resolved["summary"] = f"Process no longer detected: {incident.get('process_name', 'unknown')}"
            incidents.append(resolved)
            self._open_process_incidents.pop(key, None)

        return incidents

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
        out_of_policy = self._is_focus_out_of_policy(rule, snapshot)
        if out_of_policy:
            incidents.extend(self._handle_focus_violation(rule, snapshot, subject_key))
        else:
            incidents.extend(self._handle_focus_clear(rule, subject_key))
        return incidents

    def incident_for_id(self, incident_id: str) -> dict | None:
        for incident in self._open_process_incidents.values():
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
            resolved = dict(incident)
            resolved["status"] = "resolved"
            resolved["resolved_at"] = protocol.now_iso()
            resolved["summary"] = f"Policy disabled while incident was open: {incident.get('process_name', 'unknown')}"
            incidents.append(resolved)
        self._open_process_incidents = {}
        return incidents

    def _new_incident(self, rule: dict, *, status: str, summary: str) -> dict:
        return {
            "incident_id": str(uuid.uuid4()),
            "policy_version": self.policy_version,
            "rule_id": str(rule.get("rule_id", "")),
            "rule_name": str(rule.get("rule_name") or rule.get("rule_id", "")),
            "source": str(rule.get("source", "")),
            "severity": str(rule.get("severity", "warning")),
            "status": status,
            "summary": summary,
            "event_at": protocol.now_iso(),
            "needs_evidence": status in {"opened", "escalated"},
        }

    def _observe_unexpected_processes(self, processes: set[ProcessEntry]) -> list[dict]:
        rule = self._rules_by_id.get("unexpected_process", {})
        if not rule or not rule.get("enabled", False):
            self._open_unexpected_process_incidents = {}
            return []

        allowed = {_normalize_name(entry) for entry in _string_list(rule.get("allowed_process_names", []))}
        known = set(self._known_processes)
        known.update(_normalize_name(entry) for entry in _string_list(rule.get("known_process_names", [])))
        known.update(allowed)

        current_names = {
            _normalize_name(str(name).split("/")[-1].split("\\")[-1])
            for _pid, name, _username in (_process_parts(process) for process in processes)
            if str(name).strip()
        }
        raw_processes = [
            {"pid": int(raw_pid), "process_name": str(raw_name), "process_username": raw_username}
            for raw_pid, raw_name, raw_username in (
                _process_parts(process)
                for process in sorted(processes, key=lambda item: (str(item[1]).lower(), int(item[0])))
            )
        ]
        incidents = []

        for process in sorted(processes, key=lambda item: (str(item[1]).lower(), int(item[0]))):
            pid, name, username = _process_parts(process)
            normalized = _normalize_name(str(name).split("/")[-1].split("\\")[-1])
            if not normalized or normalized in known:
                continue
            if normalized in self._open_unexpected_process_incidents:
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
                    "normalized_process_name": normalized,
                    "raw_processes": raw_processes,
                }
            )
            self._open_unexpected_process_incidents[normalized] = incident
            incidents.append(dict(incident))

        for normalized, incident in list(self._open_unexpected_process_incidents.items()):
            if normalized in current_names:
                continue
            resolved = dict(incident)
            resolved["status"] = "resolved"
            resolved["resolved_at"] = protocol.now_iso()
            resolved["summary"] = f"Unexpected process no longer detected: {incident.get('process_name', 'unknown')}"
            resolved["needs_evidence"] = False
            incidents.append(resolved)
            self._open_unexpected_process_incidents.pop(normalized, None)

        self._known_processes.update(current_names)
        return incidents

    def _observe_rapid_application_switching(self, snapshot: dict) -> list[dict]:
        rule = self._rules_by_id.get("rapid_application_switching", {})
        if not rule or not rule.get("enabled", False):
            self._rapid_switch_state = _RapidSwitchState()
            return []

        process_name = str(snapshot.get("process_name") or "")
        window_title = str(snapshot.get("window_title") or "")
        subject_key = (_normalize_name(process_name), _normalize_name(window_title))
        if not any(subject_key):
            return []

        state = self._rapid_switch_state
        timestamp = str(snapshot.get("timestamp") or snapshot.get("event_at") or protocol.now_iso())
        if state.last_subject_key is None:
            state.last_subject_key = subject_key
            return []
        if state.last_subject_key == subject_key:
            return []

        state.last_subject_key = subject_key
        state.changes.append(
            {
                "process_name": process_name,
                "window_title": window_title,
                "timestamp": timestamp,
            }
        )

        max_switches = max(1, int(rule.get("max_switches", 4) or 4))
        window_observations = max(1, int(rule.get("window_observations", max_switches) or max_switches))
        while len(state.changes) > window_observations:
            state.changes.popleft()

        if state.open_incident_id or len(state.changes) < max_switches:
            return []

        recent_switches = list(state.changes)
        incident = self._new_incident(
            rule,
            status="opened",
            summary=f"Rapid application switching detected: {len(recent_switches)} changes in {window_observations} observations",
        )
        incident.update(
            {
                "event_type": "rapid_application_switching",
                "switch_count": len(recent_switches),
                "window_observations": window_observations,
                "recent_switches": recent_switches,
            }
        )
        state.open_incident_id = incident["incident_id"]
        return [incident]

    def _is_focus_out_of_policy(self, rule: dict, snapshot: dict) -> bool:
        process_name = _normalize_name(snapshot.get("process_name"))
        window_title = _normalize_name(snapshot.get("window_title"))
        blocked_process_names = {_normalize_name(value) for value in rule.get("blocked_process_names", [])}
        blocked_window_titles = {_normalize_name(value) for value in rule.get("blocked_window_titles", [])}
        allowed_process_names = {_normalize_name(value) for value in rule.get("allowed_process_names", [])}
        allowed_window_titles = {_normalize_name(value) for value in rule.get("allowed_window_titles", [])}

        if process_name and process_name in blocked_process_names:
            return True
        if window_title and window_title in blocked_window_titles:
            return True
        if allowed_process_names and process_name not in allowed_process_names:
            return True
        if allowed_window_titles and window_title not in allowed_window_titles:
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
        window_title = str(snapshot.get("window_title") or "unknown")
        incident = self._new_incident(
            rule,
            status="opened",
            summary=f"Focused window out of policy: {process_name} / {window_title}",
        )
        incident["process_name"] = process_name
        incident["window_title"] = window_title
        incident["pid"] = int(snapshot.get("process_id") or 0) or None
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

        resolved = {
            "incident_id": state.open_incident_id,
            "policy_version": self.policy_version,
            "rule_id": "focused_window_policy",
            "rule_name": "focused_window_policy",
            "source": "focused_window",
            "severity": "warning",
            "status": "resolved",
            "summary": summary,
            "event_at": protocol.now_iso(),
            "needs_evidence": False,
        }
        self._focus_state = _FocusState()
        return [resolved]
