import asyncio
import io
import json
import unittest
from unittest.mock import patch

from common import events, protocol
from server.state import state
from server.tasks import (
    _dispatch_gui_request,
    _exam_state,
    _handle_finish_exam_global,
    _queue_stdin_line,
    _sync_running_exams,
    _write_to_gui,
)


class _ImmediateLoop:
    def call_soon_threadsafe(self, callback, *args):
        callback(*args)


class _BrokenStdin:
    def __iter__(self):
        return self

    def __next__(self):
        raise OSError(5, "Input/output error")


class _FakeWS:
    def __init__(self):
        self.messages = []

    async def send_str(self, payload: str):
        self.messages.append(protocol.decode(payload))


class _FakeProcess:
    def poll(self):
        return None


class _FakeGUIIPC:
    closed = False

    def __init__(self):
        self.messages = []

    def send_text_nowait(self, text: str) -> bool:
        self.messages.append(text)
        return True


class ServerTaskTests(unittest.TestCase):
    def _drain_queue(self, queue: asyncio.Queue) -> list[object]:
        items = []
        while True:
            try:
                items.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                return items

    def test_queue_stdin_line_reads_all_lines_then_sends_sentinel(self):
        queue = asyncio.Queue()

        with patch("sys.stdin", io.StringIO("/help\n/exam\n")):
            _queue_stdin_line(_ImmediateLoop(), queue)

        self.assertEqual(self._drain_queue(queue), ["/help\n", "/exam\n", None])

    def test_queue_stdin_line_handles_input_output_error(self):
        queue = asyncio.Queue()

        with patch("sys.stdin", _BrokenStdin()), patch("builtins.print") as mock_print:
            _queue_stdin_line(_ImmediateLoop(), queue)

        self.assertEqual(self._drain_queue(queue), [None])
        self.assertTrue(mock_print.called)
        self.assertIn("Console input unavailable", mock_print.call_args.args[0])

    def test_exam_state_reports_admin_paused(self):
        user = {
            "exam_started": True,
            "exam_finished": False,
            "admin_paused": True,
        }
        self.assertEqual(_exam_state(user, 120), "Admin Paused")

    def test_exam_state_reports_violation_paused(self):
        user = {
            "session_state": "violation_paused",
            "exam_started": True,
            "exam_finished": False,
        }
        self.assertEqual(_exam_state(user, 120), "Violation Paused")

    def test_write_to_gui_sends_existing_json_payload_over_ipc(self):
        original_process = state.gui_process
        original_ipc = state.gui_ipc
        fake_ipc = _FakeGUIIPC()
        try:
            state.gui_process = _FakeProcess()
            state.gui_ipc = fake_ipc

            _write_to_gui({"type": "state_update", "clients": []})

            self.assertEqual(json.loads(fake_ipc.messages[0]), {"type": "state_update", "clients": []})
        finally:
            state.gui_process = original_process
            state.gui_ipc = original_ipc

    def test_dispatch_gui_console_command_uses_existing_command_json(self):
        app = {}
        loop = object()
        calls = []

        def fake_handle(command, target_app):
            calls.append((command, target_app))
            return "coroutine"

        with patch("server.tasks.handle_admin_command", new=fake_handle), patch("asyncio.run_coroutine_threadsafe") as run_mock:
            _dispatch_gui_request(loop, app, {"type": "console_command", "command": "/help"})

        self.assertEqual(calls, [("/help", app)])
        run_mock.assert_called_once_with("coroutine", loop)


class ServerTaskAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_running_exams_keeps_admin_paused_user_frozen(self):
        original_users = state.users_db
        original_clients = state.clients
        paused_ws = _FakeWS()
        try:
            state.users_db = {
                "alice": {
                    "uuid": "client-1",
                    "exam_started": True,
                    "exam_finished": False,
                    "time_spent_seconds": 15,
                    "extra_time_seconds": 0,
                    "admin_paused": True,
                    "admin_pause_reason": "Paused by admin.",
                    "paused_remaining_seconds": 42,
                }
            }
            state.clients = {
                "client-1": {
                    "ws": paused_ws,
                    "short_id": "client-1",
                    "ip": "127.0.0.1",
                }
            }

            dead = await _sync_running_exams({"exam_duration": 10}, {"client-1": "alice"}, 5.0)

            self.assertEqual(dead, [])
            self.assertEqual(state.users_db["alice"]["time_spent_seconds"], 15)
            self.assertEqual(len(paused_ws.messages), 1)
            event, data = paused_ws.messages[0]
            self.assertEqual(event, events.SYNC_TIME)
            self.assertEqual(data["remaining_seconds"], 42)
            self.assertEqual(data["timer_state"], "paused")
            self.assertEqual(data["pause_source"], "admin")
        finally:
            state.users_db = original_users
            state.clients = original_clients

    async def test_finish_exam_global_moves_waiting_user_to_awaiting_submission(self):
        original_users = state.users_db
        original_clients = state.clients
        ws = _FakeWS()
        app = {
            "exam_phase": "running",
            "exam_start_enabled": True,
            "exam_duration": 30,
        }
        try:
            state.users_db = {
                "alice": {
                    "uuid": "client-1",
                    "password": "secret1",
                    "exam_started": False,
                    "exam_finished": False,
                    "time_spent_seconds": 0,
                    "extra_time_seconds": 0,
                }
            }
            state.ensure_user_defaults(state.users_db["alice"])
            state.clients = {
                "client-1": {
                    "ws": ws,
                    "short_id": "client-1",
                    "ip": "127.0.0.1",
                    "security": None,
                }
            }

            await _handle_finish_exam_global(app)

            user = state.users_db["alice"]
            self.assertEqual(app["exam_phase"], "finished")
            self.assertFalse(app["exam_start_enabled"])
            self.assertEqual(user["session_state"], "awaiting_submission")
            self.assertTrue(user["exam_started"])
            self.assertTrue(user["exam_finished"])
            sent_events = [event for event, _ in ws.messages]
            self.assertIn(events.SESSION_STATE, sent_events)
            self.assertIn(events.FINISH_EXAM, sent_events)
        finally:
            state.users_db = original_users
            state.clients = original_clients


if __name__ == "__main__":
    unittest.main()
