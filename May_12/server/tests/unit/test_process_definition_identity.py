import unittest

from common.process_definitions import normalize_definition
from server.settings_service import apply_process_decision, build_process_database


class FakeState:
    def __init__(self):
        self.process_definitions = []
        self.process_definitions_version = "process-definitions-v1"
        self.incident_rules = []
        self.incident_rules_version = "incident-rules-v1"
        self.process_blacklist = []
        self.process_blacklist_version = "process-blacklist-v1"
        self.incidents = []
        self.active_incidents = {}
        self.users_db = {}
        self.clients = {}
        self.saved_process_definitions = 0
        self.saved_incidents = 0
        self.saved_users = 0
        self.audit = []

    def rule_config(self, rule_id):
        if rule_id == "process_definitions":
            return {"definitions": self.process_definitions}
        if rule_id == "incident_rules":
            return {"definitions": self.incident_rules}
        return {}

    def current_exam_policy(self):
        return {"policy_version": "policy-v1"}

    def _policy_without_process_definitions(self):
        return {"rules": {}}

    def operator_defaults(self):
        return {}

    def session_policy(self):
        return {}

    def save_process_definitions(self):
        self.saved_process_definitions += 1

    def save_incidents(self):
        self.saved_incidents += 1

    def save_users(self):
        self.saved_users += 1

    def append_incident(self, incident):
        incident_id = str(incident.get("incident_id", "") or "")
        if incident.get("status") == "resolved":
            self.active_incidents.pop(incident_id, None)
        elif incident_id:
            self.active_incidents[incident_id] = incident
        self.incidents.append(incident)

    def append_audit(self, entry):
        self.audit.append(entry)

    def find_user_by_uuid(self, client_id):
        return "", None


def process_definition(**overrides):
    payload = {
        "definition_id": "stable-process-definition",
        "process_name": "WidgetHost.exe",
        "process_path": r"C:\Tools\WidgetHost.exe",
        "process_dir": r"C:\Tools",
        "match_scope": "path",
        "status": "warning",
        "source_incident_id": "incident-1",
    }
    payload.update(overrides)
    return normalize_definition(payload)


def process_incident(**overrides):
    payload = {
        "incident_id": "incident-1",
        "client_id": "client-1",
        "login_id": "student-1",
        "status": "opened",
        "severity": "warning",
        "rule_id": "unexpected_process",
        "event_type": "unexpected_process",
        "source": "process_monitor",
        "pid": 1001,
        "process_name": "WidgetHost.exe",
        "process_path": r"C:\Tools\WidgetHost.exe",
        "process_dir": r"C:\Tools",
        "summary": "Unexpected process detected: WidgetHost.exe",
    }
    payload.update(overrides)
    return payload


class ProcessDefinitionIdentityTests(unittest.TestCase):
    def test_source_incident_edit_replaces_existing_process_definition(self):
        state = FakeState()
        existing_incident = process_incident()
        state.process_definitions = [process_definition()]
        state.incidents = [existing_incident]
        state.active_incidents = {"incident-1": existing_incident}

        result = apply_process_decision(
            state,
            {
                "definition": {
                    "process_name": "WidgetHost.exe",
                    "process_path": r"C:\Tools\WidgetHost.exe",
                    "process_dir": r"C:\Tools",
                    "match_scope": "directory",
                    "status": "whitelist",
                    "source_incident_id": "incident-1",
                },
                "status": "whitelist",
                "match_scope": "directory",
                "actions": {},
                "save_policy": True,
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(len(state.process_definitions), 1)
        self.assertEqual(state.process_definitions[0]["definition_id"], "stable-process-definition")
        self.assertEqual(state.process_definitions[0]["match_scope"], "directory")
        self.assertNotIn("incident-1", state.active_incidents)
        self.assertEqual(result["resolved_incident_ids"], ["incident-1"])

    def test_database_links_saved_source_incident_after_match_fields_change(self):
        state = FakeState()
        saved = process_definition(process_path=r"C:\Other\WidgetHost.exe", process_dir=r"C:\Other")
        state.process_definitions = [saved]
        state.incidents = [
            process_incident(
                process_decision={
                    "definition_id": saved["definition_id"],
                    "process_key": saved["process_key"],
                    "saved_to_policy": True,
                }
            )
        ]

        rows = build_process_database(state)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["definition_id"], "stable-process-definition")
        self.assertEqual(rows[0]["match_count"], 1)


if __name__ == "__main__":
    unittest.main()
