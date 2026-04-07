#!/usr/bin/env python3

import argparse
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import tkinter as tk
from tkinter import ttk

from client_gui import ExamTimerGUI
from server_gui import ServerGUI


PREVIEW_MODES = {
    "client_waiting": {
        "title": "Client Timer - Waiting",
        "group": "Client",
        "description": "Shows the timer window before the student starts the exam.",
    },
    "client_running": {
        "title": "Client Timer - Running",
        "group": "Client",
        "description": "Shows the running timer with the normal exam controls.",
    },
    "client_paused": {
        "title": "Client Timer - Paused",
        "group": "Client",
        "description": "Shows the timer paused with an administrator message.",
    },
    "client_submission": {
        "title": "Client Submission Window",
        "group": "Client",
        "description": "Shows the finish/upload flow with a preloaded sample file preview.",
    },
    "server_overview": {
        "title": "Server Dashboard - Overview",
        "group": "Server",
        "description": "Shows the main dashboard tab with mock clients and server state.",
    },
    "server_rule_breakings": {
        "title": "Server Dashboard - Rule Breakings",
        "group": "Server",
        "description": "Shows the incident tab with mock violations and admin actions.",
    },
}


def _enable_normal_close(window):
    def close(_event=None):
        try:
            window.destroy()
        except tk.TclError:
            pass
        return "break"

    window.protocol("WM_DELETE_WINDOW", close)
    for sequence in ("<Alt-F4>", "<Command-w>", "<Command-W>", "<Command-q>", "<Command-Q>"):
        try:
            window.bind_all(sequence, close)
        except tk.TclError:
            pass


def _sample_dir() -> Path:
    base_dir = Path(tempfile.mkdtemp(prefix="ui_preview_"))
    text_path = base_dir / "essay_answer.txt"
    text_path.write_text(
        "Exam answer preview\n\n"
        "1. This is a mock submission file used by the UI preview launcher.\n"
        "2. It helps show the native desktop submission dialog safely.\n",
        encoding="utf-8",
    )

    zip_path = base_dir / "submission_bundle.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("answers/main.py", "print('preview bundle')\n")
        archive.writestr("answers/readme.txt", "This is a preview-only archive.\n")
    return base_dir


