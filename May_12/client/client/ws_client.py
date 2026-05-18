import asyncio
import errno
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Thread

import aiohttp
import psutil

from common import events, protocol, security
from common.ipc_ws import LocalIpcClient, ThreadedIpcServer, should_use_ws_ipc
from common.text_safety import safe_console_text, sanitize_window_snapshot
from .exam import extract_exam_materials
from .exam_state import ExamStateLogger
from .incidents import ClientIncidentEngine
from .submission import validate_submission_file
from .transfers import (
    build_incident_bundle,
    build_submission_bundle,
    upload_runtime_artifact,
    upload_submission_bundle,
)
from .custommodules.focused_window_monitor import FocusedWindowMonitor
from .custommodules.hardware_monitor import HardwareMonitor
from .custommodules.idle_monitor import IdleMonitor
from .custommodules.process_monitor import ProcessMonitor
from .custommodules.replay_recorder import ReplayRecorder
from .incident_buffer import IncidentBuffer

REPLAY_SAVE_TIMEOUT_SECONDS = 45
SUBMISSION_UPLOAD_TIMEOUT_SECONDS = 900
REPLAY_PRIORITY_FINAL_SUBMISSION = 0
REPLAY_PRIORITY_INCIDENT_EVIDENCE = 1
REPLAY_PRIORITY_OPTIONAL_REQUEST = 2
REPLAY_INCIDENT_SAVE_QUEUE_LIMIT = 1
REPLAY_INCIDENT_SAVE_TIMEOUT_SECONDS = 8.0
REPLAY_INCIDENT_SAVE_DEADLINE_SECONDS = 12.0
REPLAY_INCIDENT_SAVE_RETRY_DELAY_SECONDS = 0.75
REPLAY_SAVE_COALESCE_WINDOW_SECONDS = 5.0
REPLAY_SAVE_RESULT_CACHE_SECONDS = 120.0
REQUESTED_REPLAY_UPLOAD_CACHE_SECONDS = 120.0
REPLAY_OPTIONAL_SAVE_QUEUE_LIMIT = 5
REPLAY_OPTIONAL_SAVE_DEADLINE_SECONDS = 90.0
REPLAY_QUEUE_CLOSE_TIMEOUT_SECONDS = REPLAY_SAVE_TIMEOUT_SECONDS + 5.0
INCIDENT_EVIDENCE_UPLOAD_CONCURRENCY = 2
FOCUSED_WINDOW_CHECK_INTERVAL_SECONDS = 1.0
FOCUSED_WINDOW_FULL_INFO_INTERVAL_CHECKS = 60
FOCUSED_WINDOW_SERVER_SEND_INTERVAL_SECONDS = 5.0

_GUI_PIPE_CLOSED_ERRNOS = {
    errno.EBADF,
    errno.EINVAL,
    errno.EPIPE,
}
if hasattr(errno, "ECONNRESET"):
    _GUI_PIPE_CLOSED_ERRNOS.add(errno.ECONNRESET)


def _run_in_background(loop: asyncio.AbstractEventLoop, callback, *args):
    loop.call_soon_threadsafe(callback, *args)


def _is_closed_pipe_error(exc: BaseException) -> bool:
    if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
        return True
    return isinstance(exc, OSError) and getattr(exc, "errno", None) in _GUI_PIPE_CLOSED_ERRNOS


def _project_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _child_env() -> dict:
    env = os.environ.copy()
    project_dir = _project_dir()
    env["PYTHONPATH"] = project_dir + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _time_text(seconds: int) -> str:
    minutes, remaining_seconds = divmod(seconds, 60)
    return f"{minutes}m {remaining_seconds}s"


def _computer_name() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def _extract_finish_path(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None

    lowered = stripped.lower()
    prefixes = ("finish ", "/finish ")
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return stripped[len(prefix):].strip() or None

    return None


async def _wait_for_queue_or_event(
    input_queue: asyncio.Queue,
    event: asyncio.Event,
    extra_event: asyncio.Event | None = None,
) -> tuple[object | None, bool]:
    queue_task = asyncio.create_task(input_queue.get())
    event_task = asyncio.create_task(event.wait())
    tasks = [queue_task, event_task]
    extra_task = None
    if extra_event is not None:
        extra_task = asyncio.create_task(extra_event.wait())
        tasks.append(extra_task)

    done, pending = await asyncio.wait(
        tasks,
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()

    if event_task in done and event.is_set():
        return None, True
    if extra_task is not None and extra_task in done and extra_event and extra_event.is_set():
        return None, True

    return queue_task.result(), False


class StdinBridge:
    def __init__(self, loop: asyncio.AbstractEventLoop, *, ipc_transport: str = "auto"):
        self.loop = loop
        self.queue = asyncio.Queue()
        self.ipc_transport = ipc_transport
        self.ipc_client = None
        self.ipc_task = None
        self.thread = Thread(target=self._reader, daemon=True)
        self.thread.start()
        if should_use_ws_ipc(ipc_transport):
            self.ipc_task = asyncio.create_task(self._ipc_reader())

    def _reader(self):
        for line in sys.stdin:
            _run_in_background(self.loop, self.queue.put_nowait, UserCommand("stdin", line))

    async def _ipc_reader(self):
        self.ipc_client = LocalIpcClient(role="client_cli")
        if not await self.ipc_client.connect():
            return
        try:
            while True:
                message = await self.ipc_client.incoming.get()
                if message.get("channel") != "manager.console_command":
                    continue
                command = str(message.get("data", {}).get("command", "") or "")
                if command:
                    await self.queue.put(UserCommand("stdin", command + "\n"))
        except asyncio.CancelledError:
            pass
        finally:
            await self.ipc_client.close()

    async def close(self):
        if self.ipc_task:
            self.ipc_task.cancel()
            try:
                await self.ipc_task
            except asyncio.CancelledError:
                pass


@dataclass
class UserCommand:
    action: str
    value: str = ""


class ClientGUIBridge:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        input_queue: asyncio.Queue,
        *,
        ui: str = "tk",
        ipc_transport: str = "auto",
    ):
        self.loop = loop
        self.input_queue = input_queue
        self.process = None
        self._ui = ui if ui in {"tk", "qt"} else "tk"
        self._ipc_transport = ipc_transport
        self._ipc_server = None

    def ensure_started(self):
        if self.process is not None and self.process.poll() is None:
            return

        env = _child_env()
        self._start_ipc_server(env)
        try:
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "client.gui",
                    "--ui",
                    self._ui,
                    "--ipc-transport",
                    self._ipc_transport,
                ],
                cwd=_project_dir(),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except Exception:
            self._stop_ipc_server()
            raise
        Thread(target=self._stdout_reader, daemon=True).start()

    def _stdout_reader(self):
        process = self.process
        if process is None or process.stdout is None:
            return

        for line in iter(process.stdout.readline, ""):
            command = self._parse_gui_command(line)
            if command is None:
                continue
            _run_in_background(self.loop, self.input_queue.put_nowait, command)
        try:
            process.stdout.close()
        except Exception:
            pass

    def _start_ipc_server(self, env: dict):
        self._stop_ipc_server()
        try:
            self._ipc_server = ThreadedIpcServer(
                role="client",
                on_message=self._handle_ipc_message,
            )
            self._ipc_server.start()
            env.update(self._ipc_server.child_env("timer_gui", self._ipc_transport))
        except Exception as exc:
            print(f"[GUI IPC] Local WebSocket IPC unavailable: {exc}")
            self._ipc_server = None

    def _stop_ipc_server(self):
        if not self._ipc_server:
            return
        try:
            self._ipc_server.stop()
        except Exception:
            pass
        self._ipc_server = None

    def _handle_ipc_message(self, message: dict):
        if message.get("channel") != "timer.command":
            return
        command = self._parse_gui_payload(message.get("data", {}))
        if command is None:
            return
        _run_in_background(self.loop, self.input_queue.put_nowait, command)

    def send_sync(self, remaining_seconds: int):
        self._write(f"SYNC:{remaining_seconds}\n")

    def send_pause(self, remaining_seconds: int, reason: str = ""):
        self._write(f"PAUSE:{json.dumps({'remaining_seconds': remaining_seconds, 'reason': reason})}\n")

    def send_resume(self, remaining_seconds: int, reason: str = ""):
        self._write(f"RESUME:{json.dumps({'remaining_seconds': remaining_seconds, 'reason': reason})}\n")

    def send_end(self):
        self._write("END:-1\n")

    def send_reset(self):
        self._write("RESET:1\n")

    def send_error(self, message: str):
        self._write(f"ERROR:{message}\n")

    def send_open_finish(self, message: str):
        self._write(f"OPEN_FINISH:{message}\n")

    def send_upload_success(self, message: str):
        self._write(f"UPLOAD_OK:{message}\n")

    def send_upload_error(self, message: str):
        self._write(f"UPLOAD_ERROR:{message}\n")

    def send_upload_step(self, message: str):
        self._write(f"UPLOAD_STEP:{message}\n")

    def send_exam_files(self, info: dict):
        self._write(f"EXAM_FILES:{json.dumps(info, ensure_ascii=True)}\n")

    def close(self):
        process = self.process
        if process and process.poll() is None:
            self._request_process_exit(process)
        if process is not None:
            self._mark_process_closed(process)
        else:
            self._stop_ipc_server()

    def _request_process_exit(self, process) -> None:
        sent = False
        if self._ipc_server:
            sent = self._ipc_server.send("client.timer_state", {"line": "END:-1"})
        if not sent:
            stream = getattr(process, "stdin", None)
            if stream is not None:
                try:
                    stream.write("END:-1\n")
                    stream.flush()
                except Exception:
                    pass
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            try:
                process.terminate()
                process.wait(timeout=1.0)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        self._stop_ipc_server()

    def _mark_process_closed(self, process) -> None:
        if self.process is process:
            self.process = None
        stream = getattr(process, "stdin", None)
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        self._stop_ipc_server()

    def _parse_gui_command(self, line: str) -> UserCommand | None:
        text = line.strip()
        if not text:
            return None

        if "ACTION:START" in text:
            print("[GUI] Start button pressed.")
            return UserCommand("start")

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        return self._parse_gui_payload(payload)

    def _parse_gui_payload(self, payload: dict) -> UserCommand | None:
        command = payload.get("cmd")
        if command == "start_exam":
            print("[GUI] Start button pressed.")
            return UserCommand("start")
        if command == "reset_exam_folder":
            print("[GUI] Reset exam folder requested.")
            return UserCommand("reset_exam_folder")
        if command == "finish_exam":
            selected_file = str(payload.get("archive_path", "")).strip()
            if not selected_file:
                return None
            print(f"[GUI] Finish button pressed with file: {selected_file}")
            return UserCommand("finish", selected_file)
        return None

    def _write(self, message: str):
        process = self.process
        if not process or process.poll() is not None:
            if process is not None:
                self._mark_process_closed(process)
            return
        if self._ipc_server and self._ipc_server.send(
            "client.timer_state",
            {"line": message.rstrip("\n")},
        ):
            return

        stdin = getattr(process, "stdin", None)
        if stdin is None:
            self._mark_process_closed(process)
            return

        try:
            stdin.write(message)
            stdin.flush()
        except Exception as exc:
            if _is_closed_pipe_error(exc):
                self._mark_process_closed(process)


