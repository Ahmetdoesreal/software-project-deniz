import hashlib
import json
import os
from typing import Iterable

from common.process_definitions import normalize_definitions
from common.incident_rules import default_incident_rules, normalize_incident_rules

from . import session_state

USERS_FILE = "data/server/server_users.json"
ALLOWED_USERS_FILE = "allowed_users.json"
PROCESS_BLACKLIST_FILE = "data/server/process_blacklist.txt"
EXAM_POLICY_FILE = "data/server/exam_policy.json"
PROCESS_DEFINITIONS_FILE = "data/server/process_definitions.json"
INCIDENT_RULES_FILE = "data/server/incident_rules.json"
INCIDENTS_FILE = "data/server/incidents.jsonl"
AUDIT_FILE = "data/server/session_audit.jsonl"
SETTINGS_EXPORT_SCHEMA_VERSION = 1

class ServerState:
    def __init__(self):
        self.clients: dict[str, dict] = {}
        self.users_db: dict[str, dict] = {}
        self.allowed_users: set[str] = set()
        self.process_blacklist: list[str] = []
        self.process_blacklist_version: str = ""
        self.process_definitions: list[dict] = []
        self.process_definitions_version: str = ""
        self.incident_rules: list[dict] = []
        self.incident_rules_version: str = ""
        self.exam_policy_config: dict = {}
        self.incidents: list[dict] = []
        self.active_incidents: dict[str, dict] = {}
        self.gui_process = None
        self.gui_ipc_server = None

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
                    raw = json.load(f)
                # Accept both a list ["id1","id2"] and the old dict {"id1":"pw",...}
                if isinstance(raw, list):
                    self.allowed_users = set(raw)
                elif isinstance(raw, dict):
                    self.allowed_users = set(raw.keys())
                else:
                    self.allowed_users = set()
            except Exception as e:
                print(f"[!] Failed to load {ALLOWED_USERS_FILE}: {e}")
                self.allowed_users = set()

        self.load_process_blacklist()
        self.load_exam_policy()
        self.load_process_definitions()
        self.load_incident_rules()
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
                json.dump(self._policy_without_process_definitions(), policy_file, indent=2)
        except Exception as e:
            print(f"[!] Failed to save {EXAM_POLICY_FILE}: {e}")

    def ensure_process_definitions_file(self):
        os.makedirs(os.path.dirname(PROCESS_DEFINITIONS_FILE), exist_ok=True)
        if os.path.exists(PROCESS_DEFINITIONS_FILE):
            return

        try:
            with open(PROCESS_DEFINITIONS_FILE, "w", encoding="utf-8") as definitions_file:
                json.dump([], definitions_file, indent=2)
        except Exception as e:
            print(f"[!] Failed to initialize {PROCESS_DEFINITIONS_FILE}: {e}")

    def load_process_definitions(self):
        embedded_definitions = self._embedded_process_definitions()
        if embedded_definitions and not os.path.exists(PROCESS_DEFINITIONS_FILE):
            self.process_definitions = embedded_definitions
            self.save_process_definitions()
            self._remove_embedded_process_definitions()
            self.save_exam_policy()
            return

        self.ensure_process_definitions_file()
        try:
            with open(PROCESS_DEFINITIONS_FILE, "r", encoding="utf-8") as definitions_file:
                loaded = json.load(definitions_file)
            if isinstance(loaded, dict):
                loaded = loaded.get("entries", [])
            self.process_definitions = normalize_definitions(loaded)
            self.process_definitions_version = self._process_definitions_version_stamp()
            self._remove_embedded_process_definitions()
        except Exception as e:
            print(f"[!] Failed to load {PROCESS_DEFINITIONS_FILE}: {e}")
            self.process_definitions = []
            self.process_definitions_version = self._process_definitions_version_stamp()

    def save_process_definitions(self):
        self.ensure_process_definitions_file()
        try:
            with open(PROCESS_DEFINITIONS_FILE, "w", encoding="utf-8") as definitions_file:
                json.dump(normalize_definitions(self.process_definitions), definitions_file, indent=2)
            self.process_definitions_version = self._process_definitions_version_stamp()
        except Exception as e:
            print(f"[!] Failed to save {PROCESS_DEFINITIONS_FILE}: {e}")

    def ensure_incident_rules_file(self):
        os.makedirs(os.path.dirname(INCIDENT_RULES_FILE), exist_ok=True)
        if os.path.exists(INCIDENT_RULES_FILE):
            return

        try:
            with open(INCIDENT_RULES_FILE, "w", encoding="utf-8") as rules_file:
                json.dump(default_incident_rules(), rules_file, indent=2)
        except Exception as e:
            print(f"[!] Failed to initialize {INCIDENT_RULES_FILE}: {e}")

    def load_incident_rules(self):
        embedded_rules = self._embedded_incident_rules()
        if embedded_rules and not os.path.exists(INCIDENT_RULES_FILE):
            self.incident_rules = embedded_rules
            self.save_incident_rules()
            self._remove_embedded_incident_rules()
            self.save_exam_policy()
            return

        self.ensure_incident_rules_file()
        try:
            with open(INCIDENT_RULES_FILE, "r", encoding="utf-8") as rules_file:
                loaded = json.load(rules_file)
            if isinstance(loaded, dict):
                loaded = loaded.get("entries", [])
            normalized = normalize_incident_rules(loaded)
            self.incident_rules = normalized or default_incident_rules()
            if not normalized:
                self.save_incident_rules()
            else:
                self.incident_rules_version = self._incident_rules_version_stamp()
            self._remove_embedded_incident_rules()
        except Exception as e:
            print(f"[!] Failed to load {INCIDENT_RULES_FILE}: {e}")
            self.incident_rules = default_incident_rules()
            self.incident_rules_version = self._incident_rules_version_stamp()

    def save_incident_rules(self):
        self.ensure_incident_rules_file()
        try:
            with open(INCIDENT_RULES_FILE, "w", encoding="utf-8") as rules_file:
                json.dump(normalize_incident_rules(self.incident_rules), rules_file, indent=2)
            self.incident_rules_version = self._incident_rules_version_stamp()
        except Exception as e:
            print(f"[!] Failed to save {INCIDENT_RULES_FILE}: {e}")

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
        user.setdefault("exam_folder_path", "")
        user.setdefault("exam_files_zip_path", "")
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
        user.setdefault("last_focus_event_at", "")
        user.setdefault("last_focus_event_type", "")
        user.setdefault("last_focus_severity", "")
        user.setdefault("last_focus_process", "")
        user.setdefault("last_focus_window", "")
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
        if rule_id == "process_definitions":
            config = dict(self.exam_policy_config.get("rules", {}).get("process_definitions", {}))
            config["definitions"] = self._current_process_definitions()
            return config
        if rule_id == "incident_rules":
            config = dict(self.exam_policy_config.get("rules", {}).get("incident_rules", {}))
            config["definitions"] = self._current_incident_rules()
            return config
        if rule_id == "process_path_clarification":
            return dict(self.exam_policy_config.get("rules", {}).get("process_path_clarification", {}))
        if rule_id == "focused_window_policy":
            return dict(self.exam_policy_config.get("rules", {}).get("focused_window", {}))
        if rule_id == "rapid_application_switching":
            return dict(self.exam_policy_config.get("rules", {}).get("rapid_application_switching", {}))
        if rule_id == "idle_policy":
            return dict(self.exam_policy_config.get("rules", {}).get("idle_policy", {}))
        if rule_id == "unexpected_process":
            return dict(self.exam_policy_config.get("rules", {}).get("unexpected_process", {}))
        return {}

    def current_exam_policy(self) -> dict:
        rules_config = self.exam_policy_config.get("rules", {})
        process_blacklist = rules_config.get("process_blacklist", {})
        focused_window = rules_config.get("focused_window", {})
        rapid_switching = rules_config.get("rapid_application_switching", {})
        idle_policy = rules_config.get("idle_policy", {})
        unexpected_process = rules_config.get("unexpected_process", {})
        process_definitions = self.rule_config("process_definitions")
        incident_rules = self.rule_config("incident_rules")
        process_path_clarification = rules_config.get("process_path_clarification", {})
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
                    "process_usernames": list(process_blacklist.get("process_usernames", [])),
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
                    "window_title_match_mode": str(focused_window.get("window_title_match_mode", "contains")),
                    "open_after_consecutive": int(focused_window.get("open_after_consecutive", 3)),
                    "resolve_after_consecutive": int(focused_window.get("resolve_after_consecutive", 2)),
                    "auto_violation_pause": bool(focused_window.get("auto_violation_pause", False)),
                },
                {
                    "rule_id": "rapid_application_switching",
                    "source": "focused_window",
                    "type": "rapid_application_switching",
                    "enabled": bool(rapid_switching.get("enabled", False)),
                    "severity": str(rapid_switching.get("severity", "warning")),
                    "max_switches": int(rapid_switching.get("max_switches", 10)),
                    "window_seconds": int(float(rapid_switching.get("window_seconds", 60) or 60)),
                    "window_observations": int(rapid_switching.get("window_observations", 10)),
                    "auto_violation_pause": bool(rapid_switching.get("auto_violation_pause", False)),
                },
                {
                    "rule_id": "idle_policy",
                    "source": "idle_monitor",
                    "type": "idle_policy",
                    "enabled": bool(idle_policy.get("enabled", False)),
                    "severity": str(idle_policy.get("severity", "warning")),
                    "warn_threshold_seconds": int(float(idle_policy.get("warn_threshold_seconds", 80) or 80)),
                    "critical_threshold_seconds": int(float(idle_policy.get("critical_threshold_seconds", 150) or 150)),
                    "auto_violation_pause": bool(idle_policy.get("auto_violation_pause", False)),
                },
                {
                    "rule_id": "unexpected_process",
                    "source": "process_monitor",
                    "type": "unexpected_process",
                    "enabled": bool(unexpected_process.get("enabled", False)),
                    "severity": str(unexpected_process.get("severity", "warning")),
                    "known_process_names": list(unexpected_process.get("known_process_names", [])),
                    "known_directory_paths": list(unexpected_process.get("known_directory_paths", [])),
                    "allowed_process_names": list(unexpected_process.get("allowed_process_names", [])),
                    "baseline_existing_processes": bool(unexpected_process.get("baseline_existing_processes", False)),
                    "auto_violation_pause": bool(unexpected_process.get("auto_violation_pause", False)),
                },
                {
                    "rule_id": "process_definitions",
                    "source": "process_monitor",
                    "type": "process_definitions",
                    "enabled": bool(process_definitions.get("enabled", True)),
                    "severity": str(process_definitions.get("severity", "violation")),
                    "definitions": normalize_definitions(process_definitions.get("definitions", [])),
                    "detect_unknown_processes": bool(process_definitions.get("detect_unknown_processes", True)),
                    "unknown_severity": str(process_definitions.get("unknown_severity", "warning")),
                    "baseline_existing_processes": bool(process_definitions.get("baseline_existing_processes", True)),
                    "auto_violation_pause": bool(process_definitions.get("auto_violation_pause", False)),
                    "allow_remote_kill": bool(process_definitions.get("allow_remote_kill", True)),
                },
                {
                    "rule_id": "incident_rules",
                    "source": "server_policy",
                    "type": "incident_rules",
                    "enabled": bool(incident_rules.get("enabled", True)),
                    "severity": str(incident_rules.get("severity", "warning")),
                    "definitions": normalize_incident_rules(incident_rules.get("definitions", [])),
                    "auto_violation_pause": bool(incident_rules.get("auto_violation_pause", False)),
                    "allow_remote_kill": bool(incident_rules.get("allow_remote_kill", True)),
                },
                {
                    "rule_id": "process_path_clarification",
                    "source": "process_monitor",
                    "type": "process_path_clarification",
                    "enabled": bool(process_path_clarification.get("enabled", True)),
                    "severity": str(process_path_clarification.get("severity", "warning")),
                    "auto_violation_pause": bool(process_path_clarification.get("auto_violation_pause", False)),
                    "allow_remote_kill": bool(process_path_clarification.get("allow_remote_kill", True)),
                },
            ],
        }
        payload["policy_version"] = self._policy_version(payload)
        return payload

    def append_incident(self, incident: dict):
        os.makedirs(os.path.dirname(INCIDENTS_FILE), exist_ok=True)
        incident_id = str(incident.get("incident_id", "")).strip()
        if incident_id:
            status = str(incident.get("status", "") or "")
            if status == "resolved":
                self.active_incidents.pop(incident_id, None)
            elif status in {"evidence_uploaded", "evidence_failed"} and incident_id in self.active_incidents:
                self.active_incidents[incident_id].update(
                    {
                        key: incident[key]
                        for key in (
                            "artifact_path",
                            "evidence_status",
                            "evidence_upload_failed",
                            "evidence_retry",
                        )
                        if key in incident
                    }
                )
            else:
                self.active_incidents[incident_id] = incident
        self.incidents.append(incident)

        try:
            with open(INCIDENTS_FILE, "a", encoding="utf-8") as incident_file:
                incident_file.write(json.dumps(incident, ensure_ascii=True) + "\n")
        except Exception as e:
            print(f"[!] Failed to append {INCIDENTS_FILE}: {e}")

    def save_incidents(self):
        os.makedirs(os.path.dirname(INCIDENTS_FILE), exist_ok=True)
        try:
            with open(INCIDENTS_FILE, "w", encoding="utf-8") as incident_file:
                for incident in self.incidents:
                    incident_file.write(json.dumps(incident, ensure_ascii=True) + "\n")
        except Exception as e:
            print(f"[!] Failed to save {INCIDENTS_FILE}: {e}")

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
            "exam_policy": self._policy_without_process_definitions(),
            "process_blacklist": {
                "entries": list(self.process_blacklist),
                "version": self.process_blacklist_version,
            },
            "process_definitions": {
                "entries": self._current_process_definitions(),
                "version": self.process_definitions_version,
            },
            "incident_rules": {
                "entries": self._current_incident_rules(),
                "version": self.incident_rules_version,
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

        definitions_payload = bundle.get("process_definitions")
        if isinstance(definitions_payload, dict):
            self.process_definitions = normalize_definitions(definitions_payload.get("entries", []))
        elif isinstance(definitions_payload, list):
            self.process_definitions = normalize_definitions(definitions_payload)
        else:
            self.process_definitions = self._embedded_process_definitions(normalized)
        self._remove_embedded_process_definitions()

        incident_rules_payload = bundle.get("incident_rules")
        if isinstance(incident_rules_payload, dict):
            self.incident_rules = normalize_incident_rules(incident_rules_payload.get("entries", []))
        elif isinstance(incident_rules_payload, list):
            self.incident_rules = normalize_incident_rules(incident_rules_payload)
        else:
            self.incident_rules = self._embedded_incident_rules(normalized)
        if not self.incident_rules:
            self.incident_rules = default_incident_rules()
        self._remove_embedded_incident_rules()

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
        self.save_process_definitions()
        self.save_incident_rules()

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

    def _process_definitions_version_stamp(self) -> str:
        try:
            return str(os.stat(PROCESS_DEFINITIONS_FILE).st_mtime_ns)
        except OSError:
            return "0"

    def _incident_rules_version_stamp(self) -> str:
        try:
            return str(os.stat(INCIDENT_RULES_FILE).st_mtime_ns)
        except OSError:
            return "0"

    def _embedded_process_definitions(self, policy: dict | None = None) -> list[dict]:
        source = policy if isinstance(policy, dict) else self.exam_policy_config
        return normalize_definitions(
            source.get("rules", {})
            .get("process_definitions", {})
            .get("definitions", [])
        )

    def _current_process_definitions(self) -> list[dict]:
        embedded_definitions = self._embedded_process_definitions()
        if embedded_definitions:
            return embedded_definitions
        return normalize_definitions(self.process_definitions)

    def _embedded_incident_rules(self, policy: dict | None = None) -> list[dict]:
        source = policy if isinstance(policy, dict) else self.exam_policy_config
        return normalize_incident_rules(
            source.get("rules", {})
            .get("incident_rules", {})
            .get("definitions", [])
        )

    def _current_incident_rules(self) -> list[dict]:
        embedded_rules = self._embedded_incident_rules()
        if embedded_rules:
            return embedded_rules
        return normalize_incident_rules(self.incident_rules)

    def _remove_embedded_process_definitions(self):
        rules = self.exam_policy_config.get("rules", {})
        if not isinstance(rules, dict):
            return
        process_definitions = rules.get("process_definitions", {})
        if isinstance(process_definitions, dict):
            process_definitions.pop("definitions", None)

    def _remove_embedded_incident_rules(self):
        rules = self.exam_policy_config.get("rules", {})
        if not isinstance(rules, dict):
            return
        incident_rules = rules.get("incident_rules", {})
        if isinstance(incident_rules, dict):
            incident_rules.pop("definitions", None)

    def _policy_without_process_definitions(self, policy: dict | None = None) -> dict:
        source = policy if isinstance(policy, dict) else self.exam_policy_config
        policy_copy = json.loads(json.dumps(source))
        rules = policy_copy.get("rules", {})
        if isinstance(rules, dict):
            process_definitions = rules.get("process_definitions", {})
            if isinstance(process_definitions, dict):
                process_definitions.pop("definitions", None)
            incident_rules = rules.get("incident_rules", {})
            if isinstance(incident_rules, dict):
                incident_rules.pop("definitions", None)
        return policy_copy

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
                    "process_usernames": [],
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
                    "window_title_match_mode": "contains",
                    "open_after_consecutive": 3,
                    "resolve_after_consecutive": 2,
                    "auto_violation_pause": False,
                },
                "rapid_application_switching": {
                    "enabled": False,
                    "severity": "warning",
                    "max_switches": 10,
                    "window_seconds": 60,
                    "window_observations": 10,
                    "auto_violation_pause": False,
                },
                "idle_policy": {
                    "enabled": False,
                    "severity": "warning",
                    "warn_threshold_seconds": 80,
                    "critical_threshold_seconds": 150,
                    "auto_violation_pause": False,
                },
                "unexpected_process": {
                    "enabled": False,
                    "severity": "warning",
                    "known_process_names": [],
                    "known_directory_paths": [],
                    "allowed_process_names": [],
                    "baseline_existing_processes": False,
                    "auto_violation_pause": False,
                },
                "process_definitions": {
                    "enabled": True,
                    "severity": "violation",
                    "detect_unknown_processes": True,
                    "unknown_severity": "warning",
                    "baseline_existing_processes": True,
                    "auto_violation_pause": False,
                    "allow_remote_kill": True,
                },
                "incident_rules": {
                    "enabled": True,
                    "severity": "warning",
                    "auto_violation_pause": False,
                    "allow_remote_kill": True,
                },
                "process_path_clarification": {
                    "enabled": True,
                    "severity": "warning",
                    "auto_violation_pause": False,
                    "allow_remote_kill": True,
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
                normalized["rules"]["process_blacklist"]["process_usernames"] = [
                    str(username).strip()
                    for username in process_blacklist.get("process_usernames", [])
                    if str(username).strip()
                ]

            focused_window = rules.get("focused_window", {})
            rapid_switching = rules.get("rapid_application_switching", {})
            idle_policy = rules.get("idle_policy", {})
            unexpected_process = rules.get("unexpected_process", {})
            process_definitions = rules.get("process_definitions", {})
            incident_rules = rules.get("incident_rules", {})
            process_path_clarification = rules.get("process_path_clarification", {})
        else:
            focused_window = {}
            rapid_switching = {}
            idle_policy = {}
            unexpected_process = {}
            process_definitions = {}
            incident_rules = {}
            process_path_clarification = {}

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
            match_mode = str(focused_window.get("window_title_match_mode", "contains")).strip().lower()
            if match_mode not in {"contains", "exact"}:
                match_mode = "contains"
            normalized["rules"]["focused_window"]["window_title_match_mode"] = match_mode
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
        if isinstance(rapid_switching, dict):
            normalized["rules"]["rapid_application_switching"]["enabled"] = bool(
                rapid_switching.get("enabled", False)
            )
            normalized["rules"]["rapid_application_switching"]["severity"] = str(
                rapid_switching.get("severity", normalized["rules"]["rapid_application_switching"]["severity"])
            )
            normalized["rules"]["rapid_application_switching"]["max_switches"] = max(
                1,
                int(rapid_switching.get("max_switches", 10) or 10),
            )
            normalized["rules"]["rapid_application_switching"]["window_seconds"] = max(
                1,
                int(float(rapid_switching.get("window_seconds", 60) or 60)),
            )
            normalized["rules"]["rapid_application_switching"]["window_observations"] = max(
                1,
                int(rapid_switching.get("window_observations", normalized["rules"]["rapid_application_switching"]["max_switches"]) or normalized["rules"]["rapid_application_switching"]["max_switches"]),
            )
            normalized["rules"]["rapid_application_switching"]["auto_violation_pause"] = bool(
                rapid_switching.get("auto_violation_pause", False)
            )
        if isinstance(idle_policy, dict):
            normalized["rules"]["idle_policy"]["enabled"] = bool(
                idle_policy.get("enabled", False)
            )
            normalized["rules"]["idle_policy"]["severity"] = str(
                idle_policy.get("severity", normalized["rules"]["idle_policy"]["severity"])
            )
            warn_threshold = max(
                1,
                int(float(idle_policy.get("warn_threshold_seconds", 80) or 80)),
            )
            critical_threshold = max(
                warn_threshold,
                int(float(idle_policy.get("critical_threshold_seconds", 150) or 150)),
            )
            normalized["rules"]["idle_policy"]["warn_threshold_seconds"] = warn_threshold
            normalized["rules"]["idle_policy"]["critical_threshold_seconds"] = critical_threshold
            normalized["rules"]["idle_policy"]["auto_violation_pause"] = bool(
                idle_policy.get("auto_violation_pause", False)
            )
        if isinstance(unexpected_process, dict):
            normalized["rules"]["unexpected_process"]["enabled"] = bool(
                unexpected_process.get("enabled", False)
            )
            normalized["rules"]["unexpected_process"]["severity"] = str(
                unexpected_process.get("severity", normalized["rules"]["unexpected_process"]["severity"])
            )
            normalized["rules"]["unexpected_process"]["known_process_names"] = self._string_list(
                unexpected_process.get("known_process_names", [])
            )
            normalized["rules"]["unexpected_process"]["known_directory_paths"] = self._string_list(
                unexpected_process.get("known_directory_paths", [])
            )
            normalized["rules"]["unexpected_process"]["allowed_process_names"] = self._string_list(
                unexpected_process.get("allowed_process_names", [])
            )
            normalized["rules"]["unexpected_process"]["baseline_existing_processes"] = bool(
                unexpected_process.get("baseline_existing_processes", False)
            )
            normalized["rules"]["unexpected_process"]["auto_violation_pause"] = bool(
                unexpected_process.get("auto_violation_pause", False)
            )
        if isinstance(process_definitions, dict):
            normalized["rules"]["process_definitions"]["enabled"] = bool(
                process_definitions.get("enabled", True)
            )
            normalized["rules"]["process_definitions"]["severity"] = str(
                process_definitions.get(
                    "severity",
                    normalized["rules"]["process_definitions"]["severity"],
                )
            )
            definitions = normalize_definitions(process_definitions.get("definitions", []))
            if definitions:
                normalized["rules"]["process_definitions"]["definitions"] = definitions
            normalized["rules"]["process_definitions"]["detect_unknown_processes"] = bool(
                process_definitions.get("detect_unknown_processes", True)
            )
            normalized["rules"]["process_definitions"]["unknown_severity"] = str(
                process_definitions.get("unknown_severity", "warning")
            )
            normalized["rules"]["process_definitions"]["baseline_existing_processes"] = bool(
                process_definitions.get("baseline_existing_processes", True)
            )
            normalized["rules"]["process_definitions"]["auto_violation_pause"] = bool(
                process_definitions.get("auto_violation_pause", False)
            )
            normalized["rules"]["process_definitions"]["allow_remote_kill"] = bool(
                process_definitions.get("allow_remote_kill", True)
            )
        if isinstance(incident_rules, dict):
            normalized["rules"]["incident_rules"]["enabled"] = bool(
                incident_rules.get("enabled", True)
            )
            normalized["rules"]["incident_rules"]["severity"] = str(
                incident_rules.get(
                    "severity",
                    normalized["rules"]["incident_rules"]["severity"],
                )
            )
            definitions = normalize_incident_rules(incident_rules.get("definitions", []))
            if definitions:
                normalized["rules"]["incident_rules"]["definitions"] = definitions
            normalized["rules"]["incident_rules"]["auto_violation_pause"] = bool(
                incident_rules.get("auto_violation_pause", False)
            )
            normalized["rules"]["incident_rules"]["allow_remote_kill"] = bool(
                incident_rules.get("allow_remote_kill", True)
            )
        if isinstance(process_path_clarification, dict):
            normalized["rules"]["process_path_clarification"]["enabled"] = bool(
                process_path_clarification.get("enabled", True)
            )
            normalized["rules"]["process_path_clarification"]["severity"] = str(
                process_path_clarification.get(
                    "severity",
                    normalized["rules"]["process_path_clarification"]["severity"],
                )
            )
            normalized["rules"]["process_path_clarification"]["auto_violation_pause"] = bool(
                process_path_clarification.get("auto_violation_pause", False)
            )
            normalized["rules"]["process_path_clarification"]["allow_remote_kill"] = bool(
                process_path_clarification.get("allow_remote_kill", True)
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
