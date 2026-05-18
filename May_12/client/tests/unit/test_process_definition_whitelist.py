import unittest

from client.incidents import ClientIncidentEngine


def policy(*, version: str, definitions=None, detect_unknown: bool = True) -> dict:
    return {
        "policy_version": version,
        "rules": [
            {
                "rule_id": "process_definitions",
                "enabled": True,
                "definitions": definitions or [],
                "detect_unknown_processes": detect_unknown,
                "unknown_severity": "warning",
                "baseline_existing_processes": False,
            },
            {
                "rule_id": "unexpected_process",
                "enabled": False,
            },
        ],
    }


class ProcessDefinitionWhitelistTests(unittest.TestCase):
    def test_name_whitelist_resolves_open_unexpected_process(self):
        engine = ClientIncidentEngine()
        ok, error = engine.apply_policy(policy(version="v1"))
        self.assertTrue(ok, error)

        opened = engine.observe_processes({(1001, "WidgetHost.exe", None, None)})
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]["rule_id"], "unexpected_process")
        self.assertEqual(opened[0]["status"], "opened")

        ok, error = engine.apply_policy(
            policy(
                version="v2",
                definitions=[
                    {
                        "process_name": "WidgetHost.exe",
                        "match_scope": "name",
                        "status": "whitelist",
                    }
                ],
            )
        )
        self.assertTrue(ok, error)

        resolved = engine.observe_processes({(1001, "WidgetHost.exe", None, None)})
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["incident_id"], opened[0]["incident_id"])
        self.assertEqual(resolved[0]["status"], "resolved")

    def test_disabling_unknown_detection_resolves_open_unexpected_process(self):
        engine = ClientIncidentEngine()
        ok, error = engine.apply_policy(policy(version="v1"))
        self.assertTrue(ok, error)

        opened = engine.observe_processes({(1001, "WidgetHost.exe", None, None)})
        self.assertEqual(len(opened), 1)

        ok, error = engine.apply_policy(policy(version="v2", detect_unknown=False))
        self.assertTrue(ok, error)

        resolved = engine.observe_processes({(1001, "WidgetHost.exe", None, None)})
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["incident_id"], opened[0]["incident_id"])
        self.assertEqual(resolved[0]["status"], "resolved")


if __name__ == "__main__":
    unittest.main()
