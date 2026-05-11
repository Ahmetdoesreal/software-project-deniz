import os
import tempfile
import unittest

from client.incident_buffer import IncidentBuffer


class IncidentBufferTests(unittest.TestCase):
    def test_mark_buffered_survives_restore_without_duplicate_seq(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                buffer = IncidentBuffer()
                buffer.begin_session("uuid-1")
                payload = buffer.enqueue({"incident_id": "incident-1", "rule_id": "rule", "status": "opened"})
                buffer.mark_sent(payload["seq"])
                buffer.mark_buffered(payload["seq"], "send_failed")

                restored = IncidentBuffer()
                restored.begin_session("uuid-1")
                unacked = restored.get_unacked()

                self.assertEqual(len(unacked), 1)
                self.assertEqual(unacked[0]["seq"], payload["seq"])
                self.assertTrue(unacked[0]["buffered"])
            finally:
                os.chdir(old_cwd)

    def test_pending_evidence_survives_restore_and_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                buffer = IncidentBuffer()
                buffer.begin_session("uuid-1")
                buffer.mark_evidence_pending({"incident_id": "incident-1", "needs_evidence": True})

                restored = IncidentBuffer()
                restored.begin_session("uuid-1")
                self.assertEqual(len(restored.get_pending_evidence()), 1)

                restored.mark_evidence_complete("incident-1", "artifact.zip")
                again = IncidentBuffer()
                again.begin_session("uuid-1")
                self.assertEqual(again.get_pending_evidence(), [])
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
