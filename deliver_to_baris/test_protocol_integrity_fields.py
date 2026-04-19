import json
import unittest

import protocol


class ProtocolIntegrityFieldTests(unittest.TestCase):
    def test_decode_preserves_top_level_integrity_fields(self):
        raw = json.loads(protocol.encode("status_update", {"student_id": "2300005352"}))
        raw.update(
            {
                "seq": 7,
                "session_id": "client-session-1",
                "buffered": True,
                "queued_at": "2026-04-19T00:00:00",
            }
        )

        event, payload = protocol.decode(json.dumps(raw))

        self.assertEqual(event, "status_update")
        self.assertEqual(payload["student_id"], "2300005352")
        self.assertEqual(payload["seq"], 7)
        self.assertEqual(payload["session_id"], "client-session-1")
        self.assertIs(payload["buffered"], True)

    def test_decode_tolerates_payload_integrity_fields_added_after_checksum(self):
        raw = json.loads(protocol.encode("status_update", {"student_id": "2300005352"}))
        raw["data"]["seq"] = 8
        raw["data"]["session_id"] = "client-session-2"
        raw["data"]["buffered"] = False

        event, payload = protocol.decode(json.dumps(raw))

        self.assertEqual(event, "status_update")
        self.assertEqual(payload["seq"], 8)
        self.assertEqual(payload["session_id"], "client-session-2")
        self.assertIs(payload["buffered"], False)

    def test_decode_rejects_non_integrity_payload_mutation(self):
        raw = json.loads(protocol.encode("status_update", {"student_id": "2300005352"}))
        raw["data"]["student_id"] = "attacker"

        event, payload = protocol.decode(json.dumps(raw))

        self.assertEqual(event, protocol.DECODE_ERROR)
        self.assertEqual(payload["reason"], "message checksum mismatch")


if __name__ == "__main__":
    unittest.main()
