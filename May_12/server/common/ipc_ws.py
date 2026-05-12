"""Loopback-only WebSocket IPC for local parent/child process control.

This module is intentionally small and uses the existing aiohttp dependency.
It is for same-machine app IPC only; it is not part of the LAN client/server
protocol in ``common.events``.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from aiohttp import web


ENV_URL = "EXAM_LOCAL_IPC_URL"
ENV_TOKEN = "EXAM_LOCAL_IPC_TOKEN"
ENV_ROLE = "EXAM_LOCAL_IPC_ROLE"
ENV_TRANSPORT = "EXAM_LOCAL_IPC_TRANSPORT"

TRANSPORT_AUTO = "auto"
TRANSPORT_STDIO = "stdio"
TRANSPORT_WS = "ws"
TRANSPORT_CHOICES = (TRANSPORT_AUTO, TRANSPORT_STDIO, TRANSPORT_WS)


def normalize_transport(value: str | None) -> str:
    value = str(value or TRANSPORT_AUTO).strip().lower()
    if value not in TRANSPORT_CHOICES:
        return TRANSPORT_AUTO
    return value


def ipc_env_available(env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    return bool(source.get(ENV_URL) and source.get(ENV_TOKEN))


def should_use_ws_ipc(transport: str | None = None, env: dict[str, str] | None = None) -> bool:
    transport = normalize_transport(transport or (env or os.environ).get(ENV_TRANSPORT))
    if transport == TRANSPORT_WS:
        return True
    if transport == TRANSPORT_STDIO:
        return False
    return ipc_env_available(env)


def _is_loopback_peer(peername: Any) -> bool:
    if not isinstance(peername, (tuple, list)) or not peername:
        return False
    return str(peername[0]) in {"127.0.0.1", "::1", "localhost"}


def make_envelope(
    *,
    channel: str,
    data: dict | None = None,
    role: str = "",
    message_type: str = "event",
    reply_to: str = "",
    seq: int | None = None,
    error: str = "",
) -> dict:
    envelope = {
        "type": message_type,
        "role": role,
        "channel": channel,
        "id": uuid.uuid4().hex,
        "reply_to": reply_to,
        "seq": int(seq or 0),
        "data": data or {},
    }
    if error:
        envelope["error"] = error
    return envelope


def _decode_envelope(raw: str) -> dict | None:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(message, dict):
        return None
    channel = str(message.get("channel", "") or "").strip()
    if not channel:
        return None
    data = message.get("data", {})
    if not isinstance(data, dict):
        return None
    message.setdefault("type", "event")
    message.setdefault("role", "")
    message.setdefault("id", uuid.uuid4().hex)
    message.setdefault("reply_to", "")
    message.setdefault("seq", 0)
    return message


@dataclass
class LocalIpcServer:
    role: str
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    host: str = "127.0.0.1"
    port: int = 0
    incoming: asyncio.Queue = field(default_factory=asyncio.Queue)
    _runner: web.AppRunner | None = None
    _site: web.TCPSite | None = None
    _clients: set[web.WebSocketResponse] = field(default_factory=set)

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}/ipc"

    @property
    def connected_count(self) -> int:
        return len(self._clients)

    def child_env(self, role: str, transport: str = TRANSPORT_AUTO) -> dict[str, str]:
        return {
            ENV_URL: self.url,
            ENV_TOKEN: self.token,
            ENV_ROLE: role,
            ENV_TRANSPORT: normalize_transport(transport),
        }

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/ipc", self._handle_ws)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        sockets = getattr(self._site, "_server", None).sockets
        if sockets:
            self.port = int(sockets[0].getsockname()[1])

    async def stop(self) -> None:
        for ws in list(self._clients):
            await ws.close()
        self._clients.clear()
        if self._runner:
            await self._runner.cleanup()
        self._runner = None
        self._site = None

    async def send(self, channel: str, data: dict | None = None, *, message_type: str = "event") -> int:
        envelope = make_envelope(
            channel=channel,
            data=data,
            role=self.role,
            message_type=message_type,
        )
        return await self.send_envelope(envelope)

    async def send_envelope(self, envelope: dict) -> int:
        raw = json.dumps(envelope, separators=(",", ":"))
        sent = 0
        for ws in list(self._clients):
            if ws.closed:
                self._clients.discard(ws)
                continue
            try:
                await ws.send_str(raw)
                sent += 1
            except Exception:
                self._clients.discard(ws)
        return sent

    async def _handle_ws(self, request: web.Request) -> web.StreamResponse:
        peername = request.transport.get_extra_info("peername") if request.transport else None
        if not _is_loopback_peer(peername):
            return web.Response(status=403, text="loopback peers only")

        token = request.query.get("token") or request.headers.get("X-Exam-IPC-Token")
        if token != self.token:
            return web.Response(status=401, text="invalid ipc token")

        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        try:
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                envelope = _decode_envelope(msg.data)
                if envelope is not None:
                    await self.incoming.put(envelope)
        finally:
            self._clients.discard(ws)
        return ws


class LocalIpcClient:
    def __init__(
        self,
        *,
        role: str | None = None,
        url: str | None = None,
        token: str | None = None,
    ):
        self.role = role or os.environ.get(ENV_ROLE, "child")
        self.url = url or os.environ.get(ENV_URL, "")
        self.token = token or os.environ.get(ENV_TOKEN, "")
        self.incoming: asyncio.Queue = asyncio.Queue()
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._reader_task: asyncio.Task | None = None

    @property
    def connected(self) -> bool:
        return bool(self._ws and not self._ws.closed)

    async def connect(self) -> bool:
        if not self.url or not self.token:
            return False
        self._session = aiohttp.ClientSession()
        try:
            separator = "&" if "?" in self.url else "?"
            self._ws = await self._session.ws_connect(f"{self.url}{separator}token={self.token}")
        except Exception:
            await self.close()
            return False
        self._reader_task = asyncio.create_task(self._reader())
        return True

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.close()
        self._reader_task = None
        self._ws = None
        self._session = None

    async def send(self, channel: str, data: dict | None = None, *, message_type: str = "event") -> bool:
        if not self.connected:
            return False
        envelope = make_envelope(
            channel=channel,
            data=data,
            role=self.role,
            message_type=message_type,
        )
        await self._ws.send_str(json.dumps(envelope, separators=(",", ":")))
        return True

    async def _reader(self) -> None:
        if not self._ws:
            return
        async for msg in self._ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            envelope = _decode_envelope(msg.data)
            if envelope is not None:
                await self.incoming.put(envelope)


class _LoopThread:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="local_ipc_loop", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self._ready.set()
        self.loop.run_forever()

    def submit(self, coroutine, timeout: float | None = 5.0):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        return future.result(timeout=timeout)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=2.0)
        self.loop.close()


class ThreadedIpcServer:
    def __init__(self, *, role: str, on_message: Callable[[dict], None] | None = None):
        self.role = role
        self.on_message = on_message
        self._loop_thread: _LoopThread | None = None
        self._server: LocalIpcServer | None = None
        self._pump_task = None

    @property
    def active(self) -> bool:
        return self._server is not None

    @property
    def connected_count(self) -> int:
        return self._server.connected_count if self._server else 0

    def start(self) -> dict[str, str]:
        if self._server:
            return self._server.child_env("child")
        self._loop_thread = _LoopThread()
        self._server = LocalIpcServer(role=self.role)
        self._loop_thread.submit(self._server.start())
        if self.on_message:
            self._pump_task = asyncio.run_coroutine_threadsafe(
                self._message_pump(),
                self._loop_thread.loop,
            )
        return self._server.child_env("child")

    def child_env(self, role: str, transport: str = TRANSPORT_AUTO) -> dict[str, str]:
        if not self._server:
            raise RuntimeError("IPC server is not started")
        return self._server.child_env(role, transport)

    def send(self, channel: str, data: dict | None = None) -> bool:
        if not self._server or not self._loop_thread:
            return False
        try:
            return self._loop_thread.submit(self._server.send(channel, data), timeout=2.0) > 0
        except Exception:
            return False

    def stop(self) -> None:
        if self._pump_task:
            self._pump_task.cancel()
        if self._server and self._loop_thread:
            try:
                self._loop_thread.submit(self._server.stop(), timeout=2.0)
            except Exception:
                pass
        if self._loop_thread:
            self._loop_thread.stop()
        self._server = None
        self._loop_thread = None
        self._pump_task = None

    async def _message_pump(self) -> None:
        assert self._server is not None
        while True:
            message = await self._server.incoming.get()
            try:
                self.on_message(message)
            except Exception:
                pass


class ThreadedIpcClient:
    def __init__(self, *, role: str, on_message: Callable[[dict], None] | None = None):
        self.role = role
        self.on_message = on_message
        self._loop_thread: _LoopThread | None = None
        self._client: LocalIpcClient | None = None
        self._pump_task = None

    @property
    def active(self) -> bool:
        return bool(self._client and self._client.connected)

    def start(self) -> bool:
        if not ipc_env_available():
            return False
        self._loop_thread = _LoopThread()
        self._client = LocalIpcClient(role=self.role)
        connected = bool(self._loop_thread.submit(self._client.connect(), timeout=5.0))
        if not connected:
            self.stop()
            return False
        if self.on_message:
            self._pump_task = asyncio.run_coroutine_threadsafe(
                self._message_pump(),
                self._loop_thread.loop,
            )
        return True

    def send(self, channel: str, data: dict | None = None) -> bool:
        if not self._client or not self._loop_thread or not self._client.connected:
            return False
        try:
            return bool(self._loop_thread.submit(self._client.send(channel, data), timeout=2.0))
        except Exception:
            return False

    def stop(self) -> None:
        if self._pump_task:
            self._pump_task.cancel()
        if self._client and self._loop_thread:
            try:
                self._loop_thread.submit(self._client.close(), timeout=2.0)
            except Exception:
                pass
        if self._loop_thread:
            self._loop_thread.stop()
        self._client = None
        self._loop_thread = None
        self._pump_task = None

    async def _message_pump(self) -> None:
        assert self._client is not None
        while True:
            message = await self._client.incoming.get()
            try:
                self.on_message(message)
            except Exception:
                pass
