import os
import time
import unittest

from common.ipc_ws import ENV_ROLE, ENV_TOKEN, ENV_TRANSPORT, ENV_URL, ThreadedIpcClient, ThreadedIpcServer


class _TempEnv:
    def __init__(self, values: dict[str, str]):
        self.values = values
        self.previous = {}

    def __enter__(self):
        for key, value in self.values.items():
            self.previous[key] = os.environ.get(key)
            os.environ[key] = value

    def __exit__(self, _exc_type, _exc, _tb):
        for key in self.values:
            previous = self.previous.get(key)
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


def _wait_for(predicate, timeout: float = 2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class LocalIpcIntegrationTests(unittest.TestCase):
    def test_manager_to_cli_command_roundtrip(self):
        received = []
        server = ThreadedIpcServer(role="manager")
        env = server.start()
        try:
            with _TempEnv(env):
                client = ThreadedIpcClient(
                    role="server_cli",
                    on_message=lambda message: received.append(message),
                )
                self.assertTrue(client.start())
                try:
                    self.assertTrue(
                        _wait_for(lambda: server.connected_count == 1)
                    )
                    self.assertTrue(
                        server.send(
                            "manager.console_command",
                            {"command": "/gui"},
                        )
                    )
                    self.assertTrue(_wait_for(lambda: bool(received)))
                    self.assertEqual(received[0]["channel"], "manager.console_command")
                    self.assertEqual(received[0]["data"]["command"], "/gui")
                finally:
                    client.stop()
        finally:
            server.stop()

    def test_dashboard_to_server_command_roundtrip(self):
        received = []
        server = ThreadedIpcServer(
            role="server",
            on_message=lambda message: received.append(message),
        )
        env = server.start()
        try:
            with _TempEnv(env):
                client = ThreadedIpcClient(role="dashboard_gui")
                self.assertTrue(client.start())
                try:
                    self.assertTrue(client.send("dashboard.command", {"cmd": "start_exam_global"}))
                    self.assertTrue(_wait_for(lambda: bool(received)))
                    self.assertEqual(received[0]["channel"], "dashboard.command")
                    self.assertEqual(received[0]["data"]["cmd"], "start_exam_global")
                finally:
                    client.stop()
        finally:
            server.stop()

    def test_timer_to_client_finish_command_roundtrip(self):
        received = []
        server = ThreadedIpcServer(
            role="client",
            on_message=lambda message: received.append(message),
        )
        env = server.start()
        try:
            with _TempEnv(env):
                client = ThreadedIpcClient(role="timer_gui")
                self.assertTrue(client.start())
                try:
                    self.assertTrue(
                        client.send(
                            "timer.command",
                            {"cmd": "finish_exam", "archive_path": "answer.zip"},
                        )
                    )
                    self.assertTrue(_wait_for(lambda: bool(received)))
                    self.assertEqual(received[0]["channel"], "timer.command")
                    self.assertEqual(received[0]["data"]["archive_path"], "answer.zip")
                finally:
                    client.stop()
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
