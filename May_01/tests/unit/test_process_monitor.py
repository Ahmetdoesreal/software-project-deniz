import unittest

from custommodules.process_monitor.core import ProcessMonitor


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


if __name__ == "__main__":
    unittest.main()