@dataclass
class ReplaySaveRequest:
    request_id: str
    save_id: str
    requested_at: str
    source: str
    future: asyncio.Future
    priority: int
    deadline_at: float | None
    optional: bool


_CACHE_MISS = object()


class ReplaySaveQueue:
    def __init__(
        self,
        recorder: ReplayRecorder | None,
        loop: asyncio.AbstractEventLoop,
        *,
        optional_queue_limit: int = REPLAY_OPTIONAL_SAVE_QUEUE_LIMIT,
        incident_queue_limit: int = REPLAY_INCIDENT_SAVE_QUEUE_LIMIT,
    ):
        self.recorder = recorder
        self.loop = loop
        self.optional_queue_limit = max(0, int(optional_queue_limit))
        self.incident_queue_limit = max(0, int(incident_queue_limit))
        self._queue: asyncio.PriorityQueue[tuple[int, int, ReplaySaveRequest]] = asyncio.PriorityQueue()
        self._worker_task: asyncio.Task | None = None
        self._closed = False
        self._sequence = 0
        self._queued_optional = 0
        self._queued_incident = 0
        self._active_request: ReplaySaveRequest | None = None
        self._final_submission_mode = False
        self._inflight_by_save_id: dict[str, asyncio.Future] = {}
        self._completed_by_save_id: dict[str, tuple[str | None, float]] = {}

    def enqueue(
        self,
        *,
        request_id: str | None = None,
        requested_at: str | None = None,
        source: str = "client",
        priority: int | None = None,
        deadline_seconds: float | None = None,
    ) -> tuple[ReplaySaveRequest, asyncio.Future]:
        normalized_source = str(source or "client")
        request_priority = self._priority_for_source(normalized_source) if priority is None else int(priority)
        incident_evidence = normalized_source == "incident_evidence"
        optional = request_priority >= REPLAY_PRIORITY_OPTIONAL_REQUEST
        normalized_requested_at = str(requested_at or protocol.now_iso())
        normalized_request_id = str(request_id or uuid.uuid4().hex)
        save_id = self._save_id_for_request(
            source=normalized_source,
            requested_at=normalized_requested_at,
            request_id=normalized_request_id,
        )
        if deadline_seconds is None:
            if optional:
                deadline_seconds = REPLAY_OPTIONAL_SAVE_DEADLINE_SECONDS
            elif incident_evidence:
                deadline_seconds = REPLAY_INCIDENT_SAVE_DEADLINE_SECONDS
            else:
                deadline_seconds = float(REPLAY_SAVE_TIMEOUT_SECONDS)
        deadline_at = None
        if deadline_seconds is not None:
            deadline_at = self.loop.time() + float(deadline_seconds)

        save_request = ReplaySaveRequest(
            request_id=normalized_request_id,
            save_id=save_id,
            requested_at=normalized_requested_at,
            source=normalized_source,
            future=self.loop.create_future(),
            priority=request_priority,
            deadline_at=deadline_at,
            optional=optional,
        )

        if self._closed or not self.recorder:
            save_request.future.set_result(None)
            return save_request, save_request.future

        if normalized_source == "final_submission":
            self.begin_final_submission()

        if normalized_source != "final_submission" and self._final_submission_mode:
            print(
                f"[RECORDER] Dropping replay request {save_request.request_id}: "
                "final submission is in progress."
            )
            save_request.future.set_result(None)
            return save_request, save_request.future

        if self._coalesces_source(normalized_source):
            cached_replay_path = self._completed_replay_path(save_request.save_id)
            if cached_replay_path is not _CACHE_MISS:
                print(
                    f"[RECORDER] Reusing replay save {save_request.save_id} "
                    f"for request {save_request.request_id}."
                )
                save_request.future.set_result(cached_replay_path)
                return save_request, save_request.future

            shared_future = self._inflight_by_save_id.get(save_request.save_id)
            if shared_future is not None:
                print(
                    f"[RECORDER] Sharing replay save {save_request.save_id} "
                    f"for request {save_request.request_id}."
                )
                self._chain_shared_replay(shared_future, save_request.future)
                return save_request, save_request.future

        if incident_evidence and self._queued_incident >= self.incident_queue_limit:
            print(
                f"[RECORDER] Dropping replay request {save_request.request_id}: "
                "incident replay queue is full; uploading evidence without replay."
            )
            save_request.future.set_result(None)
            return save_request, save_request.future

        if optional and self._queued_optional >= self.optional_queue_limit:
            print(
                f"[RECORDER] Dropping replay request {save_request.request_id}: "
                "optional replay queue is full."
            )
            save_request.future.set_result(None)
            return save_request, save_request.future

        self._sequence += 1
        if optional:
            self._queued_optional += 1
        if incident_evidence:
            self._queued_incident += 1
        self._queue.put_nowait((save_request.priority, self._sequence, save_request))
        if self._coalesces_source(normalized_source):
            self._inflight_by_save_id[save_request.save_id] = save_request.future
        self._ensure_worker()
        return save_request, save_request.future

    def begin_final_submission(self):
        self._final_submission_mode = True
        self._drain_pending_non_final("final submission is in progress")

    async def save(
        self,
        *,
        request_id: str | None = None,
        requested_at: str | None = None,
        source: str = "client",
        priority: int | None = None,
        deadline_seconds: float | None = None,
    ) -> str | None:
        _save_request, future = self.enqueue(
            request_id=request_id,
            requested_at=requested_at,
            source=source,
            priority=priority,
            deadline_seconds=deadline_seconds,
        )
        return await future

    def close(self):
        self._closed = True
        self._drain_pending(cancel=True)
        if self._worker_task and self._active_request is None:
            self._worker_task.cancel()

    async def aclose(self):
        self.close()
        task = self._worker_task
        if not task:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=REPLAY_QUEUE_CLOSE_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            if task.cancelled():
                return
            raise
        except asyncio.TimeoutError:
            if not task.done():
                task.cancel()

    def _drain_pending(self, *, cancel: bool):
        while True:
            try:
                _priority, _sequence, save_request = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._mark_dequeued(save_request)
            if not save_request.future.done():
                if cancel:
                    save_request.future.cancel()
                    self._inflight_by_save_id.pop(save_request.save_id, None)
                else:
                    self._complete_replay_request(save_request, None, cache=False)
            self._queue.task_done()

    def _drain_pending_non_final(self, reason: str):
        retained: list[tuple[int, int, ReplaySaveRequest]] = []
        while True:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            _priority, _sequence, save_request = item
            self._queue.task_done()
            if save_request.source != "final_submission":
                self._mark_dequeued(save_request)
                self._finish_without_replay(save_request, reason)
            else:
                retained.append(item)

        for item in retained:
            self._queue.put_nowait(item)

    @staticmethod
    def _priority_for_source(source: str) -> int:
        if source == "final_submission":
            return REPLAY_PRIORITY_FINAL_SUBMISSION
        if source == "incident_evidence":
            return REPLAY_PRIORITY_INCIDENT_EVIDENCE
        return REPLAY_PRIORITY_OPTIONAL_REQUEST

    @staticmethod
    def _coalesces_source(source: str) -> bool:
        return source != "final_submission"

    def _save_id_for_request(self, *, source: str, requested_at: str, request_id: str) -> str:
        if not self._coalesces_source(source):
            return request_id
        requested_seconds = self._requested_at_seconds(requested_at)
        window = max(1.0, float(REPLAY_SAVE_COALESCE_WINDOW_SECONDS))
        bucket_seconds = int(requested_seconds // window) * int(window)
        bucket = datetime.fromtimestamp(bucket_seconds, tz=timezone.utc)
        return f"window_{bucket.strftime('%Y%m%dT%H%M%SZ')}"

    @staticmethod
    def _requested_at_seconds(requested_at: str) -> float:
        text = str(requested_at or "").strip()
        if text:
            try:
                if text.endswith("Z"):
                    text = text[:-1] + "+00:00"
                parsed = datetime.fromisoformat(text)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.timestamp()
            except ValueError:
                pass
        return time.time()

    def _completed_replay_path(self, save_id: str):
        self._prune_completed_replays()
        cached = self._completed_by_save_id.get(save_id)
        if cached is None:
            return _CACHE_MISS
        replay_path, _stored_at = cached
        if replay_path and not os.path.exists(replay_path):
            self._completed_by_save_id.pop(save_id, None)
            return _CACHE_MISS
        return replay_path

    def _prune_completed_replays(self):
        if not self._completed_by_save_id:
            return
        now = self.loop.time()
        stale = [
            save_id
            for save_id, (_path, stored_at) in self._completed_by_save_id.items()
            if now - stored_at > REPLAY_SAVE_RESULT_CACHE_SECONDS
        ]
        for save_id in stale:
            self._completed_by_save_id.pop(save_id, None)

    def _chain_shared_replay(self, shared_future: asyncio.Future, request_future: asyncio.Future):
        def _copy_result(done_future: asyncio.Future):
            if request_future.done():
                return
            if done_future.cancelled():
                request_future.cancel()
                return
            exception = done_future.exception()
            if exception is not None:
                request_future.set_exception(exception)
            else:
                request_future.set_result(done_future.result())

        shared_future.add_done_callback(_copy_result)

    def _complete_replay_request(self, save_request: ReplaySaveRequest, replay_path: str | None, *, cache: bool):
        self._inflight_by_save_id.pop(save_request.save_id, None)
        if cache and replay_path and self._coalesces_source(save_request.source):
            self._completed_by_save_id[save_request.save_id] = (replay_path, self.loop.time())
        if not save_request.future.done():
            save_request.future.set_result(replay_path)

    def _request_expired(self, save_request: ReplaySaveRequest) -> bool:
        return save_request.deadline_at is not None and self.loop.time() > save_request.deadline_at

    def _finish_without_replay(self, save_request: ReplaySaveRequest, reason: str):
        if not save_request.future.done():
            print(f"[RECORDER] Skipping replay request {save_request.request_id}: {reason}.")
            self._complete_replay_request(save_request, None, cache=False)

    def _mark_dequeued(self, save_request: ReplaySaveRequest):
        if save_request.optional:
            self._queued_optional = max(0, self._queued_optional - 1)
        if save_request.source == "incident_evidence":
            self._queued_incident = max(0, self._queued_incident - 1)

    def _ensure_worker(self):
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())

    async def _worker(self):
        while True:
            if self._closed and self._queue.empty():
                return
            _priority, _sequence, save_request = await self._queue.get()
            self._mark_dequeued(save_request)
            try:
                if save_request.future.cancelled():
                    self._inflight_by_save_id.pop(save_request.save_id, None)
                    continue
                if self._request_expired(save_request):
                    self._finish_without_replay(save_request, "request deadline expired")
                    continue
                self._active_request = save_request
                replay_path = await self.loop.run_in_executor(
                    None,
                    self.recorder.save_replay,
                    save_request.save_id,
                )
                self._complete_replay_request(save_request, replay_path, cache=True)
            except Exception as exc:
                self._inflight_by_save_id.pop(save_request.save_id, None)
                if not save_request.future.done():
                    save_request.future.set_exception(exc)
            finally:
                self._active_request = None
                self._queue.task_done()


