import unittest
import time

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from client.preflight import auth_status_requires_admin_validation
from server import session_state
from server.handlers import auth_status, login_handler
from server.state import state
from server.tasks import _auth_bypass_snapshot, handle_admin_command


class AuthBypassCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_disable_and_enable_auth_bypass_commands(self):
        app = {
            "auth_bypass": {"cats_until": 0.0, "ad_until": 0.0},
            "auth_secret": "secret",
        }

        await handle_admin_command("/disablecatsauth 90", app)
        await handle_admin_command("/disableadauth 90", app)
        snapshot = _auth_bypass_snapshot(app)
        self.assertTrue(snapshot["cats_disabled"])
        self.assertTrue(snapshot["ad_disabled"])

        await handle_admin_command("/enablecatsauth", app)
        await handle_admin_command("/enableadauth", app)
        snapshot = _auth_bypass_snapshot(app)
        self.assertFalse(snapshot["cats_disabled"])
        self.assertFalse(snapshot["ad_disabled"])

    async def test_disableauth_and_enableauth_toggle_both_modes(self):
        app = {
            "auth_bypass": {"cats_until": 0.0, "ad_until": 0.0},
            "auth_secret": "secret",
        }

        await handle_admin_command("/disableauth 90", app)
        snapshot = _auth_bypass_snapshot(app)
        self.assertTrue(snapshot["cats_disabled"])
        self.assertTrue(snapshot["ad_disabled"])

        await handle_admin_command("/enableauth", app)
        snapshot = _auth_bypass_snapshot(app)
        self.assertFalse(snapshot["cats_disabled"])
        self.assertFalse(snapshot["ad_disabled"])

    async def test_launcher_skips_blocking_check_when_admin_validation_required(self):
        self.assertTrue(
            auth_status_requires_admin_validation(
                {
                    "admin_validation_required": True,
                    "validation_status": "pending",
                    "cats_required": False,
                    "ad_required": False,
                }
            )
        )
        self.assertFalse(
            auth_status_requires_admin_validation(
                {
                    "admin_validation_required": True,
                    "validation_status": "denied",
                    "cats_required": False,
                    "ad_required": False,
                }
            )
        )
        self.assertFalse(auth_status_requires_admin_validation(None))

    async def test_disabled_auth_requires_admin_validation_before_login(self):
        original_allowed = state.allowed_users
        original_users = state.users_db
        original_clients = state.clients
        app = web.Application()
        app["auth_bypass"] = {"cats_until": time.time() + 90, "ad_until": time.time() + 90}
        app["auth_secret"] = "secret"
        app["auth_validation"] = {"requests": {}, "approvals": {}}
        app["exam_duration"] = 45
        app.router.add_get("/auth/status", auth_status)
        app.router.add_post("/login", login_handler)
        client = TestClient(TestServer(app))
        try:
            state.allowed_users = {"alice"}
            state.users_db = {
                "alice": {
                    "uuid": "uuid-alice",
                    "time_spent_seconds": 0,
                    "extra_time_seconds": 0,
                    "exam_started": False,
                    "exam_finished": False,
                    "banned": False,
                }
            }
            state.ensure_user_defaults(state.users_db["alice"])
            session_state.set_state(state.users_db["alice"], session_state.WAITING)
            state.clients = {}
            await client.start_server()

            response = await client.post("/login", json={"login_id": "alice", "password": "plain-password"})
            self.assertEqual(response.status, 202)
            pending = await response.json()
            self.assertEqual(pending["status"], "pending_validation")
            self.assertEqual(pending["auth_modes"], ["cats", "ad"])

            status_response = await client.get("/auth/status", params={"login_id": "alice"})
            self.assertEqual(status_response.status, 200)
            status = await status_response.json()
            self.assertTrue(status["admin_validation_required"])
            self.assertEqual(status["validation_status"], "pending")
            self.assertFalse(status["cats_required"])
            self.assertFalse(status["ad_required"])

            await handle_admin_command("/approveauth alice 90", app)

            approved_response = await client.post("/login", json={"login_id": "alice", "password": "plain-password"})
            self.assertEqual(approved_response.status, 200)
            approved = await approved_response.json()
            self.assertEqual(approved["uuid"], "uuid-alice")
        finally:
            await client.close()
            state.allowed_users = original_allowed
            state.users_db = original_users
            state.clients = original_clients

    async def test_admin_can_deny_disabled_auth_validation(self):
        original_allowed = state.allowed_users
        original_users = state.users_db
        original_clients = state.clients
        app = web.Application()
        app["auth_bypass"] = {"cats_until": time.time() + 90, "ad_until": 0.0}
        app["auth_secret"] = ""
        app["auth_validation"] = {"requests": {}, "approvals": {}}
        app["exam_duration"] = 45
        app.router.add_post("/login", login_handler)
        client = TestClient(TestServer(app))
        try:
            state.allowed_users = {"bob"}
            state.users_db = {
                "bob": {
                    "uuid": "uuid-bob",
                    "time_spent_seconds": 0,
                    "extra_time_seconds": 0,
                    "exam_started": False,
                    "exam_finished": False,
                    "banned": False,
                }
            }
            state.ensure_user_defaults(state.users_db["bob"])
            state.clients = {}
            await client.start_server()

            response = await client.post("/login", json={"login_id": "bob", "password": "plain-password"})
            self.assertEqual(response.status, 202)

            await handle_admin_command("/denyauth bob wrong student", app)

            denied_response = await client.post("/login", json={"login_id": "bob", "password": "plain-password"})
            self.assertEqual(denied_response.status, 403)
            denied = await denied_response.json()
            self.assertEqual(denied["code"], "AUTH_REJECTED")
        finally:
            await client.close()
            state.allowed_users = original_allowed
            state.users_db = original_users
            state.clients = original_clients


if __name__ == "__main__":
    unittest.main()
