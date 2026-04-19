import uuid
from collections import deque
from dataclasses import dataclass

from common import protocol
from common.process_users import current_process_usernames, normalize_process_username


ProcessEntry = tuple[int, str] | tuple[int, str, str | None]


def as_text_list(values) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def clean_name(value: str | None) -> str:
    return str(value or "").strip().lower()


def process_basename(name: str | None) -> str:
    return clean_name(str(name or "").split("/")[-1].split("\\")[-1])


def split_process(process: ProcessEntry) -> tuple[int, str, str | None]:
    pid = int(process[0])
    name = str(process[1])
    owner = str(process[2]) if len(process) > 2 and process[2] else None
    return pid, name, owner


@dataclass
class FocusTracker:
    window_key: tuple[str, str] | None = None
    bad_count: int = 0
    good_count: int = 0
    incident_id: str = ""


@dataclass
class SwitchTracker:
    last_window_key: tuple[str, str] | None = None
    changes: deque | None = None
    incident_id: str = ""

    def __post_init__(self):
        if self.changes is None:
            self.changes = deque()


class ClientIncidentEngine:
    def __init__(self):
        self.policy_version = ""
        self.rules: dict[str, dict] = {}
        self.open_process_incidents: dict[tuple[str, int, str], dict] = {}
        self.known_processes: set[str] = set()
        self.open_unexpected_processes: dict[str, dict] = {}
        self.focus = FocusTracker()
        self.switches = SwitchTracker()

    def apply_policy(self, policy: dict) -> tuple[bool, str]:
        if not isinstance(policy, dict):
            return False, "policy must be an object"

        policy_version = str(policy.get("policy_version", "")).strip()
        rules = policy.get("rules", [])
        if not policy_version:
            return False, "policy_version is required"
        if not isinstance(rules, list):
            return False, "rules must be a list"

        cleaned_rules = {}
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            rule_id = str(rule.get("rule_id", "")).strip()
            if rule_id:
                cleaned_rules[rule_id] = rule

        self.policy_version = policy_version
        self.rules = cleaned_rules
        self.focus = FocusTracker()
        self.switches = SwitchTracker()
        self.known_processes = {
            clean_name(entry)
            for rule in cleaned_rules.values()
            for entry in as_text_list(rule.get("known_process_names", []))
        }
        self.known_processes.update(
            clean_name(entry)
            for rule in cleaned_rules.values()
            for entry in as_text_list(rule.get("entries", []))
        )
        return True, ""

    def observe_processes(self, processes: set[ProcessEntry]) -> list[dict]:
        incidents = self.note_unexpected_processes(processes)

        rule = self.rules.get("process_blacklist", {})
        if not rule or not rule.get("enabled", True):
            incidents.extend(self.close_all_process_incidents())
            return incidents

        blocked_names = {clean_name(entry) for entry in rule.get("entries", [])}
        watched_users = current_process_usernames(as_text_list(rule.get("process_usernames", [])))
        current_matches = {}

        for process in sorted(processes, key=lambda item: (str(item[1]).lower(), int(item[0]))):
            pid, name, owner = split_process(process)
            blocked_name = process_basename(name)
            if blocked_name not in blocked_names:
                continue

            clean_owner = normalize_process_username(owner)
            if clean_owner and clean_owner not in watched_users:
                continue

            key = ("process_blacklist", pid, blocked_name)
            current_matches[key] = {
                "pid": pid,
                "process_name": name,
                "process_username": owner,
                "summary": f"Blacklisted process detected: {name} (pid {pid})",
            }

        for key, details in current_matches.items():
            if key in self.open_process_incidents:
                continue
            incident = self.new_incident(rule, status="opened", summary=details["summary"])
            incident["process_name"] = details["process_name"]
            incident["pid"] = details["pid"]
            incident["process_username"] = details["process_username"]
            self.open_process_incidents[key] = incident
            incidents.append(dict(incident))

        for key, incident in list(self.open_process_incidents.items()):
            if key in current_matches:
                continue
            closed = dict(incident)
            closed["status"] = "resolved"
            closed["resolved_at"] = protocol.now_iso()
            closed["summary"] = f"Process no longer detected: {incident.get('process_name', 'unknown')}"
            incidents.append(closed)
            self.open_process_incidents.pop(key, None)

        return incidents

    def observe_focused_window(self, snapshot: dict) -> list[dict]:
        incidents = self.note_fast_switching(snapshot)

        rule = self.rules.get("focused_window_policy", {})
        if not rule or not rule.get("enabled", False):
            incidents.extend(self.close_focus_incident("Focused-window policy disabled."))
            return incidents

        window_key = (
            clean_name(snapshot.get("process_name")),
            clean_name(snapshot.get("window_title")),
        )
        if self.focus_is_outside_policy(rule, snapshot):
            incidents.extend(self.note_focus_violation(rule, snapshot, window_key))
        else:
            incidents.extend(self.note_focus_returned(rule, window_key))
        return incidents

    def incident_for_id(self, incident_id: str) -> dict | None:
        for incident in self.open_process_incidents.values():
            if incident.get("incident_id") == incident_id:
                return incident
        if self.focus.incident_id:
            return {
                "incident_id": self.focus.incident_id,
                "rule_id": "focused_window_policy",
            }
        return None

    def close_all_process_incidents(self) -> list[dict]:
        incidents = []
        for incident in list(self.open_process_incidents.values()):
            closed = dict(incident)
            closed["status"] = "resolved"
            closed["resolved_at"] = protocol.now_iso()
            closed["summary"] = f"Policy disabled while incident was open: {incident.get('process_name', 'unknown')}"
            incidents.append(closed)
        self.open_process_incidents = {}
        return incidents

    def new_incident(self, rule: dict, *, status: str, summary: str) -> dict:
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

    def note_unexpected_processes(self, processes: set[ProcessEntry]) -> list[dict]:
        rule = self.rules.get("unexpected_process", {})
        if not rule or not rule.get("enabled", False):
            self.open_unexpected_processes = {}
            return []

        allowed = {clean_name(entry) for entry in as_text_list(rule.get("allowed_process_names", []))}
        known = set(self.known_processes)
        known.update(clean_name(entry) for entry in as_text_list(rule.get("known_process_names", [])))
        known.update(allowed)

        current_names = {
            process_basename(name)
            for _pid, name, _owner in (split_process(process) for process in processes)
            if str(name).strip()
        }
        raw_processes = [
            {"pid": pid, "process_name": name, "process_username": owner}
            for pid, name, owner in (
                split_process(process)
                for process in sorted(processes, key=lambda item: (str(item[1]).lower(), int(item[0])))
            )
        ]

        incidents = []
        for process in sorted(processes, key=lambda item: (str(item[1]).lower(), int(item[0]))):
            pid, name, owner = split_process(process)
            process_name = process_basename(name)
            if not process_name or process_name in known:
                continue
            if process_name in self.open_unexpected_processes:
                continue

            incident = self.new_incident(
                rule,
                status="opened",
                summary=f"Unexpected process detected: {name} (pid {pid})",
            )
            incident.update(
                {
                    "event_type": "unexpected_process",
                    "pid": pid,
                    "process_name": name,
                    "process_username": owner,
                    "normalized_process_name": process_name,
                    "raw_processes": raw_processes,
                }
            )
            self.open_unexpected_processes[process_name] = incident
            incidents.append(dict(incident))

        for process_name, incident in list(self.open_unexpected_processes.items()):
            if process_name in current_names:
                continue
            closed = dict(incident)
            closed["status"] = "resolved"
            closed["resolved_at"] = protocol.now_iso()
            closed["summary"] = f"Unexpected process no longer detected: {incident.get('process_name', 'unknown')}"
            closed["needs_evidence"] = False
            incidents.append(closed)
            self.open_unexpected_processes.pop(process_name, None)

        self.known_processes.update(current_names)
        return incidents

    def note_fast_switching(self, snapshot: dict) -> list[dict]:
        rule = self.rules.get("rapid_application_switching", {})
        if not rule or not rule.get("enabled", False):
            self.switches = SwitchTracker()
            return []

        process_name = str(snapshot.get("process_name") or "")
        window_title = str(snapshot.get("window_title") or "")
        window_key = (clean_name(process_name), clean_name(window_title))
        if not any(window_key):
            return []

        timestamp = str(snapshot.get("timestamp") or snapshot.get("event_at") or protocol.now_iso())
        if self.switches.last_window_key is None:
            self.switches.last_window_key = window_key
            return []
        if self.switches.last_window_key == window_key:
            return []

        self.switches.last_window_key = window_key
        self.switches.changes.append(
            {
                "process_name": process_name,
                "window_title": window_title,
                "timestamp": timestamp,
            }
        )

        max_switches = max(1, int(rule.get("max_switches", 4) or 4))
        window_observations = max(1, int(rule.get("window_observations", max_switches) or max_switches))
        while len(self.switches.changes) > window_observations:
            self.switches.changes.popleft()

        if self.switches.incident_id or len(self.switches.changes) < max_switches:
            return []

        recent_switches = list(self.switches.changes)
        incident = self.new_incident(
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
        self.switches.incident_id = incident["incident_id"]
        return [incident]

    def focus_is_outside_policy(self, rule: dict, snapshot: dict) -> bool:
        process_name = clean_name(snapshot.get("process_name"))
        window_title = clean_name(snapshot.get("window_title"))
        blocked_processes = {clean_name(value) for value in rule.get("blocked_process_names", [])}
        blocked_titles = {clean_name(value) for value in rule.get("blocked_window_titles", [])}
        allowed_processes = {clean_name(value) for value in rule.get("allowed_process_names", [])}
        allowed_titles = {clean_name(value) for value in rule.get("allowed_window_titles", [])}

        if process_name and process_name in blocked_processes:
            return True
        if window_title and window_title in blocked_titles:
            return True
        if allowed_processes and process_name not in allowed_processes:
            return True
        if allowed_titles and window_title not in allowed_titles:
            return True
        return False

    def note_focus_violation(
        self,
        rule: dict,
        snapshot: dict,
        window_key: tuple[str, str],
    ) -> list[dict]:
        incidents = []
        if self.focus.window_key != window_key:
            incidents.extend(self.close_focus_incident("Focused window changed to a new violating window."))
            self.focus.window_key = window_key
            self.focus.bad_count = 0
            self.focus.good_count = 0

        self.focus.bad_count += 1
        self.focus.good_count = 0
        open_after = max(1, int(rule.get("open_after_consecutive", 3) or 3))
        if self.focus.incident_id or self.focus.bad_count < open_after:
            return incidents

        process_name = str(snapshot.get("process_name") or "unknown")
        window_title = str(snapshot.get("window_title") or "unknown")
        incident = self.new_incident(
            rule,
            status="opened",
            summary=f"Focused window out of policy: {process_name} / {window_title}",
        )
        incident["process_name"] = process_name
        incident["window_title"] = window_title
        incident["pid"] = int(snapshot.get("process_id") or 0) or None
        self.focus.incident_id = incident["incident_id"]
        incidents.append(incident)
        return incidents

    def note_focus_returned(self, rule: dict, window_key: tuple[str, str]) -> list[dict]:
        self.focus.window_key = window_key
        self.focus.bad_count = 0
        if not self.focus.incident_id:
            self.focus.good_count = 0
            return []

        self.focus.good_count += 1
        resolve_after = max(1, int(rule.get("resolve_after_consecutive", 2) or 2))
        if self.focus.good_count < resolve_after:
            return []
        return self.close_focus_incident("Focused window returned to an allowed state.")

    def close_focus_incident(self, summary: str) -> list[dict]:
        if not self.focus.incident_id:
            return []

        closed = {
            "incident_id": self.focus.incident_id,
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
        self.focus = FocusTracker()
        return [closed]
