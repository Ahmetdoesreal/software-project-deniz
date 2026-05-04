import json
import os

from common import protocol


class ExamStateLogger:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.log_file = os.path.join(self.output_dir, "exam_state.jsonl")
        self._last_entry: tuple[str, int, str, str] | None = None

    def record(self, *, remaining_seconds: int, timer_state: str, source: str, reason: str = ""):
        entry_key = (timer_state, int(remaining_seconds), source, reason)
        if self._last_entry == entry_key:
            return

        payload = {
            "timestamp": protocol.now_iso(),
            "remaining_seconds": int(remaining_seconds),
            "timer_state": timer_state,
            "source": source,
        }
        if reason:
            payload["reason"] = reason

        try:
            with open(self.log_file, "a", encoding="utf-8") as log_handle:
                log_handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
            self._last_entry = entry_key
        except Exception as exc:
            print(f"[EXAM] Failed to write exam state log: {exc}")
