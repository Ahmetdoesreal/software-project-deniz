import asyncio
import json
import os
import platform
from collections.abc import Callable

from common import protocol

from .windows import get_focused_window_for_windows


# Focused window monitor configuration.
CHECK_INTERVAL_SECONDS = 1.0
FULL_INFO_INTERVAL_CHECKS = 60


class FocusedWindowMonitor:
    def __init__(
        self,
        output_dir: str,
        *,
        interval_seconds: float = CHECK_INTERVAL_SECONDS,
        full_info_interval_checks: int = FULL_INFO_INTERVAL_CHECKS,
        emit_on_change_only: bool = True,
        snapshot_callback: Callable[[dict], None] | None = None,
    ):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.log_file = os.path.join(self.output_dir, "focused_window.jsonl")
        self.snapshot_file = os.path.join(self.output_dir, "focused_window_snapshot.json")
        self.interval_seconds = interval_seconds
        self.full_info_interval_checks = max(1, int(full_info_interval_checks or 1))
        self.emit_on_change_only = emit_on_change_only
        self.snapshot_callback = snapshot_callback
        self.active = False
        self._task = None
        self._previous_snapshot = None
        self._check_count = 0

    def start(self):
        if self._task is not None:
            return

        self.active = True
        self._ensure_log_file()
        initial_snapshot = self._current_snapshot()
        self._check_count = 0
        self._previous_snapshot = initial_snapshot
        timestamp = protocol.now_iso()
        self._write_log(self._snapshot_entry("focused_window_initial", initial_snapshot, timestamp, severity="info"))
        self._write_full_snapshot(initial_snapshot, timestamp)
        if self.snapshot_callback:
            self.snapshot_callback(self._snapshot_for_callback(initial_snapshot, timestamp))
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
        timestamp = protocol.now_iso()
        report_path = self._write_full_snapshot(snapshot, timestamp)
        if not report_path:
            return None

        self._write_log(
            self._snapshot_entry(
                "focused_window_snapshot",
                snapshot,
                timestamp,
                severity="info",
            )
        )
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

    def _snapshot_entry(self, entry_type: str, snapshot: dict, timestamp: str, *, severity: str = "info") -> dict:
        return {
            "timestamp": timestamp,
            "type": entry_type,
            "event_type": entry_type,
            "severity": severity,
            "window": snapshot,
        }

    def _change_entry(self, previous_snapshot: dict, current_snapshot: dict, timestamp: str) -> dict:
        return {
            "timestamp": timestamp,
            "type": "focused_window_change",
            "event_type": "focused_window_change",
            "severity": "info",
            "previous": previous_snapshot,
            "current": current_snapshot,
        }

    def _snapshot_for_callback(self, snapshot: dict, timestamp: str) -> dict:
        payload = dict(snapshot)
        payload["timestamp"] = timestamp
        payload["event_type"] = "focused_window_poll"
        payload["severity"] = "info"
        return payload

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

    def _write_full_snapshot(self, snapshot: dict, timestamp: str) -> str | None:
        payload = self._snapshot_entry("focused_window_snapshot", snapshot, timestamp, severity="info")
        try:
            with open(self.snapshot_file, "w", encoding="utf-8") as report_file:
                json.dump(payload, report_file, indent=2)
            return self.snapshot_file
        except Exception as exc:
            print(f"[FOCUS] Failed to write focused window snapshot: {exc}")
            return None

    async def _loop(self):
        try:
            while self.active:
                await asyncio.sleep(self.interval_seconds)
                self._check_count += 1
                current_snapshot = self._current_snapshot()
                timestamp = protocol.now_iso()
                if self.snapshot_callback:
                    self.snapshot_callback(self._snapshot_for_callback(current_snapshot, timestamp))

                if self.emit_on_change_only:
                    if current_snapshot == self._previous_snapshot:
                        if self._check_count % self.full_info_interval_checks == 0:
                            snapshot_path = self._write_full_snapshot(current_snapshot, timestamp)
                            if snapshot_path:
                                self._write_log(
                                    {
                                        "timestamp": timestamp,
                                        "type": "focused_window_full_snapshot",
                                        "event_type": "focused_window_full_snapshot",
                                        "severity": "info",
                                        "snapshot_path": snapshot_path,
                                        "window": current_snapshot,
                                    }
                                )
                        continue
                    self._write_log(self._change_entry(self._previous_snapshot, current_snapshot, timestamp))
                else:
                    self._write_log(
                        self._snapshot_entry(
                            "focused_window_poll",
                            current_snapshot,
                            timestamp,
                            severity="info",
                        )
                    )

                if self._check_count % self.full_info_interval_checks == 0:
                    snapshot_path = self._write_full_snapshot(current_snapshot, timestamp)
                    if snapshot_path:
                        self._write_log(
                            {
                                "timestamp": timestamp,
                                "type": "focused_window_full_snapshot",
                                "event_type": "focused_window_full_snapshot",
                                "severity": "info",
                                "snapshot_path": snapshot_path,
                                "window": current_snapshot,
                            }
                        )

                self._previous_snapshot = current_snapshot
        except asyncio.CancelledError:
            pass
