import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from custommodules.focused_window_monitor import FocusedWindowMonitor


WINDOW_A = {
    "platform": "windows",
    "available": True,
    "window_title": "Exam App",
    "process_id": 100,
    "process_name": "exam.exe",
    "source": "user32",
}

WINDOW_B = {
    "platform": "windows",
    "available": True,
    "window_title": "Browser",
    "process_id": 200,
    "process_name": "chrome.exe",
    "source": "user32",
}


class FocusedWindowMonitorTests(unittest.TestCase):
    def test_export_current_snapshot_writes_report(self):
        with tempfile.TemporaryDirectory() as tempdir:
            monitor = FocusedWindowMonitor(tempdir)
            with patch.object(monitor, "_current_snapshot", return_value=WINDOW_A):
                report_path = monitor.export_current_snapshot()

            self.assertIsNotNone(report_path)
            payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["type"], "focused_window_snapshot")
            self.assertEqual(payload["window"]["window_title"], "Exam App")


class FocusedWindowMonitorAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_change_only_mode_logs_initial_snapshot_and_changes(self):
        with tempfile.TemporaryDirectory() as tempdir:
            monitor = FocusedWindowMonitor(
                tempdir,
                interval_seconds=0.01,
                emit_on_change_only=True,
            )

            snapshots = [WINDOW_A, WINDOW_A, WINDOW_B, WINDOW_B]

            def next_snapshot():
                if snapshots:
                    return snapshots.pop(0)
                return WINDOW_B

            with patch.object(monitor, "_current_snapshot", side_effect=next_snapshot):
                monitor.start()
                await asyncio.sleep(0.035)
                monitor.stop()
                await asyncio.sleep(0)

            log_lines = Path(monitor.log_file).read_text(encoding="utf-8").splitlines()
            entries = [json.loads(line) for line in log_lines]

            self.assertEqual(entries[0]["type"], "focused_window_initial")
            self.assertEqual(entries[0]["window"]["window_title"], "Exam App")
            self.assertEqual(entries[1]["type"], "focused_window_change")
            self.assertEqual(entries[1]["current"]["window_title"], "Browser")


if __name__ == "__main__":
    unittest.main()
