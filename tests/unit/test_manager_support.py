import sys
import tempfile
import time
import unittest
from pathlib import Path

from common.manager_support import ManagedProcessSession
from common.server_ports import describe_port_conflict
from server_launcher import _extract_startup_failure


class ManagerSupportTests(unittest.TestCase):
    def test_managed_process_session_captures_output_to_session_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = ManagedProcessSession(
                session_name="server_cli_session",
                log_dir=Path(temp_dir),
            )
            process = session.start(
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "import sys; print('alpha'); sys.stderr.write('beta\\n')",
                ],
                cwd=temp_dir,
                env={},
            )
            process.wait(timeout=5)
            session._reader_thread.join(timeout=2)

            output = session.read_output_text()
            self.assertIn("alpha", output)
            self.assertIn("beta", output)
            self.assertIn("process exited with code 0", output)

    def test_managed_process_session_records_sent_commands(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = ManagedProcessSession(
                session_name="client_cli_session",
                log_dir=Path(temp_dir),
            )
            process = session.start(
                [
                    sys.executable,
                    "-u",
                    "-c",
                    (
                        "import sys; "
                        "print('ready'); "
                        "line = sys.stdin.readline().strip(); "
                        "print(f'echo:{line}')"
                    ),
                ],
                cwd=temp_dir,
                env={},
            )
            time.sleep(0.2)
            self.assertTrue(session.send_line("start"))
            process.wait(timeout=5)
            session._reader_thread.join(timeout=2)

            output = session.read_output_text()
            self.assertIn("[MANAGER] > start", output)
            self.assertIn("echo:start", output)


class LauncherFailureParsingTests(unittest.TestCase):
    def test_extract_startup_failure_from_duplicate_server_output(self):
        output = "\n".join(
            [
                "[CHECK] Waiting up to 5.0s for an existing server with id 'default' to announce itself...",
                "[ERROR] A server with id 'default' is already running at 127.0.0.1:8080",
                "[ERROR] Use a different --id or stop the other server first.",
            ]
        )

        message = _extract_startup_failure(output)

        self.assertIn("already running", message)
        self.assertIn("Use a different --id", message)

    def test_extract_startup_failure_from_port_conflict_output(self):
        message = _extract_startup_failure("[ERROR] Port 8080 is already in use.")

        self.assertEqual(message, "Port 8080 is already in use.")

    def test_describe_port_conflict_mentions_existing_server_id(self):
        message = describe_port_conflict("default", 8080, "lab")

        self.assertIn("lab", message)
        self.assertIn("8080", message)


if __name__ == "__main__":
    unittest.main()
