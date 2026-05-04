import sys
import time
import shutil
import unittest
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from common.manager_support import ManagedProcessSession

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def _local_test_dir(scope: str):
    base_dir = PROJECT_ROOT / "data" / scope / "_test_manager_support"
    base_dir.mkdir(parents=True, exist_ok=True)
    test_dir = base_dir / uuid4().hex
    test_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield test_dir
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


class ManagerSupportTests(unittest.TestCase):
    def test_managed_process_session_captures_output_to_session_log(self):
        with _local_test_dir("server") as temp_dir:
            session = ManagedProcessSession(
                session_name="server_cli_session",
                log_dir=temp_dir,
            )
            process = session.start(
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "import sys; print('alpha'); sys.stderr.write('beta\\n')",
                ],
                cwd=str(temp_dir),
                env={},
            )
            process.wait(timeout=5)
            session._reader_thread.join(timeout=2)

            output = session.read_output_text()
            self.assertIn("alpha", output)
            self.assertIn("beta", output)
            self.assertIn("process exited with code 0", output)

    def test_managed_process_session_records_sent_commands(self):
        with _local_test_dir("client") as temp_dir:
            session = ManagedProcessSession(
                session_name="client_cli_session",
                log_dir=temp_dir,
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
                cwd=str(temp_dir),
                env={},
            )
            time.sleep(0.2)
            self.assertTrue(session.send_line("start"))
            process.wait(timeout=5)
            session._reader_thread.join(timeout=2)

            output = session.read_output_text()
            self.assertIn("[MANAGER] > start", output)
            self.assertIn("echo:start", output)


if __name__ == "__main__":
    unittest.main()
