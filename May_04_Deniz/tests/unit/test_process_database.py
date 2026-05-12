import json
import shutil
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from client.incidents import ClientIncidentEngine
from common.incident_rules import normalize_incident_rule
from common.process_definitions import normalize_definition
from server import session_state
from server import state as state_module
from server.gui import (
    build_incident_rule_decision_payload,
    build_process_decision_payload,
    incident_rule_row_from_incident,
    incident_rule_row_matches_filter,
    process_row_google_search_url,
    process_row_matches_filter,
)
from server.settings_service import (
    apply_incident_rule_decision,
    apply_process_decision,
    build_incident_rules_database,
    build_process_database,
    update_incident_rules,
)
from server.state import state


TEST_DATA_ROOT = Path(__file__).resolve().parents[2] / "data" / "server" / "_test_process_database"


@contextmanager
def _isolated_state():
    test_dir = TEST_DATA_ROOT / uuid4().hex
    test_dir.mkdir(parents=True, exist_ok=False)
    original = {
        "users_db": state.users_db,
        "clients": state.clients,
        "incidents": state.incidents,
        "active_incidents": state.active_incidents,
        "process_blacklist": state.process_blacklist,
        "process_blacklist_version": state.process_blacklist_version,
        "process_definitions": state.process_definitions,
        "process_definitions_version": state.process_definitions_version,
        "incident_rules": state.incident_rules,
        "incident_rules_version": state.incident_rules_version,
        "exam_policy_config": state.exam_policy_config,
    }
    try:
        state.users_db = {}
        state.clients = {}
        state.incidents = []
        state.active_incidents = {}
        state.process_blacklist = []
        state.process_blacklist_version = "0"
        state.process_definitions = []
        state.process_definitions_version = "0"
        state.incident_rules = []
        state.incident_rules_version = "0"
        state.exam_policy_config = state._normalize_exam_policy_config({})
        with (
            patch.object(state_module, "USERS_FILE", str(test_dir / "users.json")),
            patch.object(state_module, "EXAM_POLICY_FILE", str(test_dir / "exam_policy.json")),
            patch.object(state_module, "PROCESS_BLACKLIST_FILE", str(test_dir / "process_blacklist.txt")),
            patch.object(state_module, "PROCESS_DEFINITIONS_FILE", str(test_dir / "process_definitions.json")),
            patch.object(state_module, "INCIDENT_RULES_FILE", str(test_dir / "incident_rules.json")),
            patch.object(state_module, "INCIDENTS_FILE", str(test_dir / "incidents.jsonl")),
            patch.object(state_module, "AUDIT_FILE", str(test_dir / "audit.jsonl")),
        ):
            yield test_dir
    finally:
        state.users_db = original["users_db"]
        state.clients = original["clients"]
        state.incidents = original["incidents"]
        state.active_incidents = original["active_incidents"]
        state.process_blacklist = original["process_blacklist"]
        state.process_blacklist_version = original["process_blacklist_version"]
        state.process_definitions = original["process_definitions"]
        state.process_definitions_version = original["process_definitions_version"]
        state.incident_rules = original["incident_rules"]
        state.incident_rules_version = original["incident_rules_version"]
        state.exam_policy_config = original["exam_policy_config"]
        shutil.rmtree(test_dir, ignore_errors=True)


def _incident(incident_id: str, login_id: str, status: str = "opened", *, pid: int = 42) -> dict:
    return {
        "incident_id": incident_id,
        "login_id": login_id,
        "client_id": f"uuid-{login_id}",
        "rule_id": "unexpected_process",
        "status": status,
        "severity": "warning",
        "process_name": "discord.exe",
        "process_path": "C:\\Tools\\discord.exe",
        "process_dir": "C:\\Tools",
        "pid": pid,
        "event_at": f"2026-05-01T00:00:0{1 if status == 'opened' else 2}+00:00",
    }


def _focused_incident(incident_id: str, login_id: str, title: str, status: str = "opened") -> dict:
    return {
        "incident_id": incident_id,
        "login_id": login_id,
        "client_id": f"uuid-{login_id}",
        "rule_id": "focused_window_policy",
        "event_type": "focused_window_policy",
        "source": "focused_window",
        "status": status,
        "severity": "warning",
        "process_name": "chrome.exe",
        "window_title": title,
        "pid": 77,
        "summary": f"Focused window out of policy: chrome.exe / {title}",
        "event_at": f"2026-05-01T00:01:0{1 if status == 'opened' else 2}+00:00",
    }


