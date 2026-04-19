import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from client.transfers import build_incident_bundle, build_submission_bundle


class TransferBundleTests(unittest.TestCase):
    def test_build_submission_bundle_includes_focused_window_artifacts(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_path = Path(tempdir)
            session_uuid = "session-123"
            client_dir = temp_path / "data" / "client" / session_uuid
            client_dir.mkdir(parents=True, exist_ok=True)

            submission_file = temp_path / "answer.txt"
            submission_file.write_text("hello", encoding="utf-8")

            process_report = client_dir / "process_report.json"
            process_report.write_text('{"processes": []}', encoding="utf-8")
            process_log = client_dir / "processes.jsonl"
            process_log.write_text('{"type":"diff"}\n', encoding="utf-8")
            hardware_snapshot = client_dir / "hardware_snapshot.json"
            hardware_snapshot.write_text('{"hardware": true}', encoding="utf-8")
            hardware_log = client_dir / "hardware_changes.jsonl"
            hardware_log.write_text('{"type":"hardware_change"}\n', encoding="utf-8")
            focused_snapshot = client_dir / "focused_window_snapshot.json"
            focused_snapshot.write_text('{"window":"Exam App"}', encoding="utf-8")
            focused_log = client_dir / "focused_window.jsonl"
            focused_log.write_text('{"type":"focused_window_initial"}\n', encoding="utf-8")
            exam_state_log = client_dir / "exam_state.jsonl"
            exam_state_log.write_text('{"timer_state":"running"}\n', encoding="utf-8")

            original_cwd = Path.cwd()
            try:
                os.chdir(temp_path)
                bundle_path = Path(build_submission_bundle(
                    session_uuid,
                    str(submission_file),
                    str(process_report),
                    None,
                    str(hardware_snapshot),
                    str(focused_snapshot),
                )).resolve()
            finally:
                os.chdir(original_cwd)

            with zipfile.ZipFile(bundle_path) as archive:
                names = set(archive.namelist())
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

            self.assertIn("runtime/focused_window_snapshot.json", names)
            self.assertIn("runtime/focused_window.jsonl", names)
            self.assertIn("runtime/exam_state.jsonl", names)
            manifest_roles = {entry["role"] for entry in manifest["entries"]}
            self.assertIn("focused_window_snapshot", manifest_roles)
            self.assertIn("focused_window_log", manifest_roles)
            self.assertIn("exam_state_log", manifest_roles)

    def test_build_submission_bundle_skips_optional_runtime_file_copy_failures(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_path = Path(tempdir)
            session_uuid = "session-456"
            client_dir = temp_path / "data" / "client" / session_uuid
            client_dir.mkdir(parents=True, exist_ok=True)

            submission_file = temp_path / "answer.txt"
            submission_file.write_text("hello", encoding="utf-8")

            process_report = client_dir / "process_report.json"
            process_report.write_text('{"processes": []}', encoding="utf-8")
            process_log = client_dir / "processes.jsonl"
            process_log.write_text('{"type":"diff"}\n', encoding="utf-8")

            def copy_side_effect(source, destination):
                if str(source).endswith("processes.jsonl"):
                    raise PermissionError("locked")
                destination.parent.mkdir(parents=True, exist_ok=True)
                return Path(destination).write_bytes(Path(source).read_bytes())

            with patch("client.transfers._copy_runtime_file_with_retries") as copy_mock:
                copy_mock.side_effect = lambda source, destination: (
                    False if str(source).endswith("processes.jsonl") else copy_side_effect(source, destination) is not None
                )

                original_cwd = Path.cwd()
                try:
                    os.chdir(temp_path)
                    bundle_path = Path(build_submission_bundle(
                        session_uuid,
                        str(submission_file),
                        str(process_report),
                        None,
                        None,
                        None,
                    )).resolve()
                finally:
                    os.chdir(original_cwd)

            with zipfile.ZipFile(bundle_path) as archive:
                names = set(archive.namelist())
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

            self.assertIn("student_submission/answer.txt", names)
            self.assertIn("runtime/process_report_requested.json", names)
            self.assertNotIn("runtime/processes.jsonl", names)
            manifest_roles = {entry["role"] for entry in manifest["entries"]}
            self.assertIn("requested_process_report", manifest_roles)
            self.assertNotIn("continuous_process_log", manifest_roles)

    def test_build_incident_bundle_includes_incident_json(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_path = Path(tempdir)
            session_uuid = "session-789"
            client_dir = temp_path / "data" / "client" / session_uuid
            client_dir.mkdir(parents=True, exist_ok=True)

            process_report = client_dir / "process_report.json"
            process_report.write_text('{"processes": []}', encoding="utf-8")
            process_log = client_dir / "processes.jsonl"
            process_log.write_text('{"type":"diff"}\n', encoding="utf-8")

            incident = {
                "incident_id": "incident-1",
                "rule_id": "process_blacklist",
                "summary": "Blacklisted process detected.",
            }

            original_cwd = Path.cwd()
            try:
                os.chdir(temp_path)
                bundle_path = Path(build_incident_bundle(
                    session_uuid,
                    incident,
                    str(process_report),
                    None,
                    None,
                    None,
                )).resolve()
            finally:
                os.chdir(original_cwd)

            with zipfile.ZipFile(bundle_path) as archive:
                names = set(archive.namelist())
                incident_payload = json.loads(archive.read("incident.json").decode("utf-8"))

            self.assertIn("incident.json", names)
            self.assertEqual(incident_payload["incident_id"], "incident-1")


if __name__ == "__main__":
    unittest.main()
