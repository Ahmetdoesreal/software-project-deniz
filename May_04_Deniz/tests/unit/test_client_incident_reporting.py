import asyncio
import unittest

from common import events, protocol
from client.ws_client import WebSocketSession


class _SessionState:
    def __init__(self):
        self.disconnected = asyncio.Event()


class ClientIncidentReportingTests(unittest.IsolatedAsyncioTestCase):
    async def test_incident_report_is_sent_before_evidence_upload_completes(self):
        session = WebSocketSession.__new__(WebSocketSession)
        session.session_uuid = "session-1"
        session.state = _SessionState()
        session.sent_messages = []
        session.background_tasks = set()
        upload_release = asyncio.Event()

        async def send_payload(payload: str):
            session.sent_messages.append(protocol.decode(payload))

        async def upload_incident_evidence(_incident: dict):
            await upload_release.wait()
            return "data/server/artifacts/session-1/incident_bundle.zip"

        def schedule_background_task(coroutine):
            task = asyncio.create_task(coroutine)
            session.background_tasks.add(task)
            task.add_done_callback(session.background_tasks.discard)
            return task

        session._send_payload = send_payload
        session._upload_incident_evidence = upload_incident_evidence
        session._schedule_background_task = schedule_background_task

        await session._report_incident(
            {
                "incident_id": "incident-1",
                "rule_id": "process_blacklist",
                "rule_name": "Process Blacklist",
                "status": "opened",
                "severity": "violation",
                "summary": "Blacklisted process detected",
                "needs_evidence": True,
            }
        )

        self.assertEqual(len(session.sent_messages), 1)
        event, payload = session.sent_messages[0]
        self.assertEqual(event, events.INCIDENT_REPORT)
        self.assertEqual(payload["status"], "opened")
        self.assertEqual(payload["evidence_status"], "pending")
        self.assertNotIn("artifact_path", payload)

        upload_release.set()
        await asyncio.gather(*session.background_tasks)

        self.assertEqual(len(session.sent_messages), 2)
        event, payload = session.sent_messages[1]
        self.assertEqual(event, events.INCIDENT_REPORT)
        self.assertEqual(payload["status"], "evidence_uploaded")
        self.assertEqual(payload["evidence_status"], "uploaded")
        self.assertEqual(payload["artifact_path"], "data/server/artifacts/session-1/incident_bundle.zip")


if __name__ == "__main__":
    unittest.main()
