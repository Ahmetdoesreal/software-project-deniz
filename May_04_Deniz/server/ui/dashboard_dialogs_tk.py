import json
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from server.ui.process_database_helpers import (
    build_process_decision_payload,
    process_row_google_search_url,
)


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


def _client_detail_rows(client_id: str, data: dict) -> list[tuple[str, str]]:
    time_spent = int(data.get("time_spent_seconds", 0))
    extra_time = int(data.get("extra_time_seconds", 0))
    minutes_spent, seconds_spent = divmod(time_spent, 60)
    extra_minutes, extra_seconds = divmod(extra_time, 60)
    return [
        ("Login ID", str(data.get("login_id", "Unknown"))),
        ("UUID", str(client_id)),
        ("Computer Name", str(data.get("computer_name") or "-")),
        ("Short ID", str(data.get("short_id") or "-")),
        ("Connection", str(data.get("connection_status", "Unknown"))),
        ("Exam State", str(data.get("exam_state", "Unknown"))),
        ("Banned", "Yes" if data.get("banned") else "No"),
        ("Admin Paused", "Yes" if data.get("admin_paused") else "No"),
        ("Pause Reason", str(data.get("admin_pause_reason") or "-")),
        ("Remaining", _format_remaining(data.get("remaining", 0))),
        ("Time Spent", f"{minutes_spent:02d}:{seconds_spent:02d}"),
        ("Extra Time", f"{extra_minutes:02d}:{extra_seconds:02d}"),
        ("Kick Count", str(data.get("kick_count", 0))),
        ("Blacklist Catches", str(data.get("blacklist_catch_count", 0))),
        ("Last Blacklist Match", str(", ".join(data.get("last_blacklist_match", [])) or "-")),
        ("Latest Incident Rule", str(data.get("latest_incident_rule_id") or "-")),
        ("Latest Incident Severity", str(data.get("latest_incident_severity") or "-")),
        ("Latest Incident Status", str(data.get("latest_incident_status") or "-")),
        ("Latest Incident Summary", str(data.get("latest_incident_summary") or "-")),
        ("Latest Incident Artifact", str(data.get("latest_incident_artifact_path") or "-")),
        ("Applied Policy Version", str(data.get("applied_policy_version") or "-")),
        ("Last Action", str(data.get("last_action") or "-")),
        ("Current Window Title", str(data.get("last_focus_window") or "-")),
        ("Current Window Process", str(data.get("last_focus_process") or "-")),
        ("Current Window At", str(data.get("last_focus_event_at") or "-")),
        ("Current Window Severity", str(data.get("last_focus_severity") or "-")),
        ("IP Address", str(data.get("ip") or "-")),
        ("Client Exam Folder", str(data.get("exam_folder_path") or "-")),
        ("Client Exam ZIP", str(data.get("exam_files_zip_path") or "-")),
        ("Submission", str(data.get("submission_name") or "-")),
        ("Submission Size", _format_bytes(int(data.get("submission_size_bytes", 0)))),
        ("Submitted At", str(data.get("submitted_at") or "-")),
        ("Submission Path", str(data.get("submission_path") or "-")),
    ]


