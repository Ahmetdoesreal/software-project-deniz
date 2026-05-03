import unittest
import uuid

from common import events, protocol


class SaveScreenEventTests(unittest.TestCase):
    def test_savescreen_generates_request_identity(self):
        event, payload = protocol.decode(events.savescreen())

        self.assertEqual(event, events.SAVESCREEN)
        uuid.UUID(payload["request_id"])
        self.assertTrue(payload["requested_at"])
        self.assertEqual(payload["source"], "server_request")

    def test_savescreen_preserves_supplied_request_identity(self):
        event, payload = protocol.decode(
            events.savescreen(
                request_id="req-123",
                requested_at="2026-05-02T10:00:00+00:00",
                source="admin_gui",
            )
        )

        self.assertEqual(event, events.SAVESCREEN)
        self.assertEqual(payload["request_id"], "req-123")
        self.assertEqual(payload["requested_at"], "2026-05-02T10:00:00+00:00")
        self.assertEqual(payload["source"], "admin_gui")


if __name__ == "__main__":
    unittest.main()
