import unittest

from common import events, protocol, security


class SecurityTests(unittest.TestCase):
    def test_secures_and_decodes_signed_message(self):
        context = security.build_session_context("session-1", "secret")
        context.encrypt_events = set()

        raw = events.exam_policy({"policy_version": "v1", "rules": []})
        protected = security.protect_wire_message(raw, context)
        event, data = security.decode_wire_message(protected, context)

        self.assertEqual(event, events.EXAM_POLICY)
        self.assertEqual(data["policy_version"], "v1")

    def test_rejects_replayed_nonce(self):
        context = security.build_session_context("session-2", "secret")
        context.encrypt_events = set()

        raw = events.incident_report({"incident_id": "incident-1", "rule_id": "process_blacklist"})
        protected = security.protect_wire_message(raw, context)

        first_event, _ = security.decode_wire_message(protected, context)
        second_event, second_data = security.decode_wire_message(protected, context)

        self.assertEqual(first_event, events.INCIDENT_REPORT)
        self.assertEqual(second_event, protocol.DECODE_ERROR)
        self.assertIn("replayed message nonce", second_data["reason"])

    def test_rejects_unsecured_message_for_secured_event(self):
        context = security.build_session_context("session-3", "secret")
        raw = events.pause_exam(60, source="admin", reason="Paused")

        event, data = security.decode_wire_message(raw, context)

        self.assertEqual(event, protocol.DECODE_ERROR)
        self.assertIn("missing secured envelope", data["reason"])

    @unittest.skipUnless(security.encryption_available(), "cryptography is not installed")
    def test_encrypted_round_trip_when_cryptography_is_available(self):
        context = security.build_session_context("session-4", "secret")
        raw = events.session_state("running", 120, policy_version="v1")

        protected = security.protect_wire_message(raw, context)
        outer_event, outer_data = protocol.decode(protected)
        decoded_event, decoded_data = security.decode_wire_message(protected, context)

        self.assertEqual(outer_event, events.SESSION_STATE)
        self.assertTrue(outer_data["encrypted"])
        self.assertEqual(decoded_event, events.SESSION_STATE)
        self.assertEqual(decoded_data["remaining_seconds"], 120)


if __name__ == "__main__":
    unittest.main()