def _mock_server_payload() -> dict:
    clients = [
        {
            "uuid": "4d7e4b98-54bb-4ad7-a4f0-001122334455",
            "login_id": "alice",
            "status_label": "Running",
            "connection_status": "Connected",
            "exam_state": "Running",
            "session_state": "running",
            "session_state_reason": "Exam in progress.",
            "resume_allowed": True,
            "blocking_incident_id": "",
            "blocking_rule_id": "",
            "exam_started": True,
            "remaining": 3120,
            "time_spent_seconds": 480,
            "extra_time_seconds": 0,
            "banned": False,
            "kick_count": 0,
            "blacklist_catch_count": 1,
            "last_blacklist_match": ["discord.exe"],
            "last_action": "Incident opened: process_blacklist",
            "admin_paused": False,
            "admin_pause_reason": "",
            "paused_remaining_seconds": 0,
            "applied_policy_version": "preview-policy-v2",
            "latest_incident_id": "incident-1001",
            "latest_incident_rule_id": "process_blacklist",
            "latest_incident_severity": "violation",
            "latest_incident_status": "opened",
            "latest_incident_summary": "Blacklisted process detected: discord.exe (pid 4216)",
            "latest_incident_artifact_path": "data/server/artifacts/alice/incident_bundle_1001.zip",
            "ip": "192.168.1.44",
            "computer_name": "LAB-ALICE",
            "short_id": "4d7e4b98",
            "exam_finished": False,
            "submitted_at": "",
            "submission_name": "",
            "submission_path": "",
            "submission_size_bytes": 0,
        },
        {
            "uuid": "6f5c1b32-77aa-46d0-b6b0-8899aabbccdd",
            "login_id": "bob",
            "status_label": "Violation Paused",
            "connection_status": "Connected",
            "exam_state": "Violation Paused",
            "session_state": "violation_paused",
            "session_state_reason": "Focused window out of policy: chrome.exe / ChatGPT",
            "resume_allowed": False,
            "blocking_incident_id": "incident-1002",
            "blocking_rule_id": "focused_window_policy",
            "exam_started": True,
            "remaining": 1980,
            "time_spent_seconds": 1020,
            "extra_time_seconds": 300,
            "banned": False,
            "kick_count": 0,
            "blacklist_catch_count": 0,
            "last_blacklist_match": [],
            "last_action": "Violation paused: focused_window_policy",
            "admin_paused": False,
            "admin_pause_reason": "",
            "paused_remaining_seconds": 1980,
            "applied_policy_version": "preview-policy-v2",
            "latest_incident_id": "incident-1002",
            "latest_incident_rule_id": "focused_window_policy",
            "latest_incident_severity": "violation",
            "latest_incident_status": "opened",
            "latest_incident_summary": "Focused window out of policy: chrome.exe / ChatGPT",
            "latest_incident_artifact_path": "data/server/artifacts/bob/incident_bundle_1002.zip",
            "ip": "192.168.1.45",
            "computer_name": "LAB-BOB",
            "short_id": "6f5c1b32",
            "exam_finished": False,
            "submitted_at": "",
            "submission_name": "",
            "submission_path": "",
            "submission_size_bytes": 0,
        },
    ]

    incidents = [
        {
            "incident_id": "incident-1002",
            "client_id": "6f5c1b32-77aa-46d0-b6b0-8899aabbccdd",
            "login_id": "bob",
            "status": "opened",
            "severity": "violation",
            "rule_id": "focused_window_policy",
            "rule_name": "Focused Window Policy",
            "source": "focused_window",
            "summary": "Focused window out of policy: chrome.exe / ChatGPT",
            "process_name": "chrome.exe",
            "pid": 8820,
            "artifact_path": "data/server/artifacts/bob/incident_bundle_1002.zip",
            "policy_version": "preview-policy-v2",
            "event_at": "2026-04-07T09:35:12+00:00",
            "active": True,
            "kill_available": True,
            "session_state": "violation_paused",
            "resume_allowed": False,
            "blocking": True,
            "details": {
                "incident_id": "incident-1002",
                "rule_id": "focused_window_policy",
                "severity": "violation",
                "status": "opened",
                "summary": "Focused window out of policy: chrome.exe / ChatGPT",
                "window_title": "ChatGPT - Google Chrome",
            },
        },
        {
            "incident_id": "incident-1001",
            "client_id": "4d7e4b98-54bb-4ad7-a4f0-001122334455",
            "login_id": "alice",
            "status": "resolved",
            "severity": "violation",
            "rule_id": "process_blacklist",
            "rule_name": "Process Blacklist",
            "source": "process_monitor",
            "summary": "Process no longer detected: discord.exe",
            "process_name": "discord.exe",
            "pid": 4216,
            "artifact_path": "data/server/artifacts/alice/incident_bundle_1001.zip",
            "policy_version": "preview-policy-v2",
            "event_at": "2026-04-07T09:20:01+00:00",
            "active": False,
            "kill_available": True,
            "session_state": "running",
            "resume_allowed": True,
            "blocking": False,
            "details": {
                "incident_id": "incident-1001",
                "rule_id": "process_blacklist",
                "severity": "violation",
                "status": "resolved",
                "summary": "Process no longer detected: discord.exe",
            },
        },
    ]

    server_info = {
        "server_id": "default",
        "host": "192.168.1.10",
        "port": 8080,
        "broadcast_interval": 1,
        "announce_interval": 3,
        "exam_duration_minutes": 60,
        "exam_phase": "running",
        "exam_start_enabled": True,
        "has_exam_files": True,
        "exam_files_path": "data/server/exam/exam_bundle.zip",
        "process_blacklist_count": 7,
        "process_blacklist_file": "data/server/process_blacklist.txt",
        "process_blacklist_version": "preview-blacklist-v4",
        "policy_file": "data/server/exam_policy.json",
        "policy_version": "preview-policy-v2",
        "operator_defaults": {
            "confirm_kill_pid": True,
            "confirm_kick": True,
            "confirm_ban": True,
            "confirm_pause": True,
        },
        "remember_settings": True,
        "incident_count": len(incidents),
        "active_incident_count": 1,
    }
    return {"type": "state_update", "server": server_info, "clients": clients, "incidents": incidents}


