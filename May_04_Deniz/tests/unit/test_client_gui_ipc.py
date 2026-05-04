import asyncio
import json
import unittest

from client.ui.exam_qt import _parse_ipc_line as qt_parse_ipc_line
from client.ui.exam_tk import _parse_ipc_line as tk_parse_ipc_line
from client.ws_client import ClientGUIBridge


class _ImmediateLoop:
    def call_soon_threadsafe(self, callback, *args):
        callback(*args)


class _FakeProcess:
    def poll(self):
        return None


class _FakeIPC:
    def __init__(self):
        self.messages = []
        self.closed = False

    def send_text_nowait(self, text: str) -> bool:
        self.messages.append(text)
        return True

    def close(self):
        self.closed = True


class ClientGUIIPCTests(unittest.TestCase):
    def _bridge(self) -> tuple[ClientGUIBridge, asyncio.Queue, _FakeIPC]:
        queue = asyncio.Queue()
        bridge = ClientGUIBridge(_ImmediateLoop(), queue, ui="tk")
        fake_ipc = _FakeIPC()
        bridge.process = _FakeProcess()
        bridge.ipc = fake_ipc
        return bridge, queue, fake_ipc

    def test_send_methods_preserve_legacy_timer_frames(self):
        bridge, _queue, fake_ipc = self._bridge()

        bridge.send_sync(42)
        bridge.send_pause(30, "Paused")
        bridge.send_resume(25, "Resumed")
        bridge.send_end()
        bridge.send_reset()
        bridge.send_error("Nope")
        bridge.send_open_finish("Upload now")
        bridge.send_upload_success("Done")
        bridge.send_upload_error("Failed")
        bridge.send_upload_step("Step 1")

        self.assertEqual(fake_ipc.messages[0], "SYNC:42\n")
        pause_payload = json.loads(fake_ipc.messages[1].removeprefix("PAUSE:"))
        self.assertEqual(pause_payload["remaining_seconds"], 30)
        self.assertEqual(fake_ipc.messages[3], "END:-1\n")
        self.assertEqual(fake_ipc.messages[4], "RESET:1\n")
        self.assertEqual(fake_ipc.messages[-1], "UPLOAD_STEP:Step 1\n")

    def test_gui_json_commands_still_become_user_commands(self):
        bridge, queue, _fake_ipc = self._bridge()

        bridge._handle_ipc_text(json.dumps({"cmd": "start_exam"}))
        start_command = queue.get_nowait()
        self.assertEqual(start_command.action, "start")

        bridge._handle_ipc_text(json.dumps({"cmd": "finish_exam", "archive_path": "answer.zip"}))
        finish_command = queue.get_nowait()
        self.assertEqual(finish_command.action, "finish")
        self.assertEqual(finish_command.value, "answer.zip")

    def test_tk_and_qt_timer_parsers_accept_existing_frames(self):
        self.assertEqual(tk_parse_ipc_line("SYNC:12"), ("SYNC", "12"))
        self.assertEqual(qt_parse_ipc_line("UPLOAD_ERROR:bad file"), ("UPLOAD_ERROR", "bad file"))


if __name__ == "__main__":
    unittest.main()
