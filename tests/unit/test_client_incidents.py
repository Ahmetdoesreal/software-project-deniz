import unittest

from client.incidents import ClientIncidentEngine


PROCESS_BLACKLIST_POLICY = {
    "policy_version": "policy-v1",
    "rules": [
        {
            "rule_id": "process_blacklist",
            "source": "process_monitor",
            "type": "process_blacklist",
            "enabled": True,
            "severity": "violation",
            "entries": ["discord.exe"],
            "blacklist_version": "blacklist-v1",
            "process_usernames": ["student"],
        },
        {
            "rule_id": "focused_window_policy",
            "source": "focused_window",
            "type": "focused_window",
            "enabled": True,
            "severity": "warning",
            "allowed_process_names": ["exam.exe"],
            "allowed_window_titles": [],
            "blocked_process_names": [],
            "blocked_window_titles": [],
            "open_after_consecutive": 3,
            "resolve_after_consecutive": 2,
        },
        {
            "rule_id": "rapid_application_switching",
            "source": "focused_window",
            "type": "rapid_application_switching",
            "enabled": True,
            "severity": "warning",
            "max_switches": 3,
            "window_observations": 4,
        },
        {
            "rule_id": "unexpected_process",
            "source": "process_monitor",
            "type": "unexpected_process",
            "enabled": True,
            "severity": "warning",
            "known_process_names": ["exam.exe", "python.exe"],
            "allowed_process_names": ["browser.exe"],
        },
    ],
}


