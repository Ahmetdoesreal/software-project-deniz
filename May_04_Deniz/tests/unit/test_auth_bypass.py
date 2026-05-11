import unittest

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


if __name__ == "__main__":
    unittest.main()
