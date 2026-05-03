import json
import sys
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from collections import Counter
from datetime import datetime
from pathlib import Path
from threading import Thread
from tkinter import filedialog, messagebox, ttk


PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from common.manager_support import install_close_guard
from common.process_definitions import build_google_search_url
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


def _detail_lines(client_id: str, data: dict) -> list[tuple[str, str]]:
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
        ("IP Address", str(data.get("ip") or "-")),
        ("Submission", str(data.get("submission_name") or "-")),
        ("Submission Size", _format_bytes(int(data.get("submission_size_bytes", 0)))),
        ("Submitted At", str(data.get("submitted_at") or "-")),
        ("Submission Path", str(data.get("submission_path") or "-")),
    ]


def _incident_detail_lines(incident: dict) -> list[tuple[str, str]]:
    return [
        ("Incident ID", str(incident.get("incident_id") or "-")),
        ("User", str(incident.get("login_id") or "-")),
        ("Client ID", str(incident.get("client_id") or "-")),
        ("Severity", str(incident.get("severity") or "-")),
        ("Status", str(incident.get("status") or "-")),
        ("Rule", str(incident.get("rule_name") or incident.get("rule_id") or "-")),
        ("Source", str(incident.get("source") or "-")),
        ("Process", str(incident.get("process_name") or "-")),
        ("PID", str(incident.get("pid") or "-")),
        ("Active", "Yes" if incident.get("active") else "No"),
        ("Auto Action", str(incident.get("auto_action_name") or "-")),
        (
            "Auto Action State",
            str(incident.get("auto_action_state_label") or incident.get("auto_action_state") or "-"),
        ),
        ("Session State", str(incident.get("session_state") or "-")),
        ("Reconnect Allowed", "Yes" if incident.get("resume_allowed") else "No"),
        ("Blocking Incident", "Yes" if incident.get("blocking") else "No"),
        ("Policy Version", str(incident.get("policy_version") or "-")),
        ("Artifact", str(incident.get("artifact_path") or "-")),
        ("Event At", str(incident.get("event_at") or "-")),
        ("Summary", str(incident.get("summary") or "-")),
        ("Raw Details", json.dumps(incident.get("details", {}), ensure_ascii=False, sort_keys=True)),
    ]


def _format_counter(values: list[str]) -> str:
    counts = Counter(value for value in values if value)
    if not counts:
        return "-"
    return ", ".join(f"{label}: {count}" for label, count in sorted(counts.items()))


PROCESS_DATABASE_FILTERS = ("All", "Unknown", "Whitelist", "Blacklist", "Warnings", "Active", "Resolved")


def process_row_matches_filter(row: dict, filter_name: str) -> bool:
    filter_name = str(filter_name or "All").strip().lower()
    status = str(row.get("status", "") or "").strip().lower()
    if filter_name == "all":
        return True
    if filter_name == "warnings":
        return status == "warning" or bool(row.get("warning"))
    if filter_name == "active":
        return bool(row.get("active"))
    if filter_name == "resolved":
        return bool(row.get("resolved")) and not bool(row.get("active"))
    return status == filter_name


def format_process_action_availability(row: dict) -> str:
    availability = row.get("action_availability", {})
    if not isinstance(availability, dict):
        return "-"
    parts = []
    for action in ("ban", "kick", "pause_exam", "kill_pid"):
        state = availability.get(action, {})
        possible = int(state.get("possible", 0) or 0) if isinstance(state, dict) else 0
        applied = int(state.get("applied", 0) or 0) if isinstance(state, dict) else 0
        blocked = int(state.get("not_possible", 0) or 0) if isinstance(state, dict) else 0
        if possible or applied or blocked:
            parts.append(f"{action.replace('_', ' ')} {possible}/{applied}/{blocked}")
    return "; ".join(parts) if parts else "-"


