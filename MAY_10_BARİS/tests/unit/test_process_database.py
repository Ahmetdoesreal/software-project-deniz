import json
import shutil
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from client.incidents import ClientIncidentEngine
from common.process_definitions import normalize_definition
from server import session_state
from server import state as state_module
from server.gui import (
    build_process_decision_payload,
    process_row_google_search_url,
    process_row_matches_filter,
)
from server.settings_service import (
    apply_process_decision,
    build_process_database,
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
        "exam_policy_config": state.exam_policy_config,
    }
    try:
        state.users_db = {}
        state.clients = {}
        state.incidents = []
        state.active_incidents = {}
        state.process_blacklist = []
        state.process_blacklist_version = "0"
        state.exam_policy_config = state._normalize_exam_policy_config({})
        with (
            patch.object(state_module, "USERS_FILE", str(test_dir / "users.json")),
            patch.object(state_module, "EXAM_POLICY_FILE", str(test_dir / "exam_policy.json")),
            patch.object(state_module, "PROCESS_BLACKLIST_FILE", str(test_dir / "process_blacklist.txt")),
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


if __name__ == "__main__":
    unittest.main()
