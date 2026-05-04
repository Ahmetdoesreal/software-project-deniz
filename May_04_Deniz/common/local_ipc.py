"""Loopback-only WebSocket IPC for parent/GUI subprocess communication."""

from __future__ import annotations

import asyncio
import inspect
import ipaddress
import os
import queue
import secrets
import threading
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
from aiohttp import WSMsgType, web


LOCAL_IPC_WS_URL_ENV = "LOCAL_IPC_WS_URL"
LOCAL_IPC_WS_TOKEN_ENV = "LOCAL_IPC_WS_TOKEN"
LOCAL_IPC_TOKEN_HEADER = "X-Local-IPC-Token"
LOCAL_IPC_HOST = "127.0.0.1"
LOCAL_IPC_PATH = "/ipc"

MessageCallback = Callable[[str], Any | Awaitable[Any]]
CloseCallback = Callable[[], Any]


def local_ipc_env_configured(env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    return bool(source.get(LOCAL_IPC_WS_URL_ENV) and source.get(LOCAL_IPC_WS_TOKEN_ENV))


def is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(str(host)).is_loopback
    except ValueError:
        return False


def _request_peer_host(request: web.Request) -> str:
    peername = request.transport.get_extra_info("peername") if request.transport else None
    if isinstance(peername, tuple) and peername:
        return str(peername[0])
    return str(request.remote or "")


class LoopbackWebSocketIPCServer:
    """A single-client aiohttp WebSocket server bound to 127.0.0.1."""

    def __init__(
        self,
        on_message: MessageCallback,
        *,
        name: str = "local-ipc",
        token: str | None = None,
        max_pending: int = 100,
    ):
        self.on_message = on_message
        self.name = name
        self.token = token or secrets.token_urlsafe(32)
        self.max_pending = max(1, int(max_pending))
        self.url = ""
        self.host = LOCAL_IPC_HOST
        self.port = 0
        self.loop: asyncio.AbstractEventLoop | None = None
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._ws: web.WebSocketResponse | None = None
        self._pending: list[str] = []
        self._closed = False

    async def start(self) -> "LoopbackWebSocketIPCServer":
        self.loop = asyncio.get_running_loop()
        self._app = web.Application()
        self._app.router.add_get(LOCAL_IPC_PATH, self._handler)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, LOCAL_IPC_HOST, 0)
        await self._site.start()
        sockets = getattr(getattr(self._site, "_server", None), "sockets", None) or []
        if not sockets:
            await self.close()
            raise RuntimeError("Local IPC server did not expose a listening socket.")
        self.port = int(sockets[0].getsockname()[1])
        self.url = f"ws://{LOCAL_IPC_HOST}:{self.port}{LOCAL_IPC_PATH}"
        return self

    def child_env(self) -> dict[str, str]:
        return {
            LOCAL_IPC_WS_URL_ENV: self.url,
            LOCAL_IPC_WS_TOKEN_ENV: self.token,
        }

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    @property
    def closed(self) -> bool:
        return self._closed

    async def send_text(self, text: str) -> bool:
        if self._closed:
            return False
        if not self.connected:
            self._queue_pending(text)
            return True
        try:
            await self._ws.send_str(text)
            return True
        except Exception:
            self._queue_pending(text)
            return False

    def send_text_nowait(self, text: str) -> bool:
        if self._closed or self.loop is None:
            return False
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is self.loop:
            self.loop.create_task(self.send_text(text))
        else:
            asyncio.run_coroutine_threadsafe(self.send_text(text), self.loop)
        return True

    async def close(self) -> None:
        self._closed = True
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        if self._runner is not None:
            await self._runner.cleanup()
        self._runner = None
        self._site = None
        self._app = None

    def _queue_pending(self, text: str) -> None:
        self._pending.append(text)
        if len(self._pending) > self.max_pending:
            del self._pending[: len(self._pending) - self.max_pending]

    async def _flush_pending(self, ws: web.WebSocketResponse) -> None:
        pending = list(self._pending)
        self._pending.clear()
        for text in pending:
            await ws.send_str(text)

    async def _handler(self, request: web.Request) -> web.StreamResponse:
        if not is_loopback_host(_request_peer_host(request)):
            return web.Response(status=403, text="Local IPC only accepts loopback peers.")

        supplied_token = request.headers.get(LOCAL_IPC_TOKEN_HEADER, "")
        if not secrets.compare_digest(supplied_token, self.token):
            return web.Response(status=401, text="Invalid local IPC token.")

        if self.connected:
            return web.Response(status=409, text="Local IPC already has an active peer.")

        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._ws = ws
        try:
            await self._flush_pending(ws)
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    result = self.on_message(str(msg.data))
                    if inspect.isawaitable(result):
                        await result
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            if self._ws is ws:
                self._ws = None
        return ws


