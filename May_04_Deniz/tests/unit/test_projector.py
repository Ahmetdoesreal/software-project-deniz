import json
import types
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from server import session_state
from server.projector import (
    build_projection_state,
    payload_contains_sensitive_fields,
    projector_css,
    projector_events,
    projector_js,
    projector_page,
)


class ProjectorPayloadTests(unittest.TestCase):
    def test_projection_state_counts_and_excludes_sensitive_fields(self):
        app = {
            "exam_phase": "running",
            "exam_start_enabled": True,
        }
        fake_state = types.SimpleNamespace(
            users_db={
                "student1": {"uuid": "uuid-1", "session_state": session_state.RUNNING},
                "student2": {"uuid": "uuid-2", "session_state": session_state.AWAITING_SUBMISSION},
                "student3": {"uuid": "uuid-3", "session_state": session_state.SUBMITTED},
            },
            clients={"uuid-1": {"ip": "10.0.0.1"}},
            active_incidents={
                "inc-1": {
                    "incident_id": "inc-1",
                    "login_id": "student1",
                    "client_id": "uuid-1",
                    "severity": "violation",
                    "status": "opened",
                    "process_name": "blocked.exe",
                    "artifact_path": "data/server/artifacts/private.zip",
                },
                "inc-2": {"incident_id": "inc-2", "severity": "warning", "status": "opened"},
            },
            incidents=[
                {
                    "incident_id": "inc-1",
                    "login_id": "student1",
                    "client_id": "uuid-1",
                    "severity": "violation",
                    "status": "opened",
                    "process_name": "blocked.exe",
                    "window_title": "Private title",
                    "server_received_at": "2026-05-11T10:00:00Z",
                }
            ],
        )

        payload = build_projection_state(app, fake_state)

        self.assertEqual(payload["counts"]["total_users"], 3)
        self.assertEqual(payload["counts"]["connected"], 1)
        self.assertEqual(payload["counts"]["disconnected"], 2)
        self.assertEqual(payload["counts"]["active_incidents"], 2)
        self.assertEqual(payload["counts"]["active_violations"], 1)
        self.assertEqual(payload["counts"]["active_warnings"], 1)
        self.assertEqual(payload["counts"]["awaiting_submission"], 1)
        self.assertEqual(payload["counts"]["submitted"], 1)
        self.assertFalse(payload_contains_sensitive_fields(payload))
        self.assertEqual(payload["notifications"][0]["message"], "New violation incident opened")

    def test_resolved_warning_notification_is_projection_safe(self):
        app = {"exam_phase": "running", "exam_start_enabled": True}
        fake_state = types.SimpleNamespace(
            users_db={},
            clients={},
            active_incidents={},
            incidents=[{"incident_id": "inc-1", "severity": "warning", "status": "resolved"}],
        )

        payload = build_projection_state(app, fake_state)

        self.assertEqual(payload["notifications"][0]["severity"], "resolved")
        self.assertEqual(payload["notifications"][0]["message"], "Warning resolved")
        self.assertFalse(payload_contains_sensitive_fields(payload))


class ProjectorHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_projector_page_returns_html(self):
        app = web.Application()
        app.router.add_get("/projector", projector_page)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.get("/projector")
            self.assertEqual(response.status, 200)
            self.assertEqual(response.content_type, "text/html")
            body = await response.read()
            self.assertIn(b"Exam Notifications", body)
            self.assertIn(b"/projector/assets/projector.css", body)
            self.assertIn(b"/projector/assets/projector.js", body)
        finally:
            await client.close()

    async def test_projector_assets_return_separate_css_and_js(self):
        app = web.Application()
        app.router.add_get("/projector/assets/projector.css", projector_css)
        app.router.add_get("/projector/assets/projector.js", projector_js)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            css_response = await client.get("/projector/assets/projector.css")
            self.assertEqual(css_response.status, 200)
            self.assertEqual(css_response.content_type, "text/css")
            css_body = await css_response.read()
            self.assertIn(b".notice", css_body)

            js_response = await client.get("/projector/assets/projector.js")
            self.assertEqual(js_response.status, 200)
            self.assertEqual(js_response.content_type, "application/javascript")
            js_body = await js_response.read()
            self.assertIn(b"EventSource('/projector/events')", js_body)
        finally:
            await client.close()

    async def test_projector_events_streams_projection_state(self):
        app = web.Application()
        app["exam_phase"] = "waiting"
        app["exam_start_enabled"] = False
        app["broadcast_interval"] = 1
        app.router.add_get("/projector/events", projector_events)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.get("/projector/events")
            self.assertEqual(response.status, 200)
            first_line = await response.content.readline()
            self.assertTrue(first_line.startswith(b"data: "))
            payload = json.loads(first_line[len(b"data: "):])
            self.assertIn("counts", payload)
            self.assertIn("notifications", payload)
            response.close()
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
