import json
import sys
import tkinter as tk
import tkinter.font as tkfont
from collections import Counter
from datetime import datetime
from pathlib import Path
from threading import Thread
from tkinter import filedialog, messagebox, ttk

from common.manager_support import install_close_guard
from common.runtime_logging import setup_runtime_logging
from server.dashboard_popups import DashboardPopupMixin
from server.policy_settings_window import PolicySettingsMixin


def _format_remaining(seconds: int) -> str:
    minutes, remaining_seconds = divmod(int(max(0, seconds)), 60)
    return f"{minutes:02d}:{remaining_seconds:02d}"


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
        f"Auto Action: {incident.get('auto_action_name') or '-'}",
        f"Auto Action State: {incident.get('auto_action_state_label') or incident.get('auto_action_state') or '-'}",
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


def _format_counter(values: list[str]) -> str:
    counts = Counter(value for value in values if value)
    if not counts:
        return "-"
    return ", ".join(f"{label}: {count}" for label, count in sorted(counts.items()))


def _multi_incident_detail_lines(incidents: list[dict]) -> list[str]:
    users = sorted({str(incident.get("login_id") or "-") for incident in incidents})
    lines = [
        f"Selected Incidents: {len(incidents)}",
        f"Users: {', '.join(users[:8])}{' ...' if len(users) > 8 else ''}" if users else "Users: -",
        f"Active: {sum(1 for incident in incidents if incident.get('active'))}",
        f"Blocking Incidents: {sum(1 for incident in incidents if incident.get('blocking'))}",
        f"Kill Available: {sum(1 for incident in incidents if incident.get('kill_available'))}",
        f"Severity Mix: {_format_counter([str(incident.get('severity') or '-') for incident in incidents])}",
        f"Status Mix: {_format_counter([str(incident.get('status') or '-') for incident in incidents])}",
        f"Auto Action States: {_format_counter([str(incident.get('auto_action_state_label') or incident.get('auto_action_state') or '-') for incident in incidents])}",
        "",
        "Selected Rows:",
    ]
    for incident in incidents[:25]:
        lines.append(
            " | ".join(
                [
                    str(incident.get("incident_id") or "-"),
                    str(incident.get("login_id") or "-"),
                    str(incident.get("rule_name") or incident.get("rule_id") or "-"),
                    str(incident.get("status") or "-"),
                    str(incident.get("auto_action_state_label") or incident.get("auto_action_state") or "-"),
                ]
            )
        )
    if len(incidents) > 25:
        lines.append(f"... and {len(incidents) - 25} more")
    return lines


