import asyncio
import json
import time
import unittest

import aiohttp

from common.local_ipc import (
    LOCAL_IPC_WS_TOKEN_ENV,
    LOCAL_IPC_WS_URL_ENV,
    LOCAL_IPC_TOKEN_HEADER,
    LoopbackWebSocketIPCClient,
    LoopbackWebSocketIPCServer,
    ThreadedLoopbackWebSocketIPCServer,
    is_loopback_host,
)


class LocalIPCTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received: list[str] = []
        self.server = await LoopbackWebSocketIPCServer(self.received.append).start()

    async def asyncTearDown(self):
        await self.server.close()

    async def _connect(self, token: str | None = None):
        session = aiohttp.ClientSession()
        try:
            ws = await session.ws_connect(
                self.server.url,
                headers={LOCAL_IPC_TOKEN_HEADER: token if token is not None else self.server.token},
            )
            return session, ws
        except Exception:
            await session.close()
            raise

    async def test_server_binds_to_loopback(self):
        self.assertTrue(self.server.url.startswith("ws://127.0.0.1:"))
        self.assertTrue(is_loopback_host("127.0.0.1"))
        self.assertTrue(is_loopback_host("::1"))
        self.assertFalse(is_loopback_host("192.168.1.50"))

    async def test_accepts_valid_loopback_token_and_preserves_text_frames(self):
        session, ws = await self._connect()
        try:
            await self.server.send_text("SYNC:12\n")
            msg = await asyncio.wait_for(ws.receive(), timeout=1)
            self.assertEqual(msg.data, "SYNC:12\n")

            payload = {"cmd": "start_exam"}
            await ws.send_str(json.dumps(payload))
            for _ in range(20):
                if self.received:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(json.loads(self.received[-1]), payload)
        finally:
            await ws.close()
            await session.close()

    async def test_rejects_missing_and_wrong_token(self):
        for token in ("", "wrong-token"):
            with self.subTest(token=token or "missing"):
                session = aiohttp.ClientSession()
                try:
                    with self.assertRaises(aiohttp.WSServerHandshakeError) as raised:
                        await session.ws_connect(
                            self.server.url,
                            headers={LOCAL_IPC_TOKEN_HEADER: token} if token else {},
                        )
                    self.assertEqual(raised.exception.status, 401)
                finally:
                    await session.close()

    async def test_rejects_second_connection(self):
        first_session, first_ws = await self._connect()
        second_session = aiohttp.ClientSession()
        try:
            with self.assertRaises(aiohttp.WSServerHandshakeError) as raised:
                await second_session.ws_connect(
                    self.server.url,
                    headers={LOCAL_IPC_TOKEN_HEADER: self.server.token},
                )
            self.assertEqual(raised.exception.status, 409)
        finally:
            await first_ws.close()
            await first_session.close()
            await second_session.close()

    async def test_background_client_sends_and_receives_text(self):
        client_received: list[str] = []
        client = LoopbackWebSocketIPCClient(
            client_received.append,
            url=self.server.url,
            token=self.server.token,
            name="test-local-ipc-client",
        )
        self.assertTrue(client.start())
        try:
            for _ in range(100):
                if self.server.connected:
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(self.server.connected)

            await self.server.send_text("UPLOAD_OK:done\n")
            for _ in range(100):
                if client_received:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(client_received[-1], "UPLOAD_OK:done\n")

            client.send_text(json.dumps({"cmd": "finish_exam", "archive_path": "answer.zip"}))
            for _ in range(100):
                if self.received:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(json.loads(self.received[-1])["cmd"], "finish_exam")
        finally:
            client.close()


class ThreadedLocalIPCTests(unittest.TestCase):
    def test_threaded_server_exposes_child_env_and_receives_messages(self):
        received: list[str] = []
        server = ThreadedLoopbackWebSocketIPCServer(received.append, name="test-threaded-local-ipc").start()
        client = LoopbackWebSocketIPCClient(
            lambda _text: None,
            url=server.url,
            token=server.token,
            name="test-threaded-local-ipc-client",
        )
        try:
            child_env = server.child_env()
            self.assertEqual(child_env[LOCAL_IPC_WS_URL_ENV], server.url)
            self.assertEqual(child_env[LOCAL_IPC_WS_TOKEN_ENV], server.token)

            self.assertTrue(client.start())
            for _ in range(100):
                if server.connected:
                    break
                time.sleep(0.01)
            self.assertTrue(server.connected)

            client.send_text(json.dumps({"cmd": "start_exam"}))
            for _ in range(100):
                if received:
                    break
                time.sleep(0.01)
            self.assertEqual(json.loads(received[-1])["cmd"], "start_exam")
        finally:
            client.close()
            server.close()


if __name__ == "__main__":
    unittest.main()