@dataclass
class SessionState:
    disconnected: asyncio.Event
    start_event: asyncio.Event
    exam_active: bool = True
    last_printed_remaining: int | None = None
    start_request_pending: bool = False
    finish_request_pending: bool = False
    submission_only: bool = False
    submission_completed: bool = False
    intentional_shutdown: bool = False
    current_remaining_seconds: int = 0
    timer_state: str = "idle"
    pause_source: str = ""
    applied_policy_version: str = ""
    session_state: str = "waiting"
    resume_allowed: bool = False


class WebSocketSession:
    def __init__(
        self,
        ws_url: str,
        base_url: str,
        session_uuid: str,
        password: str,
        ws,
        recorder: ReplayRecorder | None,
        *,
        gui_ui: str = "tk",
        ipc_transport: str = "auto",
        incident_buffer: IncidentBuffer | None = None,
    ):
        self.ws_url = ws_url
        self.base_url = base_url
        self.session_uuid = session_uuid
        self.password = password
        self.ws = ws
        self.recorder = recorder
        self.loop = asyncio.get_running_loop()
        self.security = security.build_session_context(session_uuid, password)
        self.state = SessionState(
            disconnected=asyncio.Event(),
            start_event=asyncio.Event(),
        )
        self.output_dir = os.path.join("data", "client", self.session_uuid)
        self.stdin = StdinBridge(self.loop, ipc_transport=ipc_transport)
        self.gui = ClientGUIBridge(
            self.loop,
            self.stdin.queue,
            ui=gui_ui,
            ipc_transport=ipc_transport,
        )
        self.exam_state_logger = ExamStateLogger(self.output_dir)
        self.incident_engine = ClientIncidentEngine()
        self.incident_buffer = incident_buffer
        if self.incident_buffer:
            restored = self.incident_buffer.begin_session(session_uuid)
            if restored:
                print(f"[INCIDENT] Restored {restored} unacked incident(s) from previous session.")
        self._background_tasks: set[asyncio.Task] = set()
        self._runtime_closed = False
        self._evidence_uploading: set[str] = set()
        self._evidence_upload_semaphore = asyncio.Semaphore(INCIDENT_EVIDENCE_UPLOAD_CONCURRENCY)
        self._uploaded_replay_artifacts: dict[str, str] = {}
        self._replay_artifact_tasks: dict[str, asyncio.Task] = {}
        self._uploaded_requested_replays: dict[str, tuple[str, str, float]] = {}
        self._requested_replay_upload_tasks: dict[tuple[str, str], asyncio.Task] = {}
        self.exam_files_info: dict = {}
        self.replay_save_queue = ReplaySaveQueue(recorder, self.loop)
        self.process_monitor = self._create_process_monitor()
        self.hardware_monitor = self._create_hardware_monitor()
        self._last_focused_window_server_send = 0.0
        self.focused_window_monitor = self._create_focused_window_monitor()
        self.idle_monitor = self._create_idle_monitor()
        self._record_timer_transition(timer_state="idle", source="client", reason="session_initialized")

    def attach_connection(self, ws_url: str, base_url: str, password: str, ws):
        self.ws_url = ws_url
        self.base_url = base_url
        self.password = password
        self.ws = ws
        self.security = security.build_session_context(self.session_uuid, password)
        self.state.disconnected.clear()
        self.state.intentional_shutdown = False
        self._runtime_closed = False
        self._record_timer_transition(
            timer_state="reconnected",
            source="client",
            reason="WebSocket connection established.",
        )

    def set_exam_files_info(self, info: dict | None):
        self.exam_files_info = self._normalized_exam_files_info(info)
        if self._has_exam_files_info_for_gui():
            self.gui.ensure_started()
            self.gui.send_exam_files(self.exam_files_info)

    def _send_cached_exam_files_info(self):
        if self._has_exam_files_info_for_gui():
            self.gui.send_exam_files(self.exam_files_info)

    @staticmethod
    def _normalized_exam_files_info(info: dict | None) -> dict:
        normalized = {
            "has_files": False,
            "zip_path": "",
            "extracted_dir": "",
            "archive_sha256": "",
            "pending_extraction": False,
            "error": "",
        }
        if info:
            normalized.update(dict(info))
        normalized["has_files"] = bool(normalized.get("has_files"))
        normalized["zip_path"] = str(normalized.get("zip_path", "") or "")
        normalized["extracted_dir"] = str(normalized.get("extracted_dir", "") or "")
        normalized["archive_sha256"] = str(normalized.get("archive_sha256", "") or "")
        normalized["pending_extraction"] = bool(normalized.get("pending_extraction"))
        normalized["error"] = str(normalized.get("error", "") or "")
        return normalized

    def _has_exam_files_info_for_gui(self) -> bool:
        return bool(
            self.exam_files_info.get("has_files")
            or self.exam_files_info.get("zip_path")
            or self.exam_files_info.get("extracted_dir")
            or self.exam_files_info.get("error")
        )

    async def _send_client_info(self):
        await self._send_payload(
            events.client_info(
                _computer_name(),
                exam_folder_path=str(self.exam_files_info.get("extracted_dir", "") or ""),
                exam_files_zip_path=str(self.exam_files_info.get("zip_path", "") or ""),
            )
        )

    async def _ensure_exam_materials_extracted(self, *, force_new: bool = False) -> tuple[bool, str]:
        if not self.exam_files_info.get("has_files"):
            return True, ""

        zip_path = str(self.exam_files_info.get("zip_path", "") or "").strip()
        if not zip_path:
            message = "Exam files were announced, but no local archive path is available."
            self.exam_files_info["error"] = message
            self.gui.ensure_started()
            self.gui.send_exam_files(self.exam_files_info)
            return False, message

        if not os.path.exists(zip_path):
            message = f"Exam archive is missing: {zip_path}"
            self.exam_files_info["error"] = message
            self.exam_files_info["pending_extraction"] = True
            self.gui.ensure_started()
            self.gui.send_exam_files(self.exam_files_info)
            return False, message

        try:
            print("[EXAM] Extracting exam files..." if not force_new else "[EXAM] Resetting exam folder...")
            info = await self.loop.run_in_executor(
                None,
                lambda: extract_exam_materials(zip_path, force_new=force_new),
            )
        except Exception as exc:
            message = f"Failed to extract exam files: {exc}"
            self.exam_files_info["error"] = message
            self.exam_files_info["pending_extraction"] = True
            self.gui.ensure_started()
            self.gui.send_exam_files(self.exam_files_info)
            print(f"[EXAM] {message}")
            return False, message

        merged = dict(self.exam_files_info)
        merged.update(info)
        merged["pending_extraction"] = False
        merged["error"] = ""
        self.exam_files_info = self._normalized_exam_files_info(merged)
        self.gui.ensure_started()
        self.gui.send_exam_files(self.exam_files_info)
        print(f"[EXAM] Exam files ready at {self.exam_files_info['extracted_dir']}.")
        try:
            await self._send_client_info()
        except Exception as exc:
            print(f"[EXAM] Could not publish exam folder metadata yet: {exc}")
        return True, ""

    async def reset_exam_folder(self):
        ok, message = await self._ensure_exam_materials_extracted(force_new=True)
        if not ok and message:
            self.gui.ensure_started()
            self.gui.send_exam_files(self.exam_files_info)

    def _create_process_monitor(self):
        monitor = ProcessMonitor(
            self.output_dir,
            poll_callback=self._queue_process_snapshot,
        )
        monitor.start()
        return monitor

    def _create_hardware_monitor(self):
        monitor = HardwareMonitor(self.output_dir)
        monitor.start()
        return monitor

    def _create_focused_window_monitor(self):
        monitor = FocusedWindowMonitor(
            self.output_dir,
            interval_seconds=FOCUSED_WINDOW_CHECK_INTERVAL_SECONDS,
            full_info_interval_checks=FOCUSED_WINDOW_FULL_INFO_INTERVAL_CHECKS,
            emit_on_change_only=True,
            snapshot_callback=self._queue_focused_window_snapshot,
        )
        monitor.start()
        return monitor

    def _create_idle_monitor(self):
        monitor = IdleMonitor(
            self.output_dir,
            snapshot_callback=self._queue_idle_snapshot,
        )
        monitor.start()
        return monitor

    def _queue_idle_snapshot(self, snapshot: dict):
        self._schedule_background_task(
            self._process_local_incidents(self.incident_engine.observe_idle(snapshot))
        )

    def _stop_runtime_monitors(self):
        self.process_monitor.stop()
        self.hardware_monitor.stop()
        self.focused_window_monitor.stop()
        self.idle_monitor.stop()

    def _schedule_background_task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)

        def _on_done(done_task: asyncio.Task):
            self._background_tasks.discard(done_task)
            if done_task.cancelled():
                return
            try:
                exc = done_task.exception()
            except asyncio.CancelledError:
                return
            if exc:
                print(f"[TASK] Background task failed: {safe_console_text(exc)}")

        task.add_done_callback(_on_done)
        return task

    async def _send_payload(self, payload: str):
        await self.ws.send_str(security.protect_wire_message(payload, self.security))

    def _record_timer_transition(self, *, timer_state: str, source: str, reason: str = ""):
        remaining = int(self.state.current_remaining_seconds or 0)
        self.exam_state_logger.record(
            remaining_seconds=remaining,
            timer_state=timer_state,
            source=source,
            reason=reason,
        )
        self.process_monitor.append_state_marker(
            timer_state=timer_state,
            source=source,
            reason=reason,
        )
        self.focused_window_monitor.append_state_marker(
            remaining_seconds=remaining,
            timer_state=timer_state,
            source=source,
            reason=reason,
        )
        self.hardware_monitor.append_state_marker(
            remaining_seconds=remaining,
            timer_state=timer_state,
            source=source,
            reason=reason,
        )

    def _update_timer_state(
        self,
        *,
        remaining_seconds: int,
        timer_state: str,
        source: str,
        reason: str = "",
    ):
        previous_state = self.state.timer_state
        previous_remaining = self.state.current_remaining_seconds
        self.state.current_remaining_seconds = int(max(0, remaining_seconds))
        self.state.timer_state = timer_state
        self.state.pause_source = source if timer_state == "paused" else ""
        self.process_monitor.update_time(self.state.current_remaining_seconds)
        if previous_state != timer_state or (
            timer_state == "paused" and previous_remaining != self.state.current_remaining_seconds
        ):
            self._record_timer_transition(timer_state=timer_state, source=source, reason=reason)

    async def run(self):
        await self._flush_incident_buffer()
        await self._flush_pending_evidence()
        listener_task = asyncio.create_task(self.listener())
        try:
            await self.sender()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            listener_task.cancel()

        if self.state.disconnected.is_set() and not self.state.intentional_shutdown:
            self._mark_reconnecting()
            raise ConnectionError("Server disconnected")
        return self.state.intentional_shutdown

    def _mark_reconnecting(self):
        if self.state.submission_completed or self._runtime_closed:
            return
        reason = "Connection lost. Reconnecting..."
        remaining = int(self.state.current_remaining_seconds or 0)
        self._update_timer_state(
            remaining_seconds=remaining,
            timer_state="reconnecting",
            source="client",
            reason=reason,
        )
        self.gui.ensure_started()
        self.gui.send_pause(remaining, reason)
        print(f"[WS] {reason}")

    async def close_runtime(self):
        if self._runtime_closed:
            return
        self._runtime_closed = True
        self.gui.close()
        await self.stdin.close()
        self._stop_runtime_monitors()
        await self.replay_save_queue.aclose()
        for task in list(self._background_tasks):
            task.cancel()

    async def prompt_start_exam(self):
        print("\n--- PRE-EXAM PREPARATION ---")
        print("When you are ready, type 'start' or click the button in the GUI.")
        print("If the server has not started the exam yet, you will be asked to try again.")

        while not self.state.start_event.is_set():
            command, event_triggered = await _wait_for_queue_or_event(
                self.stdin.queue,
                self.state.start_event,
                self.state.disconnected,
            )
            if event_triggered:
                break

            if not isinstance(command, UserCommand):
                continue

            if command.action == "start":
                await self.request_exam_start()
                continue

            if command.action == "reset_exam_folder":
                await self.reset_exam_folder()
                continue

            if command.action == "stdin":
                text = command.value.strip().lower()
                if text in {"start", "/start"}:
                    await self.request_exam_start()
                    continue

            print("Type 'start' or use the GUI when you are ready.")

        if self.state.disconnected.is_set() and not self.state.start_event.is_set():
            return

        if self.state.submission_only:
            print("[EXAM] Submission is required. Use the finish window to upload your file.\n")
            return

        print("[EXAM] Started. Good luck!\n")

    async def request_exam_start(self):
        if self.state.start_request_pending:
            print("[EXAM] Start request already in progress...")
            return

        self.state.start_request_pending = True
        ok, message = await self._ensure_exam_materials_extracted(force_new=False)
        if not ok:
            self.state.start_request_pending = False
            self.gui.send_reset()
            if message:
                self.gui.send_error(message)
            return
        await self._send_payload(events.start_exam())
        print("[EXAM] Start request sent...")

    async def sender(self):
        await self.prompt_start_exam()
        if self.state.disconnected.is_set():
            return
        if self.state.submission_only:
            print("Use the finish window to upload your file, or type 'finish <file_path>'.\n")
        else:
            print("Type anything and press Enter to ping the server (Ctrl+C to quit):\n")

        while not self.state.disconnected.is_set() and self.state.exam_active:
            command, disconnected = await _wait_for_queue_or_event(
                self.stdin.queue,
                self.state.disconnected,
            )
            if disconnected:
                break

            if not isinstance(command, UserCommand):
                continue

            if command.action == "finish":
                await self.finish_exam(command.value)
                continue

            if command.action == "reset_exam_folder":
                await self.reset_exam_folder()
                continue

            if command.action != "stdin":
                continue

            text = command.value.strip()
            finish_path = _extract_finish_path(text)
            if finish_path:
                await self.finish_exam(finish_path)
                continue

            if self.state.submission_only:
                print("Submission is still required. Use the finish window or type 'finish <file_path>'.")
                continue

            if text:
                await self._send_payload(events.ping(text))

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
        event, data = security.decode_wire_message(raw_message, self.security)
        if event == protocol.DECODE_ERROR:
            print(f"[WS] Protocol error: {data.get('reason', 'decode failed')}")
            return

        if event == events.WELCOME:
            print(f"[WS] Connected! Server assigned ID: {data['id']}")
            self.gui.ensure_started()
            self._send_cached_exam_files_info()
            await self._send_client_info()
            return

        if event == events.EXAM_POLICY:
            await self.handle_exam_policy(data, update_kind="initial")
            return

        if event == events.POLICY_UPDATE:
            await self.handle_exam_policy(data, update_kind="update")
            return

        if event == events.ECHO:
            print(f"[WS] Echo: {data}")
            return

        if event == events.TIME:
            return

        if event == events.SYNC_TIME:
            if not self.state.start_event.is_set():
                await self._ensure_exam_materials_extracted(force_new=False)
            self.handle_sync_time(data)
            return

        if event == events.SESSION_STATE:
            state_name = str(data.get("state", "waiting") or "waiting")
            if state_name in {"running", "admin_paused", "disconnected_paused", "violation_paused", "awaiting_submission"}:
                await self._ensure_exam_materials_extracted(force_new=False)
            self.handle_session_state(data)
            return

        if event == events.PAUSE_EXAM:
            self.handle_pause_exam(data)
            return

        if event == events.RESUME_EXAM:
            self.handle_resume_exam(data)
            return

        if event == events.ERROR:
            self.handle_server_error(data)
            return

        if event == events.EXAM_END:
            self.handle_exam_end()
            return

        if event == events.FINISH_EXAM:
            self.handle_finish_request(data)
            return

        if event == events.SAVESCREEN:
            print("[WS] [SAVESCREEN] Server requested replay save.")
            self._schedule_background_task(self._handle_savescreen_request(data))
            return

        if event == events.GET_PROCESSES:
            print("[WS] [GET_PROCESSES] Server requested a manual process report.")
            report_path = self.process_monitor.export_requested_report()
            if report_path:
                await self._upload_runtime_artifact(
                    report_path,
                    artifact_kind="requested_process_report",
                    metadata={"source": "server_request"},
                )
            return

        if event == events.PROCESS_BLACKLIST:
            self.handle_process_blacklist(data)
            return

        if event == events.INCIDENT_RECEIVED:
            incident_id = data.get("incident_id", "")
            if self.incident_buffer:
                self.incident_buffer.mark_acked(incident_id)
            print(f"[INCIDENT] Server acknowledged incident {incident_id}.")
            return

        if event == events.KILL_PROCESS:
            await self.handle_kill_process(data)
            return

        print(f"[WS] {event}: {data}")

    def handle_sync_time(self, data: dict):
        remaining = int(data.get("remaining_seconds", 0) or 0)
        timer_state = str(data.get("timer_state", "running") or "running")
        pause_source = str(data.get("pause_source", "") or "")
        reason = str(data.get("reason", "") or "")
        self._update_timer_state(
            remaining_seconds=remaining,
            timer_state=timer_state,
            source=pause_source or "server",
            reason=reason,
        )
        self.gui.ensure_started()
        self.state.start_request_pending = False

        if not self.state.start_event.is_set():
            print("[WS] Exam is already running on the server. Joining automatically...")
            self.state.start_event.set()

        self.gui.send_sync(remaining)
        if timer_state == "paused":
            self.gui.send_pause(remaining, reason)
        else:
            self.gui.send_resume(remaining, reason)
        self._print_remaining_time(remaining)

    def handle_session_state(self, data: dict):
        state_name = str(data.get("state", "waiting") or "waiting")
        remaining = int(data.get("remaining_seconds", self.state.current_remaining_seconds) or 0)
        reason = str(data.get("reason", "") or "")
        pause_source = str(data.get("pause_source", "") or "")
        self.state.session_state = state_name
        self.state.resume_allowed = bool(data.get("resume_allowed", False))

        if state_name == "waiting":
            self.state.start_request_pending = False
            self._update_timer_state(
                remaining_seconds=remaining,
                timer_state="idle",
                source="server",
                reason=reason or "waiting",
            )
            return

        self.gui.ensure_started()

        if state_name == "awaiting_submission":
            self.state.submission_only = True
            self.state.start_event.set()
            self._record_timer_transition(
                timer_state="submission_only",
                source="server",
                reason=reason or "awaiting_submission",
            )
            self.gui.send_open_finish(reason or "Your exam has ended. Please upload your file.")
            print(f"[EXAM] {reason or 'Submission is required.'}")
            return

        if state_name in {"running", "admin_paused", "disconnected_paused", "violation_paused"}:
            self.state.start_request_pending = False
            self.state.start_event.set()

        if state_name == "running":
            self._update_timer_state(
                remaining_seconds=remaining,
                timer_state="running",
                source="server",
                reason=reason,
            )
            self.gui.send_resume(remaining, reason)
            if reason:
                print(f"[EXAM] {reason}")
            return

        if state_name in {"admin_paused", "disconnected_paused", "violation_paused"}:
            self._update_timer_state(
                remaining_seconds=remaining,
                timer_state="paused",
                source=pause_source or "server",
                reason=reason,
            )
            self.gui.send_pause(remaining, reason)
            if reason:
                print(f"[EXAM] {reason}")
            elif state_name == "violation_paused":
                print("[EXAM] Session is violation-paused pending administrator action.")
            elif state_name == "disconnected_paused":
                print("[EXAM] Session is paused pending reconnect approval.")
            else:
                print("[EXAM] Session is paused by the server.")
            return

        if state_name == "submitted":
            self.state.submission_only = False
            self.state.submission_completed = True
            self._record_timer_transition(
                timer_state="submitted",
                source="server",
                reason=reason or "submitted",
            )
            return

        if state_name == "banned":
            self.handle_server_error({"reason": reason or "This user is banned."})
            return

    async def handle_exam_policy(self, data: dict, *, update_kind: str):
        ok, reason = self.incident_engine.apply_policy(data)
        policy_version = str(data.get("policy_version", "")).strip()
        if ok:
            self.state.applied_policy_version = policy_version
            self._apply_blacklist_from_policy(data)
            self.process_monitor.emit_current_snapshot()
            print(f"[POLICY] Applied {update_kind} policy version {policy_version}.")
            await self._send_payload(events.policy_applied(policy_version, ok=True))
            return

        print(f"[POLICY] Failed to apply {update_kind} policy: {reason}")
        await self._send_payload(events.policy_applied(policy_version, ok=False, reason=reason))

    def _apply_blacklist_from_policy(self, policy: dict):
        for rule in policy.get("rules", []):
            if not isinstance(rule, dict):
                continue
            if str(rule.get("rule_id")) != "process_blacklist":
                continue
            entries = [str(entry).strip() for entry in rule.get("entries", []) if str(entry).strip()]
            version = str(rule.get("blacklist_version", "") or policy.get("policy_version", "0"))
            usernames = [str(username).strip() for username in rule.get("process_usernames", []) if str(username).strip()]
            self.process_monitor.set_blacklist(entries, version, usernames=usernames)
            return

    def handle_pause_exam(self, data: dict):
        remaining = int(data.get("remaining_seconds", self.state.current_remaining_seconds) or 0)
        reason = str(data.get("reason", "") or "")
        self._update_timer_state(
            remaining_seconds=remaining,
            timer_state="paused",
            source=str(data.get("source", "admin") or "admin"),
            reason=reason,
        )
        self.gui.ensure_started()
        self.gui.send_pause(remaining, reason)
        print(f"[EXAM] Timer paused. {reason}".strip())

    def handle_resume_exam(self, data: dict):
        remaining = int(data.get("remaining_seconds", self.state.current_remaining_seconds) or 0)
        reason = str(data.get("reason", "") or "")
        self._update_timer_state(
            remaining_seconds=remaining,
            timer_state="running",
            source=str(data.get("source", "admin") or "admin"),
            reason=reason,
        )
        self.gui.ensure_started()
        self.gui.send_resume(remaining, reason)
        print("[EXAM] Timer resumed.")

    def handle_server_error(self, data: dict):
        reason = data.get("reason", "Unknown server error.")
        self.state.start_request_pending = False
        print(f"[WS] Error: {reason}")
        self.gui.ensure_started()
        if not self.state.submission_only:
            self.gui.send_reset()
        if reason in {"Exam is not started yet.", "Exam has already finished."}:
            self.gui.send_error(reason)

    def handle_process_blacklist(self, data: dict):
        entries = [str(entry).strip() for entry in data.get("entries", []) if str(entry).strip()]
        version = str(data.get("version", "0"))
        usernames = [str(username).strip() for username in data.get("process_usernames", []) if str(username).strip()]
        self.process_monitor.set_blacklist(entries, version, usernames=usernames)
        print(
            f"[PROCESS] Received blacklist update version {version} "
            f"with {len(entries)} entrie(s)."
        )

    def handle_finish_request(self, data: dict):
        if self.state.submission_completed:
            return

        reason = data.get("reason", "The exam has been finished by the server.")
        self.state.submission_only = True
        self.state.start_event.set()
        print(f"[EXAM] {reason}")
        self.gui.ensure_started()
        self.gui.send_open_finish(reason)
        self._record_timer_transition(timer_state="submission_only", source="server", reason=reason)

    def handle_exam_end(self):
        print("\n===============================")
        print("       EXAM TIME IS UP!        ")
        print("===============================")
        self.state.exam_active = False
        self.gui.send_end()
        self._record_timer_transition(timer_state="finished", source="server", reason="exam_end")
        self.state.disconnected.set()

    async def finish_exam(self, archive_path: str):
        if self.state.submission_completed:
            print("[EXAM] Submission has already been completed.")
            return

        if self.state.finish_request_pending:
            print("[EXAM] Submission upload is already in progress.")
            return

        archive_path = archive_path.strip()
        if not archive_path:
            error_message = "Choose a file before finishing the exam."
            print(f"[EXAM] {error_message}")
            self.gui.send_upload_error(error_message)
            return

        try:
            validate_submission_file(archive_path)
        except Exception as exc:
            error_message = str(exc)
            print(f"[EXAM] Submission validation failed: {error_message}")
            self.gui.send_upload_error(error_message)
            return

        self.state.finish_request_pending = True
        self.state.submission_only = True
        self._record_timer_transition(timer_state="submission_upload", source="client", reason="finish_exam")
        print(f"[EXAM] Uploading file: {archive_path}")
        self._submission_step("Starting final submission pipeline...")
        try:
            self._submission_step("Collecting runtime snapshots and stopping live monitors...")
            self._stop_runtime_monitors()
            process_report_path = self.process_monitor.export_requested_report()
            hardware_report_path = self.hardware_monitor.export_current_snapshot()
            focused_window_report_path = self.focused_window_monitor.export_current_snapshot()
            replay_path = await self._save_replay_with_timeout(source="final_submission")

            self._submission_step("Building local submission package folder...")
            bundle_path = build_submission_bundle(
                self.session_uuid,
                archive_path,
                process_report_path,
                replay_path,
                hardware_report_path,
                focused_window_report_path,
                step_callback=self._submission_step,
            )
            self._submission_step("6/6 Sending archive and checksums to server...")
            response = await asyncio.wait_for(
                upload_submission_bundle(
                    self.base_url,
                    self.session_uuid,
                    bundle_path,
                ),
                timeout=SUBMISSION_UPLOAD_TIMEOUT_SECONDS,
            )
            self._submission_step("Waiting for server transfer confirmation...")
        except asyncio.TimeoutError:
            self.state.finish_request_pending = False
            error_message = (
                f"Submission upload timed out after {SUBMISSION_UPLOAD_TIMEOUT_SECONDS} seconds. "
                "Check server connectivity and try again."
            )
            print(f"[EXAM] Submission failed: {error_message}")
            self.gui.send_upload_error(error_message)
            return
        except Exception as exc:
            self.state.finish_request_pending = False
            error_message = str(exc)
            print(f"[EXAM] Submission failed: {error_message}")
            self.gui.send_upload_error(error_message)
            return

        self.state.submission_completed = True
        self.state.intentional_shutdown = True
        self.state.exam_active = False
        self._submission_step("Server confirmed transfer. Finalizing client shutdown...")
        self.gui.send_upload_success(response.get("message", "Submission uploaded successfully."))
        await self.ws.close(message=b"submission complete")
        self.state.disconnected.set()

    async def _upload_runtime_artifact(
        self,
        artifact_path: str,
        *,
        artifact_kind: str,
        metadata: dict | None = None,
    ) -> str | None:
        try:
            response = await upload_runtime_artifact(
                self.base_url,
                self.session_uuid,
                artifact_path,
                artifact_kind,
                metadata,
            )
            artifact_server_path = response.get("path", "server storage")
            print(f"[UPLOAD] {artifact_kind} uploaded to {artifact_server_path}")
            return artifact_server_path
        except Exception as exc:
            print(f"[UPLOAD] Failed to upload {artifact_kind}: {exc}")
            return None

    async def _handle_savescreen_request(self, data: dict):
        server_requested_at = str(data.get("requested_at", "") or "")
        client_received_at = protocol.now_iso()
        save_request, future = self.replay_save_queue.enqueue(
            request_id=str(data.get("request_id", "") or uuid.uuid4().hex),
            requested_at=client_received_at,
            source=str(data.get("source", "") or "server_request"),
        )
        try:
            replay_path = await future
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[RECORDER] Replay request {save_request.request_id} failed: {exc}")
            return

        if replay_path:
            await self._upload_requested_replay(
                replay_path,
                save_request,
                server_requested_at=server_requested_at,
            )

    async def _upload_requested_replay(
        self,
        replay_path: str,
        save_request: ReplaySaveRequest,
        *,
        server_requested_at: str | None = None,
    ) -> str | None:
        replay_save_id = save_request.save_id or self._replay_save_id_from_path(replay_path)
        replay_signature = self._file_upload_signature(replay_path)
        if not replay_signature:
            print(f"[UPLOAD] requested_replay file is missing or empty: {replay_path}")
            return None

        self._prune_requested_replay_upload_cache()
        cached_upload = self._uploaded_requested_replays.get(replay_save_id)
        if cached_upload and cached_upload[0] == replay_signature:
            cached_path = cached_upload[1]
            print(f"[UPLOAD] requested_replay already uploaded for {replay_save_id}: {cached_path}")
            return cached_path

        task_key = (replay_save_id, replay_signature)
        task = self._requested_replay_upload_tasks.get(task_key)
        if task is None:
            task = asyncio.create_task(
                self._upload_runtime_artifact(
                    replay_path,
                    artifact_kind="requested_replay",
                    metadata={
                        "source": save_request.source,
                        "request_id": save_request.request_id,
                        "requested_at": save_request.requested_at,
                        "server_requested_at": server_requested_at or "",
                        "replay_save_id": replay_save_id,
                        "replay_file_signature": replay_signature,
                    },
                )
            )
            self._requested_replay_upload_tasks[task_key] = task

            def _cleanup(done_task: asyncio.Task, key: tuple[str, str] = task_key):
                if self._requested_replay_upload_tasks.get(key) is done_task:
                    self._requested_replay_upload_tasks.pop(key, None)

            task.add_done_callback(_cleanup)
        else:
            print(f"[UPLOAD] Sharing requested_replay upload for {replay_save_id}.")

        server_path = await asyncio.shield(task)
        if server_path:
            self._uploaded_requested_replays[replay_save_id] = (
                replay_signature,
                server_path,
                self.loop.time(),
            )
        return server_path

    @staticmethod
    def _file_upload_signature(file_path: str) -> str:
        try:
            info = os.stat(file_path)
        except OSError:
            return ""
        if info.st_size <= 0:
            return ""
        mtime_ns = getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000))
        return f"{os.path.abspath(file_path)}|{info.st_size}|{mtime_ns}"

    def _prune_requested_replay_upload_cache(self):
        if not self._uploaded_requested_replays:
            return
        now = self.loop.time()
        stale = [
            save_id
            for save_id, (_signature, _server_path, stored_at) in self._uploaded_requested_replays.items()
            if now - stored_at > REQUESTED_REPLAY_UPLOAD_CACHE_SECONDS
        ]
        for save_id in stale:
            self._uploaded_requested_replays.pop(save_id, None)

    def _queue_process_snapshot(self, processes: set[tuple[int, str] | tuple[int, str, str | None]], _blacklist_version: str):
        self._schedule_background_task(self._process_local_incidents(self.incident_engine.observe_processes(processes)))

    def _queue_focused_window_snapshot(self, snapshot: dict):
        snapshot = sanitize_window_snapshot(snapshot)
        try:
            incidents = self.incident_engine.observe_focused_window(snapshot)
        except Exception as exc:
            print(f"[FOCUS] Failed to process focused window snapshot: {safe_console_text(exc)}")
            incidents = []
        self._schedule_background_task(self._process_local_incidents(incidents))
        now = self.loop.time()
        if now - self._last_focused_window_server_send < FOCUSED_WINDOW_SERVER_SEND_INTERVAL_SECONDS:
            return
        self._last_focused_window_server_send = now
        self._schedule_background_task(self._send_focused_window_status(snapshot))

    async def _send_focused_window_status(self, snapshot: dict):
        if self.state.disconnected.is_set():
            return
        payload = {
            "source": "focused_window",
            "event_type": "focused_window_status",
            "severity": "info",
            "timestamp": str(snapshot.get("timestamp") or protocol.now_iso()),
            "window": snapshot,
        }
        try:
            await self._send_payload(events.client_monitor_event(payload))
        except Exception as exc:
            print(f"[FOCUS] Failed to send focused window status: {exc}")

    async def _process_local_incidents(self, incidents: list[dict]):
        if not incidents:
            return
        for incident in incidents:
            await self._report_incident(incident)

    async def _flush_incident_buffer(self):
        incident_buffer = getattr(self, "incident_buffer", None)
        if not incident_buffer or incident_buffer.unacked_count() == 0:
            return
        unacked = incident_buffer.get_unacked()
        print(f"[INCIDENT] Flushing {len(unacked)} unacked incident(s) (seq {unacked[0].get('seq')}–{unacked[-1].get('seq')})...")
        for payload in unacked:
            seq = payload.get("seq")
            try:
                await self._send_payload(events.incident_report(payload))
                if seq is not None:
                    incident_buffer.mark_sent(seq)
            except Exception as exc:
                print(f"[INCIDENT] Flush stopped at seq={seq}: {exc} — remaining stay in buffer.")
                break

    async def _report_incident(self, incident: dict):
        incident_payload = dict(incident)
        incident_payload["session_uuid"] = self.session_uuid
        incident_payload["computer_name"] = _computer_name()
        reported_at = protocol.now_iso()
        incident_payload["reported_at"] = reported_at
        incident_payload.setdefault("queued_at", reported_at)

        needs_evidence = bool(incident_payload.get("needs_evidence"))
        if needs_evidence:
            incident_payload["evidence_status"] = "pending"

        incident_buffer = getattr(self, "incident_buffer", None)
        offline = self.state.disconnected.is_set()
        incident_payload["buffered"] = bool(offline)
        if incident_buffer:
            incident_payload = incident_buffer.enqueue(incident_payload)
            if needs_evidence:
                incident_buffer.mark_evidence_pending(incident_payload)

        seq = incident_payload.get("seq")
        if offline:
            incident_id = incident_payload.get("incident_id")
            seq_label = f" seq={seq}" if seq is not None else ""
            print(f"[INCIDENT] Queued {incident_id}{seq_label}: WebSocket disconnected.")
            return

        try:
            await self._send_payload(events.incident_report(incident_payload))
            if incident_buffer and seq is not None:
                incident_buffer.mark_sent(seq)
        except Exception as exc:
            incident_id = incident_payload.get("incident_id")
            seq_label = f" seq={seq}" if seq is not None else ""
            if incident_buffer and seq is not None:
                incident_buffer.mark_buffered(seq, "send_failed")
            print(f"[INCIDENT] Failed to send {incident_id}{seq_label}: {exc} — queued on disk.")
            return

        status = incident_payload.get("status", "")
        rule_name = incident_payload.get("rule_name") or incident_payload.get("rule_id")
        summary = incident_payload.get("summary", "")
        suffix = " (evidence upload pending)" if needs_evidence else ""
        print(f"[INCIDENT] {status} {rule_name}: {summary}{suffix}")
        if needs_evidence:
            self._schedule_background_task(
                self._upload_and_report_incident_evidence(dict(incident_payload))
            )

    async def _flush_pending_evidence(self):
        incident_buffer = getattr(self, "incident_buffer", None)
        if not incident_buffer or self.state.disconnected.is_set():
            return
        if not hasattr(self, "_evidence_uploading"):
            self._evidence_uploading = set()
        pending = incident_buffer.get_pending_evidence()
        if pending:
            print(f"[INCIDENT] Retrying evidence for {len(pending)} pending incident(s).")
        for incident in pending:
            incident_id = str(incident.get("incident_id", "") or "")
            if not incident_id or incident_id in self._evidence_uploading:
                continue
            self._schedule_background_task(
                self._upload_and_report_incident_evidence(dict(incident), retry=True)
            )

    async def _upload_incident_evidence(self, incident: dict) -> str | None:
        process_report_path = self.process_monitor.export_requested_report()
        focused_window_report_path = self.focused_window_monitor.export_current_snapshot()
        hardware_report_path = None
        if str(incident.get("source", "")) == "hardware_monitor":
            hardware_report_path = self.hardware_monitor.export_current_snapshot()

        incident_id = str(incident.get("incident_id", "") or "")
        replay_path = await self._save_replay_with_timeout(
            request_id=f"incident_{incident_id}" if incident_id else None,
            requested_at=str(incident.get("timestamp") or incident.get("reported_at") or protocol.now_iso()),
            source="incident_evidence",
        )
        bundled_replay_path = replay_path
        if replay_path:
            replay_save_id = self._replay_save_id_from_path(replay_path)
            replay_artifact_path = await self._upload_shared_incident_replay(
                replay_path,
                replay_save_id=replay_save_id,
                incident=incident,
            )
            if replay_artifact_path:
                incident["replay_save_id"] = replay_save_id
                incident["replay_artifact_path"] = replay_artifact_path
                incident["replay_artifact_shared"] = True
                bundled_replay_path = None

        bundle_path = build_incident_bundle(
            self.session_uuid,
            incident,
            process_report_path,
            bundled_replay_path,
            hardware_report_path,
            focused_window_report_path,
        )
        try:
            response = await upload_runtime_artifact(
                self.base_url,
                self.session_uuid,
                bundle_path,
                "incident_bundle",
                {
                    "incident_id": incident.get("incident_id"),
                    "rule_id": incident.get("rule_id"),
                    "status": incident.get("status"),
                },
            )
            return response.get("path")
        except Exception as exc:
            print(f"[INCIDENT] Evidence upload failed for {incident.get('incident_id')}: {exc}")
            return None

    @staticmethod
    def _replay_save_id_from_path(replay_path: str) -> str:
        name = os.path.splitext(os.path.basename(str(replay_path)))[0]
        if name.startswith("replay_"):
            return name[len("replay_"):]
        return name or "unknown"

    async def _upload_shared_incident_replay(
        self,
        replay_path: str,
        *,
        replay_save_id: str,
        incident: dict,
    ) -> str | None:
        cached_path = self._uploaded_replay_artifacts.get(replay_save_id)
        if cached_path:
            return cached_path

        task = self._replay_artifact_tasks.get(replay_save_id)
        if task is None:
            task = asyncio.create_task(
                self._upload_replay_artifact_once(
                    replay_path,
                    replay_save_id=replay_save_id,
                    incident=incident,
                )
            )
            self._replay_artifact_tasks[replay_save_id] = task

            def _cleanup(done_task: asyncio.Task, save_id: str = replay_save_id):
                if self._replay_artifact_tasks.get(save_id) is done_task:
                    self._replay_artifact_tasks.pop(save_id, None)

            task.add_done_callback(_cleanup)

        try:
            artifact_path = await asyncio.shield(task)
        except Exception as exc:
            print(
                f"[RECORDER] Shared replay upload failed for {replay_save_id}; "
                f"embedding replay in incident bundle instead: {exc}"
            )
            return None
        if artifact_path:
            self._uploaded_replay_artifacts[replay_save_id] = artifact_path
        return artifact_path

    async def _upload_replay_artifact_once(
        self,
        replay_path: str,
        *,
        replay_save_id: str,
        incident: dict,
    ) -> str | None:
        response = await upload_runtime_artifact(
            self.base_url,
            self.session_uuid,
            replay_path,
            "incident_replay",
            {
                "save_id": replay_save_id,
                "coalesce_window_seconds": REPLAY_SAVE_COALESCE_WINDOW_SECONDS,
                "source": "incident_evidence",
                "incident_id": incident.get("incident_id"),
                "rule_id": incident.get("rule_id"),
            },
        )
        artifact_path = str(response.get("path") or "")
        if artifact_path:
            print(f"[RECORDER] Shared replay {replay_save_id} uploaded to {artifact_path}.")
        return artifact_path or None

    async def _upload_and_report_incident_evidence(self, incident: dict, *, retry: bool = False):
        incident_id = str(incident.get("incident_id", "") or "")
        incident_buffer = getattr(self, "incident_buffer", None)
        if not hasattr(self, "_evidence_uploading"):
            self._evidence_uploading = set()
        if incident_id and incident_id in self._evidence_uploading:
            return
        if incident_buffer:
            incident_buffer.mark_evidence_pending(incident)
        if self.state.disconnected.is_set():
            return

        if incident_id:
            self._evidence_uploading.add(incident_id)
        try:
            async with self._evidence_upload_semaphore:
                if self.state.disconnected.is_set():
                    return
                artifact_path = await self._upload_incident_evidence(incident)
                update_payload = dict(incident)
                update_payload["reported_at"] = protocol.now_iso()
                update_payload["needs_evidence"] = False
                update_payload["buffered"] = bool(retry or update_payload.get("buffered"))
                if artifact_path:
                    update_payload["status"] = "evidence_uploaded"
                    update_payload["evidence_status"] = "uploaded"
                    update_payload["artifact_path"] = artifact_path
                    update_payload["evidence_upload_failed"] = False
                    if retry:
                        update_payload["evidence_retry"] = True
                else:
                    update_payload["status"] = "evidence_failed"
                    update_payload["evidence_status"] = "failed"
                    update_payload["evidence_upload_failed"] = True
                    if not retry:
                        self._schedule_background_task(self._retry_incident_evidence_upload(dict(incident)))

                try:
                    await self._send_payload(events.incident_report(update_payload))
                    if artifact_path:
                        if incident_buffer:
                            incident_buffer.mark_evidence_complete(incident_id, artifact_path)
                        print(f"[INCIDENT] Evidence uploaded for {incident.get('incident_id')}.")
                    elif retry:
                        print(f"[INCIDENT] Evidence retry failed for {incident.get('incident_id')}.")
                    else:
                        print(f"[INCIDENT] Evidence upload failed for {incident.get('incident_id')}; retry scheduled.")
                except Exception as exc:
                    if incident_buffer:
                        incident_buffer.mark_evidence_pending(update_payload)
                    print(f"[INCIDENT] Failed to report evidence status: {exc}")
        finally:
            if incident_id:
                self._evidence_uploading.discard(incident_id)

    async def _save_replay_with_timeout(
        self,
        *,
        request_id: str | None = None,
        requested_at: str | None = None,
        source: str = "client",
    ) -> str | None:
        if not self.recorder:
            return None
        if source == "incident_evidence":
            timeout_seconds = REPLAY_INCIDENT_SAVE_TIMEOUT_SECONDS
            deadline_seconds = REPLAY_INCIDENT_SAVE_DEADLINE_SECONDS
        else:
            timeout_seconds = float(REPLAY_SAVE_TIMEOUT_SECONDS)
            deadline_seconds = float(REPLAY_SAVE_TIMEOUT_SECONDS)
        started_at = self.loop.time()
        try:
            if source == "final_submission":
                self.replay_save_queue.begin_final_submission()
                self._submission_step("Saving recent replay fragments...")
            while True:
                remaining_timeout = max(0.1, timeout_seconds - (self.loop.time() - started_at))
                save_request, future = self.replay_save_queue.enqueue(
                    request_id=request_id,
                    requested_at=requested_at,
                    source=source,
                    deadline_seconds=deadline_seconds,
                )
                if future.done():
                    replay_path = await future
                else:
                    replay_path = await asyncio.wait_for(
                        asyncio.shield(future),
                        timeout=remaining_timeout,
                    )
                if replay_path or source != "incident_evidence":
                    return replay_path
                if getattr(self.replay_save_queue, "_final_submission_mode", False):
                    return None

                elapsed = self.loop.time() - started_at
                if elapsed >= timeout_seconds:
                    return None
                await asyncio.sleep(
                    min(
                        REPLAY_INCIDENT_SAVE_RETRY_DELAY_SECONDS,
                        max(0.0, timeout_seconds - elapsed),
                    )
                )
        except asyncio.TimeoutError:
            request_label = ""
            if "save_request" in locals():
                request_label = f" {save_request.request_id} ({save_request.save_id})"
            print(
                f"[RECORDER] Replay save{request_label} timed out after {timeout_seconds:g}s. "
                "Continuing without replay in this bundle."
            )
            return None

    def _submission_step(self, message: str):
        print(f"[EXAM][STEP] {message}")
        self.gui.ensure_started()
        self.gui.send_upload_step(message)

    async def _retry_incident_evidence_upload(self, incident: dict):
        if self.state.disconnected.is_set():
            return
        await asyncio.sleep(1.0)
        await self._upload_and_report_incident_evidence(incident, retry=True)

    async def handle_kill_process(self, data: dict):
        pid = int(data.get("pid", 0) or 0)
        incident_id = str(data.get("incident_id", "") or "")
        process_name = str(data.get("process_name", "") or "")
        if pid <= 0:
            await self._send_payload(
                events.kill_process_result(
                    pid,
                    incident_id=incident_id,
                    ok=False,
                    process_name=process_name,
                    message="invalid pid",
                )
            )
            return

        ok, message = await self.loop.run_in_executor(None, self._kill_local_process, pid)
        await self._send_payload(
            events.kill_process_result(
                pid,
                incident_id=incident_id,
                ok=ok,
                process_name=process_name,
                message=message,
            )
        )

    def _kill_local_process(self, pid: int) -> tuple[bool, str]:
        try:
            process = psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.Error) as exc:
            return False, str(exc)

        try:
            process.kill()
            process.wait(timeout=3)
            return True, f"terminated pid {pid}"
        except psutil.TimeoutExpired:
            return False, f"timed out waiting for pid {pid} to exit"
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.Error, OSError) as exc:
            return False, str(exc)

    def _print_remaining_time(self, remaining: int):
        last_remaining = self.state.last_printed_remaining
        if last_remaining is None or remaining <= last_remaining - 10:
            self.state.last_printed_remaining = remaining
            print(f"[EXAM] Time remaining: {_time_text(remaining)}")


