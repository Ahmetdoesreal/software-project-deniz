import json
import tkinter as tk
from tkinter import messagebox, ttk


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


def _client_detail_lines(client_id: str, data: dict) -> list[str]:
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
            lines=_client_detail_lines(client_id, data or {}),
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

    def _open_detail_window(self, window_key, title: str, lines: list[str]):
        top = tk.Toplevel(self)
        top.title(title)
        top.geometry("720x520")
        top.minsize(560, 380)
        self._register_window(window_key, top)

        frame = ttk.Frame(top, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        details = tk.Text(frame, wrap=tk.NONE, height=12)
        details.configure(
            relief=tk.SUNKEN,
            borderwidth=1,
            highlightthickness=0,
            padx=6,
            pady=6,
            font=self.mono_font,
        )
        detail_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=details.yview)
        detail_x_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=details.xview)
        details.configure(
            yscrollcommand=detail_scroll.set,
            xscrollcommand=detail_x_scroll.set,
        )
        details.grid(row=0, column=0, sticky=tk.NSEW)
        detail_scroll.grid(row=0, column=1, sticky=tk.NS)
        detail_x_scroll.grid(row=1, column=0, sticky=tk.EW)
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
