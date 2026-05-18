import unittest

from common.incident_rules import normalize_incident_rule
from server.settings_service import apply_incident_rule_decision, build_incident_rules_database
from server.ui.process_database_helpers import build_incident_rule_decision_payload, incident_rule_row_from_incident


class FakeState:
    def __init__(self):
        self.incident_rules = []
        self.incident_rules_version = "rules-v1"
        self.process_blacklist = []
        self.process_blacklist_version = "process-blacklist-v1"
        self.process_definitions = []
        self.process_definitions_version = "process-definitions-v1"
        self.incidents = []
        self.active_incidents = {}
        self.users_db = {}
        self.clients = {}
        self.audit = []
        self.saved_incident_rules = 0
        self.saved_incidents = 0
        self.saved_users = 0

    def rule_config(self, rule_id):
        if rule_id == "incident_rules":
            return {"definitions": self.incident_rules}
        if rule_id == "process_definitions":
            return {"definitions": self.process_definitions}
        return {}

    def current_exam_policy(self):
        return {"policy_version": "policy-v1"}

    def _policy_without_process_definitions(self):
        return {"rules": {}}

    def operator_defaults(self):
        return {}

    def session_policy(self):
        return {}

    def save_incident_rules(self):
        self.saved_incident_rules += 1

    def save_incidents(self):
        self.saved_incidents += 1

    def save_users(self):
        self.saved_users += 1

    def append_audit(self, entry):
        self.audit.append(entry)

    def find_user_by_uuid(self, client_id):
        return "", None


def incident_rule(**overrides):
    payload = {
        "definition_id": "stable-title-rule",
        "name": "Focused window / WhatsApp",
        "status": "warning",
        "rule_id": "focused_window_policy",
        "event_type": "focused_window_policy",
        "source": "focused_window",
        "window_title_patterns": ["WhatsApp"],
        "match_mode": "contains",
        "source_incident_id": "incident-1",
    }
    payload.update(overrides)
    return normalize_incident_rule(payload)


def incident(**overrides):
    payload = {
        "incident_id": "incident-1",
        "client_id": "client-1",
        "login_id": "student-1",
        "status": "opened",
        "severity": "warning",
        "rule_id": "focused_window_policy",
        "event_type": "focused_window_policy",
        "source": "focused_window",
        "process_name": "chrome.exe",
        "window_title": "WhatsApp - Google Chrome",
        "summary": "Focused window matched WhatsApp",
    }
    payload.update(overrides)
    return payload


class IncidentRuleIdentityTests(unittest.TestCase):
    def test_automatic_incident_rule_row_keeps_saved_identity(self):
        saved = incident_rule()
        row = incident_rule_row_from_incident(
            incident(
                incident_rule_decision={
                    "definition_id": saved["definition_id"],
                    "rule_key": saved["rule_key"],
                    "saved_to_policy": True,
                }
            )
        )

        payload = build_incident_rule_decision_payload(
            row,
            status="warning",
            actions={},
            save_policy=True,
            window_title_patterns=["WhatsApp Chat"],
        )

        self.assertEqual(row["definition_id"], "stable-title-rule")
        self.assertEqual(payload["definition"]["definition_id"], "stable-title-rule")
        self.assertEqual(payload["definition"]["original_definition_id"], "stable-title-rule")
        self.assertEqual(payload["definition"]["original_rule_key"], saved["rule_key"])

    def test_identityless_source_incident_edit_replaces_existing_rule(self):
        state = FakeState()
        state.incident_rules = [incident_rule()]
        state.incidents = [incident()]

        result = apply_incident_rule_decision(
            state,
            {
                "definition": {
                    "name": "Focused window / WhatsApp Chat",
                    "status": "warning",
                    "rule_id": "focused_window_policy",
                    "event_type": "focused_window_policy",
                    "source": "focused_window",
                    "window_title_patterns": ["WhatsApp Chat"],
                    "match_mode": "contains",
                    "source_incident_id": "incident-1",
                },
                "status": "warning",
                "actions": {},
                "save_policy": True,
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(len(state.incident_rules), 1)
        self.assertEqual(state.incident_rules[0]["definition_id"], "stable-title-rule")
        self.assertEqual(state.incident_rules[0]["window_title_patterns"], ["WhatsApp Chat"])
        self.assertEqual(result["definition"]["definition_id"], "stable-title-rule")

    def test_database_links_saved_source_incident_after_match_fields_change(self):
        state = FakeState()
        state.incident_rules = [
            incident_rule(
                window_title_patterns=["A title that no longer matches the original incident"],
            )
        ]
        saved = state.incident_rules[0]
        state.incidents = [
            incident(
                incident_rule_decision={
                    "definition_id": saved["definition_id"],
                    "rule_key": saved["rule_key"],
                    "saved_to_policy": True,
                }
            )
        ]

        rows = build_incident_rules_database(state)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["definition_id"], "stable-title-rule")
        self.assertEqual(rows[0]["match_count"], 1)


if __name__ == "__main__":
    unittest.main()
