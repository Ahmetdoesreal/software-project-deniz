import json
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from collections import Counter
from datetime import datetime
from pathlib import Path
from threading import Thread
from tkinter import filedialog, messagebox, ttk


PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from common.manager_support import install_close_guard
from common.ipc_ws import ThreadedIpcClient, should_use_ws_ipc
from common.runtime_logging import setup_runtime_logging
from common.stdio_compat import iter_stdin_lines, stdin_available, stdin_is_standalone, write_json_stdout, write_text_stderr
from ui.tk_theme import apply_tk_theme, style_text_widget, tk_mono_font
from ui.theme import M, STATE_COLORS
from server.ui.dashboard_dialogs_tk import DashboardPopupMixin
from server.ui.dashboard_table_helpers import (
    CLIENT_COLUMNS,
    CLIENT_FILTERS,
    INCIDENT_FILTERS,
    INCIDENT_RULE_COLUMNS,
    INCIDENT_RULE_FILTERS,
    PROCESS_COLUMNS,
    PROCESS_DATABASE_FILTERS,
    active_filter_names,
    affected_students_display,
    client_window_title,
    incident_rule_match_display,
    process_path_display,
    sorted_client_items,
    sorted_incident_rule_rows,
    sorted_incidents,
    sorted_process_rows,
)
from server.ui.policy_settings_tk import PolicySettingsMixin
from server.ui.process_database_helpers import (
    build_incident_rule_decision_payload,
    build_process_decision_payload,
    incident_rule_field_text,
    incident_rule_observed_window_title,
    incident_rule_row_from_incident,
    process_row_google_search_url,
    split_multiline_values,
)
from server.ui.row_refresh import (
    RowSnapshot,
    changed_row_indexes,
    reorder_rows_by_previous_keys,
    row_snapshot,
    same_row_order,
)

_IPC_CLIENT = None


def _emit_command(payload: dict):
    if _IPC_CLIENT and _IPC_CLIENT.send("dashboard.command", payload):
        return
    write_json_stdout(payload)


def _format_remaining(seconds: int) -> str:
    minutes, remaining_seconds = divmod(int(max(0, seconds)), 60)
    return f"{minutes:02d}:{remaining_seconds:02d}"


def _plain(value) -> str:
    text = str(value or "").strip()
    return text or "-"


def _tk_badge_colors(state: str) -> tuple[str, str]:
    state = str(state or "").strip().lower()
    if state == "connected":
        state = "running"
    if state in {"violation", "warning"}:
        state = "violation_paused"
    if state == "paused":
        state = "admin_paused"
    return STATE_COLORS.get(state, (M["on_surface_variant"], M["surface_container"]))


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


