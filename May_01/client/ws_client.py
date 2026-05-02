import asyncio
import json
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from threading import Thread

import aiohttp
import psutil

from common import events, protocol, security
from .exam_state import ExamStateLogger
from .incidents import ClientIncidentEngine
from .submission import validate_submission_file
from .transfers import (
    build_incident_bundle,
    build_submission_bundle,
    upload_runtime_artifact,
    upload_submission_bundle,
)
from custommodules.focused_window_monitor import FocusedWindowMonitor
from custommodules.hardware_monitor import HardwareMonitor
from custommodules.process_monitor import ProcessMonitor
from custommodules.replay_recorder import ReplayRecorder

REPLAY_SAVE_TIMEOUT_SECONDS = 45
SUBMISSION_UPLOAD_TIMEOUT_SECONDS = 900
FOCUSED_WINDOW_CHECK_INTERVAL_SECONDS = 1.0
FOCUSED_WINDOW_FULL_INFO_INTERVAL_CHECKS = 60
FOCUSED_WINDOW_SERVER_SEND_INTERVAL_SECONDS = 5.0


def _run_in_background(loop: asyncio.AbstractEventLoop, callback, *args):
    loop.call_soon_threadsafe(callback, *args)


def _client_gui_path() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(script_dir), "client_gui.py")


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
) -> tuple[object | None, bool]:
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
            _run_in_background(self.loop, self.queue.put_nowait, UserCommand("stdin", line))


@dataclass
class UserCommand:
    action: str
    value: str = ""