class ThreadedLoopbackWebSocketIPCServer:
    """Run ``LoopbackWebSocketIPCServer`` in a private event-loop thread."""

    def __init__(self, on_message: MessageCallback, *, name: str = "local-ipc"):
        self.on_message = on_message
        self.name = name
        self.server: LoopbackWebSocketIPCServer | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None

    def start(self, timeout: float = 5.0) -> "ThreadedLoopbackWebSocketIPCServer":
        self._thread = threading.Thread(target=self._thread_main, name=self.name, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise TimeoutError(f"{self.name} did not start within {timeout} seconds.")
        if self._error is not None:
            raise RuntimeError(f"{self.name} failed to start.") from self._error
        return self

    @property
    def url(self) -> str:
        return self.server.url if self.server is not None else ""

    @property
    def token(self) -> str:
        return self.server.token if self.server is not None else ""

    @property
    def connected(self) -> bool:
        return bool(self.server and self.server.connected)

    @property
    def closed(self) -> bool:
        return self.server is None or self.server.closed

    def child_env(self) -> dict[str, str]:
        if self.server is None:
            return {}
        return self.server.child_env()

    def send_text_nowait(self, text: str) -> bool:
        if self.server is None:
            return False
        return self.server.send_text_nowait(text)

    def close(self, timeout: float = 5.0) -> None:
        loop = self.loop
        server = self.server
        if loop is not None and server is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(server.close(), loop)
            try:
                future.result(timeout=timeout)
            except Exception:
                pass
            loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self.loop = loop
        asyncio.set_event_loop(loop)
        try:
            self.server = loop.run_until_complete(
                LoopbackWebSocketIPCServer(self.on_message, name=self.name).start()
            )
        except BaseException as exc:
            self._error = exc
            self._ready.set()
            loop.close()
            return
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            if self.server is not None and not self.server.closed:
                loop.run_until_complete(self.server.close())
            loop.close()


class LoopbackWebSocketIPCClient:
    """Background-thread WebSocket client used by GUI subprocesses."""

    def __init__(
        self,
        on_message: MessageCallback,
        *,
        on_close: CloseCallback | None = None,
        url: str | None = None,
        token: str | None = None,
        name: str = "local-ipc-client",
    ):
        import os

        self.url = url or os.environ.get(LOCAL_IPC_WS_URL_ENV, "")
        self.token = token or os.environ.get(LOCAL_IPC_WS_TOKEN_ENV, "")
        self.on_message = on_message
        self.on_close = on_close
        self.name = name
        self._outgoing: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._started = False

    def start(self) -> bool:
        if self._started or not self.url or not self.token:
            return False
        self._started = True
        self._thread = threading.Thread(target=self._thread_main, name=self.name, daemon=True)
        self._thread.start()
        return True

    def send_text(self, text: str) -> bool:
        if not self._started:
            return False
        self._outgoing.put(text)
        return True

    def close(self) -> None:
        if self._started:
            self._outgoing.put(None)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        finally:
            if self.on_close is not None:
                try:
                    self.on_close()
                except Exception:
                    pass

    async def _run(self) -> None:
        headers = {LOCAL_IPC_TOKEN_HEADER: self.token}
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.url, headers=headers) as ws:
                sender = asyncio.create_task(self._sender(ws))
                try:
                    async for msg in ws:
                        if msg.type == WSMsgType.TEXT:
                            result = self.on_message(str(msg.data))
                            if inspect.isawaitable(result):
                                await result
                        elif msg.type in {WSMsgType.CLOSED, WSMsgType.ERROR}:
                            break
                finally:
                    self._outgoing.put(None)
                    sender.cancel()
                    try:
                        await sender
                    except asyncio.CancelledError:
                        pass

    async def _sender(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        while True:
            text = await asyncio.to_thread(self._outgoing.get)
            if text is None:
                await ws.close()
                return
            await ws.send_str(text)
