import asyncio
import json
import os
import platform
from collections.abc import Callable

from common import protocol

from .windows import get_focused_window_for_windows


CHECK_INTERVAL_SECONDS = 1.0


class FocusedWindowMonitor:
    def __init__(
        self,
        output_dir: str,
        *,
        interval_seconds: float = CHECK_INTERVAL_SECONDS,
        emit_on_change_only: bool = True,
        snapshot_callback: Callable[[dict], None] | None = None,
    ):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.log_file = os.path.join(self.output_dir, "focused_window.jsonl")
        self.interval_seconds = interval_seconds
        self.emit_on_change_only = emit_on_change_only
        self.snapshot_callback = snapshot_callback
        self.active = False
        self._task = None
        self._previous_snapshot = None

    def start(self):
        if self._task is not None:
            return

        self.active = True
        self._ensure_log_file()
        initial_snapshot = self._current_snapshot()
        self._previous_snapshot = initial_snapshot
        self._write_log(self._snapshot_entry("focused_window_initial", initial_snapshot))
        if self.snapshot_callback:
            self.snapshot_callback(initial_snapshot)
        self._task = asyncio.create_task(self._loop())
        print(f"[FOCUS] Monitor started. Logging to {self.log_file}")

    def stop(self):
        self.active = False
        if not self._task:
            return

        self._task.cancel()
        self._task = None
        print("[FOCUS] Monitor stopped.")

    def export_current_snapshot(self) -> str | None:
        snapshot = self._current_snapshot()
        report_path = self._snapshot_report_path()
        payload = self._snapshot_entry("focused_window_snapshot", snapshot)
        try:
            with open(report_path, "w", encoding="utf-8") as report_file:
                json.dump(payload, report_file, indent=2)
        except Exception as exc:
            print(f"[FOCUS] Failed to write focused window snapshot: {exc}")
            return None

        print(f"[FOCUS] Wrote current focused window snapshot to {report_path}")
        self._previous_snapshot = snapshot
        return report_path

    def append_state_marker(
        self,
        *,
        remaining_seconds: int,
        timer_state: str,
        source: str,
        reason: str = "",
    ):
        payload = {
            "timestamp": protocol.now_iso(),
            "type": "exam_state_marker",
            "remaining_seconds": remaining_seconds,
            "timer_state": timer_state,
            "source": source,
        }
        if reason:
            payload["reason"] = reason
        self._write_log(payload)

    def _current_snapshot(self) -> dict:
        if platform.system() == "Windows":
            return get_focused_window_for_windows()
        return {
            "platform": platform.system().lower(),
            "available": False,
            "reason": "unsupported_platform",
            "source": "focused_window_monitor",
        }

    def _snapshot_entry(self, entry_type: str, snapshot: dict) -> dict:
        return {
            "timestamp": protocol.now_iso(),
            "type": entry_type,
            "window": snapshot,
        }

    def _change_entry(self, previous_snapshot: dict, current_snapshot: dict) -> dict:
        return {
            "timestamp": protocol.now_iso(),
            "type": "focused_window_change",
            "previous": previous_snapshot,
            "current": current_snapshot,
        }

    def _ensure_log_file(self):
        try:
            with open(self.log_file, "a", encoding="utf-8"):
                pass
        except Exception as exc:
            print(f"[FOCUS] Failed to initialize focused window log: {exc}")

    def _write_log(self, payload: dict):
        try:
            with open(self.log_file, "a", encoding="utf-8") as log_handle:
                log_handle.write(json.dumps(payload) + "\n")
        except Exception as exc:
            print(f"[FOCUS] Failed to write focused window log: {exc}")

    def _snapshot_report_path(self) -> str:
        timestamp = protocol.now_iso().replace(":", "-")
        return os.path.join(self.output_dir, f"focused_window_snapshot_{timestamp}.json")

    async def _loop(self):
        try:
            while self.active:
                await asyncio.sleep(self.interval_seconds)
                current_snapshot = self._current_snapshot()
                if self.snapshot_callback:
                    self.snapshot_callback(current_snapshot)

                if self.emit_on_change_only:
                    if current_snapshot == self._previous_snapshot:
                        continue
                    self._write_log(self._change_entry(self._previous_snapshot, current_snapshot))
                else:
                    self._write_log(self._snapshot_entry("focused_window_poll", current_snapshot))

                self._previous_snapshot = current_snapshot
        except asyncio.CancelledError:
            pass
