import json
import tempfile
import unittest
from unittest.mock import patch

from server import session_state
from server.state import state


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

    def test_import_export_round_trip_preserves_policy_blacklist_and_operator_defaults(self):
        original_blacklist = state.process_blacklist
        original_blacklist_version = state.process_blacklist_version
        original_policy_config = state.exam_policy_config
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                export_path = f"{temp_dir}/settings.json"
                exam_policy_path = f"{temp_dir}/exam_policy.json"
                blacklist_path = f"{temp_dir}/process_blacklist.txt"

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
                    patch("server.state.EXAM_POLICY_FILE", exam_policy_path),
                    patch("server.state.PROCESS_BLACKLIST_FILE", blacklist_path),
                ):
                    state.export_settings_bundle(export_path)
                    state.process_blacklist = []
                    state.exam_policy_config = state._default_exam_policy_config()
                    state.import_settings_bundle(export_path)

                self.assertEqual(state.process_blacklist, ["discord.exe", "steam.exe"])
                self.assertFalse(state.session_policy()["auto_resume_on_reconnect"])
                self.assertFalse(state.rule_config("process_blacklist")["allow_remote_kill"])
                self.assertFalse(state.operator_defaults()["confirm_kill_pid"])

                with open(export_path, "r", encoding="utf-8") as settings_file:
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
