import hashlib
import json
import os
from typing import Iterable

from . import session_state

USERS_FILE = "data/server/server_users.json"
ALLOWED_USERS_FILE = "allowed_users.json"
PROCESS_BLACKLIST_FILE = "data/server/process_blacklist.txt"
EXAM_POLICY_FILE = "data/server/exam_policy.json"
INCIDENTS_FILE = "data/server/incidents.jsonl"
AUDIT_FILE = "data/server/session_audit.jsonl"
SETTINGS_EXPORT_SCHEMA_VERSION = 1

class ServerState:
    def __init__(self):
        self.clients: dict[str, dict] = {}
        self.users_db: dict[str, dict] = {}
        self.allowed_users: dict[str, str] = {}
        self.process_blacklist: list[str] = []
        self.process_blacklist_version: str = ""
        self.exam_policy_config: dict = {}
        self.incidents: list[dict] = []
        self.active_incidents: dict[str, dict] = {}
        self.gui_process = None

    def load_users(self):
        if os.path.exists(USERS_FILE):
            try:
                with open(USERS_FILE, "r") as f:
                    self.users_db = json.load(f)
                for user in self.users_db.values():
                    self.ensure_user_defaults(user)
            except Exception as e:
                print(f"[!] Failed to load {USERS_FILE}: {e}")
                self.users_db = {}
                
        if os.path.exists(ALLOWED_USERS_FILE):
            try:
                with open(ALLOWED_USERS_FILE, "r") as f:
                    self.allowed_users = json.load(f)
            except Exception as e:
                print(f"[!] Failed to load {ALLOWED_USERS_FILE}: {e}")
                self.allowed_users = {}

        self.load_process_blacklist()
        self.load_exam_policy()
        self.load_incidents()

    def save_users(self):
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        try:
            with open(USERS_FILE, "w") as f:
                json.dump(self.users_db, f, indent=2)
        except Exception as e:
            print(f"[!] Failed to save {USERS_FILE}: {e}")

    def load_process_blacklist(self):
        self.ensure_process_blacklist_file()
        try:
            with open(PROCESS_BLACKLIST_FILE, "r", encoding="utf-8") as blacklist_file:
                self.process_blacklist = self._parse_process_blacklist_lines(blacklist_file)
            self.process_blacklist_version = self._blacklist_version_stamp()
        except Exception as e:
            print(f"[!] Failed to load {PROCESS_BLACKLIST_FILE}: {e}")
            self.process_blacklist = []
            self.process_blacklist_version = self._blacklist_version_stamp()

    def ensure_process_blacklist_file(self):
        os.makedirs(os.path.dirname(PROCESS_BLACKLIST_FILE), exist_ok=True)
        if os.path.exists(PROCESS_BLACKLIST_FILE):
            return

        default_lines = [
            "# One process name per line.",
            "# Matching is case-insensitive and checks the process name/basename.",
            "# Example:",
            "# discord.exe",
            "# steam.exe",
            "",
        ]
        try:
            with open(PROCESS_BLACKLIST_FILE, "w", encoding="utf-8") as blacklist_file:
                blacklist_file.write("\n".join(default_lines))
        except Exception as e:
            print(f"[!] Failed to initialize {PROCESS_BLACKLIST_FILE}: {e}")

    def ensure_exam_policy_file(self):
        os.makedirs(os.path.dirname(EXAM_POLICY_FILE), exist_ok=True)
        if os.path.exists(EXAM_POLICY_FILE):
            return

        try:
            with open(EXAM_POLICY_FILE, "w", encoding="utf-8") as policy_file:
                json.dump(self._default_exam_policy_config(), policy_file, indent=2)
        except Exception as e:
            print(f"[!] Failed to initialize {EXAM_POLICY_FILE}: {e}")

    def load_exam_policy(self):
        self.ensure_exam_policy_file()
        try:
            with open(EXAM_POLICY_FILE, "r", encoding="utf-8") as policy_file:
                loaded = json.load(policy_file)
            self.exam_policy_config = self._normalize_exam_policy_config(loaded)
        except Exception as e:
            print(f"[!] Failed to load {EXAM_POLICY_FILE}: {e}")
            self.exam_policy_config = self._default_exam_policy_config()

    def save_exam_policy(self):
        os.makedirs(os.path.dirname(EXAM_POLICY_FILE), exist_ok=True)
        try:
            with open(EXAM_POLICY_FILE, "w", encoding="utf-8") as policy_file:
                json.dump(self.exam_policy_config, policy_file, indent=2)
        except Exception as e:
            print(f"[!] Failed to save {EXAM_POLICY_FILE}: {e}")

    def load_incidents(self):
        self.incidents = []
        self.active_incidents = {}
        if not os.path.exists(INCIDENTS_FILE):
            return

        try:
            with open(INCIDENTS_FILE, "r", encoding="utf-8") as incident_file:
                for raw_line in incident_file:
                    line = raw_line.strip()
                    if not line:
                        continue
                    incident = json.loads(line)
                    if not isinstance(incident, dict):
                        continue
                    self.incidents.append(incident)
                    if incident.get("status") == "resolved":
                        self.active_incidents.pop(str(incident.get("incident_id", "")), None)
                    else:
                        incident_id = str(incident.get("incident_id", "")).strip()
                        if incident_id:
                            self.active_incidents[incident_id] = incident
        except Exception as e:
            print(f"[!] Failed to load {INCIDENTS_FILE}: {e}")
            self.incidents = []
            self.active_incidents = {}

    def ensure_user_defaults(self, user: dict):
        user.setdefault("time_spent_seconds", 0)
        user.setdefault("exam_started", False)
        user.setdefault("exam_finished", False)
        user.setdefault("extra_time_seconds", 0)
        user.setdefault("banned", False)
        user.setdefault("kick_count", 0)
        user.setdefault("last_action", "")
        user.setdefault("computer_name", "")
        user.setdefault("submitted_at", "")
        user.setdefault("submission_name", "")
        user.setdefault("submission_path", "")
        user.setdefault("submission_size_bytes", 0)
        user.setdefault("blacklist_catch_count", 0)
        user.setdefault("last_blacklist_match", [])
        user.setdefault("admin_paused", False)
        user.setdefault("admin_pause_reason", "")
        user.setdefault("admin_paused_at", "")
        user.setdefault("paused_remaining_seconds", 0)
        user.setdefault("applied_policy_version", "")
        user.setdefault("latest_incident_id", "")
        user.setdefault("latest_incident_rule_id", "")
        user.setdefault("latest_incident_severity", "")
        user.setdefault("latest_incident_status", "")
        user.setdefault("latest_incident_summary", "")
        user.setdefault("latest_incident_artifact_path", "")
        session_state.ensure_defaults(user)

    def is_valid_session_uuid(self, client_id: str) -> bool:
        return any(user.get("uuid") == client_id for user in self.users_db.values())

    def find_user_by_uuid(self, client_id: str):
        for login_id, user in self.users_db.items():
            if user.get("uuid") == client_id:
                return login_id, user
        return None, None

    def get_gui_process(self):
        process = self.gui_process
        if process and process.poll() is None:
            return process
        return None

    def resolve_user(self, target: str):
        if target in self.users_db:
            return target, self.users_db[target]

        login_id, user = self.find_user_by_uuid(target)
        if user:
            return login_id, user

        client_id, _ = self.resolve_client(target)
        if client_id:
            return self.find_user_by_uuid(client_id)

        return None, None

    def resolve_client(self, target: str):
        """
        Find a client by:
        1. Full UUID
        2. Short ID (first 8 chars)
        3. IP Address
        Returns (full_id, client_data) or (None, None)
        """
        # 1. Check Full ID
        if target in self.clients:
            return target, self.clients[target]

        # 2. Check Short ID and IP
        for cid, data in self.clients.items():
            if data["short_id"] == target or data["ip"] == target:
                return cid, data

        return None, None

    def blacklist_payload(self) -> dict:
        return {
            "entries": list(self.process_blacklist),
            "version": self.process_blacklist_version,
        }

    def session_policy(self) -> dict:
        return dict(self.exam_policy_config.get("session", {}))

    def operator_defaults(self) -> dict:
        return dict(self.exam_policy_config.get("operator_defaults", {}))

    def remember_settings_enabled(self) -> bool:
        return bool(self.session_policy().get("remember_settings", True))

    def rule_config(self, rule_id: str) -> dict:
        if rule_id == "process_blacklist":
            return dict(self.exam_policy_config.get("rules", {}).get("process_blacklist", {}))
        if rule_id == "focused_window_policy":
            return dict(self.exam_policy_config.get("rules", {}).get("focused_window", {}))
        return {}

    def current_exam_policy(self) -> dict:
        rules_config = self.exam_policy_config.get("rules", {})
        process_blacklist = rules_config.get("process_blacklist", {})
        focused_window = rules_config.get("focused_window", {})
        payload = {
            "policy_version": "",
            "session": dict(self.exam_policy_config.get("session", {})),
            "operator_defaults": dict(self.exam_policy_config.get("operator_defaults", {})),
            "rules": [
                {
                    "rule_id": "process_blacklist",
                    "source": "process_monitor",
                    "type": "process_blacklist",
                    "enabled": bool(process_blacklist.get("enabled", True)),
                    "severity": str(process_blacklist.get("severity", "violation")),
                    "entries": list(self.process_blacklist),
                    "blacklist_version": self.process_blacklist_version,
                    "auto_violation_pause": bool(process_blacklist.get("auto_violation_pause", True)),
                    "allow_remote_kill": bool(process_blacklist.get("allow_remote_kill", True)),
                },
                {
                    "rule_id": "focused_window_policy",
                    "source": "focused_window",
                    "type": "focused_window",
                    "enabled": bool(focused_window.get("enabled", False)),
                    "severity": str(focused_window.get("severity", "warning")),
                    "allowed_process_names": list(focused_window.get("allowed_process_names", [])),
                    "allowed_window_titles": list(focused_window.get("allowed_window_titles", [])),
                    "blocked_process_names": list(focused_window.get("blocked_process_names", [])),
                    "blocked_window_titles": list(focused_window.get("blocked_window_titles", [])),
                    "open_after_consecutive": int(focused_window.get("open_after_consecutive", 3)),
                    "resolve_after_consecutive": int(focused_window.get("resolve_after_consecutive", 2)),
                    "auto_violation_pause": bool(focused_window.get("auto_violation_pause", False)),
                },
            ],
        }
        payload["policy_version"] = self._policy_version(payload)
        return payload

    def append_incident(self, incident: dict):
        os.makedirs(os.path.dirname(INCIDENTS_FILE), exist_ok=True)
        incident_id = str(incident.get("incident_id", "")).strip()
        if incident_id:
            if incident.get("status") == "resolved":
                self.active_incidents.pop(incident_id, None)
            else:
                self.active_incidents[incident_id] = incident
        self.incidents.append(incident)

        try:
            with open(INCIDENTS_FILE, "a", encoding="utf-8") as incident_file:
                incident_file.write(json.dumps(incident, ensure_ascii=True) + "\n")
        except Exception as e:
            print(f"[!] Failed to append {INCIDENTS_FILE}: {e}")

    def append_audit(self, entry: dict):
        os.makedirs(os.path.dirname(AUDIT_FILE), exist_ok=True)
        try:
            with open(AUDIT_FILE, "a", encoding="utf-8") as audit_file:
                audit_file.write(json.dumps(entry, ensure_ascii=True) + "\n")
        except Exception as e:
            print(f"[!] Failed to append {AUDIT_FILE}: {e}")

    def save_process_blacklist(self):
        self.ensure_process_blacklist_file()
        try:
            with open(PROCESS_BLACKLIST_FILE, "w", encoding="utf-8") as blacklist_file:
                for entry in self.process_blacklist:
                    blacklist_file.write(f"{entry}\n")
            self.process_blacklist_version = self._blacklist_version_stamp()
        except Exception as e:
            print(f"[!] Failed to save {PROCESS_BLACKLIST_FILE}: {e}")

    def settings_bundle(self) -> dict:
        bundle = {
            "schema_version": SETTINGS_EXPORT_SCHEMA_VERSION,
            "exam_policy": self.exam_policy_config,
            "process_blacklist": {
                "entries": list(self.process_blacklist),
                "version": self.process_blacklist_version,
            },
            "operator_defaults": dict(self.exam_policy_config.get("operator_defaults", {})),
        }
        return bundle

    def export_settings_bundle(self, path: str):
        with open(path, "w", encoding="utf-8") as settings_file:
            json.dump(self.settings_bundle(), settings_file, indent=2)

    def import_settings_bundle(self, path: str):
        with open(path, "r", encoding="utf-8") as settings_file:
            bundle = json.load(settings_file)
        if not isinstance(bundle, dict):
            raise ValueError("settings bundle must be a JSON object")

        policy = bundle.get("exam_policy", bundle)
        operator_defaults = bundle.get("operator_defaults")
        normalized = self._normalize_exam_policy_config(policy)
        if isinstance(operator_defaults, dict):
            normalized["operator_defaults"].update(
                self._normalize_exam_policy_config({"operator_defaults": operator_defaults}).get(
                    "operator_defaults",
                    {},
                )
            )
        self.exam_policy_config = normalized

        blacklist = bundle.get("process_blacklist", {})
        if isinstance(blacklist, dict):
            self.process_blacklist = self._parse_process_blacklist_lines(
                [str(entry) for entry in blacklist.get("entries", [])]
            )
        elif isinstance(blacklist, list):
            self.process_blacklist = self._parse_process_blacklist_lines([str(entry) for entry in blacklist])
        else:
            self.process_blacklist = []

        self.save_exam_policy()
        self.save_process_blacklist()

    def _parse_process_blacklist_lines(self, lines: Iterable[str]) -> list[str]:
        entries = []
        seen = set()
        for raw_line in lines:
            entry = raw_line.strip()
            if not entry or entry.startswith("#"):
                continue
            normalized = entry.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            entries.append(entry)
        return entries

    def _blacklist_version_stamp(self) -> str:
        try:
            return str(os.stat(PROCESS_BLACKLIST_FILE).st_mtime_ns)
        except OSError:
            return "0"

    def _default_exam_policy_config(self) -> dict:
        return {
            "session": {
                "auto_resume_on_reconnect": True,
                "remember_settings": True,
            },
            "rules": {
                "process_blacklist": {
                    "enabled": True,
                    "severity": "violation",
                    "auto_violation_pause": True,
                    "allow_remote_kill": True,
                },
                "focused_window": {
                    "enabled": False,
                    "severity": "warning",
                    "allowed_process_names": [],
                    "allowed_window_titles": [],
                    "blocked_process_names": [],
                    "blocked_window_titles": [],
                    "open_after_consecutive": 3,
                    "resolve_after_consecutive": 2,
                    "auto_violation_pause": False,
                },
            },
            "operator_defaults": {
                "confirm_kill_pid": True,
                "confirm_kick": True,
                "confirm_ban": True,
                "confirm_pause": True,
            },
        }

    def _normalize_exam_policy_config(self, config: dict) -> dict:
        normalized = self._default_exam_policy_config()
        if not isinstance(config, dict):
            return normalized

        session_config = config.get("session", {})
        if isinstance(session_config, dict):
            normalized["session"]["auto_resume_on_reconnect"] = bool(
                session_config.get("auto_resume_on_reconnect", True)
            )
            normalized["session"]["remember_settings"] = bool(
                session_config.get("remember_settings", True)
            )

        operator_defaults = config.get("operator_defaults", {})
        if isinstance(operator_defaults, dict):
            normalized["operator_defaults"]["confirm_kill_pid"] = bool(
                operator_defaults.get("confirm_kill_pid", True)
            )
            normalized["operator_defaults"]["confirm_kick"] = bool(
                operator_defaults.get("confirm_kick", True)
            )
            normalized["operator_defaults"]["confirm_ban"] = bool(
                operator_defaults.get("confirm_ban", True)
            )
            normalized["operator_defaults"]["confirm_pause"] = bool(
                operator_defaults.get("confirm_pause", True)
            )

        rules = config.get("rules", {})
        if isinstance(rules, dict):
            process_blacklist = rules.get("process_blacklist", {})
            if isinstance(process_blacklist, dict):
                normalized["rules"]["process_blacklist"]["enabled"] = bool(
                    process_blacklist.get("enabled", True)
                )
                normalized["rules"]["process_blacklist"]["severity"] = str(
                    process_blacklist.get(
                        "severity",
                        normalized["rules"]["process_blacklist"]["severity"],
                    )
                )
                normalized["rules"]["process_blacklist"]["auto_violation_pause"] = bool(
                    process_blacklist.get("auto_violation_pause", True)
                )
                normalized["rules"]["process_blacklist"]["allow_remote_kill"] = bool(
                    process_blacklist.get("allow_remote_kill", True)
                )

            focused_window = rules.get("focused_window", {})
        else:
            focused_window = {}

        legacy_focused_window = config.get("focused_window", {})
        if not focused_window and isinstance(legacy_focused_window, dict):
            focused_window = legacy_focused_window
        if isinstance(focused_window, dict):
            normalized["rules"]["focused_window"]["enabled"] = bool(focused_window.get("enabled", False))
            normalized["rules"]["focused_window"]["severity"] = str(
                focused_window.get("severity", normalized["rules"]["focused_window"]["severity"])
            )
            normalized["rules"]["focused_window"]["allowed_process_names"] = self._string_list(
                focused_window.get("allowed_process_names", [])
            )
            normalized["rules"]["focused_window"]["allowed_window_titles"] = self._string_list(
                focused_window.get("allowed_window_titles", [])
            )
            normalized["rules"]["focused_window"]["blocked_process_names"] = self._string_list(
                focused_window.get("blocked_process_names", [])
            )
            normalized["rules"]["focused_window"]["blocked_window_titles"] = self._string_list(
                focused_window.get("blocked_window_titles", [])
            )
            normalized["rules"]["focused_window"]["open_after_consecutive"] = max(
                1,
                int(focused_window.get("open_after_consecutive", 3) or 3),
            )
            normalized["rules"]["focused_window"]["resolve_after_consecutive"] = max(
                1,
                int(focused_window.get("resolve_after_consecutive", 2) or 2),
            )
            normalized["rules"]["focused_window"]["auto_violation_pause"] = bool(
                focused_window.get("auto_violation_pause", False)
            )
        return normalized

    def _policy_version(self, payload: dict) -> str:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    def _string_list(self, values) -> list[str]:
        if not isinstance(values, list):
            return []
        return [str(value).strip() for value in values if str(value).strip()]

state = ServerState()
