import socket

from incident_engine import IncidentEngine


EXAM_APP_KEYWORD = "python"
BANNED_APPS = ["discord", "telegram", "whatsapp", "teams", "chrome", "firefox", "edge", "brave"]
IDLE_ALERT_THRESHOLD = 80
IDLE_DANGER_THRESHOLD = 150


def default_policy() -> dict:
    return {
        "policy_version": "mytask-baris-compatible-v1",
        "rules": [
            {
                "rule_id": "process_blacklist",
                "source": "activity_monitor",
                "type": "process_blacklist",
                "enabled": True,
                "severity": "violation",
                "entries": list(BANNED_APPS),
                "process_usernames": [],
            },
            {
                "rule_id": "focused_window_policy",
                "source": "activity_monitor",
                "type": "focused_window",
                "enabled": True,
                "severity": "warning",
                "allowed_process_names": [EXAM_APP_KEYWORD],
                "allowed_window_titles": [],
                "blocked_process_names": [],
                "blocked_window_titles": [],
                "open_after_consecutive": 3,
                "resolve_after_consecutive": 2,
            },
            {
                "rule_id": "rapid_application_switching",
                "source": "activity_monitor",
                "type": "rapid_application_switching",
                "enabled": True,
                "severity": "warning",
                "max_switches": 4,
                "window_observations": 6,
            },
            {
                "rule_id": "unexpected_process",
                "source": "activity_monitor",
                "type": "unexpected_process",
                "enabled": True,
                "severity": "warning",
                "known_process_names": [EXAM_APP_KEYWORD, "pythonw"],
                "allowed_process_names": list(BANNED_APPS),
            },
        ],
    }


class MytaskPayloadAdapter:
    """Wraps Baris-style activity snapshots with mytask incident detection."""

    def __init__(self, student_id: str, student_name: str, policy: dict | None = None):
        self.student_id = student_id
        self.student_name = student_name
        self.hostname = socket.gethostname()
        self.engine = IncidentEngine()
        ok, reason = self.engine.apply_policy(policy or default_policy())
        if not ok:
            raise ValueError(f"invalid monitoring policy: {reason}")

    def build_from_snapshot(self, snapshot: dict) -> dict:
        open_processes = list(snapshot.get("open_processes", []))
        active_window = str(snapshot.get("active_window") or "Unknown")
        idle_seconds = float(snapshot.get("idle_seconds", -1))
        process_entries = self.process_entries(snapshot)
        exam_running = self.exam_is_running(open_processes)

        old_flags = self.legacy_flags(
            active_window=active_window,
            open_processes=open_processes,
            exam_running=exam_running,
            idle_seconds=idle_seconds,
        )

        incidents = []
        incidents.extend(self.engine.watch_processes(process_entries))
        incidents.extend(
            self.engine.watch_window(
                {
                    "process_name": active_window,
                    "window_title": active_window,
                    "timestamp": snapshot.get("captured_at"),
                }
            )
        )

        flags = self.merge_flags(old_flags, self.incident_flags(incidents))

        return {
            "student_id": self.student_id,
            "student_name": self.student_name,
            "hostname": self.hostname,
            "timestamp": snapshot.get("captured_at"),
            "active_window": active_window,
            "open_apps": self.notable_apps(open_processes),
            "exam_running": exam_running,
            "idle_seconds": idle_seconds,
            "flags": flags,
            "incidents": incidents,
            "processes": [
                {"pid": pid, "process_name": name, "process_username": owner}
                for pid, name, owner in sorted(process_entries, key=lambda item: (item[1].lower(), item[0]))
            ],
        }

    def sender_details(self, payload: dict) -> dict:
        """Extra details a caller may merge into Baris NetworkSender's security.details."""
        return {
            "incidents": payload.get("incidents", []),
            "processes": payload.get("processes", []),
        }

    def process_entries(self, snapshot: dict) -> set[tuple[int, str, str | None]]:
        raw_processes = snapshot.get("processes", [])
        entries = set()

        if raw_processes:
            for process in raw_processes:
                try:
                    pid = int(process.get("pid"))
                except (AttributeError, TypeError, ValueError):
                    continue
                name = str(process.get("name") or process.get("process_name") or "").strip()
                if not name:
                    continue
                owner = process.get("username", process.get("process_username"))
                entries.add((pid, name, str(owner) if owner else None))
            return entries

        for index, name in enumerate(snapshot.get("open_processes", []), start=1):
            entries.add((index, str(name), None))
        return entries

    def legacy_flags(
        self,
        *,
        active_window: str,
        open_processes: list[str],
        exam_running: bool,
        idle_seconds: float,
    ) -> list[str]:
        flags = []
        if not exam_running:
            flags.append("EXAM_CLOSED")
        if exam_running and not self.window_is_exam(active_window):
            flags.append("FOCUS_LOST")
        for process in open_processes:
            for banned in BANNED_APPS:
                if banned in process:
                    flags.append(f"BANNED:{process}")
                    break
        if idle_seconds >= IDLE_DANGER_THRESHOLD:
            flags.append("IDLE_CRITICAL")
        elif idle_seconds >= IDLE_ALERT_THRESHOLD:
            flags.append("IDLE_WARN")
        return flags

    def incident_flags(self, incidents: list[dict]) -> list[str]:
        flags = []
        for incident in incidents:
            if incident.get("status") != "opened":
                continue
            rule_id = str(incident.get("rule_id") or incident.get("event_type") or "incident")
            flag = rule_id.upper()
            process_name = incident.get("process_name")
            if process_name:
                flag = f"{flag}:{process_name}"
            flags.append(flag)
        return flags

    def merge_flags(self, *groups: list[str]) -> list[str]:
        merged = []
        seen = set()
        for group in groups:
            for flag in group:
                if flag in seen:
                    continue
                seen.add(flag)
                merged.append(flag)
        return merged

    def exam_is_running(self, processes: list[str]) -> bool:
        return any(EXAM_APP_KEYWORD in process for process in processes)

    def window_is_exam(self, title: str) -> bool:
        return EXAM_APP_KEYWORD in title.lower()

    def notable_apps(self, processes: list[str]) -> list[str]:
        skip_prefixes = [
            "kworker",
            "kthread",
            "migration",
            "rcu_",
            "ksoftirq",
            "watchdog",
            "cpuhp",
            "netns",
            "khugepaged",
            "svchost",
        ]
        return [
            process
            for process in processes
            if process and not any(process.startswith(prefix) for prefix in skip_prefixes)
        ][:20]