def _idle_incident(incident_id: str, login_id: str, status: str = "opened") -> dict:
    return {
        "incident_id": incident_id,
        "login_id": login_id,
        "client_id": f"uuid-{login_id}",
        "rule_id": "idle_policy",
        "event_type": "idle_warn",
        "source": "idle_monitor",
        "status": status,
        "severity": "warning",
        "pid": 0,
        "summary": "Student idle for 80s",
        "event_at": f"2026-05-01T00:02:0{1 if status == 'opened' else 2}+00:00",
    }


class ProcessDatabaseTests(unittest.TestCase):
    def test_definition_normalization_and_policy_export_import(self):
        with _isolated_state() as test_dir:
            definition = normalize_definition(
                {
                    "process_name": "Discord.exe",
                    "process_path": "%LOCALAPPDATA%\\Discord\\app\\Discord.exe",
                    "status": "blacklist",
                    "actions": {"ban": True, "kill_pid": True},
                }
            )
            state.exam_policy_config = state._normalize_exam_policy_config(
                {"rules": {"process_definitions": {"definitions": [definition]}}}
            )
            export_path = test_dir / "settings.json"

            state.export_settings_bundle(str(export_path))
            state.exam_policy_config = state._normalize_exam_policy_config({})
            state.import_settings_bundle(str(export_path))

            definitions = state.rule_config("process_definitions")["definitions"]
            self.assertEqual(len(definitions), 1)
            self.assertEqual(definitions[0]["status"], "blacklist")
            self.assertTrue(definitions[0]["actions"]["ban"])
            self.assertTrue(definitions[0]["actions"]["kill_pid"])

    def test_database_builds_from_saved_definitions_and_resolved_incidents(self):
        with _isolated_state():
            state.users_db = {"student1": {"uuid": "uuid-student1"}}
            state.ensure_user_defaults(state.users_db["student1"])
            definition = normalize_definition(
                {
                    "process_name": "discord.exe",
                    "process_path": "C:\\Tools\\discord.exe",
                    "status": "unknown",
                }
            )
            state.exam_policy_config = state._normalize_exam_policy_config(
                {"rules": {"process_definitions": {"definitions": [definition]}}}
            )
            state.incidents = [_incident("inc-1", "student1", "opened"), _incident("inc-1", "student1", "resolved")]

            rows = build_process_database(state)
            row = rows[0]

            self.assertEqual(row["process_name"], "discord.exe")
            self.assertEqual(row["match_count"], 2)
            self.assertEqual(row["opened_students"], ["student1"])
            self.assertEqual(row["resolved_students"], ["student1"])
            self.assertTrue(process_row_matches_filter(row, "Resolved"))

    def test_known_blacklisted_executable_on_unknown_path_becomes_warning_clarification(self):
        policy = {
            "policy_version": "policy-v1",
            "rules": [
                {
                    "rule_id": "process_blacklist",
                    "source": "process_monitor",
                    "type": "process_blacklist",
                    "enabled": True,
                    "severity": "violation",
                    "entries": ["discord.exe"],
                    "process_usernames": [],
                },
                {
                    "rule_id": "process_definitions",
                    "source": "process_monitor",
                    "type": "process_definitions",
                    "enabled": True,
                    "definitions": [
                        {
                            "process_name": "discord.exe",
                            "process_path": "C:\\Known\\discord.exe",
                            "status": "blacklist",
                        }
                    ],
                },
                {
                    "rule_id": "process_path_clarification",
                    "source": "process_monitor",
                    "type": "process_path_clarification",
                    "enabled": True,
                    "severity": "warning",
                },
            ],
        }
        engine = ClientIncidentEngine()
        ok, reason = engine.apply_policy(policy)
        self.assertTrue(ok, reason)

        incidents = engine.observe_processes({(100, "discord.exe", None, "C:\\Other\\discord.exe")})

        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["rule_id"], "process_path_clarification")
        self.assertEqual(incidents[0]["severity"], "warning")
        self.assertIn("known_definition_candidates", incidents[0])

    def test_apply_decision_marks_history_and_bans_all_past_students(self):
        with _isolated_state():
            state.users_db = {
                "student1": {"uuid": "uuid-student1"},
                "student2": {"uuid": "uuid-student2"},
            }
            for user in state.users_db.values():
                state.ensure_user_defaults(user)
                session_state.set_state(user, session_state.RUNNING)
            state.incidents = [_incident("inc-1", "student1"), _incident("inc-2", "student2")]

            result = apply_process_decision(
                state,
                {
                    "definition": {
                        "process_name": "discord.exe",
                        "process_path": "C:\\Tools\\discord.exe",
                        "match_scope": "path",
                    },
                    "status": "blacklist",
                    "actions": {"ban": True},
                    "save_policy": True,
                },
            )

            self.assertTrue(result["ok"])
            self.assertEqual(set(result["banned_login_ids"]), {"student1", "student2"})
            self.assertTrue(state.users_db["student1"]["banned"])
            self.assertTrue(state.users_db["student2"]["banned"])
            self.assertTrue(all("process_decision" in incident for incident in state.incidents))
            self.assertEqual(state.rule_config("process_definitions")["definitions"][0]["status"], "blacklist")

    def test_apply_process_decision_wildcard_matches_existing_incidents(self):
        with _isolated_state():
            state.users_db = {"student1": {"uuid": "uuid-student1"}}
            state.ensure_user_defaults(state.users_db["student1"])
            incident = _incident("inc-whatsapp", "student1")
            incident["process_name"] = "WhatsApp.Root.exe"
            incident["process_path"] = "C:\\Apps\\WhatsApp.Root.exe"
            incident["process_dir"] = "C:\\Apps"
            state.incidents = [incident]
            state.active_incidents = {"inc-whatsapp": incident}

            result = apply_process_decision(
                state,
                {
                    "definition": {
                        "process_name": "whatsapp*",
                        "match_scope": "name",
                    },
                    "status": "blacklist",
                    "actions": {"kill_pid": True},
                    "save_policy": True,
                },
            )

            self.assertTrue(result["ok"], result.get("message"))
            self.assertEqual(result["matching_incident_ids"], ["inc-whatsapp"])
            saved = state.rule_config("process_definitions")["definitions"][0]
            self.assertEqual(saved["process_name"], "whatsapp*")
            self.assertEqual(saved["match_scope"], "name")

    def test_action_availability_reasons_for_submitted_disconnected_and_no_pid(self):
        with _isolated_state():
            state.users_db = {
                "submitted": {"uuid": "uuid-submitted", "submitted_at": "2026-05-01T01:00:00+00:00"},
                "disconnected": {"uuid": "uuid-disconnected"},
                "nopid": {"uuid": "uuid-nopid"},
            }
            for user in state.users_db.values():
                state.ensure_user_defaults(user)
                session_state.set_state(user, session_state.RUNNING)
            session_state.set_state(state.users_db["submitted"], session_state.SUBMITTED)
            state.users_db["submitted"]["submitted_at"] = "2026-05-01T01:00:00+00:00"
            state.clients = {"uuid-nopid": {"short_id": "nopid", "ip": "127.0.0.1"}}
            state.incidents = [
                _incident("inc-submitted", "submitted", pid=12),
                _incident("inc-disconnected", "disconnected", pid=13),
                _incident("inc-nopid", "nopid", pid=0),
            ]
            state.active_incidents = {incident["incident_id"]: incident for incident in state.incidents}

            row = build_process_database(state)[0]
            by_login = {entry["login_id"]: entry for entry in row["action_states"]}

            self.assertEqual(by_login["submitted"]["actions"]["kick"]["reason"], "submitted")
            self.assertEqual(by_login["disconnected"]["actions"]["kick"]["reason"], "disconnected")
            self.assertEqual(by_login["nopid"]["actions"]["kill_pid"]["reason"], "no live PID")

    def test_gui_payload_and_google_search_url(self):
        row = {
            "definition_id": "def-1",
            "process_key": "key-1",
            "process_name": "discord.exe",
            "process_path": "C:\\Tools\\discord.exe",
            "match_scope": "path",
            "status": "unknown",
        }

        payload = build_process_decision_payload(
            row,
            status="blacklist",
            match_scope="path",
            actions={"ban": True, "kick": False, "pause_exam": True, "kill_pid": False},
            save_policy=True,
        )
        url = process_row_google_search_url(row)

        self.assertEqual(payload["cmd"], "apply_process_decision")
        self.assertTrue(payload["actions"]["ban"])
        self.assertTrue(payload["actions"]["pause_exam"])
        self.assertTrue(payload["save_policy"])
        self.assertIn("https://www.google.com/search?", url)
        self.assertIn("discord.exe", url)

        wildcard_payload = build_process_decision_payload(
            row,
            status="blacklist",
            match_scope="name",
            actions={},
            save_policy=True,
            process_name="whatsapp*",
        )

        self.assertEqual(wildcard_payload["definition"]["process_name"], "whatsapp*")
        self.assertEqual(wildcard_payload["definition"]["normalized_process_name"], "whatsapp*")
        self.assertEqual(wildcard_payload["definition"]["match_scope"], "name")

    def test_incident_rule_normalization_and_policy_export_import(self):
        with _isolated_state() as test_dir:
            rule = normalize_incident_rule(
                {
                    "name": "Approved CATS title",
                    "status": "whitelist",
                    "event_type": "focused_window_policy",
                    "source": "focused_window",
                    "browser_process_names": ["chrome.exe"],
                    "window_title_patterns": ["CATS"],
                }
            )
            state.incident_rules = [rule]
            export_path = test_dir / "settings.json"

            state.export_settings_bundle(str(export_path))
            state.incident_rules = []
            state.import_settings_bundle(str(export_path))

            definitions = state.rule_config("incident_rules")["definitions"]
            self.assertEqual(len(definitions), 1)
            self.assertEqual(definitions[0]["status"], "whitelist")
            self.assertEqual(definitions[0]["window_title_patterns"], ["CATS"])

    def test_incident_rules_database_builds_rows_for_all_incident_types(self):
        with _isolated_state():
            state.users_db = {
                "student1": {"uuid": "uuid-student1"},
                "student2": {"uuid": "uuid-student2"},
                "student3": {"uuid": "uuid-student3"},
            }
            for user in state.users_db.values():
                state.ensure_user_defaults(user)
                session_state.set_state(user, session_state.RUNNING)
            rule = normalize_incident_rule(
                {
                    "name": "Approved CATS title",
                    "status": "whitelist",
                    "event_type": "focused_window_policy",
                    "source": "focused_window",
                    "browser_process_names": ["chrome.exe"],
                    "window_title_patterns": ["CATS"],
                }
            )
            update_incident_rules(state, [rule])
            state.incidents = [
                _focused_incident("focus-1", "student1", "CATS - Exam Portal - Google Chrome"),
                _idle_incident("idle-1", "student2"),
                _incident("process-1", "student3"),
            ]
            state.active_incidents = {incident["incident_id"]: incident for incident in state.incidents}

            rows = build_incident_rules_database(state)
            focused_row = next(row for row in rows if row["name"] == "Approved CATS title")
            idle_row = next(row for row in rows if row["rule_id"] == "idle_policy")
            process_row = next(row for row in rows if row["rule_id"] == "unexpected_process")

            self.assertEqual(focused_row["match_count"], 1)
            self.assertEqual(focused_row["affected_students"], ["student1"])
            self.assertTrue(incident_rule_row_matches_filter(focused_row, "Whitelist"))
            self.assertEqual(idle_row["affected_students"], ["student2"])
            self.assertEqual(process_row["affected_students"], ["student3"])

    def test_apply_incident_rule_decision_marks_history_and_bans_matching_students(self):
        with _isolated_state():
            state.users_db = {
                "student1": {"uuid": "uuid-student1"},
                "student2": {"uuid": "uuid-student2"},
            }
            for user in state.users_db.values():
                state.ensure_user_defaults(user)
                session_state.set_state(user, session_state.RUNNING)
            state.incidents = [
                _focused_incident("focus-1", "student1", "Discord - Chat"),
                _focused_incident("focus-2", "student2", "Discord - Chat"),
            ]
            state.active_incidents = {incident["incident_id"]: incident for incident in state.incidents}

            result = apply_incident_rule_decision(
                state,
                {
                    "definition": {
                        "name": "Discord title",
                        "event_type": "focused_window_policy",
                        "source": "focused_window",
                        "window_title_patterns": ["Discord"],
                    },
                    "status": "blacklist",
                    "actions": {"ban": True},
                    "save_policy": True,
                },
            )

            self.assertTrue(result["ok"])
            self.assertEqual(set(result["banned_login_ids"]), {"student1", "student2"})
            self.assertTrue(state.users_db["student1"]["banned"])
            self.assertTrue(state.users_db["student2"]["banned"])
            self.assertTrue(all("incident_rule_decision" in incident for incident in state.incidents))
            self.assertEqual(state.rule_config("incident_rules")["definitions"][0]["status"], "blacklist")

    def test_incident_rule_gui_payload(self):
        row = {
            "definition_id": "rule-1",
            "rule_key": "key-1",
            "name": "Discord title",
            "rule_id": "focused_window_policy",
            "event_type": "focused_window_policy",
            "source": "focused_window",
            "process_names": [],
            "browser_process_names": ["chrome.exe"],
            "window_title_patterns": ["Discord"],
            "match_mode": "contains",
            "priority": 3,
            "matching_history": [],
        }

        payload = build_incident_rule_decision_payload(
            row,
            status="blacklist",
            actions={"ban": False, "kick": True, "pause_exam": True, "kill_pid": True},
            save_policy=True,
            priority=12,
        )

        self.assertEqual(payload["cmd"], "apply_incident_rule_decision")
        self.assertEqual(payload["definition"]["priority"], 12)
        self.assertEqual(payload["definition"]["browser_process_names"], ["chrome.exe"])
        self.assertTrue(payload["actions"]["kick"])
        self.assertTrue(payload["actions"]["pause_exam"])
        self.assertTrue(payload["save_policy"])

    def test_incident_rule_save_prefill_reuses_legacy_title_pattern(self):
        incident = _focused_incident(
            "focus-whatsapp",
            "student1",
            "whatsapp \u2014 Yandex: 2 milyon sonuc bulundu - Profil 1 - Microsoft Edge",
        )
        settings_snapshot = {
            "exam_policy": {
                "rules": {
                    "focused_window": {
                        "blocked_window_titles": ["whatsapp"],
                        "window_title_match_mode": "contains",
                    }
                }
            }
        }

        row = incident_rule_row_from_incident(incident, settings_snapshot)

        self.assertEqual(row["window_title_patterns"], ["whatsapp"])
        self.assertEqual(row["match_mode"], "contains")
        self.assertEqual(row["process_names"], [])
        self.assertEqual(row["browser_process_names"], [])
        self.assertIn("whatsapp", row["name"])

    def test_incident_rule_save_prefill_strips_browser_suffix_without_legacy_policy(self):
        incident = _focused_incident("focus-cats", "student1", "CATS - Exam Portal - Google Chrome")

        row = incident_rule_row_from_incident(incident, {})

        self.assertEqual(row["window_title_patterns"], ["CATS"])
        self.assertEqual(row["match_mode"], "contains")
        self.assertEqual(row["process_names"], [])

    def test_incident_rule_payload_preserves_edited_match_fields(self):
        row = incident_rule_row_from_incident(
            _focused_incident("focus-whatsapp", "student1", "WhatsApp - Microsoft Edge"),
            {},
        )

        payload = build_incident_rule_decision_payload(
            row,
            status="blacklist",
            actions={"kill_pid": True},
            save_policy=True,
            priority=5,
            process_names=["msedge.exe"],
            browser_process_names=[],
            window_title_patterns=["whatsapp"],
            match_mode="contains",
        )

        definition = payload["definition"]
        self.assertEqual(definition["window_title_patterns"], ["whatsapp"])
        self.assertEqual(definition["process_names"], ["msedge.exe"])
        self.assertEqual(definition["browser_process_names"], [])
        self.assertEqual(definition["match_mode"], "contains")
        self.assertTrue(definition["actions"]["kill_pid"])


if __name__ == "__main__":
    unittest.main()
