import json
import shutil
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from server import session_state
from server.state import state

TEST_DATA_ROOT = Path(__file__).resolve().parents[2] / "data" / "server" / "_test_server_state"


@contextmanager
def _local_test_dir():
    TEST_DATA_ROOT.mkdir(parents=True, exist_ok=True)
    test_dir = TEST_DATA_ROOT / uuid4().hex
    test_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield test_dir
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


class ServerStatePolicyTests(unittest.TestCase):
    def test_current_exam_policy_version_is_stable_between_calls(self):
        original_blacklist = state.process_blacklist
        original_blacklist_version = state.process_blacklist_version
        original_policy_config = state.exam_policy_config
        try:
            state.process_blacklist = ["discord.exe"]
            state.process_blacklist_version = "blacklist-v1"
            state.exam_policy_config = {
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

            first = state.current_exam_policy()
            second = state.current_exam_policy()

            self.assertEqual(first["policy_version"], second["policy_version"])
            self.assertEqual(first["rules"][0]["entries"], ["discord.exe"])
            self.assertTrue(first["session"]["auto_resume_on_reconnect"])
        finally:
            state.process_blacklist = original_blacklist
            state.process_blacklist_version = original_blacklist_version
            state.exam_policy_config = original_policy_config

    def test_idle_policy_normalizes_and_is_emitted_to_clients(self):
        original_policy_config = state.exam_policy_config
        try:
            state.exam_policy_config = state._normalize_exam_policy_config(
                {
                    "rules": {
                        "idle_policy": {
                            "enabled": True,
                            "severity": "warning",
                            "warn_threshold_seconds": 45,
                            "critical_threshold_seconds": 120,
                            "auto_violation_pause": True,
                        }
                    }
                }
            )

            config = state.rule_config("idle_policy")
            self.assertTrue(config["enabled"])
            self.assertEqual(config["warn_threshold_seconds"], 45)
            self.assertEqual(config["critical_threshold_seconds"], 120)
            self.assertTrue(config["auto_violation_pause"])

            policy = state.current_exam_policy()
            idle_rule = next(rule for rule in policy["rules"] if rule["rule_id"] == "idle_policy")
            self.assertEqual(idle_rule["source"], "idle_monitor")
            self.assertEqual(idle_rule["type"], "idle_policy")
            self.assertEqual(idle_rule["warn_threshold_seconds"], 45)
            self.assertEqual(idle_rule["critical_threshold_seconds"], 120)
        finally:
            state.exam_policy_config = original_policy_config

    def test_import_export_round_trip_preserves_policy_blacklist_and_operator_defaults(self):
        original_blacklist = state.process_blacklist
        original_blacklist_version = state.process_blacklist_version
        original_policy_config = state.exam_policy_config
        try:
            with _local_test_dir() as test_dir:
                export_path = test_dir / "settings.json"
                exam_policy_path = test_dir / "exam_policy.json"
                blacklist_path = test_dir / "process_blacklist.txt"

                state.process_blacklist = ["discord.exe", "steam.exe"]
                state.process_blacklist_version = "blacklist-v1"
                state.exam_policy_config = state._normalize_exam_policy_config(
                    {
                        "session": {
                            "auto_resume_on_reconnect": False,
                            "remember_settings": True,
                        },
                        "rules": {
                            "process_blacklist": {
                                "enabled": True,
                                "severity": "violation",
                                "auto_violation_pause": False,
                                "allow_remote_kill": False,
                            },
                            "focused_window": {
                                "enabled": True,
                                "severity": "warning",
                                "blocked_window_titles": ["discord"],
                                "window_title_match_mode": "contains",
                            },
                            "unexpected_process": {
                                "enabled": True,
                                "known_directory_paths": ["%WINDIR%"],
                            },
                        },
                        "operator_defaults": {
                            "confirm_kill_pid": False,
                            "confirm_kick": True,
                            "confirm_ban": False,
                            "confirm_pause": True,
                        },
                    }
                )

                with (
                    patch("server.state.EXAM_POLICY_FILE", str(exam_policy_path)),
                    patch("server.state.PROCESS_BLACKLIST_FILE", str(blacklist_path)),
                ):
                    state.export_settings_bundle(str(export_path))
                    state.process_blacklist = []
                    state.exam_policy_config = state._default_exam_policy_config()
                    state.import_settings_bundle(str(export_path))

                self.assertEqual(state.process_blacklist, ["discord.exe", "steam.exe"])
                self.assertFalse(state.session_policy()["auto_resume_on_reconnect"])
                self.assertFalse(state.rule_config("process_blacklist")["allow_remote_kill"])
                self.assertFalse(state.operator_defaults()["confirm_kill_pid"])
                self.assertEqual(
                    state.rule_config("focused_window_policy")["window_title_match_mode"],
                    "contains",
                )
                self.assertEqual(
                    state.rule_config("unexpected_process")["known_directory_paths"],
                    ["%WINDIR%"],
                )

                with export_path.open("r", encoding="utf-8") as settings_file:
                    exported = json.load(settings_file)
                self.assertIn("exam_policy", exported)
                self.assertIn("process_blacklist", exported)
        finally:
            state.process_blacklist = original_blacklist
            state.process_blacklist_version = original_blacklist_version
            state.exam_policy_config = original_policy_config


class SessionStateTests(unittest.TestCase):
    def test_violation_pause_sets_blocking_fields(self):
        user = {}
        state.ensure_user_defaults(user)

        session_state.set_state(
            user,
            session_state.VIOLATION_PAUSED,
            reason="Blocked process detected.",
            remaining_seconds=120,
            blocking_incident_id="incident-1",
            blocking_rule_id="process_blacklist",
        )

        self.assertEqual(user["session_state"], session_state.VIOLATION_PAUSED)
        self.assertEqual(user["blocking_incident_id"], "incident-1")
        self.assertEqual(user["blocking_rule_id"], "process_blacklist")
        self.assertTrue(user["exam_started"])
        self.assertFalse(user["exam_finished"])

    def test_reconnect_resume_allowed_respects_policy_and_state(self):
        disconnected_user = {}
        state.ensure_user_defaults(disconnected_user)
        session_state.set_state(
            disconnected_user,
            session_state.DISCONNECTED_PAUSED,
            remaining_seconds=90,
        )

        violation_user = {}
        state.ensure_user_defaults(violation_user)
        session_state.set_state(
            violation_user,
            session_state.VIOLATION_PAUSED,
            remaining_seconds=90,
            blocking_incident_id="incident-2",
            blocking_rule_id="process_blacklist",
        )

        self.assertTrue(
            session_state.reconnect_resume_allowed(
                disconnected_user,
                {"auto_resume_on_reconnect": True},
            )
        )
        self.assertFalse(
            session_state.reconnect_resume_allowed(
                disconnected_user,
                {"auto_resume_on_reconnect": False},
            )
        )
        self.assertFalse(
            session_state.reconnect_resume_allowed(
                violation_user,
                {"auto_resume_on_reconnect": True},
            )
        )


if __name__ == "__main__":
    unittest.main()
