import unittest
from unittest.mock import patch

from client.custommodules.process_monitor.core import DIFF_INTERVAL_SECONDS, ProcessMonitor


class ProcessMonitorTests(unittest.TestCase):
    def test_blacklist_match_includes_allowed_process_owner(self):
        monitor = ProcessMonitor(".")
        monitor.set_blacklist(["discord.exe"], usernames=["student"])

        matches = monitor._detect_blacklist_matches(
            {
                (1234, "discord.exe", "DESKTOP\\student"),
                (2222, "notepad.exe", "DESKTOP\\student"),
            }
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["pid"], 1234)
        self.assertEqual(matches[0]["username"], "DESKTOP\\student")
        self.assertIsNone(matches[0]["process_path"])

    def test_blacklist_match_includes_process_path_when_available(self):
        monitor = ProcessMonitor(".")
        monitor.set_blacklist(["discord.exe"], usernames=["student"])

        matches = monitor._detect_blacklist_matches(
            {(1234, "discord.exe", "DESKTOP\\student", "C:\\Users\\student\\discord.exe")}
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["process_path"], "C:\\Users\\student\\discord.exe")

    def test_blacklist_match_accepts_wildcard_process_names(self):
        monitor = ProcessMonitor(".")
        monitor.set_blacklist(["whatsapp*"], usernames=["student"])

        matches = monitor._detect_blacklist_matches(
            {(1234, "WhatsApp.Root.exe", "DESKTOP\\student", "C:\\Apps\\WhatsApp.Root.exe")}
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["name"], "WhatsApp.Root.exe")

    def test_blacklist_match_ignores_unmonitored_process_owner(self):
        monitor = ProcessMonitor(".")
        monitor.set_blacklist(["discord.exe"], usernames=["student"])

        matches = monitor._detect_blacklist_matches({(1234, "discord.exe", "DESKTOP\\other")})

        self.assertEqual(matches, [])

    def test_blacklist_match_keeps_legacy_unknown_owner_behavior(self):
        monitor = ProcessMonitor(".")
        monitor.set_blacklist(["discord.exe"], usernames=["student"])

        matches = monitor._detect_blacklist_matches({(1234, "discord.exe")})

        self.assertEqual(len(matches), 1)
        self.assertIsNone(matches[0]["username"])

    def test_emit_current_snapshot_runs_detection_without_waiting_for_loop_tick(self):
        observed = []
        monitor = ProcessMonitor(
            ".",
            poll_callback=lambda processes, version: observed.append((processes, version)),
        )
        monitor.blacklist_version = "policy-v1"
        with patch.object(monitor, "_get_current_processes", return_value={(2222, "unknown.exe")}):
            processes = monitor.emit_current_snapshot()

        self.assertEqual(processes, {(2222, "unknown.exe")})
        self.assertEqual(observed, [({(2222, "unknown.exe")}, "policy-v1")])

    def test_process_poll_interval_is_fast_enough_for_unknown_processes(self):
        self.assertLessEqual(DIFF_INTERVAL_SECONDS, 5)


if __name__ == "__main__":
    unittest.main()