def _server_info_rows(info: dict) -> list[tuple[str, str]]:
    all_host_ips = ", ".join(str(ip) for ip in info.get("all_host_ips", []) if str(ip).strip()) or "-"
    auth_bypass = info.get("auth_bypass") or {}
    return [
        ("Server ID", str(info.get("server_id", "-"))),
        ("Host", str(info.get("host", "-"))),
        ("Bind Host", str(info.get("bind_host", "-"))),
        ("All Host IPv4s", all_host_ips),
        ("Port", str(info.get("port", "-"))),
        ("Exam Phase", str(info.get("exam_phase", "waiting")).title()),
        ("Exam Start", "Open" if info.get("exam_start_enabled") else "Locked"),
        ("Broadcast Interval (s)", str(info.get("broadcast_interval", "-"))),
        ("Announce Interval (s)", str(info.get("announce_interval", "-"))),
        ("Exam Duration (min)", str(info.get("exam_duration_minutes", "-"))),
        ("Has Exam Files", "Yes" if info.get("has_exam_files") else "No"),
        ("Exam Files Path", str(info.get("exam_files_path") or "-")),
        ("Blacklist Entries", str(info.get("process_blacklist_count", 0))),
        ("Process Definitions", str(info.get("process_definition_count", 0))),
        ("Incident Rules", str(info.get("incident_rule_count", 0))),
        ("Blacklist Version", str(info.get("process_blacklist_version", "-"))),
        ("Blacklist File", str(info.get("process_blacklist_file", "-"))),
        ("Incident Rules Version", str(info.get("incident_rules_version", "-"))),
        ("Incident Rules File", str(info.get("incident_rules_file", "-"))),
        ("Policy Version", str(info.get("policy_version", "-"))),
        ("Policy File", str(info.get("policy_file", "-"))),
        ("Remember Settings", "Yes" if info.get("remember_settings", True) else "No"),
        ("CATS Auth Disabled", f"{auth_bypass.get('cats_disabled', False)} ({auth_bypass.get('cats_remaining_seconds', 0)}s)"),
        ("AD Auth Disabled", f"{auth_bypass.get('ad_disabled', False)} ({auth_bypass.get('ad_remaining_seconds', 0)}s)"),
        ("Incidents", str(info.get("incident_count", 0))),
        ("Active Incidents", str(info.get("active_incident_count", 0))),
    ]


