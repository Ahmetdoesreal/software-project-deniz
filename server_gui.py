import json
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from threading import Thread
from tkinter import filedialog, messagebox, ttk

from common.manager_support import install_close_guard
from common.runtime_logging import setup_runtime_logging


def _format_bytes(size_bytes: int) -> str:
    size = float(max(0, size_bytes))
    units = ["B", "KB", "MB", "GB"]
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.1f} {units[unit_index]}"


def _format_remaining(seconds: int) -> str:
    minutes, remaining_seconds = divmod(int(max(0, seconds)), 60)
    return f"{minutes:02d}:{remaining_seconds:02d}"


def _detail_lines(client_id: str, data: dict) -> list[str]:
    time_spent = int(data.get("time_spent_seconds", 0))
    extra_time = int(data.get("extra_time_seconds", 0))
    minutes_spent, seconds_spent = divmod(time_spent, 60)
    extra_minutes, extra_seconds = divmod(extra_time, 60)
    return [
        f"Login ID: {data.get('login_id', 'Unknown')}",
        f"UUID: {client_id}",
        f"Computer Name: {data.get('computer_name') or '-'}",
        f"Short ID: {data.get('short_id') or '-'}",
        f"Connection: {data.get('connection_status', 'Unknown')}",
        f"Exam State: {data.get('exam_state', 'Unknown')}",
        f"Banned: {'Yes' if data.get('banned') else 'No'}",
        f"Admin Paused: {'Yes' if data.get('admin_paused') else 'No'}",
        f"Pause Reason: {data.get('admin_pause_reason') or '-'}",
        f"Remaining: {_format_remaining(data.get('remaining', 0))}",
        f"Time Spent: {minutes_spent:02d}:{seconds_spent:02d}",
        f"Extra Time: {extra_minutes:02d}:{extra_seconds:02d}",
        f"Kick Count: {data.get('kick_count', 0)}",
        f"Blacklist Catches: {data.get('blacklist_catch_count', 0)}",
        f"Last Blacklist Match: {', '.join(data.get('last_blacklist_match', [])) or '-'}",
        f"Latest Incident Rule: {data.get('latest_incident_rule_id') or '-'}",
        f"Latest Incident Severity: {data.get('latest_incident_severity') or '-'}",
        f"Latest Incident Status: {data.get('latest_incident_status') or '-'}",
        f"Latest Incident Summary: {data.get('latest_incident_summary') or '-'}",
        f"Latest Incident Artifact: {data.get('latest_incident_artifact_path') or '-'}",
        f"Applied Policy Version: {data.get('applied_policy_version') or '-'}",
        f"Last Action: {data.get('last_action') or '-'}",
        f"IP Address: {data.get('ip') or '-'}",
        f"Submission: {data.get('submission_name') or '-'}",
        f"Submission Size: {_format_bytes(int(data.get('submission_size_bytes', 0)))}",
        f"Submitted At: {data.get('submitted_at') or '-'}",
        f"Submission Path: {data.get('submission_path') or '-'}",
    ]


def _incident_detail_lines(incident: dict) -> list[str]:
    return [
        f"Incident ID: {incident.get('incident_id') or '-'}",
        f"User: {incident.get('login_id') or '-'}",
        f"Client ID: {incident.get('client_id') or '-'}",
        f"Severity: {incident.get('severity') or '-'}",
        f"Status: {incident.get('status') or '-'}",
        f"Rule: {incident.get('rule_name') or incident.get('rule_id') or '-'}",
        f"Source: {incident.get('source') or '-'}",
        f"Process: {incident.get('process_name') or '-'}",
        f"PID: {incident.get('pid') or '-'}",
        f"Active: {'Yes' if incident.get('active') else 'No'}",
        f"Session State: {incident.get('session_state') or '-'}",
        f"Reconnect Allowed: {'Yes' if incident.get('resume_allowed') else 'No'}",
        f"Blocking Incident: {'Yes' if incident.get('blocking') else 'No'}",
        f"Policy Version: {incident.get('policy_version') or '-'}",
        f"Artifact: {incident.get('artifact_path') or '-'}",
        f"Event At: {incident.get('event_at') or '-'}",
        "",
        f"Summary: {incident.get('summary') or '-'}",
        "",
        "Raw Details:",
        json.dumps(incident.get("details", {}), indent=2),
    ]


class ServerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.clients_data: dict[str, dict] = {}
        self.tree_items: dict[str, str] = {}
        self.incidents_data: list[dict] = []
        self.incident_items: dict[str, str] = {}
        self.server_info: dict = {}
        self.open_windows = {}
        self.remember_settings_var = tk.BooleanVar(value=True)

        self.title("Server Monitor Dashboard")
        self.geometry("1200x760")
        install_close_guard(self, self.on_close_request, bind_all=True)

        self._build_layout()
        self.after(1000, self.update_timers)

    def _build_layout(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))

        self.overview_tab = ttk.Frame(self.notebook)
        self.rules_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.overview_tab, text="Overview")
        self.notebook.add(self.rules_tab, text="Rule Breakings")

        self._build_overview_tab()
        self._build_rule_breakings_tab()
        self._build_command_bar()
        self._build_stats_bar()

    def _build_overview_tab(self):
        content = ttk.Frame(self.overview_tab)
        content.pack(fill=tk.BOTH, expand=True)

        left_panel = ttk.Frame(content)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_server_info_panel(left_panel)
        self._build_client_tree_area(left_panel)
        self._build_log_area(left_panel)
        self._build_action_panel(content)

    def _build_server_info_panel(self, parent):
        info_frame = ttk.LabelFrame(parent, text="Server Info")
        info_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 10))

        action_frame = ttk.Frame(info_frame, padding=(8, 8, 8, 0))
        action_frame.pack(fill=tk.X)

        self.start_exam_button = ttk.Button(
            action_frame,
            text="Start Exam",
            command=self.start_exam_globally,
        )
        self.start_exam_button.pack(side=tk.LEFT)

        self.finish_exam_button = ttk.Button(
            action_frame,
            text="Finish Exam",
            command=self.finish_exam_globally,
        )
        self.finish_exam_button.pack(side=tk.LEFT, padx=(8, 0))

        blacklist_frame = ttk.Frame(info_frame, padding=(8, 6, 8, 0))
        blacklist_frame.pack(fill=tk.X)

        self.edit_blacklist_button = ttk.Button(
            blacklist_frame,
            text="Edit Blacklist",
            command=self.edit_blacklist,
        )
        self.edit_blacklist_button.pack(side=tk.LEFT)

        self.apply_blacklist_button = ttk.Button(
            blacklist_frame,
            text="Apply Blacklist",
            command=self.apply_blacklist,
        )
        self.apply_blacklist_button.pack(side=tk.LEFT, padx=(8, 0))

        self.edit_policy_button = ttk.Button(
            blacklist_frame,
            text="Edit Policy",
            command=self.edit_policy,
        )
        self.edit_policy_button.pack(side=tk.LEFT, padx=(8, 0))

        self.apply_policy_button = ttk.Button(
            blacklist_frame,
            text="Apply Policy",
            command=self.apply_policy,
        )
        self.apply_policy_button.pack(side=tk.LEFT, padx=(8, 0))

        self.export_settings_button = ttk.Button(
            blacklist_frame,
            text="Export Settings",
            command=self.export_settings,
        )
        self.export_settings_button.pack(side=tk.LEFT, padx=(8, 0))

        self.import_settings_button = ttk.Button(
            blacklist_frame,
            text="Import Settings",
            command=self.import_settings,
        )
        self.import_settings_button.pack(side=tk.LEFT, padx=(8, 0))

        remember_toggle = ttk.Checkbutton(
            info_frame,
            text="Remember Settings",
            variable=self.remember_settings_var,
            command=self.toggle_remember_settings,
        )
        remember_toggle.pack(anchor=tk.W, padx=8, pady=(4, 0))

        self.server_info_var = tk.StringVar(value="Waiting for server state...")
        info_label = ttk.Label(
            info_frame,
            textvariable=self.server_info_var,
            justify=tk.LEFT,
            padding=8,
        )
        info_label.pack(fill=tk.X)

    def _build_client_tree_area(self, parent):
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        columns = ("login_id", "status", "remaining", "uuid")
        self.tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("login_id", text="Login ID", anchor=tk.W)
        self.tree.heading("status", text="Status", anchor=tk.CENTER)
        self.tree.heading("remaining", text="Remaining Time", anchor=tk.CENTER)
        self.tree.heading("uuid", text="UUID", anchor=tk.W)

        self.tree.column("login_id", width=150)
        self.tree.column("status", width=120, anchor=tk.CENTER)
        self.tree.column("remaining", width=120, anchor=tk.CENTER)
        self.tree.column("uuid", width=320)

        y_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=y_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        y_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_log_area(self, parent):
        log_frame = ttk.LabelFrame(parent, text="Live Client Message Log")
        log_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, pady=(10, 0))

        self.log_text = tk.Text(log_frame, height=7, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.configure(
            relief=tk.SUNKEN,
            borderwidth=1,
            highlightthickness=0,
            padx=6,
            pady=6,
            font="TkFixedFont",
        )
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_action_panel(self, parent):
        action_frame = ttk.LabelFrame(parent, text="Selected User")
        action_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))

        ttk.Button(action_frame, text="Show Info", command=self.show_info).pack(fill=tk.X, padx=10, pady=(10, 5))
        ttk.Button(action_frame, text="Options", command=self.show_options).pack(fill=tk.X, padx=10, pady=(5, 10))

    def _build_rule_breakings_tab(self):
        container = ttk.Frame(self.rules_tab, padding=10)
        container.pack(fill=tk.BOTH, expand=True)

        left = ttk.LabelFrame(container, text="Actions")
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        self.kill_pid_button = ttk.Button(left, text="Kill PID", command=self.kill_selected_pid, state=tk.DISABLED)
        self.kill_pid_button.pack(fill=tk.X, padx=10, pady=(10, 6))

        self.kick_user_button = ttk.Button(left, text="Kick User", command=self.kick_selected_user, state=tk.DISABLED)
        self.kick_user_button.pack(fill=tk.X, padx=10, pady=6)

        self.ban_user_button = ttk.Button(left, text="Ban User", command=self.ban_selected_user, state=tk.DISABLED)
        self.ban_user_button.pack(fill=tk.X, padx=10, pady=6)

        self.pause_exam_button = ttk.Button(left, text="Pause Exam", command=self.pause_selected_exam, state=tk.DISABLED)
        self.pause_exam_button.pack(fill=tk.X, padx=10, pady=6)

        self.resume_exam_button = ttk.Button(left, text="Resume Exam", command=self.resume_selected_exam, state=tk.DISABLED)
        self.resume_exam_button.pack(fill=tk.X, padx=10, pady=6)

        self.forgive_violation_button = ttk.Button(
            left,
            text="Forgive Violation",
            command=self.forgive_selected_violation,
            state=tk.DISABLED,
        )
        self.forgive_violation_button.pack(fill=tk.X, padx=10, pady=6)

        middle = ttk.Frame(container)
        middle.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tree_frame = ttk.LabelFrame(middle, text="Incident History")
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("incident_id", "time", "user", "severity", "rule", "source", "process", "pid", "status")
        self.incident_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self.incident_tree.heading("incident_id", text="Incident ID")
        self.incident_tree.heading("time", text="Time")
        self.incident_tree.heading("user", text="User")
        self.incident_tree.heading("severity", text="Severity")
        self.incident_tree.heading("rule", text="Rule")
        self.incident_tree.heading("source", text="Source")
        self.incident_tree.heading("process", text="Process")
        self.incident_tree.heading("pid", text="PID")
        self.incident_tree.heading("status", text="Status")
        self.incident_tree.column("incident_id", width=0, stretch=False)
        self.incident_tree.column("time", width=150)
        self.incident_tree.column("user", width=110)
        self.incident_tree.column("severity", width=90, anchor=tk.CENTER)
        self.incident_tree.column("rule", width=150)
        self.incident_tree.column("source", width=110)
        self.incident_tree.column("process", width=140)
        self.incident_tree.column("pid", width=80, anchor=tk.CENTER)
        self.incident_tree.column("status", width=100, anchor=tk.CENTER)
        self.incident_tree.bind("<<TreeviewSelect>>", lambda _event: self._update_incident_detail())

        incident_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.incident_tree.yview)
        self.incident_tree.configure(yscrollcommand=incident_scroll.set)

        self.incident_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        incident_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        detail_frame = ttk.LabelFrame(middle, text="Incident Details")
        detail_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self.incident_detail = tk.Text(detail_frame, wrap=tk.WORD, height=14, state=tk.DISABLED)
        self.incident_detail.configure(
            relief=tk.SUNKEN,
            borderwidth=1,
            highlightthickness=0,
            padx=6,
            pady=6,
            font="TkFixedFont",
        )
        detail_scroll = ttk.Scrollbar(detail_frame, orient=tk.VERTICAL, command=self.incident_detail.yview)
        self.incident_detail.configure(yscrollcommand=detail_scroll.set)

        self.incident_detail.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        detail_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_command_bar(self):
        cmd_frame = ttk.Frame(self, padding=5)
        cmd_frame.pack(side=tk.BOTTOM, fill=tk.X)

        ttk.Label(cmd_frame, text="Admin Command:").pack(side=tk.LEFT, padx=5)
        self.cmd_entry = ttk.Entry(cmd_frame)
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.cmd_entry.bind("<Return>", lambda _: self.send_console_command())

        ttk.Button(cmd_frame, text="Execute", command=self.send_console_command).pack(
            side=tk.RIGHT,
            padx=5,
        )

    def _build_stats_bar(self):
        self.stats_var = tk.StringVar(value="Connections Managed: 0 | Active: 0 | Disconnected: 0 | Active Incidents: 0")
        stats_label = ttk.Label(self, textvariable=self.stats_var, relief=tk.SUNKEN, padding=5)
        stats_label.pack(side=tk.BOTTOM, fill=tk.X)

    def _selected_client_id(self):
        selected = self.tree.selection()
        if not selected:
            return None
        values = self.tree.item(selected[0], "values")
        return values[3] if values else None

    def _selected_client_data(self):
        client_id = self._selected_client_id()
        if not client_id:
            return None, None
        return client_id, self.clients_data.get(client_id)

    def _selected_incident(self):
        selected = self.incident_tree.selection()
        if not selected:
            return None
        item_id = selected[0]
        incident_id = self.incident_tree.item(item_id, "values")[0]
        for incident in self.incidents_data:
            if incident.get("incident_id") == incident_id:
                return incident
        return None

    def update_timers(self):
        for client_id, data in self.clients_data.items():
            if data.get("exam_state") != "Running":
                continue
            if data.get("remaining", 0) <= 0:
                continue
            data["remaining"] -= 1
            self._upsert_tree_item(client_id, data)

        self.after(1000, self.update_timers)

    def show_info(self):
        client_id, data = self._selected_client_data()
        if not client_id:
            messagebox.showinfo("Info", "Select a client first.")
            return

        window_key = ("info", client_id)
        if self._focus_existing_window(window_key):
            return

        self._open_detail_window(
            window_key=window_key,
            title=f"Info: {data.get('login_id', 'Unknown')}",
            lines=_detail_lines(client_id, data or {}),
        )

    def show_options(self):
        client_id, data = self._selected_client_data()
        if not client_id:
            messagebox.showinfo("Options", "Select a client first.")
            return
        data = data or {}

        window_key = ("options", client_id)
        if self._focus_existing_window(window_key):
            return

        top = tk.Toplevel(self)
        top.title(f"Options: {data.get('login_id', 'Unknown')}")
        top.geometry("340x420")
        self._register_window(window_key, top)

        frame = ttk.Frame(top, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="User Actions:").pack(anchor=tk.W, pady=(0, 10))
        ttk.Button(
            frame,
            text="Kick Client",
            command=lambda: self._send_window_command(top, "kick", client_id),
            state=tk.NORMAL if data.get("connection_status") == "Connected" else tk.DISABLED,
        ).pack(fill=tk.X, pady=5)
        ttk.Button(
            frame,
            text="Ban User",
            command=lambda: self._send_window_command(top, "ban", client_id),
        ).pack(fill=tk.X, pady=5)
        ttk.Button(
            frame,
            text="Pause Exam",
            command=lambda: self._send_window_command(top, "pause_exam", client_id),
        ).pack(fill=tk.X, pady=5)
        ttk.Button(
            frame,
            text="Resume Exam",
            command=lambda: self._send_window_command(top, "resume_exam", client_id),
        ).pack(fill=tk.X, pady=5)
        ttk.Button(
            frame,
            text="Unban User",
            command=lambda: self._send_window_command(top, "unban", client_id),
        ).pack(fill=tk.X, pady=5)

        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        ttk.Label(frame, text="Connected Client Commands:").pack(anchor=tk.W, pady=4)
        ttk.Button(
            frame,
            text="Request Save Screen",
            command=lambda: self._send_client_command(top, "savescreen", client_id),
            state=tk.NORMAL if data.get("connection_status") == "Connected" else tk.DISABLED,
        ).pack(fill=tk.X, pady=5)
        ttk.Button(
            frame,
            text="Request Process Report",
            command=lambda: self._send_client_command(top, "get_processes", client_id),
            state=tk.NORMAL if data.get("connection_status") == "Connected" else tk.DISABLED,
        ).pack(fill=tk.X, pady=5)

        add_time_frame = ttk.Frame(frame, padding=(0, 10, 0, 0))
        add_time_frame.pack(fill=tk.X)

        ttk.Label(add_time_frame, text="Add Minutes:").pack(side=tk.LEFT)
        minutes_entry = ttk.Entry(add_time_frame, width=8)
        minutes_entry.pack(side=tk.LEFT, padx=8)
        ttk.Button(
            add_time_frame,
            text="Apply",
            command=lambda: self._send_add_time(top, client_id, minutes_entry.get()),
        ).pack(side=tk.LEFT)

    def kill_selected_pid(self):
        incident = self._selected_incident()
        if not incident:
            return
        pid = int(incident.get("pid", 0) or 0)
        if pid <= 0:
            messagebox.showinfo("Kill PID", "The selected incident has no process id.")
            return
        user = incident.get("login_id") or "Unknown"
        process_name = incident.get("process_name") or "Unknown"
        if self._confirm_action(
            "confirm_kill_pid",
            "Kill PID",
            f"Kill process for user {user}?\n\nProcess: {process_name}\nPID: {pid}",
        ) is False:
            return

        print(
            json.dumps(
                {
                    "cmd": "kill_pid",
                    "uuid": incident.get("client_id"),
                    "incident_id": incident.get("incident_id"),
                    "process_name": process_name,
                    "pid": pid,
                }
            ),
            flush=True,
        )
        self._append_log(f"[ADMIN] Requested PID kill for {user}: {process_name} ({pid})")

    def kick_selected_user(self):
        incident = self._selected_incident()
        if not incident:
            return
        if self._confirm_action(
            "confirm_kick",
            "Kick User",
            f"Disconnect user {incident.get('login_id') or incident.get('client_id')}?",
        ) is False:
            return
        self._emit_incident_user_command("kick", incident)

    def ban_selected_user(self):
        incident = self._selected_incident()
        if not incident:
            return
        if self._confirm_action(
            "confirm_ban",
            "Ban User",
            f"Ban user {incident.get('login_id') or incident.get('client_id')}?",
        ) is False:
            return
        self._emit_incident_user_command("ban", incident)

    def pause_selected_exam(self):
        incident = self._selected_incident()
        if not incident:
            return
        if self._confirm_action(
            "confirm_pause",
            "Pause Exam",
            f"Pause exam for {incident.get('login_id') or incident.get('client_id')}?",
        ) is False:
            return
        self._emit_incident_user_command("pause_exam", incident)

    def resume_selected_exam(self):
        incident = self._selected_incident()
        if not incident:
            return
        self._emit_incident_user_command("resume_exam", incident)

    def forgive_selected_violation(self):
        incident = self._selected_incident()
        if not incident:
            return
        if not messagebox.askyesno(
            "Forgive Violation",
            f"Forgive blocking violation for {incident.get('login_id') or incident.get('client_id')}?",
        ):
            return
        self._emit_incident_user_command("forgive_violation", incident)

    def _emit_incident_user_command(self, command: str, incident: dict):
        print(
            json.dumps(
                {
                    "cmd": command,
                    "uuid": incident.get("client_id"),
                    "incident_id": incident.get("incident_id"),
                }
            ),
            flush=True,
        )
        self._append_log(
            f"[ADMIN] Sent {command} for user {incident.get('login_id') or incident.get('client_id')}"
        )

    def _update_incident_detail(self):
        incident = self._selected_incident()
        self.incident_detail.config(state=tk.NORMAL)
        self.incident_detail.delete("1.0", tk.END)
        if incident:
            self.incident_detail.insert(tk.END, "\n".join(_incident_detail_lines(incident)))
        self.incident_detail.config(state=tk.DISABLED)
        self._sync_incident_buttons(incident)

    def _sync_incident_buttons(self, incident: dict | None):
        if not incident:
            for button in (
                self.kill_pid_button,
                self.kick_user_button,
                self.ban_user_button,
                self.pause_exam_button,
                self.resume_exam_button,
                self.forgive_violation_button,
            ):
                button.config(state=tk.DISABLED)
            return

        client = self.clients_data.get(str(incident.get("client_id", "")), {})
        connected = client.get("connection_status") == "Connected"
        session_name = str(client.get("session_state") or incident.get("session_state") or "")
        self.kill_pid_button.config(
            state=tk.NORMAL if connected and bool(incident.get("kill_available")) else tk.DISABLED
        )
        self.kick_user_button.config(state=tk.NORMAL if connected else tk.DISABLED)
        self.ban_user_button.config(state=tk.NORMAL)
        self.pause_exam_button.config(state=tk.NORMAL if session_name == "running" else tk.DISABLED)
        self.resume_exam_button.config(
            state=tk.NORMAL if session_name in {"admin_paused", "disconnected_paused"} else tk.DISABLED
        )
        self.forgive_violation_button.config(
            state=tk.NORMAL if session_name == "violation_paused" and incident.get("blocking") else tk.DISABLED
        )

    def _send_client_command(self, window, command: str, client_id: str):
        print(json.dumps({"cmd": command, "uuid": client_id}), flush=True)
        window.destroy()
        self._append_log(f"[ADMIN] Sent {command} to {client_id}")

    def _send_window_command(self, window, command: str, client_id: str):
        print(json.dumps({"cmd": command, "uuid": client_id}), flush=True)
        window.destroy()
        self._append_log(f"[ADMIN] Sent {command} to {client_id}")

    def _send_add_time(self, window, client_id: str, minutes_text: str):
        minutes_text = minutes_text.strip()
        if not minutes_text:
            messagebox.showwarning("Add Time", "Enter a number of minutes first.")
            return

        print(
            json.dumps({"type": "console_command", "command": f"/addtime {client_id} {minutes_text}"}),
            flush=True,
        )
        window.destroy()
        self._append_log(f"[ADMIN] Added {minutes_text} minute(s) to {client_id}")

    def start_exam_globally(self):
        print(json.dumps({"cmd": "start_exam_global"}), flush=True)
        self._append_log("[ADMIN] Enabled exam start globally")

    def finish_exam_globally(self):
        print(json.dumps({"cmd": "finish_exam_global"}), flush=True)
        self._append_log("[ADMIN] Requested global exam finish")

    def edit_blacklist(self):
        print(json.dumps({"cmd": "edit_blacklist"}), flush=True)
        self._append_log("[ADMIN] Opening process blacklist file")

    def apply_blacklist(self):
        print(json.dumps({"cmd": "apply_blacklist"}), flush=True)
        self._append_log("[ADMIN] Applying process blacklist")

    def edit_policy(self):
        print(json.dumps({"cmd": "edit_policy"}), flush=True)
        self._append_log("[ADMIN] Opening exam policy file")

    def apply_policy(self):
        print(json.dumps({"cmd": "apply_policy"}), flush=True)
        self._append_log("[ADMIN] Applying exam policy")

    def export_settings(self):
        path = filedialog.asksaveasfilename(
            title="Export Settings",
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return
        print(json.dumps({"cmd": "export_settings", "path": path}), flush=True)
        self._append_log(f"[ADMIN] Exporting settings to {path}")

    def import_settings(self):
        path = filedialog.askopenfilename(
            title="Import Settings",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return
        print(json.dumps({"cmd": "import_settings", "path": path}), flush=True)
        self._append_log(f"[ADMIN] Importing settings from {path}")

    def toggle_remember_settings(self):
        print(
            json.dumps(
                {
                    "cmd": "set_remember_settings",
                    "remember": bool(self.remember_settings_var.get()),
                }
            ),
            flush=True,
        )
        self._append_log(
            f"[ADMIN] Remember settings {'enabled' if self.remember_settings_var.get() else 'disabled'}"
        )

    def _open_detail_window(self, window_key, title: str, lines: list[str]):
        top = tk.Toplevel(self)
        top.title(title)
        top.geometry("460x420")
        self._register_window(window_key, top)

        frame = ttk.Frame(top, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        details = tk.Text(frame, wrap=tk.WORD, height=12)
        details.configure(
            relief=tk.SUNKEN,
            borderwidth=1,
            highlightthickness=0,
            padx=6,
            pady=6,
            font="TkFixedFont",
        )
        details.pack(fill=tk.BOTH, expand=True)
        details.insert(tk.END, "\n".join(lines))
        details.config(state=tk.DISABLED)

    def _register_window(self, window_key, window):
        self.open_windows[window_key] = window
        window.bind("<Destroy>", lambda _event: self._forget_window(window_key, window))

    def _forget_window(self, window_key, window):
        existing = self.open_windows.get(window_key)
        if existing is window:
            self.open_windows.pop(window_key, None)

    def _focus_existing_window(self, window_key) -> bool:
        window = self.open_windows.get(window_key)
        if not window or not window.winfo_exists():
            self.open_windows.pop(window_key, None)
            return False

        window.lift()
        window.focus_force()
        return True

    def send_console_command(self):
        command = self.cmd_entry.get().strip()
        if not command:
            return

        if not command.startswith("/"):
            command = "/" + command

        print(json.dumps({"type": "console_command", "command": command}), flush=True)
        self.cmd_entry.delete(0, tk.END)
        self._append_log(f"[ADMIN] Executing: {command}")

    def _append_log(self, line: str):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _confirm_action(self, operator_key: str, title: str, message: str) -> bool:
        operator_defaults = self.server_info.get("operator_defaults", {})
        if not operator_defaults.get(operator_key, True):
            return True
        return bool(messagebox.askyesno(title, message))

    def on_close_request(self):
        messagebox.showwarning(
            "Dashboard Protected",
            "The monitoring dashboard is protected while the server session is active.\n\n"
            "Use the Server Manager or server commands to control the session instead of OS close shortcuts.",
        )

    def log_message(self, client_id, message):
        data = self.clients_data.get(client_id, {})
        display_name = data.get("login_id", client_id[:8])
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_log(f"[{timestamp}] {display_name}: {message}")

    def process_state_update(self, payload):
        self.server_info = payload.get("server", {})
        self.remember_settings_var.set(bool(self.server_info.get("remember_settings", True)))
        self._update_server_info_panel()

        clients = payload.get("clients", [])
        seen_client_ids = set()
        active_count = 0

        for client in clients:
            client_id = client["uuid"]
            seen_client_ids.add(client_id)
            self.clients_data[client_id] = {
                **client,
                "remaining": int(float(client.get("remaining", 0))),
            }
            if client.get("connection_status") == "Connected":
                active_count += 1
            self._upsert_tree_item(client_id, self.clients_data[client_id])

        for client_id in list(self.tree_items.keys()):
            if client_id in seen_client_ids:
                continue
            item_id = self.tree_items.pop(client_id)
            if self.tree.exists(item_id):
                self.tree.delete(item_id)
            self.clients_data.pop(client_id, None)

        incidents = payload.get("incidents", [])
        self.incidents_data = incidents
        self._rebuild_incident_tree()

        total_count = len(clients)
        disconnected_count = total_count - active_count
        self.stats_var.set(
            f"Connections Managed: {total_count} | Active: {active_count} | "
            f"Disconnected: {disconnected_count} | Active Incidents: {self.server_info.get('active_incident_count', 0)}"
        )

    def _update_server_info_panel(self):
        info = self.server_info
        if not info:
            self.server_info_var.set("Waiting for server state...")
            return

        exam_files_path = info.get("exam_files_path") or "-"
        has_exam_files = "Yes" if info.get("has_exam_files") else "No"
        exam_phase = str(info.get("exam_phase", "waiting")).title()
        start_enabled = "Open" if info.get("exam_start_enabled") else "Locked"
        self.start_exam_button.config(
            state=tk.DISABLED if info.get("exam_phase") != "waiting" else tk.NORMAL
        )
        self.finish_exam_button.config(
            state=tk.NORMAL if info.get("exam_phase") == "running" else tk.DISABLED
        )
        text = (
            f"ID: {info.get('server_id', '-')}"
            f"    Host: {info.get('host', '-')}"
            f"    Port: {info.get('port', '-')}\n"
            f"Exam Phase: {exam_phase}"
            f"    Exam Start: {start_enabled}"
            f"    Broadcast: {info.get('broadcast_interval', '-')}s"
            f"    Announce: {info.get('announce_interval', '-')}s\n"
            f"Exam Duration: {info.get('exam_duration_minutes', '-')} min    "
            f"Exam Files: {has_exam_files}"
            f"    Path: {exam_files_path}\n"
            f"Blacklist Entries: {info.get('process_blacklist_count', 0)}"
            f"    Version: {info.get('process_blacklist_version', '-')}"
            f"    File: {info.get('process_blacklist_file', '-')}\n"
            f"Policy Version: {info.get('policy_version', '-')}"
            f"    Policy File: {info.get('policy_file', '-')}"
            f"    Remember Settings: {'Yes' if info.get('remember_settings', True) else 'No'}\n"
            f"Incidents: {info.get('incident_count', 0)}"
            f"    Active Incidents: {info.get('active_incident_count', 0)}"
        )
        self.server_info_var.set(text)

    def _upsert_tree_item(self, client_id: str, data: dict):
        values = (
            data["login_id"],
            data.get("status_label", "Unknown"),
            _format_remaining(data.get("remaining", 0)),
            client_id,
        )

        item_id = self.tree_items.get(client_id)
        if item_id and self.tree.exists(item_id):
            self.tree.item(item_id, values=values)
            return

        self.tree_items[client_id] = self.tree.insert("", tk.END, values=values)

    def _rebuild_incident_tree(self):
        selected_incident = None
        current_selection = self._selected_incident()
        if current_selection:
            selected_incident = current_selection.get("incident_id")

        for item_id in self.incident_tree.get_children():
            self.incident_tree.delete(item_id)
        self.incident_items = {}

        for incident in self.incidents_data:
            incident_id = str(incident.get("incident_id", "") or "")
            status_text = str(incident.get("status", "") or "")
            if incident.get("active"):
                status_text = f"{status_text} (active)"
            values = (
                incident_id,
                incident.get("event_at", ""),
                incident.get("login_id", ""),
                incident.get("severity", ""),
                incident.get("rule_name", ""),
                incident.get("source", ""),
                incident.get("process_name", ""),
                incident.get("pid", ""),
                status_text,
            )
            item_id = self.incident_tree.insert("", tk.END, values=values)
            self.incident_items[incident_id] = item_id
            if selected_incident and selected_incident == incident_id:
                self.incident_tree.selection_set(item_id)

        if not self.incident_tree.selection():
            children = self.incident_tree.get_children()
            if children:
                self.incident_tree.selection_set(children[0])
        self._update_incident_detail()


def ipc_reader(app: ServerGUI):
    for line in iter(sys.stdin.readline, ""):
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"[DEBUG] GUI IPC Error: {e}", file=sys.stderr)
            continue

        message_type = msg.get("type")
        if message_type == "state_update":
            app.after(0, app.process_state_update, msg)
        elif message_type == "client_message":
            app.after(0, app.log_message, msg.get("uuid"), msg.get("text"))


if __name__ == "__main__":
    setup_runtime_logging(
        "server_gui",
        Path(__file__).resolve().parent / "data" / "logs" / "server",
    )
    app = ServerGUI()
    reader_thread = Thread(target=ipc_reader, args=(app,), daemon=True)
    reader_thread.start()
    app.mainloop()