class ServerGUI(PolicySettingsMixin, DashboardPopupMixin, tk.Tk):
    def __init__(self):
        super().__init__()
        self.clients_data: dict[str, dict] = {}
        self.tree_items: dict[str, str] = {}
        self.incidents_data: list[dict] = []
        self.incident_items: dict[str, str] = {}
        self.server_info: dict = {}
        self.open_windows = {}
        self.remember_settings_var = tk.BooleanVar(value=True)
        self._init_policy_settings()
        self._incident_tree_refreshing = False

        self.title("Server Monitor Dashboard")
        self.geometry("1200x760")
        self.minsize(1000, 680)
        self.mono_font = tkfont.nametofont("TkFixedFont").copy()
        self.tree_style = ttk.Style(self)
        self.tree_style.configure("Monospace.Treeview", font=self.mono_font)
        self.tree_style.configure("Mono.TLabel", font=self.mono_font)
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

        toolbar = ttk.Frame(info_frame, padding=(8, 8, 8, 0))
        toolbar.pack(fill=tk.X)
        toolbar.columnconfigure(0, weight=1)
        toolbar.columnconfigure(1, weight=0)

        exam_controls = ttk.Frame(toolbar)
        exam_controls.grid(row=0, column=0, sticky=tk.W)

        settings_controls = ttk.Frame(toolbar)
        settings_controls.grid(row=0, column=1, sticky=tk.E)

        self.start_exam_button = ttk.Button(
            exam_controls,
            text="Start Exam",
            command=self.start_exam_globally,
            width=14,
        )
        self.start_exam_button.pack(side=tk.LEFT)

        self.finish_exam_button = ttk.Button(
            exam_controls,
            text="Finish Exam",
            command=self.finish_exam_globally,
            width=14,
        )
        self.finish_exam_button.pack(side=tk.LEFT, padx=(8, 0))

        self.policy_settings_button = ttk.Button(
            settings_controls,
            text="Policy Settings",
            command=self.open_policy_settings_window,
            width=18,
        )
        self.policy_settings_button.pack(side=tk.LEFT)

        remember_toggle = ttk.Checkbutton(
            settings_controls,
            text="Remember Settings",
            variable=self.remember_settings_var,
            command=self.toggle_remember_settings,
        )
        remember_toggle.pack(side=tk.LEFT, padx=(12, 0))

        self.server_info_var = tk.StringVar(value="Waiting for server state...")
        info_label = ttk.Label(
            info_frame,
            textvariable=self.server_info_var,
            style="Mono.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            padding=8,
            wraplength=980,
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
            style="Monospace.Treeview",
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
        x_scroll = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(
            yscrollcommand=y_scroll.set,
            xscrollcommand=x_scroll.set,
        )

        self.tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        x_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        y_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_log_area(self, parent):
        log_frame = ttk.LabelFrame(parent, text="Live Client Message Log")
        log_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, pady=(10, 0))

        self.log_text = tk.Text(log_frame, height=7, state=tk.DISABLED, wrap=tk.NONE)
        self.log_text.configure(
            relief=tk.SUNKEN,
            borderwidth=1,
            highlightthickness=0,
            padx=6,
            pady=6,
            font=self.mono_font,
        )
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_x_scroll = ttk.Scrollbar(log_frame, orient=tk.HORIZONTAL, command=self.log_text.xview)
        self.log_text.configure(
            yscrollcommand=log_scroll.set,
            xscrollcommand=log_x_scroll.set,
        )

        self.log_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        log_x_scroll.pack(side=tk.BOTTOM, fill=tk.X)
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

        columns = ("incident_id", "time", "user", "severity", "rule", "source", "process", "pid", "auto_action", "status")
        self.incident_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
            style="Monospace.Treeview",
        )
        self.incident_tree.heading("incident_id", text="Incident ID")
        self.incident_tree.heading("time", text="Time")
        self.incident_tree.heading("user", text="User")
        self.incident_tree.heading("severity", text="Severity")
        self.incident_tree.heading("rule", text="Rule")
        self.incident_tree.heading("source", text="Source")
        self.incident_tree.heading("process", text="Process")
        self.incident_tree.heading("pid", text="PID")
        self.incident_tree.heading("auto_action", text="Auto Action")
        self.incident_tree.heading("status", text="Status")
        self.incident_tree.column("incident_id", width=0, stretch=False)
        self.incident_tree.column("time", width=150)
        self.incident_tree.column("user", width=110)
        self.incident_tree.column("severity", width=90, anchor=tk.CENTER)
        self.incident_tree.column("rule", width=150)
        self.incident_tree.column("source", width=110)
        self.incident_tree.column("process", width=140)
        self.incident_tree.column("pid", width=80, anchor=tk.CENTER)
        self.incident_tree.column("auto_action", width=115, anchor=tk.CENTER)
        self.incident_tree.column("status", width=100, anchor=tk.CENTER)
        self.incident_tree.bind("<<TreeviewSelect>>", lambda _event: self._update_incident_detail())

        incident_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.incident_tree.yview)
        incident_x_scroll = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.incident_tree.xview)
        self.incident_tree.configure(
            yscrollcommand=incident_scroll.set,
            xscrollcommand=incident_x_scroll.set,
        )

        self.incident_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        incident_x_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        incident_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        detail_frame = ttk.LabelFrame(middle, text="Incident Details")
        detail_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self.incident_detail = tk.Text(detail_frame, wrap=tk.NONE, height=14, state=tk.DISABLED)
        self.incident_detail.configure(
            relief=tk.SUNKEN,
            borderwidth=1,
            highlightthickness=0,
            padx=6,
            pady=6,
            font=self.mono_font,
        )
        detail_scroll = ttk.Scrollbar(detail_frame, orient=tk.VERTICAL, command=self.incident_detail.yview)
        detail_x_scroll = ttk.Scrollbar(detail_frame, orient=tk.HORIZONTAL, command=self.incident_detail.xview)
        self.incident_detail.configure(
            yscrollcommand=detail_scroll.set,
            xscrollcommand=detail_x_scroll.set,
        )

        self.incident_detail.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        detail_x_scroll.pack(side=tk.BOTTOM, fill=tk.X)
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
        incidents = self._selected_incidents()
        return incidents[0] if incidents else None

    def _selected_incident_ids(self) -> list[str]:
        incident_ids: list[str] = []
        for item_id in self.incident_tree.selection():
            values = self.incident_tree.item(item_id, "values")
            if values:
                incident_ids.append(str(values[0]))
        return incident_ids

    def _selected_incidents(self) -> list[dict]:
        selected_ids = set(self._selected_incident_ids())
        if not selected_ids:
            return []
        return [
            incident
            for incident in self.incidents_data
            if str(incident.get("incident_id", "") or "") in selected_ids
        ]

    def _incident_connected(self, incident: dict) -> bool:
        client = self.clients_data.get(str(incident.get("client_id", "") or ""), {})
        return client.get("connection_status") == "Connected"

    def _incident_session_state(self, incident: dict) -> str:
        client = self.clients_data.get(str(incident.get("client_id", "") or ""), {})
        return str(client.get("session_state") or incident.get("session_state") or "")

    def _unique_client_incidents(self, incidents: list[dict], predicate) -> list[dict]:
        selected: list[dict] = []
        seen_client_ids: set[str] = set()
        for incident in incidents:
            client_id = str(incident.get("client_id", "") or "")
            if not client_id or client_id in seen_client_ids:
                continue
            if not predicate(incident):
                continue
            seen_client_ids.add(client_id)
            selected.append(incident)
        return selected

    def _incident_target_label(self, incidents: list[dict], plural_label: str) -> str:
        if len(incidents) == 1:
            return str(incidents[0].get("login_id") or incidents[0].get("client_id") or "Unknown")
        return f"{len(incidents)} selected {plural_label}"

    def update_timers(self):
        for client_id, data in self.clients_data.items():
            if data.get("exam_state") != "Running":
                continue
            if data.get("remaining", 0) <= 0:
                continue
            data["remaining"] -= 1
            self._upsert_tree_item(client_id, data)

        self.after(1000, self.update_timers)

    def kill_selected_pid(self):
        incidents = self._selected_incidents()
        if not incidents:
            return
        eligible: list[dict] = []
        seen_targets: set[tuple[str, int]] = set()
        for incident in incidents:
            pid = int(incident.get("pid", 0) or 0)
            client_id = str(incident.get("client_id", "") or "")
            if pid <= 0 or not client_id:
                continue
            if not incident.get("kill_available") or not self._incident_connected(incident):
                continue
            target = (client_id, pid)
            if target in seen_targets:
                continue
            seen_targets.add(target)
            eligible.append(incident)
        if not eligible:
            messagebox.showinfo("Kill PID", "No selected incidents have a killable live process.")
            return
        if len(eligible) == 1:
            incident = eligible[0]
            pid = int(incident.get("pid", 0) or 0)
            user = incident.get("login_id") or "Unknown"
            process_name = incident.get("process_name") or "Unknown"
            if self._confirm_action(
                "confirm_kill_pid",
                "Kill PID",
                f"Kill process for user {user}?\n\nProcess: {process_name}\nPID: {pid}",
            ) is False:
                return
        else:
            user_count = len({str(incident.get("client_id", "") or "") for incident in eligible})
            if self._confirm_action(
                "confirm_kill_pid",
                "Kill PID",
                f"Kill {len(eligible)} selected process(es) across {user_count} user(s)?",
            ) is False:
                return

        for incident in eligible:
            print(
                json.dumps(
                    {
                        "cmd": "kill_pid",
                        "uuid": incident.get("client_id"),
                        "incident_id": incident.get("incident_id"),
                        "process_name": incident.get("process_name") or "Unknown",
                        "pid": int(incident.get("pid", 0) or 0),
                    }
                ),
                flush=True,
            )
        self._append_log(
            f"[ADMIN] Requested PID kill for {len(eligible)} selected process(es)"
        )

    def kick_selected_user(self):
        incidents = self._unique_client_incidents(
            self._selected_incidents(),
            lambda incident: self._incident_connected(incident),
        )
        if not incidents:
            return
        target_count = len(incidents)
        target_label = self._incident_target_label(incidents, "user(s)")
        if self._confirm_action(
            "confirm_kick",
            "Kick User",
            f"Disconnect user {target_label}?" if target_count == 1 else f"Disconnect {target_label}?",
        ) is False:
            return
        self._emit_incident_user_commands("kick", incidents)

    def ban_selected_user(self):
        incidents = self._unique_client_incidents(self._selected_incidents(), lambda _incident: True)
        if not incidents:
            return
        target_count = len(incidents)
        target_label = self._incident_target_label(incidents, "user(s)")
        if self._confirm_action(
            "confirm_ban",
            "Ban User",
            f"Ban user {target_label}?" if target_count == 1 else f"Ban {target_label}?",
        ) is False:
            return
        self._emit_incident_user_commands("ban", incidents)

    def pause_selected_exam(self):
        incidents = self._unique_client_incidents(
            self._selected_incidents(),
            lambda incident: self._incident_session_state(incident) == "running",
        )
        if not incidents:
            return
        target_count = len(incidents)
        target_label = self._incident_target_label(incidents, "exam session(s)")
        if self._confirm_action(
            "confirm_pause",
            "Pause Exam",
            f"Pause exam for {target_label}?" if target_count == 1 else f"Pause {target_label}?",
        ) is False:
            return
        self._emit_incident_user_commands("pause_exam", incidents)

    def resume_selected_exam(self):
        incidents = self._unique_client_incidents(
            self._selected_incidents(),
            lambda incident: self._incident_session_state(incident) in {"admin_paused", "disconnected_paused"},
        )
        if not incidents:
            return
        self._emit_incident_user_commands("resume_exam", incidents)

    def forgive_selected_violation(self):
        incidents = self._unique_client_incidents(
            sorted(self._selected_incidents(), key=lambda incident: (not incident.get("blocking"), str(incident.get("incident_id") or ""))),
            lambda incident: self._incident_session_state(incident) == "violation_paused" and bool(incident.get("blocking")),
        )
        if not incidents:
            return
        target_count = len(incidents)
        if not messagebox.askyesno(
            "Forgive Violation",
            (
                f"Forgive blocking violation for {incidents[0].get('login_id') or incidents[0].get('client_id')}?"
                if target_count == 1
                else f"Forgive blocking violations for {target_count} selected user(s)?"
            ),
        ):
            return
        self._emit_incident_user_commands("forgive_violation", incidents)

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

    def _emit_incident_user_commands(self, command: str, incidents: list[dict]):
        for incident in incidents:
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
            f"[ADMIN] Sent {command} for {len(incidents)} selected user(s)"
        )

    def _update_incident_detail(self):
        if self._incident_tree_refreshing:
            return
        incidents = self._selected_incidents()
        self.incident_detail.config(state=tk.NORMAL)
        self.incident_detail.delete("1.0", tk.END)
        if len(incidents) == 1:
            self.incident_detail.insert(tk.END, "\n".join(_incident_detail_lines(incidents[0])))
        elif incidents:
            self.incident_detail.insert(tk.END, "\n".join(_multi_incident_detail_lines(incidents)))
        self.incident_detail.config(state=tk.DISABLED)
        self._sync_incident_buttons(incidents)

    def _sync_incident_buttons(self, incidents: list[dict]):
        if not incidents:
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

        self.kill_pid_button.config(
            state=tk.NORMAL
            if any(self._incident_connected(incident) and bool(incident.get("kill_available")) for incident in incidents)
            else tk.DISABLED
        )
        self.kick_user_button.config(
            state=tk.NORMAL if any(self._incident_connected(incident) for incident in incidents) else tk.DISABLED
        )
        self.ban_user_button.config(state=tk.NORMAL)
        self.pause_exam_button.config(
            state=tk.NORMAL
            if any(self._incident_session_state(incident) == "running" for incident in incidents)
            else tk.DISABLED
        )
        self.resume_exam_button.config(
            state=tk.NORMAL
            if any(
                self._incident_session_state(incident) in {"admin_paused", "disconnected_paused"}
                for incident in incidents
            )
            else tk.DISABLED
        )
        self.forgive_violation_button.config(
            state=tk.NORMAL
            if any(
                self._incident_session_state(incident) == "violation_paused" and incident.get("blocking")
                for incident in incidents
            )
            else tk.DISABLED
        )

    def start_exam_globally(self):
        print(json.dumps({"cmd": "start_exam_global"}), flush=True)
        self._append_log("[ADMIN] Enabled exam start globally")

    def finish_exam_globally(self):
        print(json.dumps({"cmd": "finish_exam_global"}), flush=True)
        self._append_log("[ADMIN] Requested global exam finish")

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
        settings_snapshot = payload.get("settings", {})
        if isinstance(settings_snapshot, dict) and settings_snapshot:
            self.update_settings_snapshot(settings_snapshot)

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
        selected_incidents = set(self._selected_incident_ids())
        focus_item = self.incident_tree.focus()
        focus_values = self.incident_tree.item(focus_item, "values") if focus_item else ()
        focused_incident_id = str(focus_values[0]) if focus_values else ""
        yview = self.incident_tree.yview()
        restored_selection: list[str] = []
        restored_focus = ""

        self._incident_tree_refreshing = True
        try:
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
                    incident.get("auto_action_state_label", ""),
                    status_text,
                )
                item_id = self.incident_tree.insert("", tk.END, values=values)
                self.incident_items[incident_id] = item_id
                if incident_id in selected_incidents:
                    restored_selection.append(item_id)
                if focused_incident_id and incident_id == focused_incident_id:
                    restored_focus = item_id

            if restored_selection:
                self.incident_tree.selection_set(restored_selection)
            else:
                self.incident_tree.selection_remove(self.incident_tree.selection())

            if restored_focus:
                self.incident_tree.focus(restored_focus)
            elif restored_selection:
                self.incident_tree.focus(restored_selection[0])

            if yview:
                self.incident_tree.yview_moveto(yview[0])
        finally:
            self._incident_tree_refreshing = False

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
        elif message_type == "settings_result":
            app.after(0, app.process_settings_result, msg)


if __name__ == "__main__":
    setup_runtime_logging(
        "server_gui",
        Path(__file__).resolve().parent / "data" / "logs" / "server",
    )
    app = ServerGUI()
    reader_thread = Thread(target=ipc_reader, args=(app,), daemon=True)
    reader_thread.start()
    app.mainloop()
