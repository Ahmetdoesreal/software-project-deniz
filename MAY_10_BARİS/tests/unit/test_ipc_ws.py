import unittest

import aiohttp

from common.ipc_ws import (
    ENV_TOKEN,
    ENV_URL,
    LocalIpcClient,
    LocalIpcServer,
    _is_loopback_peer,
    make_envelope,
    should_use_ws_ipc,
)


class IpcEnvelopeTests(unittest.TestCase):
    def test_make_envelope_contains_required_fields(self):
        envelope = make_envelope(
            channel="manager.console_command",
            role="manager",
            data={"command": "/gui"},
        )

        self.assertEqual(envelope["type"], "event")
        self.assertEqual(envelope["role"], "manager")
        self.assertEqual(envelope["channel"], "manager.console_command")
        self.assertEqual(envelope["data"], {"command": "/gui"})
        self.assertTrue(envelope["id"])
        self.assertIn("reply_to", envelope)
        self.assertIn("seq", envelope)

    def test_transport_selection_uses_env_only_in_auto_mode(self):
        env = {ENV_URL: "ws://127.0.0.1:1234/ipc", ENV_TOKEN: "secret"}

        self.assertTrue(should_use_ws_ipc("auto", env))
        self.assertTrue(should_use_ws_ipc("ws", {}))
        self.assertFalse(should_use_ws_ipc("stdio", env))
        self.assertFalse(should_use_ws_ipc("auto", {}))

    def test_loopback_peer_guard(self):
        self.assertTrue(_is_loopback_peer(("127.0.0.1", 50000)))
        self.assertTrue(_is_loopback_peer(("::1", 50000)))
        self.assertFalse(_is_loopback_peer(("192.168.1.50", 50000)))
        self.assertFalse(_is_loopback_peer(None))


class IpcWebSocketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = LocalIpcServer(role="test_server")
        await self.server.start()

    async def asyncTearDown(self):
        await self.server.stop()

    async def test_rejects_missing_token(self):
        async with aiohttp.ClientSession() as session:
            with self.assertRaises(aiohttp.WSServerHandshakeError) as raised:
                await session.ws_connect(self.server.url)

        self.assertEqual(raised.exception.status, 401)

    async def test_client_to_server_roundtrip(self):
        client = LocalIpcClient(
            role="test_client",
            url=self.server.url,
            token=self.server.token,
        )
        self.assertTrue(await client.connect())
        try:
            self.assertTrue(
                await client.send(
                    "dashboard.command",
                    {"cmd": "start_exam_global"},
                )
            )
            message = await self.server.incoming.get()
            self.assertEqual(message["channel"], "dashboard.command")
            self.assertEqual(message["role"], "test_client")
            self.assertEqual(message["data"]["cmd"], "start_exam_global")
        finally:
            await client.close()

    async def test_server_to_client_roundtrip(self):
        client = LocalIpcClient(
            role="test_client",
            url=self.server.url,
            token=self.server.token,
        )
        self.assertTrue(await client.connect())
        try:
            sent = await self.server.send(
                "server.dashboard_state",
                {"type": "state_update", "clients": []},
            )
            self.assertEqual(sent, 1)
            message = await client.incoming.get()
            self.assertEqual(message["channel"], "server.dashboard_state")
            self.assertEqual(message["data"]["type"], "state_update")
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