class ServerGUI(PolicySettingsMixin, DashboardPopupMixin, tk.Tk):
    def __init__(self, *, standalone_mode: bool = False):
        super().__init__()
        self.standalone_mode = standalone_mode
        self.clients_data: dict[str, dict] = {}
        self.tree_items: dict[str, str] = {}
        self.incidents_data: list[dict] = []
        self.incident_items: dict[str, str] = {}
        self.process_database_data: list[dict] = []
        self.process_database_items: dict[str, str] = {}
        self.incident_rules_data: list[dict] = []
        self.incident_rules_items: dict[str, str] = {}
        self.server_info: dict = {}
        self.open_windows = {}
        self.remember_settings_var = tk.BooleanVar(value=True)
        self.filter_vars: dict[str, dict[str, tk.BooleanVar]] = {}
        self.sort_state: dict[str, tuple[str, bool]] = {
            "clients": ("login_id", False),
            "incidents": ("time", True),
            "processes": ("executable", False),
            "incident_rules": ("last_seen", True),
        }
        self.selected_client_info_var = tk.StringVar(value="Select a client to see basic details.")
        self.selected_client_title_var = tk.StringVar(value="No client selected")
        self.selected_client_subtitle_var = tk.StringVar(value="Select a client row to view status and actions.")
        self.selected_client_badge_var = tk.StringVar(value="Idle")
        self.selected_client_fields: dict[str, tk.StringVar] = {}
        self._init_policy_settings()
        self._incident_tree_refreshing = False
        self._process_tree_refreshing = False
        self._incident_rules_tree_refreshing = False
        self._row_snapshots: dict[str, RowSnapshot] = {}
        self._force_table_rebuilds: set[str] = set()
        self._tree_hover_items: dict[object, str] = {}
        self._horizontal_scroll_active_until: dict[object, float] = {}

        self.title("Server Monitor Dashboard")
        self.geometry("1200x760")
        self.minsize(1000, 680)
        apply_tk_theme(self)
        self.mono_font = tk_mono_font(self)
        self.header_font = tkfont.nametofont("TkDefaultFont").copy()
        self.header_font.configure(weight="bold")
        self.tree_style = ttk.Style(self)
        self.tree_style.configure("Monospace.Treeview", font=self.mono_font)
        self.tree_style.map(
            "Monospace.Treeview",
            background=[("selected", "#00296b"), ("active", "#232a37")],
            foreground=[("selected", "#ffffff"), ("active", "#f8fafc")],
        )
        self.tree_style.configure("Mono.TLabel", font=self.mono_font)
        install_close_guard(self, self.on_close_request, bind_all=True)

        self._build_layout()
        self.after(1000, self.update_timers)

    def _emit_command(self, payload: dict):
        _emit_command(payload)

    def _build_layout(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))

        self.overview_tab = ttk.Frame(self.notebook)
        self.rules_tab = ttk.Frame(self.notebook)
        self.process_database_tab = ttk.Frame(self.notebook)
        self.incident_rules_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.overview_tab, text="Overview")
        self.notebook.add(self.rules_tab, text="Rule Breakings")
        self.notebook.add(self.process_database_tab, text="Process Database")
        self.notebook.add(self.incident_rules_tab, text="Incident Rules")

        self._build_overview_tab()
        self._build_rule_breakings_tab()
        self._build_process_database_tab()
        self._build_incident_rules_tab()
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

        self.server_info_detail_button = ttk.Button(
            settings_controls,
            text="Detailed Info",
            command=self.show_server_info_details,
            state=tk.DISABLED,
            width=14,
        )
        self.server_info_detail_button.pack(side=tk.LEFT, padx=(12, 0))

        remember_row = ttk.Frame(info_frame, padding=(8, 4, 8, 0))
        remember_row.pack(fill=tk.X)
        remember_toggle = ttk.Checkbutton(
            remember_row,
            text="Remember Settings",
            variable=self.remember_settings_var,
            command=self.toggle_remember_settings,
        )
        remember_toggle.pack(side=tk.LEFT)

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

    def _build_filter_bar(self, parent, table_name: str, filters: tuple[str, ...], rebuild_callback):
        bar = ttk.Frame(parent)
        bar.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(bar, text="Filters:").pack(side=tk.LEFT, padx=(0, 6))
        table_vars: dict[str, tk.BooleanVar] = {}
        self.filter_vars[table_name] = table_vars
        for filter_name in filters:
            var = tk.BooleanVar(value=filter_name == "All")
            table_vars[filter_name] = var
            ttk.Checkbutton(
                bar,
                text=filter_name,
                variable=var,
                command=lambda name=filter_name: self._on_filter_toggled(table_name, name, rebuild_callback),
            ).pack(side=tk.LEFT, padx=(0, 8))
        return bar

    def _on_filter_toggled(self, table_name: str, filter_name: str, rebuild_callback):
        table_vars = self.filter_vars.get(table_name, {})
        if not table_vars:
            return
        if filter_name == "All" and table_vars["All"].get():
            for name, var in table_vars.items():
                if name != "All":
                    var.set(False)
        elif filter_name != "All" and filter_name in table_vars and table_vars[filter_name].get():
            table_vars["All"].set(False)
        if not any(var.get() for var in table_vars.values()):
            table_vars["All"].set(True)
        self._force_table_rebuilds.add(table_name)
        rebuild_callback()

    def _active_filters(self, table_name: str) -> set[str]:
        return active_filter_names(
            {name: var.get() for name, var in self.filter_vars.get(table_name, {}).items()}
        )

    def _set_sort(self, table_name: str, column: str, rebuild_callback):
        current_column, descending = self.sort_state.get(table_name, (column, False))
        if current_column == column:
            descending = not descending
        else:
            current_column = column
            descending = False
        self.sort_state[table_name] = (current_column, descending)
        self._force_table_rebuilds.add(table_name)
        rebuild_callback()

    def _heading_text(self, table_name: str, column: str, label: str) -> str:
        current_column, descending = self.sort_state.get(table_name, ("", False))
        if current_column != column:
            return label
        return f"{label} {'v' if descending else '^'}"

    def _configure_sort_headings(self, tree, table_name: str, columns: tuple[tuple[str, str], ...], rebuild_callback):
        for column, label in columns:
            tree.heading(
                column,
                text=self._heading_text(table_name, column, label),
                command=lambda col=column: self._set_sort(table_name, col, rebuild_callback),
            )

    def _install_tree_hover(self, tree):
        hover_tag = "_hover"
        tree.tag_configure(hover_tag, background="#232a37", foreground="#f8fafc")
        self._tree_hover_items[tree] = ""

        def clear_hover():
            item_id = self._tree_hover_items.get(tree, "")
            if item_id and tree.exists(item_id):
                tags = tuple(tag for tag in tree.item(item_id, "tags") if tag != hover_tag)
                tree.item(item_id, tags=tags)
            self._tree_hover_items[tree] = ""

        def on_motion(event):
            item_id = tree.identify_row(event.y)
            if item_id == self._tree_hover_items.get(tree, ""):
                return
            clear_hover()
            if not item_id or item_id in tree.selection():
                return
            tags = tuple(tree.item(item_id, "tags"))
            if hover_tag not in tags:
                tree.item(item_id, tags=tags + (hover_tag,))
            self._tree_hover_items[tree] = item_id

        tree.bind("<Motion>", on_motion, add="+")
        tree.bind("<Leave>", lambda _event: clear_hover(), add="+")
        tree.bind("<<TreeviewSelect>>", lambda _event: clear_hover(), add="+")

    def _prepare_rows_for_refresh(self, table_name: str, rows):
        previous = self._row_snapshots.get(table_name)
        if table_name not in self._force_table_rebuilds:
            rows = reorder_rows_by_previous_keys(rows, previous)
        snapshot = row_snapshot(rows)
        force_rebuild = table_name in self._force_table_rebuilds
        self._force_table_rebuilds.discard(table_name)
        return rows, snapshot, previous, force_rebuild

    def _mark_horizontal_scroll_active(self, tree):
        self._horizontal_scroll_active_until[tree] = time.monotonic() + 0.35

    def _horizontal_scroll_is_active(self, tree) -> bool:
        return time.monotonic() < self._horizontal_scroll_active_until.get(tree, 0.0)

    def _xview_from_scrollbar(self, tree, *args):
        self._mark_horizontal_scroll_active(tree)
        tree.xview(*args)

    def _restore_tree_scroll(self, tree, yview, xview):
        def restore(*, delayed: bool = False):
            if yview:
                tree.yview_moveto(yview[0])
            if xview and (not delayed or not self._horizontal_scroll_is_active(tree)):
                tree.xview_moveto(xview[0])

        restore(delayed=False)
        self.after_idle(lambda: restore(delayed=True))

    def _build_client_tree_area(self, parent):
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._build_filter_bar(tree_frame, "clients", CLIENT_FILTERS, self._rebuild_client_tree)

        columns = tuple(column for column, _label in CLIENT_COLUMNS)
        self.tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            style="Monospace.Treeview",
        )
        self._configure_sort_headings(self.tree, "clients", CLIENT_COLUMNS, self._rebuild_client_tree)

        self.tree.column("login_id", width=130, minwidth=90, stretch=True)
        self.tree.column("status", width=120, minwidth=100, anchor=tk.CENTER, stretch=True)
        self.tree.column("remaining", width=100, minwidth=85, anchor=tk.CENTER, stretch=False)
        self.tree.column("window_title", width=260, minwidth=160, stretch=True)
        self.tree.column("ip", width=120, minwidth=110, stretch=True)
        self.tree.column("uuid", width=280, minwidth=160, stretch=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_selected_client_panel())
        self._install_tree_hover(self.tree)

        y_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        x_scroll = ttk.Scrollbar(
            tree_frame,
            orient=tk.HORIZONTAL,
            command=lambda *args: self._xview_from_scrollbar(self.tree, *args),
        )
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
        style_text_widget(self.log_text)
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
        action_frame.configure(width=320)

        header = ttk.Frame(action_frame, padding=(10, 8, 10, 4))
        header.pack(fill=tk.X)
        title_row = ttk.Frame(header)
        title_row.pack(fill=tk.X)
        ttk.Label(
            title_row,
            textvariable=self.selected_client_title_var,
            font=self.header_font,
            anchor=tk.W,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.selected_client_badge = tk.Label(
            title_row,
            textvariable=self.selected_client_badge_var,
            padx=8,
            pady=2,
            bg=M["surface_container_high"],
            fg=M["on_surface_variant"],
        )
        self.selected_client_badge.pack(side=tk.RIGHT)
        ttk.Label(
            header,
            textvariable=self.selected_client_subtitle_var,
            justify=tk.LEFT,
            anchor=tk.W,
            wraplength=280,
        ).pack(fill=tk.X, pady=(6, 0))

        body = ttk.Frame(action_frame, padding=(10, 2, 10, 8))
        body.pack(fill=tk.BOTH, expand=True)
        self._add_selected_section(
            body,
            "Session",
            (
                ("connection", "Connection", False),
                ("exam", "Exam", False),
                ("remaining", "Remaining", True),
                ("status", "Status", False),
            ),
        )
        self._add_selected_section(
            body,
            "Machine",
            (
                ("ip", "IP", True),
                ("computer", "Computer", True),
                ("uuid", "UUID", True),
            ),
        )
        self._add_selected_section(
            body,
            "Current Window",
            (
                ("window", "Title", False),
                ("process", "Process", True),
                ("window_at", "Seen At", True),
                ("window_severity", "Severity", False),
            ),
        )
        self._add_selected_section(
            body,
            "Latest Incident",
            (
                ("incident_summary", "Summary", False),
                ("incident_rule", "Rule", True),
                ("incident_severity", "Severity", False),
                ("incident_status", "Status", False),
            ),
        )

        actions = ttk.LabelFrame(action_frame, text="Actions", padding=8)
        actions.pack(fill=tk.X, padx=10, pady=(0, 10))
        self.selected_details_button = ttk.Button(
            actions,
            text="Details",
            command=self.show_info,
            state=tk.DISABLED,
        )
        self.selected_details_button.pack(fill=tk.X, pady=(0, 6))
        self.selected_folders_button = ttk.Button(
            actions,
            text="Folders",
            command=self.show_folder_info,
            state=tk.DISABLED,
        )
        self.selected_folders_button.pack(fill=tk.X, pady=(0, 6))
        self.selected_actions_button = ttk.Button(
            actions,
            text="Actions",
            command=self.show_options,
            state=tk.DISABLED,
        )
        self.selected_actions_button.pack(fill=tk.X)

    def _add_selected_section(self, parent, title: str, rows: tuple[tuple[str, str, bool], ...]):
        section = ttk.Frame(parent)
        section.pack(fill=tk.X, pady=(8, 4))
        ttk.Label(section, text=title, font=self.header_font).pack(anchor=tk.W, pady=(0, 3))
        for key, label, technical in rows:
            var = tk.StringVar(value="-")
            self.selected_client_fields[key] = var
            row = ttk.Frame(section)
            row.pack(fill=tk.X, pady=1)
            ttk.Label(row, text=f"{label}:", width=11, anchor=tk.W).pack(side=tk.LEFT, anchor=tk.N)
            label_options = {"style": "Mono.TLabel"} if technical else {}
            ttk.Label(
                row,
                textvariable=var,
                justify=tk.LEFT,
                anchor=tk.W,
                wraplength=185,
                **label_options,
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)

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

        self.save_incident_rule_button = ttk.Button(
            left,
            text="Save as Rule",
            command=self.save_selected_incident_as_rule,
            state=tk.DISABLED,
        )
        self.save_incident_rule_button.pack(fill=tk.X, padx=10, pady=6)

        middle = ttk.Frame(container)
        middle.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tree_frame = ttk.LabelFrame(middle, text="Incident History")
        tree_frame.pack(fill=tk.BOTH, expand=True)
        self._build_filter_bar(tree_frame, "incidents", INCIDENT_FILTERS, self._rebuild_incident_tree)

        columns = ("incident_id", "time", "user", "severity", "rule", "source", "process", "pid", "auto_action", "status")
        self.incident_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
            style="Monospace.Treeview",
        )
        self.incident_columns = tuple((column, label) for column, label in (
            ("incident_id", "Incident ID"),
            ("time", "Time"),
            ("user", "User"),
            ("severity", "Severity"),
            ("rule", "Rule"),
            ("source", "Source"),
            ("process", "Process"),
            ("pid", "PID"),
            ("auto_action", "Auto Action"),
            ("status", "Status"),
        ))
        self._configure_sort_headings(self.incident_tree, "incidents", self.incident_columns, self._rebuild_incident_tree)
        self.incident_tree.column("incident_id", width=0, minwidth=0, stretch=False)
        self.incident_tree.column("time", width=150, minwidth=120, stretch=True)
        self.incident_tree.column("user", width=110, minwidth=90, stretch=True)
        self.incident_tree.column("severity", width=90, minwidth=80, anchor=tk.CENTER, stretch=False)
        self.incident_tree.column("rule", width=150, minwidth=120, stretch=True)
        self.incident_tree.column("source", width=110, minwidth=90, stretch=True)
        self.incident_tree.column("process", width=140, minwidth=100, stretch=True)
        self.incident_tree.column("pid", width=80, minwidth=70, anchor=tk.CENTER, stretch=False)
        self.incident_tree.column("auto_action", width=115, minwidth=100, anchor=tk.CENTER, stretch=True)
        self.incident_tree.column("status", width=100, minwidth=90, anchor=tk.CENTER, stretch=True)
        self.incident_tree.bind("<<TreeviewSelect>>", lambda _event: self._update_incident_detail())
        self._install_tree_hover(self.incident_tree)

        incident_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.incident_tree.yview)
        incident_x_scroll = ttk.Scrollbar(
            tree_frame,
            orient=tk.HORIZONTAL,
            command=lambda *args: self._xview_from_scrollbar(self.incident_tree, *args),
        )
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
        detail_x_scroll = ttk.Scrollbar(
            detail_frame,
            orient=tk.HORIZONTAL,
            command=lambda *args: self._xview_from_scrollbar(self.incident_detail, *args),
        )
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
        self._build_filter_bar(container, "processes", PROCESS_DATABASE_FILTERS, self._rebuild_process_database_tree)

        toolbar = ttk.Frame(container)
        toolbar.pack(fill=tk.X, pady=(0, 10))

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

        columns = tuple(column for column, _label in PROCESS_COLUMNS)
        self.process_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            style="Monospace.Treeview",
        )
        self._configure_sort_headings(self.process_tree, "processes", PROCESS_COLUMNS, self._rebuild_process_database_tree)
        self.process_tree.column("process_key", width=0, minwidth=0, stretch=False)
        self.process_tree.column("executable", width=150, minwidth=110, stretch=True)
        self.process_tree.column("status", width=90, minwidth=80, anchor=tk.CENTER, stretch=False)
        self.process_tree.column("path", width=330, minwidth=180, stretch=True)
        self.process_tree.column("scope", width=90, minwidth=80, anchor=tk.CENTER, stretch=False)
        self.process_tree.column("matches", width=80, minwidth=70, anchor=tk.CENTER, stretch=False)
        self.process_tree.column("students", width=160, minwidth=120, stretch=True)
        self.process_tree.column("last_seen", width=150, minwidth=120, stretch=True)
        self.process_tree.column("actions", width=145, minwidth=110, stretch=True)
        self.process_tree.column("availability", width=220, minwidth=150, stretch=True)
        self.process_tree.bind("<<TreeviewSelect>>", lambda _event: self._sync_process_buttons())
        self.process_tree.bind("<Double-1>", lambda _event: self.show_process_decision_window())
        self._install_tree_hover(self.process_tree)

        process_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.process_tree.yview)
        process_x_scroll = ttk.Scrollbar(
            tree_frame,
            orient=tk.HORIZONTAL,
            command=lambda *args: self._xview_from_scrollbar(self.process_tree, *args),
        )
        self.process_tree.configure(
            yscrollcommand=process_scroll.set,
            xscrollcommand=process_x_scroll.set,
        )
        self.process_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        process_x_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        process_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_incident_rules_tab(self):
        container = ttk.Frame(self.incident_rules_tab, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        self._build_filter_bar(container, "incident_rules", INCIDENT_RULE_FILTERS, self._rebuild_incident_rules_tree)

        toolbar = ttk.Frame(container)
        toolbar.pack(fill=tk.X, pady=(0, 10))

        self.incident_rule_options_button = ttk.Button(
            toolbar,
            text="Options",
            command=self.show_incident_rule_decision_window,
            state=tk.DISABLED,
        )
        self.incident_rule_options_button.pack(side=tk.LEFT, padx=(0, 6))

        ttk.Button(
            toolbar,
            text="Open Rules File",
            command=self.edit_incident_rules,
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            toolbar,
            text="Apply Rules File",
            command=self.apply_incident_rules,
        ).pack(side=tk.LEFT)

        tree_frame = ttk.LabelFrame(container, text="Incident Rules And Evidence")
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = tuple(column for column, _label in INCIDENT_RULE_COLUMNS)
        self.incident_rules_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            style="Monospace.Treeview",
        )
        self._configure_sort_headings(self.incident_rules_tree, "incident_rules", INCIDENT_RULE_COLUMNS, self._rebuild_incident_rules_tree)
        self.incident_rules_tree.column("rule_key", width=0, minwidth=0, stretch=False)
        self.incident_rules_tree.column("name", width=180, minwidth=120, stretch=True)
        self.incident_rules_tree.column("status", width=90, minwidth=80, anchor=tk.CENTER, stretch=False)
        self.incident_rules_tree.column("match", width=360, minwidth=180, stretch=True)
        self.incident_rules_tree.column("matches", width=80, minwidth=70, anchor=tk.CENTER, stretch=False)
        self.incident_rules_tree.column("students", width=160, minwidth=120, stretch=True)
        self.incident_rules_tree.column("last_seen", width=150, minwidth=120, stretch=True)
        self.incident_rules_tree.column("actions", width=145, minwidth=110, stretch=True)
        self.incident_rules_tree.column("availability", width=220, minwidth=150, stretch=True)
        self.incident_rules_tree.bind("<<TreeviewSelect>>", lambda _event: self._sync_incident_rule_buttons())
        self.incident_rules_tree.bind("<Double-1>", lambda _event: self.show_incident_rule_decision_window())
        self._install_tree_hover(self.incident_rules_tree)

        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.incident_rules_tree.yview)
        x_scroll = ttk.Scrollbar(
            tree_frame,
            orient=tk.HORIZONTAL,
            command=lambda *args: self._xview_from_scrollbar(self.incident_rules_tree, *args),
        )
        self.incident_rules_tree.configure(yscrollcommand=scroll.set, xscrollcommand=x_scroll.set)
        self.incident_rules_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        x_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

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
        return values[5] if values and len(values) > 5 else None

    def _selected_client_data(self):
        client_id = self._selected_client_id()
        if not client_id:
            return None, None
        return client_id, self.clients_data.get(client_id)

    def _update_selected_client_panel(self):
        client_id, data = self._selected_client_data()
        if not client_id or not data:
            self.selected_client_info_var.set("Select a client to see basic details.")
            self.selected_client_title_var.set("No client selected")
            self.selected_client_subtitle_var.set("Select a client row to view status and actions.")
            self.selected_client_badge_var.set("Idle")
            if hasattr(self, "selected_client_badge"):
                fg, bg = _tk_badge_colors("waiting")
                self.selected_client_badge.config(fg=fg, bg=bg)
            for var in self.selected_client_fields.values():
                var.set("-")
            self.selected_details_button.config(state=tk.DISABLED)
            self.selected_folders_button.config(state=tk.DISABLED)
            self.selected_actions_button.config(state=tk.DISABLED)
            return

        connected = data.get("connection_status") == "Connected"
        exam_state = _plain(data.get("exam_state"))
        status_label = _plain(data.get("status_label"))
        self.selected_client_title_var.set(_plain(data.get("login_id")))
        self.selected_client_subtitle_var.set(
            f"{_plain(data.get('computer_name'))} | {_plain(data.get('ip'))}"
        )
        self.selected_client_badge_var.set(status_label)
        if hasattr(self, "selected_client_badge"):
            fg, bg = _tk_badge_colors(str(data.get("exam_state") or data.get("status_label") or ""))
            self.selected_client_badge.config(fg=fg, bg=bg)
        values = {
            "connection": _plain(data.get("connection_status")),
            "exam": exam_state,
            "remaining": _format_remaining(data.get("remaining", 0)),
            "status": status_label,
            "ip": _plain(data.get("ip")),
            "computer": _plain(data.get("computer_name")),
            "uuid": _plain(client_id),
            "window": _plain(data.get("last_focus_window")),
            "process": _plain(data.get("last_focus_process")),
            "window_at": _plain(data.get("last_focus_event_at")),
            "window_severity": _plain(data.get("last_focus_severity")),
            "incident_summary": _plain(data.get("latest_incident_summary")),
            "incident_rule": _plain(data.get("latest_incident_rule_id")),
            "incident_severity": _plain(data.get("latest_incident_severity")),
            "incident_status": _plain(data.get("latest_incident_status")),
        }
        for key, value in values.items():
            var = self.selected_client_fields.get(key)
            if var is not None:
                var.set(value)
        self.selected_details_button.config(state=tk.NORMAL)
        self.selected_folders_button.config(state=tk.NORMAL)
        self.selected_actions_button.config(state=tk.NORMAL if connected or data else tk.DISABLED)

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

    def _selected_incident_rule_key(self):
        selected = self.incident_rules_tree.selection()
        if not selected:
            return None
        values = self.incident_rules_tree.item(selected[0], "values")
        return values[0] if values else None

    def _selected_incident_rule_row(self):
        rule_key = self._selected_incident_rule_key()
        if not rule_key:
            return None
        for row in self.incident_rules_data:
            if str(row.get("rule_key", "") or "") == str(rule_key):
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

    def _update_client_remaining_cells(self, client_ids: set[str]):
        changed = False
        for client_id in client_ids:
            item_id = self.tree_items.get(client_id)
            if not item_id or not self.tree.exists(item_id):
                continue
            values = list(self.tree.item(item_id, "values"))
            if len(values) < 3:
                continue
            next_remaining = _format_remaining(self.clients_data.get(client_id, {}).get("remaining", 0))
            if str(values[2]) == next_remaining:
                continue
            values[2] = next_remaining
            self.tree.item(item_id, values=tuple(values))
            changed = True
        if changed:
            visible_rows = []
            for item_id in self.tree.get_children():
                values = self.tree.item(item_id, "values")
                if len(values) > 5:
                    visible_rows.append((str(values[5]), values))
            self._row_snapshots["clients"] = row_snapshot(visible_rows)

    def update_timers(self):
        changed_client_ids: set[str] = set()
        for client_id, data in self.clients_data.items():
            if data.get("exam_state") != "Running":
                continue
            if data.get("remaining", 0) <= 0:
                continue
            data["remaining"] -= 1
            changed_client_ids.add(client_id)
        if changed_client_ids:
            self._update_client_remaining_cells(changed_client_ids)
            self._update_selected_client_panel()

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
            _emit_command(
                {
                    "cmd": "kill_pid",
                    "uuid": incident.get("client_id"),
                    "incident_id": incident.get("incident_id"),
                    "process_name": incident.get("process_name") or "Unknown",
                    "pid": int(incident.get("pid", 0) or 0),
                }
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
        _emit_command(
            {
                "cmd": command,
                "uuid": incident.get("client_id"),
                "incident_id": incident.get("incident_id"),
            }
        )
        self._append_log(
            f"[ADMIN] Sent {command} for user {incident.get('login_id') or incident.get('client_id')}"
        )

    def _emit_incident_user_commands(self, command: str, incidents: list[dict]):
        for incident in incidents:
            _emit_command(
                {
                    "cmd": command,
                    "uuid": incident.get("client_id"),
                    "incident_id": incident.get("incident_id"),
                }
            )
        self._append_log(
            f"[ADMIN] Sent {command} for {len(incidents)} selected user(s)"
        )

    def _update_incident_detail(self):
        if self._incident_tree_refreshing:
            return
        incidents = self._selected_incidents()
        yview = self.incident_detail.yview()
        xview = self.incident_detail.xview()
        for item_id in self.incident_detail.get_children():
            self.incident_detail.delete(item_id)
        rows: list[tuple[str, str]] = []
        if len(incidents) == 1:
            rows = _incident_detail_lines(incidents[0])
        elif incidents:
            rows = _multi_incident_detail_lines(incidents)
        for field, value in rows:
            self.incident_detail.insert("", tk.END, values=(field, value))
        self._restore_tree_scroll(self.incident_detail, yview, xview)
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
                self.save_incident_rule_button,
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
        self.save_incident_rule_button.config(state=tk.NORMAL if len(incidents) == 1 else tk.DISABLED)

    def start_exam_globally(self):
        _emit_command({"cmd": "start_exam_global"})
        self._append_log("[ADMIN] Enabled exam start globally")

    def finish_exam_globally(self):
        _emit_command({"cmd": "finish_exam_global"})
        self._append_log("[ADMIN] Requested global exam finish")

    def edit_policy(self):
        _emit_command({"cmd": "edit_policy"})
        self._append_log("[ADMIN] Opening exam policy file")

    def apply_policy(self):
        _emit_command({"cmd": "apply_policy"})
        self._append_log("[ADMIN] Applying exam policy")

    def edit_process_definitions(self):
        _emit_command({"cmd": "edit_process_definitions"})
        self._append_log("[ADMIN] Opening process definitions file")

    def apply_process_definitions(self):
        _emit_command({"cmd": "apply_process_definitions"})
        self._append_log("[ADMIN] Applying process definitions")

    def edit_incident_rules(self):
        _emit_command({"cmd": "edit_incident_rules"})
        self._append_log("[ADMIN] Opening incident rules file")

    def apply_incident_rules(self):
        _emit_command({"cmd": "apply_incident_rules"})
        self._append_log("[ADMIN] Applying incident rules")

    def save_selected_incident_as_rule(self):
        incident = self._selected_incident()
        if not incident:
            return
        self.show_incident_rule_decision_window(self._incident_to_rule_row(incident))

    def _incident_to_rule_row(self, incident: dict) -> dict:
        return incident_rule_row_from_incident(incident, getattr(self, "settings_snapshot", {}))

    def show_incident_rule_decision_window(self, row: dict | None = None):
        row = row or self._selected_incident_rule_row()
        if not row:
            messagebox.showinfo("Incident Rules", "Select an incident rule entry first.")
            return
        key = ("incident_rule_decision", str(row.get("rule_key") or row.get("source_incident_id") or id(row)))
        if key in self.open_windows and self.open_windows[key].winfo_exists():
            self.open_windows[key].lift()
            return

        top = tk.Toplevel(self)
        top.title(f"Incident Rule: {row.get('name') or 'Rule'}")
        top.geometry("940x680")
        top.minsize(760, 540)
        self._register_window(key, top)

        frame = ttk.Frame(top, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=1)

        identity = ttk.LabelFrame(frame, text="Rule Match")
        identity.grid(row=0, column=0, sticky=tk.EW, pady=(0, 10))
        identity.columnconfigure(1, weight=1)
        rows = [
            ("Name", row.get("name") or "-"),
            ("Rule ID", row.get("rule_id") or "-"),
            ("Event Type", row.get("event_type") or "-"),
            ("Source", row.get("source") or "-"),
            ("Observed Title", incident_rule_observed_window_title(row) or "-"),
            ("Matches", str(row.get("match_count", 0) or len(row.get("matching_history", [])))),
        ]
        for index, (label, value) in enumerate(rows):
            ttk.Label(identity, text=f"{label}:").grid(row=index, column=0, sticky=tk.W, padx=(8, 8), pady=2)
            ttk.Label(identity, text=str(value), style="Mono.TLabel", wraplength=760).grid(row=index, column=1, sticky=tk.W, pady=2)

        match_fields = ttk.LabelFrame(frame, text="Saved Match Fields")
        match_fields.grid(row=1, column=0, sticky=tk.EW, pady=(0, 10))
        match_fields.columnconfigure(1, weight=1)
        ttk.Label(match_fields, text="Title Patterns").grid(row=0, column=0, sticky=tk.NW, padx=(8, 8), pady=4)
        title_text = tk.Text(match_fields, height=3, width=78, font=self.mono_font, wrap=tk.WORD)
        style_text_widget(title_text)
        title_text.insert("1.0", incident_rule_field_text(row, "window_title_patterns"))
        title_text.grid(row=0, column=1, sticky=tk.EW, pady=4)
        ttk.Label(match_fields, text="Match Mode").grid(row=1, column=0, sticky=tk.W, padx=(8, 8), pady=4)
        match_mode_var = tk.StringVar(value=str(row.get("match_mode") or "contains"))
        ttk.Combobox(match_fields, textvariable=match_mode_var, values=("contains", "exact"), state="readonly", width=14).grid(
            row=1, column=1, sticky=tk.W, pady=4
        )
        ttk.Label(match_fields, text="Processes").grid(row=2, column=0, sticky=tk.NW, padx=(8, 8), pady=4)
        process_text = tk.Text(match_fields, height=2, width=78, font=self.mono_font, wrap=tk.NONE)
        style_text_widget(process_text)
        process_text.insert("1.0", incident_rule_field_text(row, "process_names"))
        process_text.grid(row=2, column=1, sticky=tk.EW, pady=4)
        ttk.Label(match_fields, text="Browser Processes").grid(row=3, column=0, sticky=tk.NW, padx=(8, 8), pady=4)
        browser_text = tk.Text(match_fields, height=2, width=78, font=self.mono_font, wrap=tk.NONE)
        style_text_widget(browser_text)
        browser_text.insert("1.0", incident_rule_field_text(row, "browser_process_names"))
        browser_text.grid(row=3, column=1, sticky=tk.EW, pady=4)

        controls = ttk.LabelFrame(frame, text="Decision")
        controls.grid(row=2, column=0, sticky=tk.EW, pady=(0, 10))
        for column in range(5):
            controls.columnconfigure(column, weight=1)
        status_var = tk.StringVar(value=str(row.get("status") or "unknown"))
        save_var = tk.BooleanVar(value=True)
        priority_var = tk.StringVar(value=str(row.get("priority", 0) or 0))
        action_vars = {
            "ban": tk.BooleanVar(value=bool(row.get("actions", {}).get("ban", False))),
            "kick": tk.BooleanVar(value=bool(row.get("actions", {}).get("kick", False))),
            "pause_exam": tk.BooleanVar(value=bool(row.get("actions", {}).get("pause_exam", False))),
            "kill_pid": tk.BooleanVar(value=bool(row.get("actions", {}).get("kill_pid", False))),
        }
        ttk.Label(controls, text="Status").grid(row=0, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Combobox(controls, textvariable=status_var, values=("unknown", "whitelist", "warning", "blacklist"), state="readonly").grid(row=0, column=1, sticky=tk.EW, padx=(0, 12), pady=6)
        ttk.Label(controls, text="Priority").grid(row=0, column=2, sticky=tk.W, padx=8, pady=6)
        ttk.Entry(controls, textvariable=priority_var, width=10).grid(row=0, column=3, sticky=tk.EW, padx=(0, 12), pady=6)
        ttk.Checkbutton(controls, text="Ban", variable=action_vars["ban"]).grid(row=1, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Checkbutton(controls, text="Kick", variable=action_vars["kick"]).grid(row=1, column=1, sticky=tk.W, padx=8, pady=6)
        ttk.Checkbutton(controls, text="Pause Exam", variable=action_vars["pause_exam"]).grid(row=1, column=2, sticky=tk.W, padx=8, pady=6)
        ttk.Checkbutton(controls, text="Kill PID", variable=action_vars["kill_pid"]).grid(row=1, column=3, sticky=tk.W, padx=8, pady=6)
        ttk.Checkbutton(controls, text="Save decision to policy", variable=save_var).grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=8, pady=6)
        ttk.Button(
            controls,
            text="Apply Rule",
            command=lambda: self._emit_incident_rule_decision(
                top,
                row,
                status_var.get(),
                {name: var.get() for name, var in action_vars.items()},
                save_var.get(),
                priority_var.get(),
                split_multiline_values(title_text.get("1.0", tk.END)),
                match_mode_var.get(),
                split_multiline_values(process_text.get("1.0", tk.END), split_commas=True),
                split_multiline_values(browser_text.get("1.0", tk.END), split_commas=True),
            ),
        ).grid(row=2, column=3, columnspan=2, sticky=tk.EW, padx=8, pady=6)

        history_frame = ttk.LabelFrame(frame, text="Matching Incidents")
        history_frame.grid(row=3, column=0, sticky=tk.NSEW)
        history_columns = ("student", "rule", "status", "pid", "active", "summary")
        history_tree = ttk.Treeview(history_frame, columns=history_columns, show="headings", style="Monospace.Treeview")
        for column, text, width in (
            ("student", "Student", 130),
            ("rule", "Rule", 150),
            ("status", "Status", 90),
            ("pid", "PID", 70),
            ("active", "Active", 70),
            ("summary", "Summary", 430),
        ):
            history_tree.heading(column, text=text)
            history_tree.column(column, width=width, minwidth=60, anchor=tk.W)
        history_scroll = ttk.Scrollbar(history_frame, orient=tk.VERTICAL, command=history_tree.yview)
        history_tree.configure(yscrollcommand=history_scroll.set)
        history_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        history_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        for entry in row.get("matching_history", []):
            history_tree.insert(
                "",
                tk.END,
                values=(
                    entry.get("login_id") or entry.get("client_id") or "-",
                    entry.get("rule_id") or "-",
                    entry.get("status") or "-",
                    entry.get("pid") or "-",
                    "Yes" if entry.get("active") else "No",
                    entry.get("summary") or "-",
                ),
            )

    def _emit_incident_rule_decision(
        self,
        window,
        row: dict,
        status: str,
        actions: dict,
        save_policy: bool,
        priority_text: str,
        window_title_patterns: list[str],
        match_mode: str,
        process_names: list[str],
        browser_process_names: list[str],
    ):
        try:
            priority = int(str(priority_text or "0").strip())
        except ValueError:
            messagebox.showwarning("Incident Rule", "Priority must be an integer.")
            return
        payload = build_incident_rule_decision_payload(
            row,
            status=status,
            actions=actions,
            save_policy=save_policy,
            priority=priority,
            process_names=process_names,
            browser_process_names=browser_process_names,
            window_title_patterns=window_title_patterns,
            match_mode=match_mode,
        )
        self._emit_command(payload)
        window.destroy()
        self._append_log(f"[ADMIN] Applied incident rule decision for {row.get('name') or row.get('rule_key')}")

    def export_settings(self):
        path = filedialog.asksaveasfilename(
            title="Export Settings",
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return
        _emit_command({"cmd": "export_settings", "path": path})
        self._append_log(f"[ADMIN] Exporting settings to {path}")

    def import_settings(self):
        path = filedialog.askopenfilename(
            title="Import Settings",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return
        _emit_command({"cmd": "import_settings", "path": path})
        self._append_log(f"[ADMIN] Importing settings from {path}")

    def toggle_remember_settings(self):
        _emit_command(
            {
                "cmd": "set_remember_settings",
                "remember": bool(self.remember_settings_var.get()),
            }
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

        _emit_command({"type": "console_command", "command": command})
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

        for client_id in list(self.clients_data.keys()):
            if client_id in seen_client_ids:
                continue
            self.clients_data.pop(client_id, None)

        self._rebuild_client_tree()
        incidents = payload.get("incidents", [])
        self.incidents_data = incidents
        self._rebuild_incident_tree()
        self.process_database_data = payload.get("process_database", [])
        self._rebuild_process_database_tree()
        self.incident_rules_data = payload.get("incident_rules_database", [])
        self._rebuild_incident_rules_tree()
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
        all_host_ips = ", ".join(str(ip) for ip in info.get("all_host_ips", []) if str(ip).strip()) or "-"
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
            f"All Host IPv4s: {all_host_ips}\n"
            f"Exam Phase: {exam_phase}"
            f"    Exam Start: {start_enabled}"
            f"    Duration: {info.get('exam_duration_minutes', '-')} min\n"
            f"Exam Files: {has_exam_files}"
            f"    Active Incidents: {info.get('active_incident_count', 0)}"
            f"    Total Incidents: {info.get('incident_count', 0)}\n"
            "Use Detailed Info for full configuration."
        )
        self.server_info_var.set(text)

    def _client_tree_rows(self):
        sort_column, descending = self.sort_state.get("clients", ("login_id", False))
        return [
            (
                client_id,
                (
                    data.get("login_id", ""),
                    data.get("status_label", "Unknown"),
                    _format_remaining(data.get("remaining", 0)),
                    client_window_title(data),
                    data.get("ip") or "",
                    client_id,
                ),
            )
            for client_id, data in sorted_client_items(
                self.clients_data,
                self._active_filters("clients"),
                sort_column,
                descending,
            )
        ]

    def _incident_tree_rows(self):
        sort_column, descending = self.sort_state.get("incidents", ("time", True))
        rows = []
        for incident in sorted_incidents(
            self.incidents_data,
            self._active_filters("incidents"),
            sort_column,
            descending,
        ):
            incident_id = str(incident.get("incident_id", "") or "")
            status_text = str(incident.get("status", "") or "")
            if incident.get("active"):
                status_text = f"{status_text} (active)"
            rows.append(
                (
                    incident_id,
                    (
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
                    ),
                )
            )
        return rows

    def _process_tree_rows(self):
        sort_column, descending = self.sort_state.get("processes", ("executable", False))
        return [
            (
                str(row.get("process_key", "") or ""),
                (
                    str(row.get("process_key", "") or ""),
                    row.get("process_name") or row.get("normalized_process_name") or "",
                    row.get("status", ""),
                    process_path_display(row),
                    row.get("match_scope", ""),
                    row.get("match_count", 0),
                    affected_students_display(row),
                    row.get("last_seen", ""),
                    row.get("saved_action_labels", ""),
                    format_process_action_availability(row),
                ),
            )
            for row in sorted_process_rows(
                self.process_database_data,
                self._active_filters("processes"),
                sort_column,
                descending,
            )
        ]

    def _incident_rule_tree_rows(self):
        sort_column, descending = self.sort_state.get("incident_rules", ("last_seen", True))
        return [
            (
                str(row.get("rule_key", "") or ""),
                (
                    str(row.get("rule_key", "") or ""),
                    row.get("name") or "",
                    row.get("status", ""),
                    incident_rule_match_display(row),
                    row.get("match_count", 0),
                    affected_students_display(row),
                    row.get("last_seen", ""),
                    row.get("saved_action_labels", ""),
                    format_process_action_availability(row),
                ),
            )
            for row in sorted_incident_rule_rows(
                self.incident_rules_data,
                self._active_filters("incident_rules"),
                sort_column,
                descending,
            )
        ]

    def _rebuild_client_tree(self):
        selected_id = self._selected_client_id()
        focus_item = self.tree.focus()
        focus_values = self.tree.item(focus_item, "values") if focus_item else ()
        focused_id = str(focus_values[5]) if focus_values and len(focus_values) > 5 else ""
        yview = self.tree.yview()
        xview = self.tree.xview()
        restored_selection = ""
        restored_focus = ""
        self._configure_sort_headings(self.tree, "clients", CLIENT_COLUMNS, self._rebuild_client_tree)
        rows, snapshot, previous, force_rebuild = self._prepare_rows_for_refresh("clients", self._client_tree_rows())
        if not force_rebuild and same_row_order(previous, snapshot):
            for index in changed_row_indexes(previous, snapshot):
                key, values = rows[index]
                item_id = self.tree_items.get(str(key))
                if item_id and self.tree.exists(item_id):
                    self.tree.item(item_id, values=values)
            self._row_snapshots["clients"] = snapshot
            self._update_selected_client_panel()
            return

        for item_id in self.tree.get_children():
            self.tree.delete(item_id)
        self.tree_items = {}

        for client_id, values in rows:
            item_id = self.tree.insert("", tk.END, values=values)
            self.tree_items[client_id] = item_id
            if selected_id and client_id == selected_id:
                restored_selection = item_id
            if focused_id and client_id == focused_id:
                restored_focus = item_id

        if restored_selection:
            self.tree.selection_set(restored_selection)
        else:
            self.tree.selection_remove(self.tree.selection())

        if restored_focus:
            self.tree.focus(restored_focus)
        elif restored_selection:
            self.tree.focus(restored_selection)

        if yview:
            self._restore_tree_scroll(self.tree, yview, xview)
        self._row_snapshots["clients"] = snapshot
        self._update_selected_client_panel()

    def _rebuild_incident_tree(self):
        selected_incidents = set(self._selected_incident_ids())
        focus_item = self.incident_tree.focus()
        focus_values = self.incident_tree.item(focus_item, "values") if focus_item else ()
        focused_incident_id = str(focus_values[0]) if focus_values else ""
        yview = self.incident_tree.yview()
        xview = self.incident_tree.xview()
        restored_selection: list[str] = []
        restored_focus = ""
        self._configure_sort_headings(self.incident_tree, "incidents", self.incident_columns, self._rebuild_incident_tree)
        rows, snapshot, previous, force_rebuild = self._prepare_rows_for_refresh("incidents", self._incident_tree_rows())

        self._incident_tree_refreshing = True
        try:
            if not force_rebuild and same_row_order(previous, snapshot):
                for index in changed_row_indexes(previous, snapshot):
                    key, values = rows[index]
                    item_id = self.incident_items.get(str(key))
                    if item_id and self.incident_tree.exists(item_id):
                        self.incident_tree.item(item_id, values=values)
                self._row_snapshots["incidents"] = snapshot
                self._incident_tree_refreshing = False
                self._update_incident_detail()
                return

            for item_id in self.incident_tree.get_children():
                self.incident_tree.delete(item_id)
            self.incident_items = {}

            for incident_id, values in rows:
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

            self._restore_tree_scroll(self.incident_tree, yview, xview)
            self._row_snapshots["incidents"] = snapshot
        finally:
            self._incident_tree_refreshing = False

        self._update_incident_detail()

    def _rebuild_process_database_tree(self):
        selected_key = self._selected_process_key()
        focus_item = self.process_tree.focus()
        focus_values = self.process_tree.item(focus_item, "values") if focus_item else ()
        focused_key = str(focus_values[0]) if focus_values else ""
        yview = self.process_tree.yview()
        xview = self.process_tree.xview()
        restored_selection = ""
        restored_focus = ""
        self._configure_sort_headings(self.process_tree, "processes", PROCESS_COLUMNS, self._rebuild_process_database_tree)
        rows, snapshot, previous, force_rebuild = self._prepare_rows_for_refresh("processes", self._process_tree_rows())

        self._process_tree_refreshing = True
        try:
            if not force_rebuild and same_row_order(previous, snapshot):
                for index in changed_row_indexes(previous, snapshot):
                    key, values = rows[index]
                    item_id = self.process_database_items.get(str(key))
                    if item_id and self.process_tree.exists(item_id):
                        self.process_tree.item(item_id, values=values)
                self._row_snapshots["processes"] = snapshot
                self._process_tree_refreshing = False
                self._sync_process_buttons()
                return

            for item_id in self.process_tree.get_children():
                self.process_tree.delete(item_id)
            self.process_database_items = {}

            for process_key, values in rows:
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

            self._restore_tree_scroll(self.process_tree, yview, xview)
            self._row_snapshots["processes"] = snapshot
        finally:
            self._process_tree_refreshing = False
        self._sync_process_buttons()

    def _rebuild_incident_rules_tree(self):
        selected_key = self._selected_incident_rule_key()
        focus_item = self.incident_rules_tree.focus()
        focus_values = self.incident_rules_tree.item(focus_item, "values") if focus_item else ()
        focused_key = str(focus_values[0]) if focus_values else ""
        yview = self.incident_rules_tree.yview()
        xview = self.incident_rules_tree.xview()
        restored_selection = ""
        restored_focus = ""
        self._configure_sort_headings(self.incident_rules_tree, "incident_rules", INCIDENT_RULE_COLUMNS, self._rebuild_incident_rules_tree)
        rows, snapshot, previous, force_rebuild = self._prepare_rows_for_refresh("incident_rules", self._incident_rule_tree_rows())

        self._incident_rules_tree_refreshing = True
        try:
            if not force_rebuild and same_row_order(previous, snapshot):
                for index in changed_row_indexes(previous, snapshot):
                    key, values = rows[index]
                    item_id = self.incident_rules_items.get(str(key))
                    if item_id and self.incident_rules_tree.exists(item_id):
                        self.incident_rules_tree.item(item_id, values=values)
                self._row_snapshots["incident_rules"] = snapshot
                self._incident_rules_tree_refreshing = False
                self._sync_incident_rule_buttons()
                return

            for item_id in self.incident_rules_tree.get_children():
                self.incident_rules_tree.delete(item_id)
            self.incident_rules_items = {}

            for rule_key, values in rows:
                item_id = self.incident_rules_tree.insert("", tk.END, values=values)
                self.incident_rules_items[rule_key] = item_id
                if selected_key and rule_key == selected_key:
                    restored_selection = item_id
                if focused_key and rule_key == focused_key:
                    restored_focus = item_id

            if restored_selection:
                self.incident_rules_tree.selection_set(restored_selection)
            else:
                self.incident_rules_tree.selection_remove(self.incident_rules_tree.selection())

            if restored_focus:
                self.incident_rules_tree.focus(restored_focus)
            elif restored_selection:
                self.incident_rules_tree.focus(restored_selection)

            self._restore_tree_scroll(self.incident_rules_tree, yview, xview)
            self._row_snapshots["incident_rules"] = snapshot
        finally:
            self._incident_rules_tree_refreshing = False
        self._sync_incident_rule_buttons()

    def _sync_process_buttons(self):
        has_selection = self._selected_process_row() is not None
        state_name = tk.NORMAL if has_selection else tk.DISABLED
        self.process_options_button.config(state=state_name)
        self.process_google_button.config(state=state_name)

    def _sync_incident_rule_buttons(self):
        state_name = tk.NORMAL if self._selected_incident_rule_row() is not None else tk.DISABLED
        self.incident_rule_options_button.config(state=state_name)


def ipc_reader(app: ServerGUI):
    for line in iter_stdin_lines():
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            write_text_stderr(f"[DEBUG] GUI IPC Error: {e}")
            continue

        message_type = msg.get("type")
        if message_type == "state_update":
            app.after(0, app.process_state_update, msg)
        elif message_type == "client_message":
            app.after(0, app.log_message, msg.get("uuid"), msg.get("text"))
        elif message_type == "settings_result":
            app.after(0, app.process_settings_result, msg)

    # When the parent server process exits, stdin pipe closes.
    # In managed mode, close the dashboard instead of leaving an orphan window.
    if not app.standalone_mode:
        try:
            app.after(0, app.destroy)
        except Exception:
            pass


def _ipc_message_handler(app: ServerGUI, msg: dict):
    if msg.get("channel") != "server.dashboard_state":
        return
    payload = msg.get("data", {})
    if not isinstance(payload, dict):
        return
    message_type = payload.get("type")
    if message_type == "state_update":
        app.after(0, app.process_state_update, payload)
    elif message_type == "client_message":
        app.after(0, app.log_message, payload.get("uuid"), payload.get("text"))
    elif message_type == "settings_result":
        app.after(0, app.process_settings_result, payload)


def run() -> int:
    global _IPC_CLIENT
    setup_runtime_logging(
        "server_gui",
        PROJECT_DIR / "data" / "logs" / "server",
    )
    use_ws_ipc = should_use_ws_ipc()
    app = ServerGUI(standalone_mode=stdin_is_standalone() and not use_ws_ipc)
    if use_ws_ipc:
        _IPC_CLIENT = ThreadedIpcClient(
            role="dashboard_gui",
            on_message=lambda message: _ipc_message_handler(app, message),
        )
        if not _IPC_CLIENT.start():
            _IPC_CLIENT = None
            if not stdin_available():
                app.standalone_mode = True
    if stdin_available():
        reader_thread = Thread(target=ipc_reader, args=(app,), daemon=True)
        reader_thread.start()
    app.mainloop()
    if _IPC_CLIENT:
        _IPC_CLIENT.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

