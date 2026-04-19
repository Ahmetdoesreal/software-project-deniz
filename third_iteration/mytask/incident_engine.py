import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from process_users import user_key, watched_users


ProcessEntry = tuple[int, str] | tuple[int, str, str | None]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def text_list(values) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def clean(value: str | None) -> str:
    return str(value or "").strip().lower()


def app_name(value: str | None) -> str:
    name = clean(str(value or "").split("/")[-1].split("\\")[-1])
    if name.endswith(".exe"):
        name = name[:-4]
    return name


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


class IncidentEngine:
    def __init__(self):
        self.policy_version = ""
        self.rules: dict[str, dict] = {}
        self.open_blocked_processes: dict[tuple[str, int, str], dict] = {}
        self.open_unexpected_processes: dict[str, dict] = {}
        self.known_processes: set[str] = set()
        self.seen_first_process_snapshot = False
        self.focus = FocusTracker()
        self.switches = SwitchTracker()

    def apply_policy(self, policy: dict) -> tuple[bool, str]:
        if not isinstance(policy, dict):
            return False, "policy must be an object"

        version = str(policy.get("policy_version", "")).strip() or "local-policy"
        rules = policy.get("rules", [])
        if not isinstance(rules, list):
            return False, "rules must be a list"

        self.policy_version = version
        self.rules = {
            str(rule.get("rule_id", "")).strip(): rule
            for rule in rules
            if isinstance(rule, dict) and str(rule.get("rule_id", "")).strip()
        }
        self.open_blocked_processes = {}
        self.open_unexpected_processes = {}
        self.focus = FocusTracker()
        self.switches = SwitchTracker()
        self.seen_first_process_snapshot = False
        self.known_processes = {
            app_name(entry)
            for rule in self.rules.values()
            for entry in text_list(rule.get("known_process_names", []))
        }
        self.known_processes.update(
            app_name(entry)
            for rule in self.rules.values()
            for entry in text_list(rule.get("entries", []))
        )
        return True, ""

    def watch_processes(self, processes: set[ProcessEntry]) -> list[dict]:
        incidents = []
        incidents.extend(self.note_unexpected_processes(processes))
        incidents.extend(self.note_blocked_processes(processes))
        return incidents

    def watch_window(self, snapshot: dict) -> list[dict]:
        incidents = []
        incidents.extend(self.note_fast_switching(snapshot))

        rule = self.rules.get("focused_window_policy", {})
        if not rule or not rule.get("enabled", False):
            incidents.extend(self.close_focus("Focused-window policy disabled."))
            return incidents

        window_key = (
            clean(snapshot.get("process_name")),
            clean(snapshot.get("window_title")),
        )
        if self.focus_is_bad(rule, snapshot):
            incidents.extend(self.note_focus_violation(rule, snapshot, window_key))
        else:
            incidents.extend(self.note_focus_ok(rule, window_key))
        return incidents

    def new_incident(self, rule: dict, status: str, summary: str) -> dict:
        return {
            "incident_id": str(uuid.uuid4()),
            "policy_version": self.policy_version,
            "rule_id": str(rule.get("rule_id", "")),
            "rule_name": str(rule.get("rule_name") or rule.get("rule_id", "")),
            "source": str(rule.get("source", "")),
            "severity": str(rule.get("severity", "warning")),
            "status": status,
            "summary": summary,
            "event_at": now_iso(),
            "needs_evidence": status in {"opened", "escalated"},
        }

    def note_blocked_processes(self, processes: set[ProcessEntry]) -> list[dict]:
        rule = self.rules.get("process_blacklist", {})
        if not rule or not rule.get("enabled", True):
            return self.close_blocked_processes("Process blacklist disabled.")

        blocked = {app_name(entry) for entry in text_list(rule.get("entries", []))}
        if not blocked:
            return self.close_blocked_processes("Process blacklist is empty.")

        allowed_owners = watched_users(text_list(rule.get("process_usernames", [])))
        current = {}
        for process in sorted(processes, key=lambda item: (str(item[1]).lower(), int(item[0]))):
            pid, name, owner = split_process(process)
            name_key = app_name(name)
            if name_key not in blocked:
                continue
            owner_key = user_key(owner)
            if owner_key and owner_key not in allowed_owners:
                continue

            key = ("process_blacklist", pid, name_key)
            current[key] = {
                "pid": pid,
                "process_name": name,
                "process_username": owner,
                "summary": f"Blacklisted process detected: {name} (pid {pid})",
            }

        incidents = []
        for key, details in current.items():
            if key in self.open_blocked_processes:
                continue
            incident = self.new_incident(rule, "opened", details["summary"])
            incident.update(
                {
                    "event_type": "process_blacklist",
                    "pid": details["pid"],
                    "process_name": details["process_name"],
                    "process_username": details["process_username"],
                }
            )
            self.open_blocked_processes[key] = incident
            incidents.append(dict(incident))

        for key, incident in list(self.open_blocked_processes.items()):
            if key in current:
                continue
            closed = dict(incident)
            closed["status"] = "resolved"
            closed["resolved_at"] = now_iso()
            closed["needs_evidence"] = False
            closed["summary"] = f"Process no longer detected: {incident.get('process_name', 'unknown')}"
            incidents.append(closed)
            self.open_blocked_processes.pop(key, None)

        return incidents

    def close_blocked_processes(self, summary: str) -> list[dict]:
        incidents = []
        for incident in list(self.open_blocked_processes.values()):
            closed = dict(incident)
            closed["status"] = "resolved"
            closed["resolved_at"] = now_iso()
            closed["needs_evidence"] = False
            closed["summary"] = summary
            incidents.append(closed)
        self.open_blocked_processes = {}
        return incidents

    def note_unexpected_processes(self, processes: set[ProcessEntry]) -> list[dict]:
        rule = self.rules.get("unexpected_process", {})
        if not rule or not rule.get("enabled", False):
            self.open_unexpected_processes = {}
            return []

        allowed = {app_name(entry) for entry in text_list(rule.get("allowed_process_names", []))}
        known = set(self.known_processes)
        known.update(app_name(entry) for entry in text_list(rule.get("known_process_names", [])))
        known.update(allowed)

        current_names = {
            app_name(name)
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

        if not self.seen_first_process_snapshot:
            self.known_processes.update(current_names)
            self.seen_first_process_snapshot = True
            return []

        incidents = []
        for process in sorted(processes, key=lambda item: (str(item[1]).lower(), int(item[0]))):
            pid, name, owner = split_process(process)
            name_key = app_name(name)
            if not name_key or name_key in known:
                continue
            if name_key in self.open_unexpected_processes:
                continue

            incident = self.new_incident(
                rule,
                "opened",
                f"Unexpected process detected: {name} (pid {pid})",
            )
            incident.update(
                {
                    "event_type": "unexpected_process",
                    "pid": pid,
                    "process_name": name,
                    "process_username": owner,
                    "normalized_process_name": name_key,
                    "raw_processes": raw_processes,
                }
            )
            self.open_unexpected_processes[name_key] = incident
            incidents.append(dict(incident))

        for name_key, incident in list(self.open_unexpected_processes.items()):
            if name_key in current_names:
                continue
            closed = dict(incident)
            closed["status"] = "resolved"
            closed["resolved_at"] = now_iso()
            closed["needs_evidence"] = False
            closed["summary"] = f"Unexpected process no longer detected: {incident.get('process_name', 'unknown')}"
            incidents.append(closed)
            self.open_unexpected_processes.pop(name_key, None)

        self.known_processes.update(current_names)
        return incidents

    def note_fast_switching(self, snapshot: dict) -> list[dict]:
        rule = self.rules.get("rapid_application_switching", {})
        if not rule or not rule.get("enabled", False):
            self.switches = SwitchTracker()
            return []

        process_name = str(snapshot.get("process_name") or "")
        window_title = str(snapshot.get("window_title") or "")
        window_key = (clean(process_name), clean(window_title))
        if not any(window_key):
            return []

        timestamp = str(snapshot.get("timestamp") or snapshot.get("event_at") or now_iso())
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

        recent = list(self.switches.changes)
        incident = self.new_incident(
            rule,
            "opened",
            f"Rapid application switching detected: {len(recent)} changes in {window_observations} observations",
        )
        incident.update(
            {
                "event_type": "rapid_application_switching",
                "switch_count": len(recent),
                "window_observations": window_observations,
                "recent_switches": recent,
            }
        )
        self.switches.incident_id = incident["incident_id"]
        return [incident]

    def focus_is_bad(self, rule: dict, snapshot: dict) -> bool:
        process_name = clean(snapshot.get("process_name"))
        window_title = clean(snapshot.get("window_title"))
        blocked_processes = {clean(value) for value in rule.get("blocked_process_names", [])}
        blocked_titles = {clean(value) for value in rule.get("blocked_window_titles", [])}
        allowed_processes = {clean(value) for value in rule.get("allowed_process_names", [])}
        allowed_titles = {clean(value) for value in rule.get("allowed_window_titles", [])}

        if process_name and process_name in blocked_processes:
            return True
        if window_title and window_title in blocked_titles:
            return True
        if allowed_processes and not any(allowed in process_name for allowed in allowed_processes):
            return True
        if allowed_titles and not any(allowed in window_title for allowed in allowed_titles):
            return True
        return False

    def note_focus_violation(self, rule: dict, snapshot: dict, window_key: tuple[str, str]) -> list[dict]:
        incidents = []
        if self.focus.window_key != window_key:
            incidents.extend(self.close_focus("Focused window changed to a new violating window."))
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
            "opened",
            f"Focused window out of policy: {process_name} / {window_title}",
        )
        incident["event_type"] = "focused_window_policy"
        incident["process_name"] = process_name
        incident["window_title"] = window_title
        incident["pid"] = int(snapshot.get("process_id") or 0) or None
        self.focus.incident_id = incident["incident_id"]
        incidents.append(incident)
        return incidents

    def note_focus_ok(self, rule: dict, window_key: tuple[str, str]) -> list[dict]:
        self.focus.window_key = window_key
        self.focus.bad_count = 0
        if not self.focus.incident_id:
            self.focus.good_count = 0
            return []

        self.focus.good_count += 1
        resolve_after = max(1, int(rule.get("resolve_after_consecutive", 2) or 2))
        if self.focus.good_count < resolve_after:
            return []
        return self.close_focus("Focused window returned to an allowed state.")

    def close_focus(self, summary: str) -> list[dict]:
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
            "event_at": now_iso(),
            "needs_evidence": False,
        }
        self.focus = FocusTracker()
        return [closed]
