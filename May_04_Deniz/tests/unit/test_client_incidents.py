import unittest
from unittest.mock import patch

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
            "window_seconds": 60,
            "window_observations": 4,
        },
        {
            "rule_id": "unexpected_process",
            "source": "process_monitor",
            "type": "unexpected_process",
            "enabled": True,
            "severity": "warning",
            "known_process_names": ["exam.exe", "python.exe"],
            "known_directory_paths": [],
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

    def test_idle_policy_opens_and_resolves_incidents(self):
        engine = ClientIncidentEngine()
        ok, reason = engine.apply_policy(
            {
                "policy_version": "policy-idle",
                "rules": [
                    {
                        "rule_id": "idle_policy",
                        "source": "idle_monitor",
                        "type": "idle_policy",
                        "enabled": True,
                        "warn_threshold_seconds": 5,
                        "critical_threshold_seconds": 10,
                        "auto_violation_pause": True,
                    }
                ],
            }
        )
        self.assertTrue(ok, reason)

        opened = engine.observe_idle({"idle_seconds": 6})
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]["rule_id"], "idle_policy")
        self.assertEqual(opened[0]["event_type"], "idle_warn")

        self.assertEqual(engine.observe_idle({"idle_seconds": 6}), [])

        resolved = engine.observe_idle({"idle_seconds": 0})
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["status"], "resolved")
        self.assertEqual(resolved[0]["event_type"], "idle_resolved")

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

    def test_rapid_switching_resolves_after_cooling_below_threshold(self):
        engine = ClientIncidentEngine()
        policy = dict(PROCESS_BLACKLIST_POLICY)
        policy["rules"] = list(PROCESS_BLACKLIST_POLICY["rules"])
        policy["rules"][2] = dict(policy["rules"][2], max_switches=2, window_seconds=3)
        ok, reason = engine.apply_policy(policy)
        self.assertTrue(ok, reason)

        snapshots = [
            {"process_name": "exam.exe", "window_title": "Exam", "timestamp": "2026-01-01T00:00:00+00:00"},
            {"process_name": "notes.exe", "window_title": "Notes", "timestamp": "2026-01-01T00:00:01+00:00"},
            {"process_name": "exam.exe", "window_title": "Exam", "timestamp": "2026-01-01T00:00:02+00:00"},
        ]
        incidents = []
        for snapshot in snapshots:
            incidents.extend(engine.observe_focused_window(snapshot))
        opened = [incident for incident in incidents if incident["rule_id"] == "rapid_application_switching" and incident["status"] == "opened"]
        self.assertEqual(len(opened), 1)

        resolved = engine.observe_focused_window(
            {"process_name": "exam.exe", "window_title": "Exam", "timestamp": "2026-01-01T00:00:10+00:00"}
        )
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["status"], "resolved")
        self.assertEqual(resolved[0]["incident_id"], opened[0]["incident_id"])

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

    def test_unexpected_process_includes_path_and_does_not_auto_learn(self):
        engine = ClientIncidentEngine()
        ok, reason = engine.apply_policy(PROCESS_BLACKLIST_POLICY)
        self.assertTrue(ok, reason)

        process = (2, "unknown_tool.exe", None, "C:\\Tools\\unknown_tool.exe")
        incidents = engine.observe_processes({(1, "exam.exe"), process})
        unexpected = [incident for incident in incidents if incident["rule_id"] == "unexpected_process"]

        self.assertEqual(len(unexpected), 1)
        self.assertEqual(unexpected[0]["process_path"], "C:\\Tools\\unknown_tool.exe")
        self.assertEqual(unexpected[0]["process_dir"], "C:\\Tools")

        resolved = engine.observe_processes({(1, "exam.exe")})
        self.assertEqual([incident["status"] for incident in resolved], ["resolved"])

        reopened = engine.observe_processes({(1, "exam.exe"), process})
        unexpected_reopened = [incident for incident in reopened if incident["rule_id"] == "unexpected_process"]
        self.assertEqual(len(unexpected_reopened), 1)
        self.assertEqual(unexpected_reopened[0]["status"], "opened")

    def test_unexpected_process_accepts_legacy_process_tuple(self):
        engine = ClientIncidentEngine()
        ok, reason = engine.apply_policy(PROCESS_BLACKLIST_POLICY)
        self.assertTrue(ok, reason)

        incidents = engine.observe_processes({(2, "unknown_tool.exe")})
        unexpected = [incident for incident in incidents if incident["rule_id"] == "unexpected_process"]

        self.assertEqual(len(unexpected), 1)
        self.assertIsNone(unexpected[0]["process_path"])

    def test_unexpected_process_ignores_known_directory_with_percent_env_var(self):
        engine = ClientIncidentEngine()
        policy = dict(PROCESS_BLACKLIST_POLICY)
        policy["rules"] = [dict(rule) for rule in PROCESS_BLACKLIST_POLICY["rules"]]
        policy["rules"][3]["known_directory_paths"] = ["%WINDIR%"]

        with patch.dict("os.environ", {"WINDIR": "C:\\Windows"}):
            ok, reason = engine.apply_policy(policy)
            self.assertTrue(ok, reason)
            incidents = engine.observe_processes(
                {(1, "cmd.exe", None, "C:\\Windows\\System32\\cmd.exe")}
            )

        self.assertEqual([incident for incident in incidents if incident["rule_id"] == "unexpected_process"], [])

    def test_known_directory_does_not_match_similar_prefix_without_separator(self):
        engine = ClientIncidentEngine()
        policy = dict(PROCESS_BLACKLIST_POLICY)
        policy["rules"] = [dict(rule) for rule in PROCESS_BLACKLIST_POLICY["rules"]]
        policy["rules"][3]["known_directory_paths"] = ["C:\\Windows"]

        ok, reason = engine.apply_policy(policy)
        self.assertTrue(ok, reason)
        incidents = engine.observe_processes(
            {(1, "tool.exe", None, "C:\\WindowsFake\\tool.exe")}
        )
        unexpected = [incident for incident in incidents if incident["rule_id"] == "unexpected_process"]

        self.assertEqual(len(unexpected), 1)

    def test_unexpected_process_ignores_known_and_allowed_processes(self):
        engine = ClientIncidentEngine()
        ok, reason = engine.apply_policy(PROCESS_BLACKLIST_POLICY)
        self.assertTrue(ok, reason)

        incidents = engine.observe_processes({(1, "exam.exe"), (2, "python.exe"), (3, "browser.exe")})

        self.assertEqual([incident for incident in incidents if incident["rule_id"] == "unexpected_process"], [])

    def test_process_database_unknown_detection_baselines_then_detects_new_processes(self):
        engine = ClientIncidentEngine()
        policy = {
            "policy_version": "policy-v1",
            "rules": [
                {
                    "rule_id": "unexpected_process",
                    "source": "process_monitor",
                    "type": "unexpected_process",
                    "enabled": False,
                    "known_process_names": ["exam.exe"],
                    "known_directory_paths": [],
                    "allowed_process_names": [],
                },
                {
                    "rule_id": "process_definitions",
                    "source": "process_monitor",
                    "type": "process_definitions",
                    "enabled": True,
                    "definitions": [],
                    "detect_unknown_processes": True,
                    "baseline_existing_processes": True,
                },
            ],
        }
        ok, reason = engine.apply_policy(policy)
        self.assertTrue(ok, reason)

        first = engine.observe_processes({(1, "exam.exe"), (2, "already_open.exe")})
        self.assertEqual([incident for incident in first if incident["rule_id"] == "unexpected_process"], [])

        second = engine.observe_processes({(1, "exam.exe"), (2, "already_open.exe"), (3, "new_tool.exe")})
        unexpected = [incident for incident in second if incident["rule_id"] == "unexpected_process"]
        self.assertEqual(len(unexpected), 1)
        self.assertEqual(unexpected[0]["process_name"], "new_tool.exe")

        resolved = engine.observe_processes({(1, "exam.exe"), (2, "already_open.exe")})
        self.assertEqual([incident["status"] for incident in resolved], ["resolved"])

        reopened = engine.observe_processes({(1, "exam.exe"), (2, "already_open.exe"), (4, "new_tool.exe")})
        unexpected_reopened = [incident for incident in reopened if incident["rule_id"] == "unexpected_process"]
        self.assertEqual(len(unexpected_reopened), 1)

    def test_blacklist_path_clarification_runs_before_generic_unknown_detection(self):
        engine = ClientIncidentEngine()
        policy = {
            "policy_version": "policy-v1",
            "rules": [
                {
                    "rule_id": "process_blacklist",
                    "source": "process_monitor",
                    "type": "process_blacklist",
                    "enabled": True,
                    "severity": "violation",
                    "entries": ["discord.exe"],
                    "process_usernames": [],
                },
                {
                    "rule_id": "process_definitions",
                    "source": "process_monitor",
                    "type": "process_definitions",
                    "enabled": True,
                    "definitions": [
                        {
                            "process_name": "discord.exe",
                            "process_path": "C:\\Known\\discord.exe",
                            "status": "blacklist",
                        }
                    ],
                    "detect_unknown_processes": True,
                    "baseline_existing_processes": False,
                },
            ],
        }
        ok, reason = engine.apply_policy(policy)
        self.assertTrue(ok, reason)

        incidents = engine.observe_processes({(10, "discord.exe", None, "C:\\Other\\discord.exe")})

        self.assertEqual([incident["rule_id"] for incident in incidents], ["process_path_clarification"])

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
