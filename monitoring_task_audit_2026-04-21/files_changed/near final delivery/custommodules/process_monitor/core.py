import asyncio
import argparse
import json
import os
import platform
import sys
from collections.abc import Callable
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common import protocol
from common.process_users import current_process_usernames, normalize_process_username

try:
    from .psutil_collector import get_processes_via_psutil
except ImportError:
    from psutil_collector import get_processes_via_psutil


FULL_SNAPSHOT_INTERVAL_SECONDS = 120
DIFF_INTERVAL_SECONDS = 15
ProcessEntry = tuple[int, str] | tuple[int, str, str | None]


class ProcessMonitor:
    def __init__(
        self,
        output_dir: str,
        *,
        catch_callback: Callable[[list[dict], str], None] | None = None,
        poll_callback: Callable[[set[ProcessEntry], str], None] | None = None,
    ):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.log_file = os.path.join(self.output_dir, "processes.jsonl")
        self.previous_procs = set()
        self.active = False
        self._task = None
        self.current_remaining_time = 0
        self.catch_callback = catch_callback
        self.poll_callback = poll_callback
        self.blacklist_entries: list[str] = []
        self.blacklist_names: set[str] = set()
        self.blacklist_usernames: set[str] = current_process_usernames()
        self.blacklist_version = "0"
        self.reported_matches: set[tuple[int, str, str | None]] = set()

    def start(self):
        """Start the background process monitoring."""
        if self._task is not None:
            return

        self.active = True
        self.previous_procs = self._get_current_processes()
        self._task = asyncio.create_task(self._loop())
        print(f"[PROCESS] Monitor started. Logging to {self.log_file}")

    def stop(self):
        """Stop tracking."""
        self.active = False
        if not self._task:
            return

        self._task.cancel()
        self._task = None
        print("[PROCESS] Monitor stopped.")

    def update_time(self, remaining_seconds: int):
        """Hook called by the client when it receives a SYNC_TIME."""
        self.current_remaining_time = remaining_seconds

    def set_blacklist(
        self,
        entries: list[str],
        version: str = "0",
        usernames: list[str] | tuple[str, ...] | set[str] | None = None,
    ):
        self.blacklist_entries = list(entries)
        self.blacklist_names = {entry.strip().lower() for entry in entries if entry.strip()}
        self.blacklist_usernames = current_process_usernames(usernames)
        self.blacklist_version = str(version or "0")
        self.reported_matches.clear()
        print(
            f"[PROCESS] Applied blacklist version {self.blacklist_version} "
            f"with {len(self.blacklist_entries)} entrie(s) for "
            f"{len(self.blacklist_usernames)} monitored user(s)."
        )

    def trigger_full_report(self):
        """Immediately generate and save a full list of processes."""
        self.export_requested_report()

    def export_requested_report(self) -> str | None:
        current_procs = self._get_current_processes()
        payload = self._build_full_list_payload("requested", current_procs)
        self._write_log(payload)

        report_path = self._requested_report_path()
        if not self._write_report_file(report_path, payload):
            return None

        print(f"[PROCESS] Wrote requested full process report to {report_path}")
        self.previous_procs = current_procs
        return report_path

    def append_state_marker(self, *, timer_state: str, source: str, reason: str = ""):
        payload = self._build_base_payload("exam_state_marker")
        payload["remaining_seconds"] = self.current_remaining_time
        payload["timer_state"] = timer_state
        payload["source"] = source
        if reason:
            payload["reason"] = reason
        self._write_log(payload)

    def _get_current_processes(self) -> set[ProcessEntry]:
        return get_processes_via_psutil()

    def _build_base_payload(self, entry_type: str) -> dict:
        return {
            "timestamp": protocol.now_iso(),
            "remaining_time": self.current_remaining_time,
            "type": entry_type,
            "event_type": entry_type,
            "severity": "info",
            "platform": platform.system().lower(),
        }

    def _build_full_list_payload(
        self,
        entry_type: str,
        processes: set[ProcessEntry],
    ) -> dict:
        payload = self._build_base_payload(entry_type)
        payload["processes"] = [list(proc) for proc in sorted(processes)]
        return payload

    def _build_diff_payload(
        self,
        added: set[ProcessEntry],
        removed: set[ProcessEntry],
    ) -> dict:
        payload = self._build_base_payload("diff")
        payload["added"] = [list(proc) for proc in sorted(added)]
        payload["removed"] = [list(proc) for proc in sorted(removed)]
        return payload

    def _write_log(self, payload: dict):
        try:
            with open(self.log_file, "a") as f:
                f.write(json.dumps(payload) + "\n")
        except Exception as e:
            print(f"[PROCESS] Failed to write log: {e}")

    def _write_report_file(self, report_path: str, payload: dict) -> bool:
        try:
            with open(report_path, "w") as report_file:
                json.dump(payload, report_file, indent=2)
            return True
        except Exception as e:
            print(f"[PROCESS] Failed to write requested report: {e}")
            return False

    def _requested_report_path(self) -> str:
        timestamp = protocol.now_iso().replace(":", "-")
        return os.path.join(self.output_dir, f"process_report_requested_{timestamp}.json")

    def _detect_blacklist_matches(self, processes: set[ProcessEntry]) -> list[dict]:
        if not self.blacklist_names:
            self.reported_matches.clear()
            return []

        current_matches = set()
        for process in processes:
            pid, name, username = _process_parts(process)
            normalized_name = _normalize_process_name(name)
            if normalized_name not in self.blacklist_names:
                continue
            normalized_username = normalize_process_username(username)
            if normalized_username and normalized_username not in self.blacklist_usernames:
                continue
            current_matches.add((pid, name, username))

        new_matches = current_matches - self.reported_matches
        self.reported_matches = current_matches
        return [
            {
                "pid": pid,
                "name": name,
                "username": username,
            }
            for pid, name, username in sorted(new_matches, key=lambda item: (item[1].lower(), item[0]))
        ]

    def _report_blacklist_matches(self, matches: list[dict]):
        if not matches:
            return
        print(f"[PROCESS] Blacklist catch detected: {', '.join(match['name'] for match in matches)}")
        if self.catch_callback:
            self.catch_callback(matches, self.blacklist_version)

    async def _loop(self):
        ticks_per_full_snapshot = FULL_SNAPSHOT_INTERVAL_SECONDS // DIFF_INTERVAL_SECONDS
        tick_count = 0

        try:
            while self.active:
                await asyncio.sleep(DIFF_INTERVAL_SECONDS)
                tick_count += 1
                current_procs = self._get_current_processes()
                if self.poll_callback:
                    self.poll_callback(current_procs, self.blacklist_version)
                self._report_blacklist_matches(self._detect_blacklist_matches(current_procs))

                if tick_count >= ticks_per_full_snapshot:
                    self._write_log(
                        self._build_full_list_payload("full_list", current_procs)
                    )
                    tick_count = 0
                else:
                    added = current_procs - self.previous_procs
                    removed = self.previous_procs - current_procs
                    if added or removed:
                        self._write_log(self._build_diff_payload(added, removed))

                self.previous_procs = current_procs
        except asyncio.CancelledError:
            pass


