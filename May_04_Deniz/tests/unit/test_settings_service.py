import shutil
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from server import state as state_module
from server.state import state
from server.settings_service import (
    apply_incident_policy_action,
    get_settings_snapshot,
    update_known_directories,
    update_operator_defaults,
    update_process_blacklist,
    update_runtime_settings,
    update_session_settings,
)


TEST_DATA_ROOT = Path(__file__).resolve().parents[2] / "data" / "server" / "_test_settings_service"


@contextmanager
def _local_test_paths():
    test_dir = TEST_DATA_ROOT / uuid4().hex
    test_dir.mkdir(parents=True, exist_ok=False)
    try:
        with (
            patch.object(state_module, "EXAM_POLICY_FILE", str(test_dir / "exam_policy.json")),
            patch.object(state_module, "PROCESS_BLACKLIST_FILE", str(test_dir / "process_blacklist.txt")),
            patch.object(state_module, "AUDIT_FILE", str(test_dir / "session_audit.jsonl")),
        ):
            yield test_dir
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


class SettingsServiceTests(unittest.TestCase):
    def setUp(self):
        self.original_blacklist = state.process_blacklist
        self.original_blacklist_version = state.process_blacklist_version
        self.original_policy = state.exam_policy_config
        state.process_blacklist = []
        state.process_blacklist_version = "0"
        state.exam_policy_config = state._normalize_exam_policy_config({})

    def tearDown(self):
        state.process_blacklist = self.original_blacklist
        state.process_blacklist_version = self.original_blacklist_version
        state.exam_policy_config = self.original_policy

    def test_process_blacklist_add_remove_replace(self):
        with _local_test_paths():
            added = update_process_blacklist(state, "add", ["discord.exe", "steam.exe"])
            self.assertTrue(added.ok)
            self.assertTrue(added.changed)
            self.assertEqual(state.process_blacklist, ["discord.exe", "steam.exe"])

            removed = update_process_blacklist(state, "remove", ["DISCORD.EXE"])
            self.assertTrue(removed.ok)
            self.assertEqual(state.process_blacklist, ["steam.exe"])

            replaced = update_process_blacklist(state, "replace", ["notepad.exe"])
            self.assertTrue(replaced.ok)
            self.assertEqual(state.process_blacklist, ["notepad.exe"])

    def test_mark_incident_process_known(self):
        with _local_test_paths():
            result = apply_incident_policy_action(
                state,
                {"process_name": "Unknown_Tool.exe"},
                "mark_known_process",
            )

            self.assertTrue(result.ok)
            self.assertIn("unknown_tool.exe", state.rule_config("unexpected_process")["known_process_names"])

    def test_mark_incident_directory_known(self):
        with _local_test_paths():
            result = apply_incident_policy_action(
                state,
                {"process_path": "C:\\Tools\\unknown_tool.exe"},
                "mark_known_directory",
            )

            self.assertTrue(result.ok)
            self.assertIn("c:\\tools", state.rule_config("unexpected_process")["known_directory_paths"])

    def test_add_incident_process_to_blacklist(self):
        with _local_test_paths():
            result = apply_incident_policy_action(
                state,
                {"process_path": "C:\\Tools\\unknown_tool.exe"},
                "add_process_blacklist",
            )

            self.assertTrue(result.ok)
            self.assertEqual(state.process_blacklist, ["unknown_tool.exe"])

    def test_update_operator_defaults_and_session_settings(self):
        with _local_test_paths():
            operator = update_operator_defaults(state, {"confirm_kill_pid": False})
            session = update_session_settings(state, {"auto_resume_on_reconnect": False})

            self.assertTrue(operator.ok)
            self.assertTrue(session.ok)
            self.assertFalse(state.operator_defaults()["confirm_kill_pid"])
            self.assertFalse(state.session_policy()["auto_resume_on_reconnect"])

    def test_known_directories_expand_percent_env_vars(self):
        with _local_test_paths(), patch.dict("os.environ", {"WINDIR": "C:\\Windows"}):
            result = update_known_directories(state, "add", ["%WINDIR%"])

            self.assertTrue(result.ok)
            self.assertIn("c:\\windows", state.rule_config("unexpected_process")["known_directory_paths"])

    def test_runtime_settings_reject_invalid_duration_and_non_zip(self):
        app = {"exam_duration": 45, "exam_files": None, "settings_state": state}
        result = update_runtime_settings(app, {"exam_duration": 0, "exam_files": "notes.txt"})

        self.assertFalse(result.ok)
        self.assertIn("exam_duration must be greater than 0.", result.errors)
        self.assertIn("exam_files must be a .zip file.", result.errors)

    def test_runtime_settings_accept_duration_and_zip(self):
        with _local_test_paths() as test_dir:
            exam_zip = test_dir / "exam.zip"
            exam_zip.write_bytes(b"zip")
            app = {"exam_duration": 45, "exam_files": None, "settings_state": state}

            result = update_runtime_settings(app, {"exam_duration": 60, "exam_files": str(exam_zip)})

            self.assertTrue(result.ok)
            self.assertTrue(result.changed)
            self.assertEqual(app["exam_duration"], 60)
            self.assertEqual(app["exam_files"], str(exam_zip))

    def test_settings_snapshot_includes_policy_versions(self):
        snapshot = get_settings_snapshot(state, {"exam_duration": 45, "exam_files": None})

        self.assertIn("policy_version", snapshot)
        self.assertIn("process_blacklist_version", snapshot)
        self.assertEqual(snapshot["runtime"]["exam_duration"], 45)


if __name__ == "__main__":
    unittest.main()
