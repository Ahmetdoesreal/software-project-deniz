import unittest

from common.incident_rules import (
    apply_incident_rule_to_incident,
    best_incident_rule,
    default_incident_rules,
    incident_matches_rule,
    normalize_incident_rule,
)


class IncidentRulesTests(unittest.TestCase):
    def test_default_new_tab_whitelist_matches_browser_title(self):
        incident = {
            "rule_id": "focused_window_policy",
            "event_type": "focused_window_policy",
            "source": "focused_window",
            "process_name": "msedge.exe",
            "window_title": "New Tab - Microsoft Edge",
            "status": "opened",
            "severity": "warning",
        }

        rule = best_incident_rule(default_incident_rules(), incident)

        self.assertIsNotNone(rule)
        self.assertEqual(rule["status"], "whitelist")
        self.assertIsNone(apply_incident_rule_to_incident(default_incident_rules(), incident))

    def test_whitelist_priority_suppresses_blacklist(self):
        definitions = [
            {
                "name": "Block browser",
                "status": "blacklist",
                "source": "focused_window",
                "browser_process_names": ["chrome.exe"],
                "priority": 1000,
            },
            {
                "name": "Allowed exam portal",
                "status": "whitelist",
                "source": "focused_window",
                "browser_process_names": ["chrome.exe"],
                "window_title_patterns": ["CATS"],
                "priority": 1,
            },
        ]
        incident = {
            "source": "focused_window",
            "process_name": "chrome.exe",
            "window_title": "CATS - Exam Portal - Google Chrome",
            "status": "opened",
        }

        self.assertEqual(best_incident_rule(definitions, incident)["status"], "whitelist")

    def test_blacklist_rule_attaches_actions_and_severity(self):
        rule = normalize_incident_rule(
            {
                "name": "Block chat title",
                "status": "blacklist",
                "event_type": "focused_window_policy",
                "window_title_patterns": ["Discord"],
                "actions": {"pause_exam": True, "kill_pid": True},
            }
        )
        incident = {
            "event_type": "focused_window_policy",
            "window_title": "Discord - Chat",
            "status": "opened",
            "severity": "warning",
        }

        updated = apply_incident_rule_to_incident([rule], incident)

        self.assertIsNotNone(updated)
        self.assertEqual(updated["severity"], "violation")
        self.assertEqual(updated["matched_incident_rule_id"], rule["definition_id"])
        self.assertTrue(updated["configured_actions"]["pause_exam"])
        self.assertTrue(updated["configured_actions"]["kill_pid"])

    def test_unicode_invisible_title_characters_are_normalized(self):
        rule = {
            "event_type": "focused_window_policy",
            "window_title_patterns": ["Yandex Microsoft Edge"],
            "match_mode": "contains",
        }
        incident = {
            "event_type": "focused_window_policy",
            "window_title": "Yandex\u200e\u00a0Microsoft\u2060 Edge",
        }

        self.assertTrue(incident_matches_rule(incident, rule))


if __name__ == "__main__":
    unittest.main()