def _normalize_process_name(name: str) -> str:
    base_name = os.path.basename(str(name or "").strip())
    return base_name.lower()


def _process_parts(process: ProcessEntry) -> tuple[int, str, str | None]:
    pid = int(process[0])
    name = str(process[1])
    username = str(process[2]) if len(process) > 2 and process[2] else None
    return pid, name, username


def _print_processes(processes: set[ProcessEntry], limit: int) -> None:
    for process in sorted(processes, key=lambda item: (str(item[1]).lower(), int(item[0])))[:limit]:
        pid, name, username = _process_parts(process)
        print(f"{pid}\t{name}\t{username or ''}")
    print(f"[PROCESS] listed {min(len(processes), limit)} of {len(processes)} process(es)")


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test process collection and blacklist matching without starting the full client."
    )
    parser.add_argument("--output-dir", default="data/client/process_monitor_standalone")
    parser.add_argument("--limit", type=int, default=25, help="Maximum number of processes to print.")
    parser.add_argument(
        "--blacklist",
        action="append",
        default=[],
        help="Process name to match. Can be passed more than once.",
    )
    parser.add_argument(
        "--user",
        action="append",
        default=[],
        help="Extra process owner to monitor. Can be passed more than once.",
    )
    args = parser.parse_args()

    monitor = ProcessMonitor(args.output_dir)
    processes = monitor._get_current_processes()
    _print_processes(processes, max(0, args.limit))

    if args.blacklist:
        monitor.set_blacklist(args.blacklist, version="standalone", usernames=args.user)
        matches = monitor._detect_blacklist_matches(processes)
        print(json.dumps({"matches": matches}, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