class DashboardPopupMixin:
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
            rows=_client_detail_rows(client_id, data or {}),
        )

    def show_server_info_details(self):
        info = self.server_info
        if not info:
            messagebox.showinfo("Server Info", "No server state available yet.")
            return

        window_key = ("server_info", "details")
        if self._focus_existing_window(window_key):
            return

        self._open_detail_window(
            window_key=window_key,
            title="Server Info Details",
            rows=_server_info_rows(info),
        )

    def show_folder_info(self):
        client_id, data = self._selected_client_data()
        if not client_id:
            messagebox.showinfo("Folders", "Select a client first.")
            return
        data = data or {}
        rows = [
            ("Login ID", str(data.get("login_id") or "-")),
            ("UUID", str(client_id)),
            ("Client Exam Folder", str(data.get("exam_folder_path") or "Desktop\\Exam\\DD-MM-YYYY")),
            ("Client Exam ZIP", str(data.get("exam_files_zip_path") or "-")),
            ("Latest Incident Artifact", str(data.get("latest_incident_artifact_path") or "-")),
            ("Submission Path", str(data.get("submission_path") or "-")),
            ("Submission Name", str(data.get("submission_name") or "-")),
        ]
        window_key = ("folders", client_id)
        if self._focus_existing_window(window_key):
            return
        self._open_detail_window(
            window_key=window_key,
            title=f"Folders: {data.get('login_id', 'Unknown')}",
            rows=rows,
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
        top.geometry("540x360")
        top.minsize(500, 330)
        self._register_window(window_key, top)

        frame = ttk.Frame(top, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)

        actions = ttk.LabelFrame(frame, text="User Actions", padding=10)
        actions.grid(row=0, column=0, sticky=tk.EW)
        for column in range(3):
            actions.columnconfigure(column, weight=1, uniform="actions")

        ttk.Button(
            actions,
            text="Kick Client",
            command=lambda: self._send_window_command(top, "kick", client_id),
            state=tk.NORMAL if data.get("connection_status") == "Connected" else tk.DISABLED,
        ).grid(row=0, column=0, sticky=tk.EW, padx=(0, 6), pady=(0, 6))
        ttk.Button(
            actions,
            text="Ban User",
            command=lambda: self._send_window_command(top, "ban", client_id),
        ).grid(row=0, column=1, sticky=tk.EW, padx=3, pady=(0, 6))
        ttk.Button(
            actions,
            text="Unban User",
            command=lambda: self._send_window_command(top, "unban", client_id),
        ).grid(row=0, column=2, sticky=tk.EW, padx=(6, 0), pady=(0, 6))
        ttk.Button(
            actions,
            text="Pause Exam",
            command=lambda: self._send_window_command(top, "pause_exam", client_id),
        ).grid(row=1, column=0, sticky=tk.EW, padx=(0, 6))
        ttk.Button(
            actions,
            text="Resume Exam",
            command=lambda: self._send_window_command(top, "resume_exam", client_id),
        ).grid(row=1, column=1, sticky=tk.EW, padx=3)

        client_commands = ttk.LabelFrame(frame, text="Connected Client Commands", padding=10)
        client_commands.grid(row=1, column=0, sticky=tk.EW, pady=(10, 0))
        for column in range(2):
            client_commands.columnconfigure(column, weight=1, uniform="client_commands")

        ttk.Button(
            client_commands,
            text="Request Save Screen",
            command=lambda: self._send_client_command(top, "savescreen", client_id),
            state=tk.NORMAL if data.get("connection_status") == "Connected" else tk.DISABLED,
        ).grid(row=0, column=0, sticky=tk.EW, padx=(0, 6))
        ttk.Button(
            client_commands,
            text="Request Process Report",
            command=lambda: self._send_client_command(top, "get_processes", client_id),
            state=tk.NORMAL if data.get("connection_status") == "Connected" else tk.DISABLED,
        ).grid(row=0, column=1, sticky=tk.EW, padx=(6, 0))

        add_time_frame = ttk.LabelFrame(frame, text="Exam Time", padding=10)
        add_time_frame.grid(row=2, column=0, sticky=tk.EW, pady=(10, 0))
        add_time_frame.columnconfigure(1, weight=1)

        ttk.Label(add_time_frame, text="Add Minutes").grid(row=0, column=0, sticky=tk.W, padx=(0, 8))
        minutes_entry = ttk.Entry(add_time_frame, width=8)
        minutes_entry.grid(row=0, column=1, sticky=tk.W)
        ttk.Button(
            add_time_frame,
            text="Apply",
            command=lambda: self._send_add_time(top, client_id, minutes_entry.get()),
        ).grid(row=0, column=2, sticky=tk.E, padx=(8, 0))

    def google_search_selected_process(self):
        row = self._selected_process_row()
        if not row:
            return
        webbrowser.open(process_row_google_search_url(row))
        self._append_log(f"[ADMIN] Google search for {row.get('process_name') or row.get('normalized_process_name')}")

    def show_process_decision_window(self):
        row = self._selected_process_row()
        if not row:
            messagebox.showinfo("Process Database", "Select a process entry first.")
            return

        window_key = ("process_decision", str(row.get("process_key", "") or ""))
        if self._focus_existing_window(window_key):
            return

        top = tk.Toplevel(self)
        top.title(f"Process Decision: {row.get('process_name') or row.get('normalized_process_name') or 'Unknown'}")
        top.geometry("1040x760")
        top.minsize(920, 660)
        self._register_window(window_key, top)

        frame = ttk.Frame(top, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        frame.rowconfigure(3, weight=1)

        identity = ttk.LabelFrame(frame, text="Process")
        identity.grid(row=0, column=0, sticky=tk.EW)
        identity.columnconfigure(1, weight=1)
        rows = [
            ("Executable", row.get("process_name") or row.get("normalized_process_name") or "-"),
            ("Path", row.get("process_path") or row.get("normalized_process_path") or "-"),
            ("Directory", row.get("process_dir") or row.get("normalized_process_dir") or "-"),
            ("Status", row.get("status") or "-"),
            ("Students Opened", ", ".join(row.get("opened_students", [])) or "-"),
            ("Students Closed / Resolved", ", ".join(row.get("closed_students", [])) or "-"),
        ]
        for index, (label, value) in enumerate(rows):
            ttk.Label(identity, text=f"{label}:").grid(row=index, column=0, sticky=tk.W, padx=(8, 8), pady=2)
            ttk.Label(identity, text=str(value), style="Mono.TLabel", wraplength=840).grid(row=index, column=1, sticky=tk.W, pady=2)

        controls = ttk.LabelFrame(frame, text="Decision")
        controls.grid(row=1, column=0, sticky=tk.EW, pady=(10, 10))
        for column in range(4):
            controls.columnconfigure(column, weight=1, uniform="decision")

        status_var = tk.StringVar(value=str(row.get("status") or "unknown"))
        scope_var = tk.StringVar(value=str(row.get("match_scope") or "path"))
        save_var = tk.BooleanVar(value=True)
        action_vars = {
            "ban": tk.BooleanVar(value=bool(row.get("actions", {}).get("ban", False))),
            "kick": tk.BooleanVar(value=bool(row.get("actions", {}).get("kick", False))),
            "pause_exam": tk.BooleanVar(value=bool(row.get("actions", {}).get("pause_exam", False))),
            "kill_pid": tk.BooleanVar(value=bool(row.get("actions", {}).get("kill_pid", False))),
        }

        ttk.Label(controls, text="Status").grid(row=0, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Combobox(
            controls,
            textvariable=status_var,
            values=("unknown", "whitelist", "blacklist", "warning"),
            state="readonly",
            width=18,
        ).grid(row=0, column=1, sticky=tk.EW, padx=(0, 12), pady=6)

        ttk.Label(controls, text="Match Scope").grid(row=0, column=2, sticky=tk.W, padx=8, pady=6)
        ttk.Combobox(
            controls,
            textvariable=scope_var,
            values=("path", "directory", "name"),
            state="readonly",
            width=18,
        ).grid(row=0, column=3, sticky=tk.EW, padx=(0, 12), pady=6)

        ttk.Checkbutton(controls, text="Ban", variable=action_vars["ban"]).grid(row=1, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Checkbutton(controls, text="Kick", variable=action_vars["kick"]).grid(row=1, column=1, sticky=tk.W, padx=8, pady=6)
        ttk.Checkbutton(controls, text="Pause Exam", variable=action_vars["pause_exam"]).grid(row=1, column=2, sticky=tk.W, padx=8, pady=6)
        ttk.Checkbutton(controls, text="Kill PID", variable=action_vars["kill_pid"]).grid(row=1, column=3, sticky=tk.W, padx=8, pady=6)
        ttk.Checkbutton(controls, text="Save decision to policy", variable=save_var).grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=8, pady=6)

        ttk.Button(
            controls,
            text="Google Search",
            command=lambda: webbrowser.open(process_row_google_search_url(row)),
        ).grid(row=2, column=2, sticky=tk.EW, padx=8, pady=6)
        ttk.Button(
            controls,
            text="Apply Policy",
            command=lambda: self._emit_process_decision(
                top,
                row,
                status_var.get(),
                scope_var.get(),
                {name: var.get() for name, var in action_vars.items()},
                save_var.get(),
            ),
        ).grid(row=2, column=3, sticky=tk.EW, padx=8, pady=6)

        students_frame = ttk.LabelFrame(frame, text="Matching Students And Action State")
        students_frame.grid(row=2, column=0, sticky=tk.NSEW)
        student_columns = ("student", "status", "pid", "active", "actions")
        students_tree = ttk.Treeview(
            students_frame,
            columns=student_columns,
            show="headings",
            style="Monospace.Treeview",
        )
        for column, text, width, minwidth in (
            ("student", "Student", 140, 100),
            ("status", "Session", 120, 95),
            ("pid", "PID", 80, 65),
            ("active", "Active", 70, 65),
            ("actions", "Action State", 560, 180),
        ):
            students_tree.heading(column, text=text)
            students_tree.column(column, width=width, minwidth=minwidth, anchor=tk.W)
        students_scroll = ttk.Scrollbar(students_frame, orient=tk.VERTICAL, command=students_tree.yview)
        students_tree.configure(yscrollcommand=students_scroll.set)
        students_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        students_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        for student in row.get("action_states", []):
            students_tree.insert(
                "",
                tk.END,
                values=(
                    student.get("login_id") or student.get("client_id") or "-",
                    student.get("session_state") or "-",
                    student.get("pid") or "-",
                    "Yes" if student.get("active") else "No",
                    self._format_student_action_state(student),
                ),
            )

        previous_frame = ttk.LabelFrame(frame, text="Previous Matching Entries / Definitions")
        previous_frame.grid(row=3, column=0, sticky=tk.NSEW, pady=(10, 0))
        previous_columns = ("status", "scope", "path", "actions", "decided")
        previous_tree = ttk.Treeview(
            previous_frame,
            columns=previous_columns,
            show="headings",
            style="Monospace.Treeview",
        )
        for column, text, width, minwidth in (
            ("status", "Status", 90, 80),
            ("scope", "Scope", 90, 70),
            ("path", "Path / Directory", 430, 180),
            ("actions", "Actions", 180, 110),
            ("decided", "Decided", 150, 110),
        ):
            previous_tree.heading(column, text=text)
            previous_tree.column(column, width=width, minwidth=minwidth, anchor=tk.W)
        previous_scroll = ttk.Scrollbar(previous_frame, orient=tk.VERTICAL, command=previous_tree.yview)
        previous_tree.configure(yscrollcommand=previous_scroll.set)
        previous_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        previous_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        for previous in row.get("previous_matching_entries", []):
            previous_tree.insert(
                "",
                tk.END,
                values=(
                    previous.get("status") or "-",
                    previous.get("match_scope") or "-",
                    previous.get("process_path") or previous.get("process_dir") or "-",
                    ", ".join(name for name, enabled in previous.get("actions", {}).items() if enabled) or "-",
                    previous.get("decided_at") or previous.get("updated_at") or "-",
                ),
            )

    def _format_student_action_state(self, student: dict) -> str:
        parts = []
        for action in ("ban", "kick", "pause_exam", "kill_pid"):
            action_state = student.get("actions", {}).get(action, {})
            state_name = str(action_state.get("state", "not_possible") or "not_possible")
            reason = str(action_state.get("reason", "") or "")
            label = action.replace("_", " ")
            parts.append(f"{label}: {state_name}{f' ({reason})' if reason else ''}")
        return "; ".join(parts)

    def _emit_process_decision(self, window, row: dict, status: str, match_scope: str, actions: dict, save_policy: bool):
        payload = build_process_decision_payload(
            row,
            status=status,
            match_scope=match_scope,
            actions=actions,
            save_policy=save_policy,
        )
        self._emit_command(payload)
        window.destroy()
        self._append_log(
            f"[ADMIN] Applied process decision for {row.get('process_name') or row.get('normalized_process_name')}"
        )

    def _send_client_command(self, window, command: str, client_id: str):
        self._emit_command({"cmd": command, "uuid": client_id})
        window.destroy()
        self._append_log(f"[ADMIN] Sent {command} to {client_id}")

    def _send_window_command(self, window, command: str, client_id: str):
        self._emit_command({"cmd": command, "uuid": client_id})
        window.destroy()
        self._append_log(f"[ADMIN] Sent {command} to {client_id}")

    def _send_add_time(self, window, client_id: str, minutes_text: str):
        minutes_text = minutes_text.strip()
        if not minutes_text:
            messagebox.showwarning("Add Time", "Enter a number of minutes first.")
            return

        self._emit_command({"type": "console_command", "command": f"/addtime {client_id} {minutes_text}"})
        window.destroy()
        self._append_log(f"[ADMIN] Added {minutes_text} minute(s) to {client_id}")

    def _open_detail_window(self, window_key, title: str, rows: list[tuple[str, str]]):
        top = tk.Toplevel(self)
        top.title(title)
        top.geometry("780x520")
        top.minsize(620, 380)
        self._register_window(window_key, top)

        frame = ttk.Frame(top, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        detail_columns = ("field", "value")
        details = ttk.Treeview(
            frame,
            columns=detail_columns,
            show="headings",
            selectmode="browse",
            style="Monospace.Treeview",
        )
        details.heading("field", text="Field")
        details.heading("value", text="Value")
        details.column("field", width=220, minwidth=130, stretch=False, anchor=tk.W)
        details.column("value", width=520, minwidth=180, stretch=True, anchor=tk.W)

        detail_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=details.yview)
        detail_x_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=details.xview)
        details.configure(
            yscrollcommand=detail_scroll.set,
            xscrollcommand=detail_x_scroll.set,
        )
        details.grid(row=0, column=0, sticky=tk.NSEW)
        detail_scroll.grid(row=0, column=1, sticky=tk.NS)
        detail_x_scroll.grid(row=1, column=0, sticky=tk.EW)
        for field, value in rows:
            details.insert("", tk.END, values=(field, value))

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
