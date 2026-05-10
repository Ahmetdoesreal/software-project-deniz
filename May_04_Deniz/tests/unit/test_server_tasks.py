import asyncio
import io
import unittest
from unittest.mock import patch

from common import events, protocol
from server.state import state
from server.tasks import (
    _exam_state,
    _handle_finish_exam_global,
    _queue_stdin_line,
    _safe_close_message,
    _sync_running_exams,
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

    def test_safe_close_message_keeps_short_reason(self):
        encoded = _safe_close_message("kicked by server")
        self.assertEqual(encoded, b"kicked by server")

    def test_safe_close_message_truncates_long_reason(self):
        long_reason = "x" * 500
        encoded = _safe_close_message(long_reason)
        self.assertLessEqual(len(encoded), 120)
        self.assertTrue(encoded.startswith(b"x"))

    def test_safe_close_message_preserves_utf8_boundary(self):
        reason = "\u015f" * 80
        encoded = _safe_close_message(reason)
        self.assertLessEqual(len(encoded), 120)
        self.assertTrue(encoded.decode("utf-8"))


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

    async def test_finish_exam_global_skips_banned_user(self):
        original_users = state.users_db
        original_clients = state.clients
        app = {
            "exam_phase": "running",
            "exam_start_enabled": True,
            "exam_duration": 30,
        }
        try:
            state.users_db = {
                "bob": {
                    "uuid": "client-banned",
                    "exam_started": True,
                    "exam_finished": False,
                    "time_spent_seconds": 5,
                    "extra_time_seconds": 0,
                    "session_state": "banned",
                    "banned": True,
                }
            }
            state.ensure_user_defaults(state.users_db["bob"])
            state.clients = {}

            await _handle_finish_exam_global(app)

            user = state.users_db["bob"]
            self.assertEqual(user["session_state"], "banned")
            self.assertTrue(user["banned"])
            self.assertNotEqual(user["session_state"], "awaiting_submission")
            self.assertEqual(app["exam_phase"], "finished")
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