def _launch_client_preview(mode: str):
    root = tk.Tk()
    app = ExamTimerGUI(root)
    _enable_normal_close(root)
    root.attributes("-topmost", False)
    root.title(f"{PREVIEW_MODES[mode]['title']} - Preview")

    if mode == "client_running":
        app.set_remaining(47 * 60 + 18)
    elif mode == "client_paused":
        app.pause_timer(33 * 60 + 4, "Paused by administrator for preview.")
    elif mode == "client_submission":
        app.prompt_finish_from_server("Preview mode: upload window opened with a sample file.")

        def load_preview():
            sample_dir = _sample_dir()
            preview_file = sample_dir / "submission_bundle.zip"
            window = app.submission_window
            if not window or not window.winfo_exists():
                return
            _enable_normal_close(window)
            window.selected_file = str(preview_file)
            window.path_var.set(str(preview_file))
            window._load_preview(str(preview_file))

        root.after(200, load_preview)

    root.mainloop()


def _launch_server_preview(mode: str):
    app = ServerGUI()
    _enable_normal_close(app)
    app.title(f"{PREVIEW_MODES[mode]['title']} - Preview")
    payload = _mock_server_payload()
    app.process_state_update(payload)
    app.log_message(
        "6f5c1b32-77aa-46d0-b6b0-8899aabbccdd",
        "[INCIDENT] focused_window_policy: ChatGPT detected in preview mode",
    )
    app.log_message(
        "4d7e4b98-54bb-4ad7-a4f0-001122334455",
        "[POLICY] preview-policy-v2 applied",
    )
    if mode == "server_rule_breakings":
        app.notebook.select(app.rules_tab)
    app.mainloop()


def _launch_mode(mode: str):
    if mode.startswith("client_"):
        _launch_client_preview(mode)
        return
    if mode.startswith("server_"):
        _launch_server_preview(mode)
        return
    raise ValueError(f"Unknown preview mode: {mode}")


class PreviewLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("UI Preview Launcher")
        self.geometry("760x420")
        self._build()

    def _build(self):
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            outer,
            text="Desktop UI Preview Launcher",
        ).pack(anchor=tk.W)
        ttk.Label(
            outer,
            text="Choose a screen and open it in a separate preview window.",
        ).pack(anchor=tk.W, pady=(2, 10))

        body = ttk.Frame(outer)
        body.pack(fill=tk.BOTH, expand=True)

        left = ttk.LabelFrame(body, text="Available Previews")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        columns = ("group", "title")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("group", text="Area")
        self.tree.heading("title", text="Preview")
        self.tree.column("group", width=90, anchor=tk.CENTER)
        self.tree.column("title", width=320, anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        for mode, meta in PREVIEW_MODES.items():
            self.tree.insert("", tk.END, iid=mode, values=(meta["group"], meta["title"]))

        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_description())
        self.tree.bind("<Double-1>", lambda _event: self.open_selected())

        right = ttk.LabelFrame(body, text="Description")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.description = tk.Text(right, wrap=tk.WORD, state=tk.DISABLED, height=12)
        self.description.configure(
            relief=tk.SUNKEN,
            borderwidth=1,
            highlightthickness=0,
            padx=6,
            pady=6,
        )
        self.description.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        actions = ttk.Frame(outer, padding=(0, 10, 0, 0))
        actions.pack(fill=tk.X)
        ttk.Button(actions, text="Open Selected Preview", command=self.open_selected).pack(side=tk.LEFT)
        ttk.Button(actions, text="Quit", command=self.destroy).pack(side=tk.RIGHT)

        first = next(iter(PREVIEW_MODES))
        self.tree.selection_set(first)
        self._update_description()

    def _selected_mode(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def _update_description(self):
        mode = self._selected_mode()
        text = PREVIEW_MODES.get(mode, {}).get("description", "Select a preview.")
        self.description.config(state=tk.NORMAL)
        self.description.delete("1.0", tk.END)
        self.description.insert(tk.END, text)
        self.description.config(state=tk.DISABLED)

    def open_selected(self):
        mode = self._selected_mode()
        if not mode:
            return
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--mode", mode])


def main():
    parser = argparse.ArgumentParser(description="Preview the desktop GUIs with mock data.")
    parser.add_argument("--mode", choices=sorted(PREVIEW_MODES), help="Open a specific preview directly.")
    args = parser.parse_args()

    if args.mode:
        _launch_mode(args.mode)
        return

    launcher = PreviewLauncher()
    launcher.mainloop()


if __name__ == "__main__":
    main()
