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
    ],
}


class ClientIncidentEngineTests(unittest.TestCase):
    def test_process_blacklist_incident_opens_once_and_resolves(self):
        engine = ClientIncidentEngine()
        ok, reason = engine.apply_policy(PROCESS_BLACKLIST_POLICY)
        self.assertTrue(ok, reason)

        incidents = engine.observe_processes({(1234, "discord.exe")})
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["status"], "opened")
        self.assertEqual(incidents[0]["pid"], 1234)

        self.assertEqual(engine.observe_processes({(1234, "discord.exe")}), [])

        resolved = engine.observe_processes(set())
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["status"], "resolved")
        self.assertEqual(resolved[0]["incident_id"], incidents[0]["incident_id"])

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


if __name__ == "__main__":
    unittest.main()