class ClientGUIBridge:
    def __init__(self, loop: asyncio.AbstractEventLoop, input_queue: asyncio.Queue):
        self.loop = loop
        self.input_queue = input_queue
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

    def close(self):
        process = self.process
        self.process = None
        if process and process.poll() is None:
            process.kill()

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

        command = payload.get("cmd")
        if command == "start_exam":
            print("[GUI] Start button pressed.")
            return UserCommand("start")
        if command == "finish_exam":
            selected_file = str(payload.get("archive_path", "")).strip()
            if not selected_file:
                return None
            print(f"[GUI] Finish button pressed with file: {selected_file}")
            return UserCommand("finish", selected_file)
        return None

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
        self.stdin = StdinBridge(self.loop)
        self.gui = ClientGUIBridge(self.loop, self.stdin.queue)
        self.exam_state_logger = ExamStateLogger(self.output_dir)
        self.incident_engine = ClientIncidentEngine()
        self._background_tasks: set[asyncio.Task] = set()
        self.process_monitor = self._create_process_monitor()
        self.hardware_monitor = self._create_hardware_monitor()
        self._last_focused_window_server_send = 0.0
        self.focused_window_monitor = self._create_focused_window_monitor()
        self._record_timer_transition(timer_state="idle", source="client", reason="session_initialized")

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

    def _stop_runtime_monitors(self):
        self.process_monitor.stop()
        self.hardware_monitor.stop()
        self.focused_window_monitor.stop()

    def _schedule_background_task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
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
        listener_task = asyncio.create_task(self.listener())
        try:
            await self.sender()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            listener_task.cancel()
            self.gui.close()
            self._stop_runtime_monitors()
            for task in list(self._background_tasks):
                task.cancel()

        if self.state.disconnected.is_set() and not self.state.intentional_shutdown:
            raise ConnectionError("Server disconnected")
        return self.state.intentional_shutdown

    async def prompt_start_exam(self):
        print("\n--- PRE-EXAM PREPARATION ---")
        print("When you are ready, type 'start' or click the button in the GUI.")
        print("If the server has not started the exam yet, you will be asked to try again.")

        while not self.state.start_event.is_set():
            command, event_triggered = await _wait_for_queue_or_event(
                self.stdin.queue,
                self.state.start_event,
            )
            if event_triggered:
                break

            if not isinstance(command, UserCommand):
                continue

            if command.action == "start":
                await self.request_exam_start()
                continue

            if command.action == "stdin":
                text = command.value.strip().lower()
                if text in {"start", "/start"}:
                    await self.request_exam_start()
                    continue

            print("Type 'start' or use the GUI when you are ready.")

        if self.state.submission_only:
            print("[EXAM] Submission is required. Use the finish window to upload your file.\n")
            return

        print("[EXAM] Started. Good luck!\n")

    async def request_exam_start(self):
        if self.state.start_request_pending:
            print("[EXAM] Start request already in progress...")
            return

        self.state.start_request_pending = True
        await self._send_payload(events.start_exam())
        print("[EXAM] Start request sent...")

    async def sender(self):
        await self.prompt_start_exam()
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
            await self._send_payload(events.client_info(_computer_name()))
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
            self.handle_sync_time(data)
            return

        if event == events.SESSION_STATE:
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
            if self.recorder:
                replay_path = await self.loop.run_in_executor(None, self.recorder.save_replay)
                if replay_path:
                    await self._upload_runtime_artifact(
                        replay_path,
                        artifact_kind="requested_replay",
                        metadata={"source": "server_request"},
                    )
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
            replay_path = await self._save_replay_with_timeout()

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
    ):
        try:
            response = await upload_runtime_artifact(
                self.base_url,
                self.session_uuid,
                artifact_path,
                artifact_kind,
                metadata,
            )
            print(f"[UPLOAD] {artifact_kind} uploaded to {response.get('path', 'server storage')}")
        except Exception as exc:
            print(f"[UPLOAD] Failed to upload {artifact_kind}: {exc}")

    def _queue_process_snapshot(self, processes: set[tuple[int, str] | tuple[int, str, str | None]], _blacklist_version: str):
        self._schedule_background_task(self._process_local_incidents(self.incident_engine.observe_processes(processes)))

    def _queue_focused_window_snapshot(self, snapshot: dict):
        self._schedule_background_task(self._process_local_incidents(self.incident_engine.observe_focused_window(snapshot)))
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
        if not incidents or self.state.disconnected.is_set():
            return
        for incident in incidents:
            await self._report_incident(incident)

    async def _report_incident(self, incident: dict):
        incident_payload = dict(incident)
        incident_payload["session_uuid"] = self.session_uuid
        incident_payload["computer_name"] = _computer_name()
        incident_payload["reported_at"] = protocol.now_iso()

        upload_failed = False
        if incident_payload.get("needs_evidence"):
            artifact_path = await self._upload_incident_evidence(incident_payload)
            if artifact_path:
                incident_payload["artifact_path"] = artifact_path
            else:
                upload_failed = True
                incident_payload["evidence_upload_failed"] = True
                self._schedule_background_task(self._retry_incident_evidence_upload(dict(incident_payload)))

        try:
            await self._send_payload(events.incident_report(incident_payload))
        except Exception as exc:
            print(f"[INCIDENT] Failed to send incident {incident_payload.get('incident_id')}: {exc}")
            return

        status = incident_payload.get("status", "")
        rule_name = incident_payload.get("rule_name") or incident_payload.get("rule_id")
        summary = incident_payload.get("summary", "")
        suffix = " (evidence upload pending)" if upload_failed else ""
        print(f"[INCIDENT] {status} {rule_name}: {summary}{suffix}")

    async def _upload_incident_evidence(self, incident: dict) -> str | None:
        process_report_path = self.process_monitor.export_requested_report()
        focused_window_report_path = self.focused_window_monitor.export_current_snapshot()
        hardware_report_path = None
        if str(incident.get("source", "")) == "hardware_monitor":
            hardware_report_path = self.hardware_monitor.export_current_snapshot()

        replay_path = await self._save_replay_with_timeout()

        bundle_path = build_incident_bundle(
            self.session_uuid,
            incident,
            process_report_path,
            replay_path,
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

    async def _save_replay_with_timeout(self) -> str | None:
        if not self.recorder:
            return None
        try:
            self._submission_step("Saving current 60-second replay snapshot...")
            return await asyncio.wait_for(
                self.loop.run_in_executor(None, self.recorder.save_replay),
                timeout=REPLAY_SAVE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            print(
                f"[RECORDER] Replay save timed out after {REPLAY_SAVE_TIMEOUT_SECONDS}s. "
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
        artifact_path = await self._upload_incident_evidence(incident)
        if not artifact_path:
            return

        retry_payload = dict(incident)
        retry_payload["artifact_path"] = artifact_path
        retry_payload["evidence_retry"] = True
        retry_payload["evidence_upload_failed"] = False
        retry_payload["reported_at"] = protocol.now_iso()
        try:
            await self._send_payload(events.incident_report(retry_payload))
            print(f"[INCIDENT] Evidence retry succeeded for {incident.get('incident_id')}.")
        except Exception as exc:
            print(f"[INCIDENT] Failed to report retried evidence upload: {exc}")

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
):
    """Connect via WebSocket, handle exam flow and pings."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            return await WebSocketSession(ws_url, base_url, session_uuid, password, ws, recorder).run()
