import asyncio
import json
import os
import platform
import subprocess
from collections.abc import Callable

from common import protocol

SYSTEM = platform.system()
CHECK_INTERVAL_SECONDS = 5.0


class IdleMonitor:
    def __init__(
        self,
        output_dir: str,
        *,
        interval_seconds: float = CHECK_INTERVAL_SECONDS,
        snapshot_callback: Callable[[dict], None] | None = None,
    ):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.log_file = os.path.join(self.output_dir, "idle_monitor.jsonl")
        self.interval_seconds = interval_seconds
        self.snapshot_callback = snapshot_callback
        self.active = False
        self._task = None

    def start(self):
        if self._task is not None:
            return
        self.active = True
        self._ensure_log_file()
        self._task = asyncio.create_task(self._loop())
        print(f"[IDLE] Monitor started. Logging to {self.log_file}")

    def stop(self):
        self.active = False
        if not self._task:
            return
        self._task.cancel()
        self._task = None
        print("[IDLE] Monitor stopped.")

    def append_state_marker(self, *, timer_state: str, source: str, reason: str = "", **kwargs):
        payload = {
            "timestamp": protocol.now_iso(),
            "type": "exam_state_marker",
            "timer_state": timer_state,
            "source": source,
        }
        if reason:
            payload["reason"] = reason
        self._write_log(payload)

    def get_idle_seconds(self) -> float:
        try:
            if SYSTEM == "Windows":
                from .windows import get_idle_seconds
                return get_idle_seconds()
            if SYSTEM == "Linux":
                return self._linux_idle_seconds()
        except Exception:
            pass
        return -1.0

    def _linux_idle_seconds(self) -> float:
        out = subprocess.check_output(
            ["xprintidle"], stderr=subprocess.DEVNULL, timeout=2
        )
        return int(out.strip()) / 1000.0

    def _ensure_log_file(self):
        try:
            with open(self.log_file, "a", encoding="utf-8"):
                pass
        except Exception as exc:
            print(f"[IDLE] Failed to initialize log: {exc}")

    def _write_log(self, payload: dict):
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload) + "\n")
        except Exception as exc:
            print(f"[IDLE] Failed to write log: {exc}")

    async def _loop(self):
        try:
            while self.active:
                await asyncio.sleep(self.interval_seconds)
                idle_seconds = self.get_idle_seconds()
                timestamp = protocol.now_iso()
                snapshot = {
                    "idle_seconds": idle_seconds,
                    "timestamp": timestamp,
                    "event_type": "idle_poll",
                    "severity": "info",
                }
                self._write_log(snapshot)
                if self.snapshot_callback and idle_seconds >= 0:
                    self.snapshot_callback(snapshot)
        except asyncio.CancelledError:
            pass