class ClientIncidentEngineTests(unittest.TestCase):
    def test_process_blacklist_incident_opens_once_and_resolves(self):
        engine = ClientIncidentEngine()
        ok, reason = engine.apply_policy(PROCESS_BLACKLIST_POLICY)
        self.assertTrue(ok, reason)

        incidents = engine.observe_processes({(1234, "discord.exe", "DESKTOP\\student")})
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["status"], "opened")
        self.assertEqual(incidents[0]["pid"], 1234)
        self.assertEqual(incidents[0]["process_username"], "DESKTOP\\student")

        self.assertEqual(engine.observe_processes({(1234, "discord.exe", "DESKTOP\\student")}), [])

        resolved = engine.observe_processes(set())
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["status"], "resolved")
        self.assertEqual(resolved[0]["incident_id"], incidents[0]["incident_id"])

    def test_process_blacklist_ignores_unmonitored_process_owner(self):
        engine = ClientIncidentEngine()
        ok, reason = engine.apply_policy(PROCESS_BLACKLIST_POLICY)
        self.assertTrue(ok, reason)

        incidents = engine.observe_processes({(1234, "discord.exe", "DESKTOP\\other")})

        self.assertEqual(incidents, [])

    def test_focused_window_incident_uses_debounce_and_resolve_thresholds(self):
        engine = ClientIncidentEngine()
        ok, reason = engine.apply_policy(PROCESS_BLACKLIST_POLICY)
        self.assertTrue(ok, reason)

        violating_window = {
            "process_name": "chrome.exe",
            "window_title": "Browser",
            "process_id": 999,
        }
        allowed_window = {
            "process_name": "exam.exe",
            "window_title": "Exam App",
            "process_id": 111,
        }

        self.assertEqual(engine.observe_focused_window(violating_window), [])
        self.assertEqual(engine.observe_focused_window(violating_window), [])
        opened = engine.observe_focused_window(violating_window)
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]["status"], "opened")

        self.assertEqual(engine.observe_focused_window(allowed_window), [])
        resolved = engine.observe_focused_window(allowed_window)
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["status"], "resolved")
        self.assertEqual(resolved[0]["incident_id"], opened[0]["incident_id"])

    def test_rapid_switching_does_not_open_before_threshold(self):
        engine = ClientIncidentEngine()
        ok, reason = engine.apply_policy(PROCESS_BLACKLIST_POLICY)
        self.assertTrue(ok, reason)

        self.assertEqual(engine.observe_focused_window({"process_name": "exam.exe", "window_title": "Exam"}), [])
        self.assertEqual(engine.observe_focused_window({"process_name": "notes.exe", "window_title": "Notes"}), [])
        self.assertEqual(engine.observe_focused_window({"process_name": "exam.exe", "window_title": "Exam"}), [])

    def test_rapid_switching_opens_after_threshold(self):
        engine = ClientIncidentEngine()
        ok, reason = engine.apply_policy(PROCESS_BLACKLIST_POLICY)
        self.assertTrue(ok, reason)

        snapshots = [
            {"process_name": "exam.exe", "window_title": "Exam"},
            {"process_name": "notes.exe", "window_title": "Notes"},
            {"process_name": "exam.exe", "window_title": "Exam"},
            {"process_name": "browser.exe", "window_title": "Search"},
        ]
        incidents = []
        for snapshot in snapshots:
            incidents.extend(engine.observe_focused_window(snapshot))

        rapid = [incident for incident in incidents if incident["rule_id"] == "rapid_application_switching"]
        self.assertEqual(len(rapid), 1)
        self.assertEqual(rapid[0]["status"], "opened")
        self.assertEqual(rapid[0]["event_type"], "rapid_application_switching")
        self.assertEqual(rapid[0]["switch_count"], 3)
        self.assertEqual(len(rapid[0]["recent_switches"]), 3)

    def test_unexpected_process_opens_for_new_unapproved_process(self):
        engine = ClientIncidentEngine()
        ok, reason = engine.apply_policy(PROCESS_BLACKLIST_POLICY)
        self.assertTrue(ok, reason)

        incidents = engine.observe_processes({(1, "exam.exe"), (2, "unknown_tool.exe")})
        unexpected = [incident for incident in incidents if incident["rule_id"] == "unexpected_process"]

        self.assertEqual(len(unexpected), 1)
        self.assertEqual(unexpected[0]["status"], "opened")
        self.assertEqual(unexpected[0]["event_type"], "unexpected_process")
        self.assertEqual(unexpected[0]["pid"], 2)
        self.assertEqual(unexpected[0]["process_name"], "unknown_tool.exe")
        self.assertEqual(unexpected[0]["severity"], "warning")

    def test_unexpected_process_ignores_known_and_allowed_processes(self):
        engine = ClientIncidentEngine()
        ok, reason = engine.apply_policy(PROCESS_BLACKLIST_POLICY)
        self.assertTrue(ok, reason)

        incidents = engine.observe_processes({(1, "exam.exe"), (2, "python.exe"), (3, "browser.exe")})

        self.assertEqual([incident for incident in incidents if incident["rule_id"] == "unexpected_process"], [])

    def test_focused_window_blocked_title_uses_contains_matching(self):
        engine = ClientIncidentEngine()
        policy = dict(PROCESS_BLACKLIST_POLICY)
        policy["rules"] = [dict(rule) for rule in PROCESS_BLACKLIST_POLICY["rules"]]
        policy["rules"][1].update(
            {
                "allowed_process_names": [],
                "blocked_window_titles": ["discord"],
                "window_title_match_mode": "contains",
                "open_after_consecutive": 1,
            }
        )
        ok, reason = engine.apply_policy(policy)
        self.assertTrue(ok, reason)

        incidents = engine.observe_focused_window(
            {"process_name": "chrome.exe", "window_title": "Discord - Chat", "process_id": 1}
        )

        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["status"], "opened")

    def test_focused_window_allowed_title_uses_contains_matching(self):
        engine = ClientIncidentEngine()
        policy = dict(PROCESS_BLACKLIST_POLICY)
        policy["rules"] = [dict(rule) for rule in PROCESS_BLACKLIST_POLICY["rules"]]
        policy["rules"][1].update(
            {
                "allowed_process_names": [],
                "allowed_window_titles": ["exam portal"],
                "window_title_match_mode": "contains",
                "open_after_consecutive": 1,
            }
        )
        ok, reason = engine.apply_policy(policy)
        self.assertTrue(ok, reason)

        incidents = engine.observe_focused_window(
            {"process_name": "browser.exe", "window_title": "Spring Exam Portal - Question 1", "process_id": 1}
        )

        self.assertEqual(incidents, [])


if __name__ == "__main__":
    unittest.main()
