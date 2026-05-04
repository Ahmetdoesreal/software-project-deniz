import unittest

from common import protocol
from server.handlers import _handle_incident_report_event
from server import session_state
from server.state import state


class _FakeWS:
    def __init__(self):
        self.messages = []

    async def send_str(self, payload: str):
        self.messages.append(protocol.decode(payload))


class _FakeRequest:
    def __init__(self, exam_duration_minutes: int = 10):
        self.app = {"exam_duration": exam_duration_minutes}


class ServerHandlerIncidentTests(unittest.IsolatedAsyncioTestCase):
    async def test_violation_incident_can_auto_pause_user(self):
        original_users = state.users_db
        original_clients = state.clients
        original_incidents = state.incidents
        original_active_incidents = state.active_incidents
        original_policy_config = state.exam_policy_config
        ws = _FakeWS()
        try:
            state.users_db = {
                "alice": {
                    "uuid": "client-1",
                    "password": "secret",
                    "time_spent_seconds": 30,
                    "extra_time_seconds": 0,
                }
            }
            state.ensure_user_defaults(state.users_db["alice"])
            session_state.set_state(state.users_db["alice"], session_state.RUNNING, reason="Exam started.")
            state.clients = {"client-1": {"ws": ws, "security": None}}
            state.incidents = []
            state.active_incidents = {}
            state.exam_policy_config = state._normalize_exam_policy_config(
                {
                    "rules": {
                        "process_blacklist": {
                            "enabled": True,
                            "severity": "violation",
                            "auto_violation_pause": True,
                            "allow_remote_kill": True,
                        }
                    }
                }
            )

            await _handle_incident_report_event(
                ws,
                _FakeRequest(),
                "client-1",
                {
                    "incident_id": "incident-1",
                    "rule_id": "process_blacklist",
                    "rule_name": "Process Blacklist",
                    "status": "opened",
                    "severity": "violation",
                    "summary": "Blacklisted process detected",
                    "process_name": "discord.exe",
                    "pid": 1234,
                },
            )

            user = state.users_db["alice"]
            self.assertEqual(user["session_state"], session_state.VIOLATION_PAUSED)
            self.assertEqual(user["blocking_incident_id"], "incident-1")
            self.assertEqual(len(ws.messages), 3)
            self.assertEqual(ws.messages[0][0], "session_state")
            self.assertEqual(ws.messages[1][0], "pause_exam")
            self.assertEqual(ws.messages[2][0], "incident_received")

            await _handle_incident_report_event(
                ws,
                _FakeRequest(),
                "client-1",
                {
                    "incident_id": "incident-1",
                    "rule_id": "process_blacklist",
                    "rule_name": "Process Blacklist",
                    "status": "evidence_uploaded",
                    "severity": "violation",
                    "summary": "Evidence uploaded",
                    "artifact_path": "data/server/artifacts/client-1/incident.zip",
                    "evidence_status": "uploaded",
                },
            )

            self.assertEqual(len(ws.messages), 4)
            self.assertEqual(ws.messages[3][0], "incident_received")
            self.assertEqual(user["session_state"], session_state.VIOLATION_PAUSED)
            self.assertEqual(state.active_incidents["incident-1"]["status"], "opened")
            self.assertEqual(
                state.active_incidents["incident-1"]["artifact_path"],
                "data/server/artifacts/client-1/incident.zip",
            )
        finally:
            state.users_db = original_users
            state.clients = original_clients
            state.incidents = original_incidents
            state.active_incidents = original_active_incidents
            state.exam_policy_config = original_policy_config


if __name__ == "__main__":
    unittest.main()
