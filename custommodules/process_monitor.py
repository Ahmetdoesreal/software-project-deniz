import asyncio
import json
import psutil
import time
import os
import shared

class ProcessMonitor:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.log_file = os.path.join(self.output_dir, "processes.jsonl")
        
        # Keep track of processes as a set of tuples: (pid, name)
        self.previous_procs = set()
        self.active = False
        self._task = None
        
        # State refs injected by the client
        self.current_remaining_time = 0

    def start(self):
        """Start the background process monitoring."""
        if self._task is None:
            self.active = True
            self.previous_procs = self._get_current_processes()
            self._task = asyncio.create_task(self._loop())
            print(f"[PROCESS] Monitor started. Logging to {self.log_file}")

    def stop(self):
        """Stop tracking."""
        self.active = False
        if self._task:
            self._task.cancel()
            self._task = None
            print("[PROCESS] Monitor stopped.")

    def update_time(self, remaining_seconds: int):
        """Hook called by the client when it receives a SYNC_TIME."""
        self.current_remaining_time = remaining_seconds

    def _get_current_processes(self):
        """Returns a set of (pid, name) tuples."""
        procs = set()
        for p in psutil.process_iter(['pid', 'name']):
            try:
                # Need to handle potential access denied or zombied processes
                pid = p.info['pid']
                name = p.info['name']
                if name: # filter out entirely missing names
                    procs.add((pid, name))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        return procs

    def trigger_full_report(self):
        """Immediately generates and saves a full list of processes."""
        if not self.active: return
        
        current_procs = self._get_current_processes()
        payload = {
            "timestamp": shared.now_iso(),
            "remaining_time": self.current_remaining_time,
            "type": "full_list_manual",
            "processes": [[pid, name] for pid, name in current_procs]
        }
        self._write_log(payload)
        print(f"[PROCESS] Wrote manual full process report to {self.log_file}")

    def _write_log(self, payload: dict):
        try:
            with open(self.log_file, "a") as f:
                f.write(json.dumps(payload) + "\n")
        except Exception as e:
            print(f"[PROCESS] Failed to write log: {e}")

    async def _loop(self):
        # 120 / 15 = 8 intervals per full list
        tick_count = 0 
        
        try:
            while self.active:
                await asyncio.sleep(15)
                tick_count += 1
                
                current_procs = self._get_current_processes()
                
                # Check for 2 minute interval (Tick 8)
                if tick_count >= 8:
                    payload = {
                        "timestamp": shared.now_iso(),
                        "remaining_time": self.current_remaining_time,
                        "type": "full_list",
                        "processes": [[pid, name] for pid, name in current_procs]
                    }
                    self._write_log(payload)
                    tick_count = 0
                else:
                    # Calculate Diffs (15s intervals)
                    added = current_procs - self.previous_procs
                    removed = self.previous_procs - current_procs
                    
                    if added or removed:
                        payload = {
                            "timestamp": shared.now_iso(),
                            "remaining_time": self.current_remaining_time,
                            "type": "diff",
                            "added": [[pid, name] for pid, name in added],
                            "removed": [[pid, name] for pid, name in removed]
                        }
                        self._write_log(payload)

                # Move forward
                self.previous_procs = current_procs
                
        except asyncio.CancelledError:
            pass
