import unittest

from incident_engine import IncidentEngine


def test_policy() -> dict:
    return {
        "policy_version": "test",
        "rules": [
            {
                "rule_id": "process_blacklist",
                "source": "activity_monitor",
                "enabled": True,
                "severity": "violation",
                "entries": ["discord"],
                "process_usernames": ["student"],
            },
            {
                "rule_id": "unexpected_process",
                "source": "activity_monitor",
                "enabled": True,
                "severity": "warning",
                "known_process_names": ["python"],
                "allowed_process_names": [],
            },
            {
                "rule_id": "focused_window_policy",
                "source": "activity_monitor",
                "enabled": True,
                "severity": "warning",
                "allowed_process_names": ["exam"],
                "open_after_consecutive": 1,
                "resolve_after_consecutive": 1,
            },
            {
                "rule_id": "rapid_application_switching",
                "source": "activity_monitor",
                "enabled": True,
                "severity": "warning",
                "max_switches": 2,
                "window_observations": 3,
            },
        ],
    }


class IncidentEngineTests(unittest.TestCase):
    def engine(self) -> IncidentEngine:
        engine = IncidentEngine()
        ok, reason = engine.apply_policy(test_policy())
        self.assertTrue(ok, reason)
        return engine

    def test_blocked_process_checks_process_owner(self):
        engine = self.engine()

        other_user = engine.watch_processes({(10, "discord.exe", "DESKTOP\\other")})
        student_user = engine.watch_processes({(11, "discord.exe", "DESKTOP\\student")})

        self.assertEqual([item for item in other_user if item["rule_id"] == "process_blacklist"], [])
        blocked = [item for item in student_user if item["rule_id"] == "process_blacklist"]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["process_username"], "DESKTOP\\student")

    def test_unexpected_process_uses_first_snapshot_as_baseline(self):
        engine = self.engine()

        first = engine.watch_processes({(1, "python.exe", "student"), (2, "already_open.exe", "student")})
        second = engine.watch_processes(
            {
                (1, "python.exe", "student"),
                (2, "already_open.exe", "student"),
                (3, "new_tool.exe", "student"),
            }
        )

        self.assertEqual([item for item in first if item["rule_id"] == "unexpected_process"], [])
        unexpected = [item for item in second if item["rule_id"] == "unexpected_process"]
        self.assertEqual(len(unexpected), 1)
        self.assertEqual(unexpected[0]["process_name"], "new_tool.exe")

    def test_focus_and_rapid_switching_incidents(self):
        engine = self.engine()

        focus = engine.watch_window({"process_name": "browser", "window_title": "Search"})
        self.assertEqual([item["rule_id"] for item in focus], ["focused_window_policy"])

        engine.watch_window({"process_name": "exam", "window_title": "Exam"})
        rapid = []
        rapid.extend(engine.watch_window({"process_name": "notes", "window_title": "Notes"}))
        rapid.extend(engine.watch_window({"process_name": "browser", "window_title": "Browser"}))

        self.assertTrue(any(item["rule_id"] == "rapid_application_switching" for item in rapid))


if __name__ == "__main__":
    unittest.main()