def build_process_decision_payload(
    row: dict,
    *,
    status: str,
    match_scope: str,
    actions: dict,
    save_policy: bool,
) -> dict:
    return {
        "cmd": "apply_process_decision",
        "definition": {
            "definition_id": row.get("definition_id", ""),
            "process_key": row.get("process_key", ""),
            "process_name": row.get("process_name", ""),
            "normalized_process_name": row.get("normalized_process_name", ""),
            "process_path": row.get("process_path", ""),
            "normalized_process_path": row.get("normalized_process_path", ""),
            "process_dir": row.get("process_dir", ""),
            "normalized_process_dir": row.get("normalized_process_dir", ""),
            "match_scope": match_scope,
            "status": status,
            "actions": {
                "ban": bool(actions.get("ban", False)),
                "kick": bool(actions.get("kick", False)),
                "pause_exam": bool(actions.get("pause_exam", False)),
                "kill_pid": bool(actions.get("kill_pid", False)),
            },
            "source_incident_id": row.get("source_incident_id", ""),
            "matching_history": list(row.get("matching_history", [])),
            "previous_matching_entries": list(row.get("previous_matching_entries", [])),
        },
        "status": status,
        "match_scope": match_scope,
        "actions": {
            "ban": bool(actions.get("ban", False)),
            "kick": bool(actions.get("kick", False)),
            "pause_exam": bool(actions.get("pause_exam", False)),
            "kill_pid": bool(actions.get("kill_pid", False)),
        },
        "save_policy": bool(save_policy),
    }


def process_row_google_search_url(row: dict) -> str:
    return build_google_search_url(row.get("process_name", ""), row.get("process_path", ""))


def _multi_incident_detail_lines(incidents: list[dict]) -> list[tuple[str, str]]:
    users = sorted({str(incident.get("login_id") or "-") for incident in incidents})
    rows: list[tuple[str, str]] = [
        ("Selected Incidents", str(len(incidents))),
        ("Users", f"{', '.join(users[:8])}{' ...' if len(users) > 8 else ''}" if users else "-"),
        ("Active", str(sum(1 for incident in incidents if incident.get("active")))),
        ("Blocking Incidents", str(sum(1 for incident in incidents if incident.get("blocking")))),
        ("Kill Available", str(sum(1 for incident in incidents if incident.get("kill_available")))),
        ("Severity Mix", _format_counter([str(incident.get("severity") or "-") for incident in incidents])),
        ("Status Mix", _format_counter([str(incident.get("status") or "-") for incident in incidents])),
        (
            "Auto Action States",
            _format_counter(
                [str(incident.get("auto_action_state_label") or incident.get("auto_action_state") or "-") for incident in incidents]
            ),
        ),
    ]
    for incident in incidents[:25]:
        rows.append(
            (
                f"Selected Row {len(rows) - 7}",
                " | ".join(
                    [
                        str(incident.get("incident_id") or "-"),
                        str(incident.get("login_id") or "-"),
                        str(incident.get("rule_name") or incident.get("rule_id") or "-"),
                        str(incident.get("status") or "-"),
                        str(incident.get("auto_action_state_label") or incident.get("auto_action_state") or "-"),
                    ]
                ),
            )
        )
    if len(incidents) > 25:
        rows.append(("More Rows", f"... and {len(incidents) - 25} more"))
    return rows


def _server_info_rows(info: dict) -> list[tuple[str, str]]:
    return [
        ("Server ID", str(info.get("server_id", "-"))),
        ("Host", str(info.get("host", "-"))),
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
        ("Blacklist Version", str(info.get("process_blacklist_version", "-"))),
        ("Blacklist File", str(info.get("process_blacklist_file", "-"))),
        ("Policy Version", str(info.get("policy_version", "-"))),
        ("Policy File", str(info.get("policy_file", "-"))),
        ("Remember Settings", "Yes" if info.get("remember_settings", True) else "No"),
        ("Incidents", str(info.get("incident_count", 0))),
        ("Active Incidents", str(info.get("active_incident_count", 0))),
    ]


