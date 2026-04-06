import uuid
from dataclasses import dataclass

from common import protocol


def _string_list(values) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _normalize_name(value: str | None) -> str:
    return str(value or "").strip().lower()


@dataclass
class _FocusState:
    subject_key: tuple[str, str] | None = None
    out_of_policy_count: int = 0
    in_policy_count: int = 0
    open_incident_id: str = ""


class ClientIncidentEngine:
    def __init__(self):
        self.policy_version = ""
        self._rules_by_id: dict[str, dict] = {}
        self._open_process_incidents: dict[tuple[str, int, str], dict] = {}
        self._focus_state = _FocusState()

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
        return True, ""

    def observe_processes(self, processes: set[tuple[int, str]]) -> list[dict]:
        rule = self._rules_by_id.get("process_blacklist", {})
        if not rule or not rule.get("enabled", True):
            return self._resolve_all_process_incidents()

        blacklist = {_normalize_name(entry) for entry in rule.get("entries", [])}
        current_matches = {}
        for pid, name in sorted(processes, key=lambda item: (str(item[1]).lower(), int(item[0]))):
            normalized = _normalize_name(name.split("/")[-1].split("\\")[-1])
            if normalized not in blacklist:
                continue
            key = ("process_blacklist", int(pid), normalized)
            current_matches[key] = {
                "pid": int(pid),
                "process_name": str(name),
                "summary": f"Blacklisted process detected: {name} (pid {pid})",
            }

        incidents = []
        for key, details in current_matches.items():
            if key in self._open_process_incidents:
                continue
            incident = self._new_incident(rule, status="opened", summary=details["summary"])
            incident["process_name"] = details["process_name"]
            incident["pid"] = details["pid"]
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
        rule = self._rules_by_id.get("focused_window_policy", {})
        if not rule or not rule.get("enabled", False):
            return self._resolve_focus_if_open("Focused-window policy disabled.")

        subject_key = (
            _normalize_name(snapshot.get("process_name")),
            _normalize_name(snapshot.get("window_title")),
        )
        out_of_policy = self._is_focus_out_of_policy(rule, snapshot)
        if out_of_policy:
            return self._handle_focus_violation(rule, snapshot, subject_key)
        return self._handle_focus_clear(rule, subject_key)

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