async def run_ws(
    ws_url: str,
    base_url: str,
    session_uuid: str,
    password: str,
    recorder: ReplayRecorder | None,
    *,
    gui_ui: str = "tk",
    ipc_transport: str = "auto",
    incident_buffer: IncidentBuffer | None = None,
):
    """Connect via WebSocket, handle exam flow and pings."""
    result, runtime = await run_ws_with_runtime(
        ws_url,
        base_url,
        session_uuid,
        password,
        recorder,
        gui_ui=gui_ui,
        ipc_transport=ipc_transport,
        incident_buffer=incident_buffer,
    )
    await runtime.close_runtime()
    return result


async def run_ws_with_runtime(
    ws_url: str,
    base_url: str,
    session_uuid: str,
    password: str,
    recorder: ReplayRecorder | None,
    *,
    gui_ui: str = "tk",
    ipc_transport: str = "auto",
    incident_buffer: IncidentBuffer | None = None,
    runtime: WebSocketSession | None = None,
    exam_files_info: dict | None = None,
) -> tuple[bool, WebSocketSession]:
    """Connect via WebSocket using a persistent per-session runtime."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            if runtime is None:
                runtime = WebSocketSession(
                    ws_url, base_url, session_uuid, password, ws, recorder,
                    gui_ui=gui_ui,
                    ipc_transport=ipc_transport,
                    incident_buffer=incident_buffer,
                )
            else:
                runtime.attach_connection(ws_url, base_url, password, ws)
            if exam_files_info is not None:
                runtime.set_exam_files_info(exam_files_info)
            return await runtime.run(), runtime
