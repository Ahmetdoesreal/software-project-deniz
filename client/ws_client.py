import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass
from threading import Thread

import aiohttp

from common import events, protocol
from custommodules.process_monitor import ProcessMonitor
from custommodules.replay_recorder import ReplayRecorder


def _run_in_background(loop: asyncio.AbstractEventLoop, callback, *args):
    loop.call_soon_threadsafe(callback, *args)


def _client_gui_path() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(script_dir), "client_gui.py")


def _time_text(seconds: int) -> str:
    minutes, remaining_seconds = divmod(seconds, 60)
    return f"{minutes}m {remaining_seconds}s"


async def _wait_for_queue_or_event(
    input_queue: asyncio.Queue,
    event: asyncio.Event,
) -> tuple[str | None, bool]:
    queue_task = asyncio.create_task(input_queue.get())
    event_task = asyncio.create_task(event.wait())

    done, pending = await asyncio.wait(
        [queue_task, event_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()

    if event_task in done and event.is_set():
        return None, True

    return queue_task.result(), False


class StdinBridge:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.queue = asyncio.Queue()
        self.thread = Thread(target=self._reader, daemon=True)
        self.thread.start()

    def _reader(self):
        for line in sys.stdin:
            _run_in_background(self.loop, self.queue.put_nowait, line)


class ClientGUIBridge:
    def __init__(self, loop: asyncio.AbstractEventLoop, start_event: asyncio.Event):
        self.loop = loop
        self.start_event = start_event
        self.process = None

    def ensure_started(self):
        if self.process is not None and self.process.poll() is None:
            return

        self.process = subprocess.Popen(
            [sys.executable, _client_gui_path()],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        Thread(target=self._stdout_reader, daemon=True).start()

    def _stdout_reader(self):
        for line in iter(self.process.stdout.readline, ""):
            if "ACTION:START" in line:
                print("[GUI] Start button pressed.")
                _run_in_background(self.loop, self.start_event.set)
        self.process.stdout.close()

    def send_sync(self, remaining_seconds: int):
        self._write(f"SYNC:{remaining_seconds}\n")

    def send_end(self):
        self._write("END:-1\n")

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.kill()
        self.process = None

    def _write(self, message: str):
        if not self.process or self.process.poll() is not None:
            return

        try:
            self.process.stdin.write(message)
            self.process.stdin.flush()
        except Exception:
            pass


@dataclass
class SessionState:
    disconnected: asyncio.Event
    start_event: asyncio.Event
    exam_active: bool = True
    last_printed_remaining: int | None = None


class WebSocketSession:
    def __init__(self, ws_url: str, ws, recorder: ReplayRecorder | None):
        self.ws_url = ws_url
        self.ws = ws
        self.recorder = recorder
        self.loop = asyncio.get_running_loop()
        self.state = SessionState(
            disconnected=asyncio.Event(),
            start_event=asyncio.Event(),
        )
        self.stdin = StdinBridge(self.loop)
        self.gui = ClientGUIBridge(self.loop, self.state.start_event)
        self.process_monitor = self._create_process_monitor()

    def _create_process_monitor(self):
        client_uuid = protocol.extract_client_uuid(self.ws_url)
        out_dir = os.path.join("data", "client", client_uuid)
        monitor = ProcessMonitor(out_dir)
        monitor.start()
        return monitor

    async def run(self):
        listener_task = asyncio.create_task(self.listener())
        try:
            await self.sender()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            listener_task.cancel()
            self.gui.close()
            self.process_monitor.stop()

        if self.state.disconnected.is_set():
            raise ConnectionError("Server disconnected")

    async def prompt_start_exam(self):
        print("\n--- PRE-EXAM PREPARATION ---")
        print("When you are ready, type 'start' or click the button in the GUI to begin the exam.")

        while not self.state.start_event.is_set():
            line, event_triggered = await _wait_for_queue_or_event(
                self.stdin.queue,
                self.state.start_event,
            )
            if event_triggered:
                break

            text = line.strip().lower() if line else ""
            if text in {"start", "/start"}:
                self.state.start_event.set()
                break

            print("Type 'start' or use the GUI to begin.")

        await self.ws.send_str(events.start_exam())
        print("[EXAM] Started. Good luck!\n")

    async def sender(self):
        await self.prompt_start_exam()
        print("Type anything and press Enter to ping the server (Ctrl+C to quit):\n")

        while not self.state.disconnected.is_set() and self.state.exam_active:
            line, disconnected = await _wait_for_queue_or_event(
                self.stdin.queue,
                self.state.disconnected,
            )
            if disconnected:
                break

            if not line:
                return

            text = line.strip()
            if text:
                await self.ws.send_str(events.ping(text))

    async def listener(self):
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self.handle_text_message(msg.data)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except Exception as e:
            print(f"[WS] Listener error: {e}")
        finally:
            self.state.disconnected.set()

    async def handle_text_message(self, raw_message: str):
        event, data = protocol.decode(raw_message)

        if event == events.WELCOME:
            print(f"[WS] Connected! Server assigned ID: {data['id']}")
            self.gui.ensure_started()
            return

        if event == events.ECHO:
            print(f"[WS] Echo: {data}")
            return

        if event == events.TIME:
            return

        if event == events.SYNC_TIME:
            self.handle_sync_time(data)
            return

        if event == events.EXAM_END:
            self.handle_exam_end()
            return

        if event == events.SAVESCREEN:
            print("[WS] [SAVESCREEN] Server requested replay save.")
            if self.recorder:
                await self.loop.run_in_executor(None, self.recorder.save_replay)
            return

        if event == events.GET_PROCESSES:
            print("[WS] [GET_PROCESSES] Server requested a manual process report.")
            self.process_monitor.trigger_full_report()
            return

        print(f"[WS] {event}: {data}")

    def handle_sync_time(self, data: dict):
        remaining = data.get("remaining_seconds", 0)
        self.process_monitor.update_time(remaining)
        self.gui.ensure_started()

        if not self.state.start_event.is_set():
            print("[WS] Exam is already running on the server. Joining automatically...")
            self.state.start_event.set()

        self.gui.send_sync(remaining)
        self._print_remaining_time(remaining)

    def handle_exam_end(self):
        print("\n===============================")
        print("       EXAM TIME IS UP!        ")
        print("===============================")
        self.state.exam_active = False
        self.gui.send_end()
        self.state.disconnected.set()

    def _print_remaining_time(self, remaining: int):
        last_remaining = self.state.last_printed_remaining
        if last_remaining is None or remaining <= last_remaining - 10:
            self.state.last_printed_remaining = remaining
            print(f"[EXAM] Time remaining: {_time_text(remaining)}")


async def run_ws(ws_url: str, recorder: ReplayRecorder | None):
    """Connect via WebSocket, handle exam flow and pings."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            await WebSocketSession(ws_url, ws, recorder).run()