class ServerGUI(tk.Tk):
    def __init__(self, *, standalone_mode: bool = False):
        super().__init__()
        self.standalone_mode = standalone_mode
        self.clients_data: dict[str, dict] = {}
        self.tree_items: dict[str, str] = {}
        self.incidents_data: list[dict] = []
        self.incident_items: dict[str, str] = {}
        self.process_database_data: list[dict] = []
        self.process_database_items: dict[str, str] = {}
        self.server_info: dict = {}
        self.open_windows = {}
        self.remember_settings_var = tk.BooleanVar(value=True)
        self.process_filter_var = tk.StringVar(value="All")
        self._incident_tree_refreshing = False
        self._process_tree_refreshing = False

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
        self.process_database_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.overview_tab, text="Overview")
        self.notebook.add(self.rules_tab, text="Rule Breakings")
        self.notebook.add(self.process_database_tab, text="Process Database")

        self._build_overview_tab()
        self._build_rule_breakings_tab()
        self._build_process_database_tab()
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
        for column in range(3):
            blacklist_frame.columnconfigure(column, weight=1)

        self.edit_blacklist_button = ttk.Button(
            blacklist_frame,
            text="Edit Blacklist",
            command=self.edit_blacklist,
        )
        self.edit_blacklist_button.grid(row=0, column=0, sticky=tk.EW)

        self.apply_blacklist_button = ttk.Button(
            blacklist_frame,
            text="Apply Blacklist",
            command=self.apply_blacklist,
        )
        self.apply_blacklist_button.grid(row=0, column=1, sticky=tk.EW, padx=(8, 0))

        self.edit_policy_button = ttk.Button(
            blacklist_frame,
            text="Edit Policy",
            command=self.edit_policy,
        )
        self.edit_policy_button.grid(row=0, column=2, sticky=tk.EW, padx=(8, 0))

        self.apply_policy_button = ttk.Button(
            blacklist_frame,
            text="Apply Policy",
            command=self.apply_policy,
        )
        self.apply_policy_button.grid(row=1, column=0, sticky=tk.EW, pady=(8, 0))

        self.export_settings_button = ttk.Button(
            blacklist_frame,
            text="Export Settings",
            command=self.export_settings,
        )
        self.export_settings_button.grid(row=1, column=1, sticky=tk.EW, padx=(8, 0), pady=(8, 0))

        self.import_settings_button = ttk.Button(
            blacklist_frame,
            text="Import Settings",
            command=self.import_settings,
        )
        self.import_settings_button.grid(row=1, column=2, sticky=tk.EW, padx=(8, 0), pady=(8, 0))

        remember_toggle = ttk.Checkbutton(
            info_frame,
            text="Remember Settings",
            variable=self.remember_settings_var,
            command=self.toggle_remember_settings,
        )
        remember_toggle.pack(anchor=tk.W, padx=8, pady=(4, 0))

        detail_actions = ttk.Frame(info_frame, padding=(8, 4, 8, 0))
        detail_actions.pack(fill=tk.X)
        self.server_info_detail_button = ttk.Button(
            detail_actions,
            text="Detailed Info",
            command=self.show_server_info_details,
            state=tk.DISABLED,
        )
        self.server_info_detail_button.pack(side=tk.LEFT)

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

        detail_columns = ("field", "value")
        self.incident_detail = ttk.Treeview(
            detail_frame,
            columns=detail_columns,
            show="headings",
            selectmode="browse",
            style="Monospace.Treeview",
        )
        self.incident_detail.heading("field", text="Field")
        self.incident_detail.heading("value", text="Value")
        self.incident_detail.column("field", width=220, stretch=False, anchor=tk.W)
        self.incident_detail.column("value", width=700, stretch=True, anchor=tk.W)

        detail_scroll = ttk.Scrollbar(detail_frame, orient=tk.VERTICAL, command=self.incident_detail.yview)
        detail_x_scroll = ttk.Scrollbar(detail_frame, orient=tk.HORIZONTAL, command=self.incident_detail.xview)
        self.incident_detail.configure(
            yscrollcommand=detail_scroll.set,
            xscrollcommand=detail_x_scroll.set,
        )

        self.incident_detail.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        detail_x_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        detail_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_process_database_tab(self):
        container = ttk.Frame(self.process_database_tab, padding=10)
        container.pack(fill=tk.BOTH, expand=True)

        toolbar = ttk.Frame(container)
        toolbar.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(toolbar, text="Filter:").pack(side=tk.LEFT)
        filter_box = ttk.Combobox(
            toolbar,
            textvariable=self.process_filter_var,
            values=PROCESS_DATABASE_FILTERS,
            state="readonly",
            width=14,
        )
        filter_box.pack(side=tk.LEFT, padx=(6, 10))
        filter_box.bind("<<ComboboxSelected>>", lambda _event: self._rebuild_process_database_tree())

        self.process_options_button = ttk.Button(
            toolbar,
            text="Options",
            command=self.show_process_decision_window,
            state=tk.DISABLED,
        )
        self.process_options_button.pack(side=tk.LEFT, padx=(0, 6))

        self.process_google_button = ttk.Button(
            toolbar,
            text="Google Search",
            command=self.google_search_selected_process,
            state=tk.DISABLED,
        )
        self.process_google_button.pack(side=tk.LEFT)

        tree_frame = ttk.LabelFrame(container, text="Process Definitions And Evidence")
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = (
            "process_key",
            "executable",
            "status",
            "path",
            "scope",
            "matches",
            "students",
            "last_seen",
            "actions",
            "availability",
        )
        self.process_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            style="Monospace.Treeview",
        )
        self.process_tree.heading("process_key", text="Process Key")
        self.process_tree.heading("executable", text="Executable")
        self.process_tree.heading("status", text="Status")
        self.process_tree.heading("path", text="Path / Directory")
        self.process_tree.heading("scope", text="Scope")
        self.process_tree.heading("matches", text="Matches")
        self.process_tree.heading("students", text="Affected Students")
        self.process_tree.heading("last_seen", text="Last Seen")
        self.process_tree.heading("actions", text="Saved Actions")
        self.process_tree.heading("availability", text="Action Availability")
        self.process_tree.column("process_key", width=0, stretch=False)
        self.process_tree.column("executable", width=150)
        self.process_tree.column("status", width=90, anchor=tk.CENTER)
        self.process_tree.column("path", width=330)
        self.process_tree.column("scope", width=90, anchor=tk.CENTER)
        self.process_tree.column("matches", width=80, anchor=tk.CENTER)
        self.process_tree.column("students", width=160)
        self.process_tree.column("last_seen", width=150)
        self.process_tree.column("actions", width=145)
        self.process_tree.column("availability", width=220)
        self.process_tree.bind("<<TreeviewSelect>>", lambda _event: self._sync_process_buttons())
        self.process_tree.bind("<Double-1>", lambda _event: self.show_process_decision_window())

        process_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.process_tree.yview)
        process_x_scroll = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.process_tree.xview)
        self.process_tree.configure(
            yscrollcommand=process_scroll.set,
            xscrollcommand=process_x_scroll.set,
        )
        self.process_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        process_x_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        process_scroll.pack(side=tk.RIGHT, fill=tk.Y)

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
        self.stats_var = tk.StringVar(
            value=(
                "Connections Managed: 0 | Active: 0 | Disconnected: 0 | "
                "Active Incidents: 0 | Active Warnings: 0"
            )
        )
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

    def _selected_process_key(self):
        selected = self.process_tree.selection()
        if not selected:
            return None
        values = self.process_tree.item(selected[0], "values")
        return values[0] if values else None

    def _selected_process_row(self):
        process_key = self._selected_process_key()
        if not process_key:
            return None
        for row in self.process_database_data:
            if str(row.get("process_key", "") or "") == str(process_key):
                return row
        return None

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
            rows=_detail_lines(client_id, data or {}),
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
        top.geometry("430x500")
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
        top.geometry("920x720")
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
            ttk.Label(identity, text=str(value), style="Mono.TLabel", wraplength=720).grid(row=index, column=1, sticky=tk.W, pady=2)

        controls = ttk.LabelFrame(frame, text="Decision")
        controls.grid(row=1, column=0, sticky=tk.EW, pady=(10, 10))

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
            width=14,
        ).grid(row=0, column=1, sticky=tk.W, padx=(0, 12), pady=6)

        ttk.Label(controls, text="Match Scope").grid(row=0, column=2, sticky=tk.W, padx=8, pady=6)
        ttk.Combobox(
            controls,
            textvariable=scope_var,
            values=("path", "directory", "name"),
            state="readonly",
            width=14,
        ).grid(row=0, column=3, sticky=tk.W, padx=(0, 12), pady=6)

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
        for column, text, width in (
            ("student", "Student", 140),
            ("status", "Session", 120),
            ("pid", "PID", 80),
            ("active", "Active", 70),
            ("actions", "Action State", 560),
        ):
            students_tree.heading(column, text=text)
            students_tree.column(column, width=width, anchor=tk.W)
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
        for column, text, width in (
            ("status", "Status", 90),
            ("scope", "Scope", 90),
            ("path", "Path / Directory", 430),
            ("actions", "Actions", 180),
            ("decided", "Decided", 150),
        ):
            previous_tree.heading(column, text=text)
            previous_tree.column(column, width=width, anchor=tk.W)
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
        print(json.dumps(payload), flush=True)
        window.destroy()
        self._append_log(
            f"[ADMIN] Applied process decision for {row.get('process_name') or row.get('normalized_process_name')}"
        )

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
        for item_id in self.incident_detail.get_children():
            self.incident_detail.delete(item_id)
        rows: list[tuple[str, str]] = []
        if len(incidents) == 1:
            rows = _incident_detail_lines(incidents[0])
        elif incidents:
            rows = _multi_incident_detail_lines(incidents)
        for field, value in rows:
            self.incident_detail.insert("", tk.END, values=(field, value))
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

    def _open_detail_window(self, window_key, title: str, rows: list[tuple[str, str]]):
        top = tk.Toplevel(self)
        top.title(title)
        top.geometry("560x460")
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
        details.column("field", width=220, stretch=False, anchor=tk.W)
        details.column("value", width=700, stretch=True, anchor=tk.W)

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
        if self.standalone_mode:
            self.destroy()
            return
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
        self.process_database_data = payload.get("process_database", [])
        self._rebuild_process_database_tree()
        active_warning_count = sum(
            1
            for incident in incidents
            if bool(incident.get("active")) and str(incident.get("severity", "")).strip().lower() == "warning"
        )

        total_count = len(clients)
        disconnected_count = total_count - active_count
        self.stats_var.set(
            f"Connections Managed: {total_count} | Active: {active_count} | "
            f"Disconnected: {disconnected_count} | Active Incidents: {self.server_info.get('active_incident_count', 0)} | "
            f"Active Warnings: {active_warning_count}"
        )

    def _update_server_info_panel(self):
        info = self.server_info
        if not info:
            self.server_info_var.set("Waiting for server state...")
            self.server_info_detail_button.config(state=tk.DISABLED)
            return

        has_exam_files = "Yes" if info.get("has_exam_files") else "No"
        exam_phase = str(info.get("exam_phase", "waiting")).title()
        start_enabled = "Open" if info.get("exam_start_enabled") else "Locked"
        self.server_info_detail_button.config(state=tk.NORMAL)
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
            f"    Duration: {info.get('exam_duration_minutes', '-')} min\n"
            f"Exam Files: {has_exam_files}"
            f"    Active Incidents: {info.get('active_incident_count', 0)}"
            f"    Total Incidents: {info.get('incident_count', 0)}\n"
            "Use Detailed Info for full configuration."
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

    def _rebuild_process_database_tree(self):
        selected_key = self._selected_process_key()
        focus_item = self.process_tree.focus()
        focus_values = self.process_tree.item(focus_item, "values") if focus_item else ()
        focused_key = str(focus_values[0]) if focus_values else ""
        yview = self.process_tree.yview()
        restored_selection = ""
        restored_focus = ""

        self._process_tree_refreshing = True
        try:
            for item_id in self.process_tree.get_children():
                self.process_tree.delete(item_id)
            self.process_database_items = {}

            for row in self.process_database_data:
                if not process_row_matches_filter(row, self.process_filter_var.get()):
                    continue
                process_key = str(row.get("process_key", "") or "")
                path_display = (
                    row.get("process_path")
                    or row.get("process_dir")
                    or row.get("normalized_process_path")
                    or row.get("normalized_process_dir")
                    or "-"
                )
                students = ", ".join(row.get("affected_students", [])[:4])
                if len(row.get("affected_students", [])) > 4:
                    students += " ..."
                values = (
                    process_key,
                    row.get("process_name") or row.get("normalized_process_name") or "",
                    row.get("status", ""),
                    path_display,
                    row.get("match_scope", ""),
                    row.get("match_count", 0),
                    students or "-",
                    row.get("last_seen", ""),
                    row.get("saved_action_labels", ""),
                    format_process_action_availability(row),
                )
                item_id = self.process_tree.insert("", tk.END, values=values)
                self.process_database_items[process_key] = item_id
                if selected_key and process_key == selected_key:
                    restored_selection = item_id
                if focused_key and process_key == focused_key:
                    restored_focus = item_id

            if restored_selection:
                self.process_tree.selection_set(restored_selection)
            else:
                self.process_tree.selection_remove(self.process_tree.selection())

            if restored_focus:
                self.process_tree.focus(restored_focus)
            elif restored_selection:
                self.process_tree.focus(restored_selection)

            if yview:
                self.process_tree.yview_moveto(yview[0])
        finally:
            self._process_tree_refreshing = False
        self._sync_process_buttons()

    def _sync_process_buttons(self):
        has_selection = self._selected_process_row() is not None
        state_name = tk.NORMAL if has_selection else tk.DISABLED
        self.process_options_button.config(state=state_name)
        self.process_google_button.config(state=state_name)


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

    # When the parent server process exits, stdin pipe closes.
    # In managed mode, close the dashboard instead of leaving an orphan window.
    if not app.standalone_mode:
        try:
            app.after(0, app.destroy)
        except Exception:
            pass


if __name__ == "__main__":
    setup_runtime_logging(
        "server_gui",
        PROJECT_DIR / "data" / "logs" / "server",
    )
    app = ServerGUI(standalone_mode=sys.stdin.isatty())
    reader_thread = Thread(target=ipc_reader, args=(app,), daemon=True)
    reader_thread.start()
    app.mainloop()
