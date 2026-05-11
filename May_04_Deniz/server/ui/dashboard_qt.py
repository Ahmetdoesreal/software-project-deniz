"""Qt server monitor dashboard.

Mirrors ``server.ui.dashboard_tk`` and is selected by ``server.gui --ui qt``.
"""

from __future__ import annotations

import faulthandler
import json
import queue
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from threading import Thread
from typing import Optional


PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


def _missing_pyside6_message() -> str:
    return (
        "PySide6 is required for the Qt UI. Install it with:\n"
        "    pip install PySide6\n"
        "Or run the legacy interface with: --ui tk"
    )


from common.stdio_compat import iter_stdin_lines, stdin_available, stdin_is_standalone, write_json_stdout, write_text_stderr


try:
    from PySide6.QtCore import QEvent, Qt, QObject, QTimer, Signal
    from PySide6.QtGui import QBrush, QColor, QFont
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QCheckBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QSplitter,
        QStatusBar,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )
    from server.ui.policy_settings_qt import IncidentRuleDecisionDialog, PolicySettingsDialog, ProcessDecisionDialog
except ImportError:  # pragma: no cover - import guard
    write_text_stderr(_missing_pyside6_message())
    raise

from common.runtime_logging import setup_runtime_logging
from common.ipc_ws import ThreadedIpcClient, should_use_ws_ipc
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
    sorted_incidents,
    sorted_incident_rule_rows,
    sorted_process_rows,
)
from server.ui.policy_settings_tk import PolicySettingsMixin
from server.ui.process_database_helpers import (
    build_process_decision_payload,
    process_row_google_search_url,
)
from server.ui.row_refresh import (
    RowSnapshot,
    changed_row_indexes,
    reorder_rows_by_previous_keys,
    row_snapshot,
    same_row_order,
)
from ui.widgets import apply_glass_theme, make_button, monospace_font, style_button
from ui.theme import M, STATE_COLORS
from ui.styles import state_badge_style
from ui.background import StarfieldBackground


CLIENT_COLUMN_WIDTHS = {
    "login_id": (130, 90),
    "status": (130, 100),
    "remaining": (105, 85),
    "window_title": (300, 160),
    "ip": (145, 110),
    "uuid": (280, 160),
}

INCIDENT_COLUMN_WIDTHS = {
    "incident_id": (0, 0),
    "time": (165, 120),
    "user": (120, 90),
    "severity": (100, 80),
    "rule": (170, 120),
    "source": (120, 90),
    "process": (150, 100),
    "pid": (90, 70),
    "auto_action": (130, 100),
    "status": (120, 90),
}

PROCESS_COLUMN_WIDTHS = {
    "process_key": (0, 0),
    "executable": (170, 110),
    "status": (100, 80),
    "path": (360, 180),
    "scope": (100, 80),
    "matches": (90, 70),
    "students": (180, 120),
    "last_seen": (165, 120),
    "actions": (155, 110),
    "availability": (245, 150),
}

INCIDENT_RULE_COLUMN_WIDTHS = {
    "rule_key": (0, 0),
    "name": (180, 110),
    "status": (100, 80),
    "match": (380, 170),
    "matches": (90, 70),
    "students": (180, 120),
    "last_seen": (165, 120),
    "actions": (155, 110),
    "availability": (245, 150),
}

_IPC_CLIENT = None


def _monospace_font() -> QFont:
    return monospace_font()


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
                [
                    str(incident.get("auto_action_state_label") or incident.get("auto_action_state") or "-")
                    for incident in incidents
                ]
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


def _emit_command(payload: dict) -> None:
    if _IPC_CLIENT and _IPC_CLIENT.send("dashboard.command", payload):
        return
    write_json_stdout(payload)


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


def _configure_table_columns(widget, columns, widths: dict[str, tuple[int, int]]) -> None:
    header = widget.horizontalHeader() if hasattr(widget, "horizontalHeader") else widget.header()
    header.setSectionsMovable(False)
    header.setStretchLastSection(False)
    header.setMinimumSectionSize(70)
    minimums: dict[int, int] = {}
    for index, (column, _label) in enumerate(columns):
        width, minimum = widths.get(column, (140, 80))
        hidden = width <= 0 or minimum <= 0
        widget.setColumnHidden(index, hidden)
        header.setSectionResizeMode(index, QHeaderView.Fixed if hidden else QHeaderView.Interactive)
        if hidden:
            header.resizeSection(index, 0)
            continue
        minimums[index] = minimum
        header.resizeSection(index, max(width, minimum))

    def _clamp_section(index: int, _old_size: int, new_size: int) -> None:
        minimum = minimums.get(index)
        if minimum is None or new_size >= minimum:
            return
        header.blockSignals(True)
        try:
            header.resizeSection(index, minimum)
        finally:
            header.blockSignals(False)

    header.sectionResized.connect(_clamp_section)


def _plain(value) -> str:
    text = str(value or "").strip()
    return text or "-"


class _IPCSignals(QObject):
    parent_closed = Signal()


class _DetailsDialog(QDialog):
    def __init__(self, title: str, rows: list[tuple[str, str]], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 460)
        layout = QVBoxLayout(self)
        table = QTableWidget(len(rows), 2, self)
        table.setHorizontalHeaderLabels(["Field", "Value"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setFont(_monospace_font())
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(90)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.resizeSection(0, 190)
        header.resizeSection(1, 340)
        for row, (field, value) in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(field))
            table.setItem(row, 1, QTableWidgetItem(value))
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        buttons.accepted.connect(self.close)
        layout.addWidget(buttons)


class _OptionsDialog(QDialog):
    def __init__(
        self,
        client_id: str,
        data: dict,
        send_command,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.client_id = client_id
        self.data = data or {}
        self.send_command = send_command
        login = self.data.get("login_id", "Unknown")
        self.setWindowTitle(f"Options: {login}")
        self.resize(430, 500)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("User Actions:"))

        connected = self.data.get("connection_status") == "Connected"

        kick_btn = make_button("Kick Client", "outlined")
        kick_btn.setEnabled(connected)
        kick_btn.clicked.connect(lambda: self._send_and_close("kick"))
        layout.addWidget(kick_btn)

        ban_btn = make_button("Ban User", "outlined")
        ban_btn.clicked.connect(lambda: self._send_and_close("ban"))
        layout.addWidget(ban_btn)

        pause_btn = make_button("Pause Exam", "tonal")
        pause_btn.clicked.connect(lambda: self._send_and_close("pause_exam"))
        layout.addWidget(pause_btn)

        resume_btn = make_button("Resume Exam", "filled")
        resume_btn.clicked.connect(lambda: self._send_and_close("resume_exam"))
        layout.addWidget(resume_btn)

        unban_btn = make_button("Unban User", "text")
        unban_btn.clicked.connect(lambda: self._send_and_close("unban"))
        layout.addWidget(unban_btn)

        layout.addSpacing(8)
        layout.addWidget(QLabel("Connected Client Commands:"))
        savescreen_btn = make_button("Request Save Screen", "text")
        savescreen_btn.setEnabled(connected)
        savescreen_btn.clicked.connect(lambda: self._send_and_close("savescreen"))
        layout.addWidget(savescreen_btn)
        process_btn = make_button("Request Process Report", "text")
        process_btn.setEnabled(connected)
        process_btn.clicked.connect(lambda: self._send_and_close("get_processes"))
        layout.addWidget(process_btn)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Add Minutes:"))
        self.minutes_entry = QLineEdit()
        self.minutes_entry.setMaximumWidth(80)
        time_row.addWidget(self.minutes_entry)
        apply_btn = make_button("Apply", "filled")
        apply_btn.clicked.connect(self._apply_add_time)
        time_row.addWidget(apply_btn)
        time_row.addStretch(1)
        layout.addLayout(time_row)

        layout.addStretch(1)

    def _send_and_close(self, command: str) -> None:
        self.send_command({"cmd": command, "uuid": self.client_id})
        self.close()

    def _apply_add_time(self) -> None:
        minutes_text = self.minutes_entry.text().strip()
        if not minutes_text:
            QMessageBox.warning(self, "Add Time", "Enter a number of minutes first.")
            return
        self.send_command(
            {"type": "console_command", "command": f"/addtime {self.client_id} {minutes_text}"}
        )
        self.close()


class ServerGUI(PolicySettingsMixin, DashboardPopupMixin, QMainWindow):
    INCIDENT_COLUMNS = [
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
    ]

    def __init__(self, *, standalone_mode: bool = False) -> None:
        super().__init__()
        self.standalone_mode = standalone_mode
        self.clients_data: dict[str, dict] = {}
        self.incidents_data: list[dict] = []
        self.process_database_data: list[dict] = []
        self.incident_rules_data: list[dict] = []
        self.process_database_items: dict[str, str] = {}
        self.incident_rules_items: dict[str, str] = {}
        self.server_info: dict = {}
        self.settings_snapshot: dict = {}
        self._open_dialogs: dict[tuple[str, str], QDialog] = {}
        self.filter_checks: dict[str, dict[str, QCheckBox]] = {}
        self.sort_state: dict[str, tuple[str, bool]] = {
            "clients": ("login_id", False),
            "incidents": ("time", True),
            "processes": ("executable", False),
            "incident_rules": ("last_seen", True),
        }
        self._mono = _monospace_font()
        self._allow_close = False
        self._incident_tree_refreshing = False
        self._process_tree_refreshing = False
        self._incident_rules_tree_refreshing = False
        self._row_snapshots: dict[str, RowSnapshot] = {}
        self._force_table_rebuilds: set[str] = set()
        self._hover_rows: dict[object, int] = {}
        self._hover_tree_items: dict[object, QTreeWidgetItem | None] = {}
        self._hover_viewports: dict[object, object] = {}
        self._hover_brush = QBrush(QColor(255, 255, 255, 18))

        self.setWindowTitle("Server Monitor Dashboard")
        self.resize(1200, 760)
        self.setMinimumSize(1000, 680)

        self._build_layout()

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick_running_timers)
        self._tick_timer.start()

    # ------------------------------------------------------------------ tk compat shims
    def after(self, delay_ms: int, func, *args) -> None:
        """Compatibility shim: mirrors tk.Tk.after() for mixin code."""
        QTimer.singleShot(delay_ms, lambda: func(*args))

    def open_policy_settings_window(self) -> None:
        key = ("policy_settings", "window")
        if self._focus_existing_dialog(key):
            return
        
        dialog = PolicySettingsDialog(parent=self)
        self.policy_dialog = dialog
        self._register_dialog(key, dialog)
        
        dialog.settings_saved.connect(self._on_settings_saved)
        dialog.export_requested.connect(self.export_settings)
        dialog.import_requested.connect(self.import_settings)
        dialog.edit_policy_requested.connect(self.edit_policy)
        dialog.apply_policy_requested.connect(self.apply_policy)
        dialog.edit_definitions_requested.connect(self.edit_process_definitions)
        dialog.apply_definitions_requested.connect(self.apply_process_definitions)
        dialog.edit_incident_rules_requested.connect(self.edit_incident_rules)
        dialog.apply_incident_rules_requested.connect(self.apply_incident_rules)
        
        if hasattr(self, 'settings_snapshot') and self.settings_snapshot:
            dialog.update_snapshot(self.settings_snapshot)
            
        dialog.show()

    def _on_settings_saved(self, payload: dict):
        _emit_command(payload)
        self._append_log("[ADMIN] Saving GUI settings")

    # ------------------------------------------------------------------ layout
    def _build_layout(self) -> None:
        central = StarfieldBackground(self)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(20, 16, 20, 12)
        outer.setSpacing(10)

        self.tabs = QTabWidget(self)
        outer.addWidget(self.tabs, stretch=1)

        self.overview_tab = QWidget()
        self.rules_tab = QWidget()
        self.process_database_tab = QWidget()
        self.incident_rules_tab = QWidget()
        self.tabs.addTab(self.overview_tab, "Overview")
        self.tabs.addTab(self.rules_tab, "Rule Breakings")
        self.tabs.addTab(self.process_database_tab, "Process Database")
        self.tabs.addTab(self.incident_rules_tab, "Incident Rules")
        self._build_overview_tab()
        self._build_rule_breakings_tab()
        self._build_process_database_tab()
        self._build_incident_rules_tab()

        cmd_row = QHBoxLayout()
        cmd_row.addWidget(QLabel("Admin Command:"))
        self.cmd_entry = QLineEdit()
        self.cmd_entry.returnPressed.connect(self.send_console_command)
        cmd_row.addWidget(self.cmd_entry, stretch=1)
        execute_btn = make_button("Execute", "filled")
        execute_btn.clicked.connect(self.send_console_command)
        cmd_row.addWidget(execute_btn)
        outer.addLayout(cmd_row)

        self.stats_label = QLabel(
            "Connections Managed: 0 | Active: 0 | Disconnected: 0 | "
            "Active Incidents: 0 | Active Warnings: 0"
        )
        self.statusBar().addPermanentWidget(self.stats_label, 1)

    def _build_overview_tab(self) -> None:
        layout = QHBoxLayout(self.overview_tab)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        self._build_server_info_panel(left_layout)
        self._build_client_tree_area(left_layout)
        self._build_log_area(left_layout)

        layout.addWidget(left_widget, stretch=1)
        self._build_action_panel(layout)

    def _build_server_info_panel(self, parent_layout: QVBoxLayout) -> None:
        info_box = QGroupBox("Server Info")
        info_layout = QVBoxLayout(info_box)

        action_row = QHBoxLayout()
        self.start_exam_button = make_button("Start Exam", "filled")
        self.start_exam_button.clicked.connect(self.start_exam_globally)
        action_row.addWidget(self.start_exam_button)
        self.finish_exam_button = make_button("Finish Exam", "outlined")
        self.finish_exam_button.clicked.connect(self.finish_exam_globally)
        action_row.addWidget(self.finish_exam_button)
        action_row.addStretch(1)

        self.policy_settings_button = make_button("Policy Settings", "tonal")
        self.policy_settings_button.clicked.connect(self.open_policy_settings_window)
        action_row.addWidget(self.policy_settings_button)

        self.server_info_detail_button = make_button("Detailed Info", "text")
        self.server_info_detail_button.setEnabled(False)
        self.server_info_detail_button.clicked.connect(self.show_server_info_details)
        action_row.addWidget(self.server_info_detail_button)

        info_layout.addLayout(action_row)

        remember_row = QHBoxLayout()
        self.remember_check = QCheckBox("Remember Settings")
        self.remember_check.setChecked(True)
        self.remember_check.toggled.connect(self.toggle_remember_settings)
        remember_row.addWidget(self.remember_check)
        remember_row.addStretch(1)
        info_layout.addLayout(remember_row)

        self.server_info_label = QLabel("Waiting for server state...")
        self.server_info_label.setFont(self._mono)
        self.server_info_label.setWordWrap(True)
        info_layout.addWidget(self.server_info_label)

        parent_layout.addWidget(info_box)

    def _build_filter_bar(self, parent_layout, table_name: str, filters: tuple[str, ...], rebuild_callback) -> None:
        row = QHBoxLayout()
        row.addWidget(QLabel("Filters:"))
        table_checks: dict[str, QCheckBox] = {}
        self.filter_checks[table_name] = table_checks
        for filter_name in filters:
            check = QCheckBox(filter_name)
            check.setChecked(filter_name == "All")
            check.stateChanged.connect(
                lambda _state, name=filter_name: self._on_filter_toggled(table_name, name, rebuild_callback)
            )
            table_checks[filter_name] = check
            row.addWidget(check)
        row.addStretch(1)
        parent_layout.addLayout(row)

    def _on_filter_toggled(self, table_name: str, filter_name: str, rebuild_callback) -> None:
        checks = self.filter_checks.get(table_name, {})
        if not checks:
            return
        if filter_name == "All" and checks["All"].isChecked():
            for name, check in checks.items():
                if name == "All":
                    continue
                check.blockSignals(True)
                check.setChecked(False)
                check.blockSignals(False)
        elif filter_name != "All" and checks[filter_name].isChecked():
            checks["All"].blockSignals(True)
            checks["All"].setChecked(False)
            checks["All"].blockSignals(False)
        if not any(check.isChecked() for check in checks.values()):
            checks["All"].blockSignals(True)
            checks["All"].setChecked(True)
            checks["All"].blockSignals(False)
        self._force_table_rebuilds.add(table_name)
        rebuild_callback()

    def _active_filters(self, table_name: str) -> set[str]:
        return active_filter_names(
            {name: check.isChecked() for name, check in self.filter_checks.get(table_name, {}).items()}
        )

    def _set_sort(self, table_name: str, column: str, rebuild_callback) -> None:
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

    def _client_headers(self) -> list[str]:
        return [self._heading_text("clients", column, label) for column, label in CLIENT_COLUMNS]

    def _incident_headers(self) -> list[str]:
        return [self._heading_text("incidents", column, label) for column, label in self.INCIDENT_COLUMNS]

    def _refresh_process_headers(self) -> None:
        header_item = self.process_tree.headerItem()
        for index, (column, label) in enumerate(PROCESS_COLUMNS):
            header_item.setText(index, self._heading_text("processes", column, label))

    def _refresh_incident_rule_headers(self) -> None:
        header_item = self.incident_rules_tree.headerItem()
        for index, (column, label) in enumerate(INCIDENT_RULE_COLUMNS):
            header_item.setText(index, self._heading_text("incident_rules", column, label))

    def _prepare_rows_for_refresh(self, table_name: str, rows):
        previous = self._row_snapshots.get(table_name)
        if table_name not in self._force_table_rebuilds:
            rows = reorder_rows_by_previous_keys(rows, previous)
        snapshot = row_snapshot(rows)
        force_rebuild = table_name in self._force_table_rebuilds
        self._force_table_rebuilds.discard(table_name)
        return rows, snapshot, previous, force_rebuild

    def eventFilter(self, watched, event):  # noqa: N802 - Qt API
        if event.type() == QEvent.Leave and watched in self._hover_viewports:
            widget = self._hover_viewports.get(watched)
            if isinstance(widget, QTableWidget):
                self._set_table_hover_row(widget, -1)
            elif isinstance(widget, QTreeWidget):
                self._set_tree_hover_item(widget, None)
        return super().eventFilter(watched, event)

    def _install_table_hover(self, table: QTableWidget) -> None:
        table.setMouseTracking(True)
        table.viewport().setMouseTracking(True)
        table.viewport().installEventFilter(self)
        self._hover_viewports[table.viewport()] = table
        self._hover_rows[table] = -1
        table.itemEntered.connect(lambda item, widget=table: self._set_table_hover_row(widget, item.row()))
        table.itemSelectionChanged.connect(lambda widget=table: self._refresh_table_hover(widget))

    def _install_tree_hover(self, tree: QTreeWidget) -> None:
        tree.setMouseTracking(True)
        tree.viewport().setMouseTracking(True)
        tree.viewport().installEventFilter(self)
        self._hover_viewports[tree.viewport()] = tree
        self._hover_tree_items[tree] = None
        tree.itemEntered.connect(lambda item, _column, widget=tree: self._set_tree_hover_item(widget, item))
        tree.itemSelectionChanged.connect(lambda widget=tree: self._refresh_tree_hover(widget))

    def _set_table_hover_row(self, table: QTableWidget, row: int) -> None:
        previous = self._hover_rows.get(table, -1)
        if previous == row:
            return
        self._paint_table_hover_row(table, previous, enabled=False)
        self._hover_rows[table] = row
        self._paint_table_hover_row(table, row, enabled=True)

    def _paint_table_hover_row(self, table: QTableWidget, row: int, *, enabled: bool) -> None:
        if row < 0 or row >= table.rowCount():
            return
        if enabled and row in {index.row() for index in table.selectionModel().selectedRows()}:
            return
        for column in range(table.columnCount()):
            item = table.item(row, column)
            if item is not None:
                item.setBackground(self._hover_brush if enabled else QBrush())

    def _refresh_table_hover(self, table: QTableWidget) -> None:
        row = self._hover_rows.get(table, -1)
        if row >= 0:
            self._paint_table_hover_row(table, row, enabled=False)
            self._paint_table_hover_row(table, row, enabled=True)

    def _set_tree_hover_item(self, tree: QTreeWidget, item: QTreeWidgetItem | None) -> None:
        previous = self._hover_tree_items.get(tree)
        if previous is item:
            return
        self._paint_tree_hover_item(tree, previous, enabled=False)
        self._hover_tree_items[tree] = item
        self._paint_tree_hover_item(tree, item, enabled=True)

    def _paint_tree_hover_item(self, tree: QTreeWidget, item: QTreeWidgetItem | None, *, enabled: bool) -> None:
        if item is None:
            return
        if enabled and item.isSelected():
            return
        for column in range(tree.columnCount()):
            item.setBackground(column, self._hover_brush if enabled else QBrush())

    def _refresh_tree_hover(self, tree: QTreeWidget) -> None:
        item = self._hover_tree_items.get(tree)
        if item is not None:
            self._paint_tree_hover_item(tree, item, enabled=False)
            self._paint_tree_hover_item(tree, item, enabled=True)

    def _build_client_tree_area(self, parent_layout: QVBoxLayout) -> None:
        self._build_filter_bar(parent_layout, "clients", CLIENT_FILTERS, self._rebuild_client_table)
        self.client_table = QTableWidget(0, len(CLIENT_COLUMNS))
        self.client_table.setHorizontalHeaderLabels(self._client_headers())
        self.client_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.client_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.client_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.client_table.verticalHeader().setVisible(False)
        self.client_table.setFont(self._mono)
        _configure_table_columns(self.client_table, CLIENT_COLUMNS, CLIENT_COLUMN_WIDTHS)
        self.client_table.horizontalHeader().sectionClicked.connect(
            lambda index: self._set_sort("clients", CLIENT_COLUMNS[index][0], self._rebuild_client_table)
        )
        self.client_table.itemSelectionChanged.connect(self._update_selected_client_panel)
        self._install_table_hover(self.client_table)
        parent_layout.addWidget(self.client_table, stretch=1)

    def _build_log_area(self, parent_layout: QVBoxLayout) -> None:
        log_box = QGroupBox("Live Client Message Log")
        log_layout = QVBoxLayout(log_box)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(self._mono)
        self.log_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        log_layout.addWidget(self.log_text)
        parent_layout.addWidget(log_box, stretch=1)

    def _build_action_panel(self, layout: QHBoxLayout) -> None:
        action_box = QGroupBox("Selected User")
        action_layout = QVBoxLayout(action_box)
        action_layout.setSpacing(10)
        action_box.setMinimumWidth(320)

        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(4, 2, 4, 6)
        header_layout.setSpacing(6)
        title_row = QHBoxLayout()
        self.selected_client_title = QLabel("No client selected")
        self.selected_client_title.setStyleSheet(
            f"color: {M['on_surface']}; font-size: 15px; font-weight: 700;"
        )
        title_row.addWidget(self.selected_client_title, stretch=1)
        self.selected_state_badge = QLabel("Idle")
        self.selected_state_badge.setAlignment(Qt.AlignCenter)
        self.selected_state_badge.setStyleSheet(state_badge_style("waiting"))
        title_row.addWidget(self.selected_state_badge)
        header_layout.addLayout(title_row)
        self.selected_client_subtitle = QLabel("Select a client row to view status and actions.")
        self.selected_client_subtitle.setWordWrap(True)
        self.selected_client_subtitle.setStyleSheet(
            f"color: {M['on_surface_variant']}; font-size: 12px;"
        )
        header_layout.addWidget(self.selected_client_subtitle)
        action_layout.addWidget(header)

        self.selected_field_labels: dict[str, QLabel] = {}
        self._add_selected_section(
            action_layout,
            "Session",
            (
                ("connection", "Connection", False),
                ("exam", "Exam", False),
                ("remaining", "Remaining", True),
                ("status", "Status", False),
            ),
        )
        self._add_selected_section(
            action_layout,
            "Machine",
            (
                ("ip", "IP", True),
                ("computer", "Computer", True),
                ("uuid", "UUID", True),
            ),
        )
        self._add_selected_section(
            action_layout,
            "Current Window",
            (
                ("window", "Title", False),
                ("process", "Process", True),
                ("window_at", "Seen At", True),
                ("window_severity", "Severity", False),
            ),
        )
        self._add_selected_section(
            action_layout,
            "Latest Incident",
            (
                ("incident_summary", "Summary", False),
                ("incident_rule", "Rule", True),
                ("incident_severity", "Severity", False),
                ("incident_status", "Status", False),
            ),
        )

        action_layout.addStretch(1)

        actions_box = QGroupBox("Actions")
        actions_layout = QVBoxLayout(actions_box)
        self.selected_details_button = make_button("Details", "tonal")
        self.selected_details_button.setEnabled(False)
        self.selected_details_button.clicked.connect(self.show_info)
        actions_layout.addWidget(self.selected_details_button)
        self.selected_folders_button = make_button("Folders", "tonal")
        self.selected_folders_button.setEnabled(False)
        self.selected_folders_button.clicked.connect(self.show_folder_info)
        actions_layout.addWidget(self.selected_folders_button)
        self.selected_actions_button = make_button("Actions", "filled")
        self.selected_actions_button.setEnabled(False)
        self.selected_actions_button.clicked.connect(self.show_options)
        actions_layout.addWidget(self.selected_actions_button)
        action_layout.addWidget(actions_box)
        layout.addWidget(action_box)

    def _add_selected_section(
        self,
        parent_layout: QVBoxLayout,
        title: str,
        rows: tuple[tuple[str, str, bool], ...],
    ) -> None:
        section = QWidget()
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(4, 0, 4, 0)
        section_layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"color: {M['on_surface_variant']}; font-size: 11px; font-weight: 700;"
        )
        section_layout.addWidget(title_label)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        for row, (key, label, technical) in enumerate(rows):
            name = QLabel(label)
            name.setStyleSheet(f"color: {M['on_surface_variant']}; font-size: 11px;")
            value = QLabel("-")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if technical:
                value.setFont(self._mono)
            value.setStyleSheet(f"color: {M['on_surface']}; font-size: 12px;")
            grid.addWidget(name, row, 0, Qt.AlignTop)
            grid.addWidget(value, row, 1)
            self.selected_field_labels[key] = value
        section_layout.addLayout(grid)
        parent_layout.addWidget(section)

    def _build_rule_breakings_tab(self) -> None:
        layout = QHBoxLayout(self.rules_tab)

        actions_box = QGroupBox("Actions")
        actions_layout = QVBoxLayout(actions_box)
        self.kill_pid_button = self._action_button(actions_layout, "Kill PID", self.kill_selected_pid)
        self.kick_user_button = self._action_button(actions_layout, "Kick User", self.kick_selected_user)
        self.ban_user_button = self._action_button(actions_layout, "Ban User", self.ban_selected_user)
        self.pause_exam_button = self._action_button(actions_layout, "Pause Exam", self.pause_selected_exam)
        self.resume_exam_button = self._action_button(actions_layout, "Resume Exam", self.resume_selected_exam)
        self.forgive_violation_button = self._action_button(
            actions_layout, "Forgive Violation", self.forgive_selected_violation
        )
        self.save_incident_rule_button = self._action_button(
            actions_layout, "Save as Rule", self.save_selected_incident_as_rule
        )
        actions_layout.addStretch(1)
        layout.addWidget(actions_box)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        layout.addWidget(center, stretch=1)

        history_box = QGroupBox("Incident History")
        history_layout = QVBoxLayout(history_box)
        self._build_filter_bar(history_layout, "incidents", INCIDENT_FILTERS, self._rebuild_incident_table)
        self.incident_table = QTableWidget(0, len(self.INCIDENT_COLUMNS))
        self.incident_table.setHorizontalHeaderLabels(self._incident_headers())
        self.incident_table.setColumnHidden(0, True)
        self.incident_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.incident_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.incident_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.incident_table.verticalHeader().setVisible(False)
        self.incident_table.setFont(self._mono)
        _configure_table_columns(self.incident_table, self.INCIDENT_COLUMNS, INCIDENT_COLUMN_WIDTHS)
        self.incident_table.horizontalHeader().sectionClicked.connect(
            lambda index: self._set_sort("incidents", self.INCIDENT_COLUMNS[index][0], self._rebuild_incident_table)
        )
        self.incident_table.itemSelectionChanged.connect(self._update_incident_detail)
        self._install_table_hover(self.incident_table)
        history_layout.addWidget(self.incident_table)
        center_layout.addWidget(history_box, stretch=1)

        details_box = QGroupBox("Incident Details")
        details_layout = QVBoxLayout(details_box)
        self.incident_detail_table = QTableWidget(0, 2)
        self.incident_detail_table.setHorizontalHeaderLabels(["Field", "Value"])
        self.incident_detail_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.incident_detail_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.incident_detail_table.verticalHeader().setVisible(False)
        self.incident_detail_table.setFont(self._mono)
        _configure_table_columns(
            self.incident_detail_table,
            (("field", "Field"), ("value", "Value")),
            {"field": (220, 130), "value": (700, 180)},
        )
        details_layout.addWidget(self.incident_detail_table)
        center_layout.addWidget(details_box, stretch=1)

    def _action_button(self, layout: QVBoxLayout, label: str, slot) -> QPushButton:
        btn = make_button(label, "outlined")
        btn.setEnabled(False)
        btn.clicked.connect(slot)
        layout.addWidget(btn)
        return btn

    def _build_process_database_tab(self) -> None:
        layout = QVBoxLayout(self.process_database_tab)
        layout.setContentsMargins(10, 10, 10, 10)

        self._build_filter_bar(layout, "processes", PROCESS_DATABASE_FILTERS, self._rebuild_process_database_tree)
        toolbar = QHBoxLayout()
        self.process_options_button = make_button("Options", "tonal")
        self.process_options_button.setEnabled(False)
        self.process_options_button.clicked.connect(self._on_process_options_clicked)
        toolbar.addWidget(self.process_options_button)

        self.process_google_button = make_button("Google Search", "text")
        self.process_google_button.setEnabled(False)
        self.process_google_button.clicked.connect(self._on_process_google_clicked)
        toolbar.addWidget(self.process_google_button)

        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        process_box = QGroupBox("Process Definitions And Evidence")
        process_box_layout = QVBoxLayout(process_box)

        self.process_tree = QTreeWidget()
        self.process_tree.setColumnCount(len(PROCESS_COLUMNS))
        self.process_tree.setHeaderLabels([label for _column, label in PROCESS_COLUMNS])
        self.process_tree.setColumnHidden(0, True)
        self.process_tree.setFont(self._mono)
        self.process_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.process_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.process_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.process_tree.setRootIsDecorated(False)
        _configure_table_columns(self.process_tree, PROCESS_COLUMNS, PROCESS_COLUMN_WIDTHS)
        self.process_tree.header().sectionClicked.connect(
            lambda index: self._set_sort("processes", PROCESS_COLUMNS[index][0], self._rebuild_process_database_tree)
        )
        self.process_tree.itemSelectionChanged.connect(self._sync_process_buttons)
        self.process_tree.itemDoubleClicked.connect(lambda _item, _col: self._on_process_options_clicked())
        self._install_tree_hover(self.process_tree)

        process_box_layout.addWidget(self.process_tree)
        layout.addWidget(process_box, stretch=1)

    def _build_incident_rules_tab(self) -> None:
        layout = QVBoxLayout(self.incident_rules_tab)
        layout.setContentsMargins(10, 10, 10, 10)

        self._build_filter_bar(layout, "incident_rules", INCIDENT_RULE_FILTERS, self._rebuild_incident_rules_tree)
        toolbar = QHBoxLayout()
        self.incident_rule_options_button = make_button("Options", "tonal")
        self.incident_rule_options_button.setEnabled(False)
        self.incident_rule_options_button.clicked.connect(self._on_incident_rule_options_clicked)
        toolbar.addWidget(self.incident_rule_options_button)

        toolbar.addStretch(1)
        open_button = make_button("Open Rules File", "text")
        open_button.clicked.connect(self.edit_incident_rules)
        toolbar.addWidget(open_button)
        apply_button = make_button("Apply Rules File", "text")
        apply_button.clicked.connect(self.apply_incident_rules)
        toolbar.addWidget(apply_button)
        layout.addLayout(toolbar)

        rules_box = QGroupBox("Incident Rules And Evidence")
        rules_box_layout = QVBoxLayout(rules_box)

        self.incident_rules_tree = QTreeWidget()
        self.incident_rules_tree.setColumnCount(len(INCIDENT_RULE_COLUMNS))
        self.incident_rules_tree.setHeaderLabels([label for _column, label in INCIDENT_RULE_COLUMNS])
        self.incident_rules_tree.setColumnHidden(0, True)
        self.incident_rules_tree.setFont(self._mono)
        self.incident_rules_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.incident_rules_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.incident_rules_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.incident_rules_tree.setRootIsDecorated(False)
        _configure_table_columns(self.incident_rules_tree, INCIDENT_RULE_COLUMNS, INCIDENT_RULE_COLUMN_WIDTHS)
        self.incident_rules_tree.header().sectionClicked.connect(
            lambda index: self._set_sort("incident_rules", INCIDENT_RULE_COLUMNS[index][0], self._rebuild_incident_rules_tree)
        )
        self.incident_rules_tree.itemSelectionChanged.connect(self._sync_incident_rule_buttons)
        self.incident_rules_tree.itemDoubleClicked.connect(lambda _item, _col: self._on_incident_rule_options_clicked())
        self._install_tree_hover(self.incident_rules_tree)

        rules_box_layout.addWidget(self.incident_rules_tree)
        layout.addWidget(rules_box, stretch=1)

    def _on_process_options_clicked(self) -> None:
        row = self._selected_process_row()
        if not row:
            QMessageBox.information(self, "Process Database", "Select a process entry first.")
            return
            
        key = ("process_decision", str(row.get("process_key", "") or ""))
        if self._focus_existing_dialog(key):
            return

        dialog = ProcessDecisionDialog(row, parent=self)
        self._register_dialog(key, dialog)
        dialog.decision_applied.connect(self._on_decision_applied)
        dialog.show()

    def _on_decision_applied(self, payload: dict):
        _emit_command(payload)
        self._append_log(
            f"[ADMIN] Applied process decision for {payload.get('definition', {}).get('process_name') or 'Unknown'}"
        )

    def _on_process_google_clicked(self) -> None:
        import webbrowser
        row = self._selected_process_row()
        if not row:
            return
        webbrowser.open(process_row_google_search_url(row))
        self._append_log(
            f"[ADMIN] Google search for {row.get('process_name') or row.get('normalized_process_name')}"
        )

    def _on_incident_rule_options_clicked(self) -> None:
        self.show_incident_rule_decision_window()

    def show_incident_rule_decision_window(self, row: Optional[dict] = None) -> None:
        row = row or self._selected_incident_rule_row()
        if not row:
            QMessageBox.information(self, "Incident Rules", "Select an incident rule entry first.")
            return

        key = ("incident_rule_decision", str(row.get("rule_key") or row.get("source_incident_id") or id(row)))
        if self._focus_existing_dialog(key):
            return

        dialog = IncidentRuleDecisionDialog(row, parent=self)
        self._register_dialog(key, dialog)
        dialog.decision_applied.connect(self._on_incident_rule_decision_applied)
        dialog.show()

    def _on_incident_rule_decision_applied(self, payload: dict) -> None:
        _emit_command(payload)
        definition = payload.get("definition", {}) if isinstance(payload.get("definition"), dict) else {}
        self._append_log(
            f"[ADMIN] Applied incident rule decision for {definition.get('name') or definition.get('rule_key') or 'Incident rule'}"
        )

    def save_selected_incident_as_rule(self) -> None:
        incident = self._selected_incident()
        if not incident:
            return
        self.show_incident_rule_decision_window(self._incident_to_rule_row(incident))

    def _incident_to_rule_row(self, incident: dict) -> dict:
        details = incident.get("details", {})
        if not isinstance(details, dict):
            details = {}
        window_title = str(incident.get("window_title") or details.get("window_title") or "").strip()
        process_name = str(incident.get("process_name") or "").strip()
        return {
            "rule_key": "",
            "definition_id": "",
            "name": str(incident.get("rule_name") or incident.get("rule_id") or "Incident rule"),
            "status": "unknown",
            "actions": {},
            "rule_id": str(incident.get("rule_id") or ""),
            "event_type": str(incident.get("event_type") or incident.get("rule_id") or ""),
            "source": str(incident.get("source") or ""),
            "process_names": [process_name] if process_name else [],
            "browser_process_names": [],
            "window_title_patterns": [window_title] if window_title else [],
            "match_mode": "contains" if window_title else "exact",
            "priority": 0,
            "source_incident_id": str(incident.get("incident_id") or ""),
            "matching_history": [incident],
            "previous_matching_entries": [],
            "action_states": [],
        }

    # ------------------------------------------------------------------ process database helpers
    def _selected_process_row(self) -> Optional[dict]:
        items = self.process_tree.selectedItems()
        if not items:
            return None
        item = items[0]
        process_key = item.text(0)
        for row in self.process_database_data:
            if str(row.get("process_key", "") or "") == str(process_key):
                return row
        return None

    def _sync_process_buttons(self) -> None:
        has_selection = self._selected_process_row() is not None
        self.process_options_button.setEnabled(has_selection)
        self.process_google_button.setEnabled(has_selection)

    def _rebuild_process_database_tree(self) -> None:
        selected_row = self._selected_process_row()
        selected_key = str((selected_row or {}).get("process_key", "") or "")
        vertical_value = self.process_tree.verticalScrollBar().value()
        horizontal_value = self.process_tree.horizontalScrollBar().value()
        rows, snapshot, previous, force_rebuild = self._prepare_rows_for_refresh("processes", self._process_tree_rows())
        self._refresh_process_headers()
        if not force_rebuild and same_row_order(previous, snapshot):
            for index in changed_row_indexes(previous, snapshot):
                _process_key, values = rows[index]
                item = self.process_tree.topLevelItem(index)
                if item is not None:
                    for column, value in enumerate(values):
                        item.setText(column, str(value))
            self._row_snapshots["processes"] = snapshot
            self._sync_process_buttons()
            return

        self.process_tree.blockSignals(True)
        self._set_tree_hover_item(self.process_tree, None)
        self.process_tree.clear()
        restored_item = None
        for process_key, values in rows:
            item = QTreeWidgetItem([str(value) for value in values])
            self.process_tree.addTopLevelItem(item)
            if selected_key and process_key == selected_key:
                restored_item = item
        if restored_item is not None:
            self.process_tree.setCurrentItem(restored_item)
        self.process_tree.blockSignals(False)
        self.process_tree.verticalScrollBar().setValue(vertical_value)
        self.process_tree.horizontalScrollBar().setValue(horizontal_value)
        self._row_snapshots["processes"] = snapshot
        self._sync_process_buttons()

    # ------------------------------------------------------------------ incident rule helpers
    def _selected_incident_rule_row(self) -> Optional[dict]:
        items = self.incident_rules_tree.selectedItems()
        if not items:
            return None
        rule_key = items[0].text(0)
        for row in self.incident_rules_data:
            if str(row.get("rule_key", "") or "") == str(rule_key):
                return row
        return None

    def _sync_incident_rule_buttons(self) -> None:
        has_selection = self._selected_incident_rule_row() is not None
        self.incident_rule_options_button.setEnabled(has_selection)

    def _rebuild_incident_rules_tree(self) -> None:
        selected_row = self._selected_incident_rule_row()
        selected_key = str((selected_row or {}).get("rule_key", "") or "")
        vertical_value = self.incident_rules_tree.verticalScrollBar().value()
        horizontal_value = self.incident_rules_tree.horizontalScrollBar().value()
        rows, snapshot, previous, force_rebuild = self._prepare_rows_for_refresh("incident_rules", self._incident_rule_tree_rows())
        self._refresh_incident_rule_headers()
        if not force_rebuild and same_row_order(previous, snapshot):
            for index in changed_row_indexes(previous, snapshot):
                _rule_key, values = rows[index]
                item = self.incident_rules_tree.topLevelItem(index)
                if item is not None:
                    for column, value in enumerate(values):
                        item.setText(column, str(value))
            self._row_snapshots["incident_rules"] = snapshot
            self._sync_incident_rule_buttons()
            return

        self.incident_rules_tree.blockSignals(True)
        self._set_tree_hover_item(self.incident_rules_tree, None)
        self.incident_rules_tree.clear()
        restored_item = None
        for rule_key, values in rows:
            item = QTreeWidgetItem([str(value) for value in values])
            self.incident_rules_tree.addTopLevelItem(item)
            if selected_key and rule_key == selected_key:
                restored_item = item
        if restored_item is not None:
            self.incident_rules_tree.setCurrentItem(restored_item)
        self.incident_rules_tree.blockSignals(False)
        self.incident_rules_tree.verticalScrollBar().setValue(vertical_value)
        self.incident_rules_tree.horizontalScrollBar().setValue(horizontal_value)
        self._row_snapshots["incident_rules"] = snapshot
        self._sync_incident_rule_buttons()

    # ------------------------------------------------------------------ selection
    def _selected_client_id(self) -> Optional[str]:
        rows = self.client_table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.client_table.item(rows[0].row(), 5)
        return item.text() if item else None

    def _selected_client_data(self) -> tuple[Optional[str], Optional[dict]]:
        client_id = self._selected_client_id()
        if not client_id:
            return None, None
        return client_id, self.clients_data.get(client_id)

    def _update_selected_client_panel(self) -> None:
        client_id, data = self._selected_client_data()
        if not client_id or not data:
            self.selected_client_title.setText("No client selected")
            self.selected_client_subtitle.setText("Select a client row to view status and actions.")
            self.selected_state_badge.setText("Idle")
            self.selected_state_badge.setStyleSheet(state_badge_style("waiting"))
            for label in self.selected_field_labels.values():
                label.setText("-")
            self.selected_details_button.setEnabled(False)
            self.selected_folders_button.setEnabled(False)
            self.selected_actions_button.setEnabled(False)
            return

        connected = data.get("connection_status") == "Connected"
        exam_state = _plain(data.get("exam_state"))
        status_label = _plain(data.get("status_label"))
        login_id = _plain(data.get("login_id"))
        self.selected_client_title.setText(login_id)
        self.selected_client_subtitle.setText(
            f"{_plain(data.get('computer_name'))} | {_plain(data.get('ip'))}"
        )
        self.selected_state_badge.setText(status_label)
        self.selected_state_badge.setStyleSheet(state_badge_style(str(data.get("exam_state") or "")))
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
            if key in self.selected_field_labels:
                self.selected_field_labels[key].setText(value)
        self.selected_details_button.setEnabled(True)
        self.selected_folders_button.setEnabled(True)
        self.selected_actions_button.setEnabled(bool(connected or data))

    def _selected_incident_ids(self) -> list[str]:
        ids: list[str] = []
        for row_index in {index.row() for index in self.incident_table.selectionModel().selectedRows()}:
            item = self.incident_table.item(row_index, 0)
            if item:
                ids.append(item.text())
        return ids

    def _selected_incidents(self) -> list[dict]:
        selected_ids = set(self._selected_incident_ids())
        if not selected_ids:
            return []
        return [
            incident
            for incident in self.incidents_data
            if str(incident.get("incident_id", "") or "") in selected_ids
        ]

    def _selected_incident(self) -> Optional[dict]:
        incidents = self._selected_incidents()
        return incidents[0] if len(incidents) == 1 else None

    def _incident_connected(self, incident: dict) -> bool:
        client = self.clients_data.get(str(incident.get("client_id", "") or ""), {})
        return client.get("connection_status") == "Connected"

    def _incident_session_state(self, incident: dict) -> str:
        client = self.clients_data.get(str(incident.get("client_id", "") or ""), {})
        return str(client.get("session_state") or incident.get("session_state") or "")

    def _unique_client_incidents(self, incidents: list[dict], predicate) -> list[dict]:
        selected: list[dict] = []
        seen: set[str] = set()
        for incident in incidents:
            client_id = str(incident.get("client_id", "") or "")
            if not client_id or client_id in seen:
                continue
            if not predicate(incident):
                continue
            seen.add(client_id)
            selected.append(incident)
        return selected

    def _incident_target_label(self, incidents: list[dict], plural_label: str) -> str:
        if len(incidents) == 1:
            return str(incidents[0].get("login_id") or incidents[0].get("client_id") or "Unknown")
        return f"{len(incidents)} selected {plural_label}"

    # ------------------------------------------------------------------ ticking
    def _update_client_remaining_cells(self, client_ids: set[str]) -> None:
        changed = False
        for row in range(self.client_table.rowCount()):
            id_item = self.client_table.item(row, 5)
            if id_item is None or id_item.text() not in client_ids:
                continue
            remaining = _format_remaining(self.clients_data.get(id_item.text(), {}).get("remaining", 0))
            item = self.client_table.item(row, 2)
            if item is not None and item.text() == remaining:
                continue
            self._set_table_item_text(self.client_table, row, 2, remaining)
            changed = True
        if changed:
            self._row_snapshots["clients"] = self._current_table_snapshot(self.client_table, 5)

    def _tick_running_timers(self) -> None:
        changed_client_ids: set[str] = set()
        for client_id, data in self.clients_data.items():
            if not data:
                continue
            if data.get("exam_state") != "Running":
                continue
            if data.get("remaining", 0) <= 0:
                continue
            data["remaining"] -= 1
            changed_client_ids.add(client_id)
        if changed_client_ids:
            self._update_client_remaining_cells(changed_client_ids)
            self._update_selected_client_panel()

    # ------------------------------------------------------------------ details
    def show_info(self) -> None:
        client_id, data = self._selected_client_data()
        if not client_id:
            QMessageBox.information(self, "Info", "Select a client first.")
            return

        key = ("info", client_id)
        if self._focus_existing_dialog(key):
            return

        dialog = _DetailsDialog(
            f"Info: {data.get('login_id', 'Unknown') if data else 'Unknown'}",
            _detail_lines(client_id, data or {}),
            parent=self,
        )
        self._register_dialog(key, dialog)
        dialog.show()

    def show_server_info_details(self) -> None:
        if not self.server_info:
            QMessageBox.information(self, "Server Info", "No server state available yet.")
            return

        key = ("server_info", "details")
        if self._focus_existing_dialog(key):
            return
        dialog = _DetailsDialog("Server Info Details", _server_info_rows(self.server_info), parent=self)
        self._register_dialog(key, dialog)
        dialog.show()

    def show_folder_info(self) -> None:
        client_id, data = self._selected_client_data()
        if not client_id:
            QMessageBox.information(self, "Folders", "Select a client first.")
            return
        data = data or {}
        key = ("folders", client_id)
        if self._focus_existing_dialog(key):
            return
        rows = [
            ("Login ID", str(data.get("login_id") or "-")),
            ("UUID", str(client_id)),
            ("Client Exam Folder", str(data.get("exam_folder_path") or "Desktop\\Exam\\DD-MM-YYYY")),
            ("Client Exam ZIP", str(data.get("exam_files_zip_path") or "-")),
            ("Latest Incident Artifact", str(data.get("latest_incident_artifact_path") or "-")),
            ("Submission Path", str(data.get("submission_path") or "-")),
            ("Submission Name", str(data.get("submission_name") or "-")),
        ]
        dialog = _DetailsDialog(
            f"Folders: {data.get('login_id', 'Unknown')}",
            rows,
            parent=self,
        )
        self._register_dialog(key, dialog)
        dialog.show()

    def show_options(self) -> None:
        client_id, data = self._selected_client_data()
        if not client_id:
            QMessageBox.information(self, "Options", "Select a client first.")
            return
        key = ("options", client_id)
        if self._focus_existing_dialog(key):
            return
        dialog = _OptionsDialog(client_id, data or {}, self._send_window_command, parent=self)
        self._register_dialog(key, dialog)
        dialog.show()

    def _register_dialog(self, key: tuple[str, str], dialog: QDialog) -> None:
        self._open_dialogs[key] = dialog
        dialog.finished.connect(lambda _result, k=key, d=dialog: self._forget_dialog(k, d))

    def _forget_dialog(self, key: tuple[str, str], dialog: QDialog) -> None:
        existing = self._open_dialogs.get(key)
        if existing is dialog:
            self._open_dialogs.pop(key, None)

    def _focus_existing_dialog(self, key: tuple[str, str]) -> bool:
        dialog = self._open_dialogs.get(key)
        if not dialog:
            return False
        dialog.raise_()
        dialog.activateWindow()
        return True

    def _send_window_command(self, payload: dict) -> None:
        _emit_command(payload)
        self._append_log(f"[ADMIN] Sent {payload.get('cmd')} to {payload.get('uuid', '')}")

    # ------------------------------------------------------------------ incident actions
    def kill_selected_pid(self) -> None:
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
            QMessageBox.information(
                self, "Kill PID", "No selected incidents have a killable live process."
            )
            return
        if len(eligible) == 1:
            incident = eligible[0]
            pid = int(incident.get("pid", 0) or 0)
            user = incident.get("login_id") or "Unknown"
            process_name = incident.get("process_name") or "Unknown"
            if not self._confirm_action(
                "confirm_kill_pid",
                "Kill PID",
                f"Kill process for user {user}?\n\nProcess: {process_name}\nPID: {pid}",
            ):
                return
        else:
            user_count = len({str(incident.get("client_id", "") or "") for incident in eligible})
            if not self._confirm_action(
                "confirm_kill_pid",
                "Kill PID",
                f"Kill {len(eligible)} selected process(es) across {user_count} user(s)?",
            ):
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
        self._append_log(f"[ADMIN] Requested PID kill for {len(eligible)} selected process(es)")

    def kick_selected_user(self) -> None:
        incidents = self._unique_client_incidents(
            self._selected_incidents(), lambda incident: self._incident_connected(incident)
        )
        if not incidents:
            return
        target_count = len(incidents)
        target_label = self._incident_target_label(incidents, "user(s)")
        message = (
            f"Disconnect user {target_label}?" if target_count == 1 else f"Disconnect {target_label}?"
        )
        if not self._confirm_action("confirm_kick", "Kick User", message):
            return
        self._emit_incident_user_commands("kick", incidents)

    def ban_selected_user(self) -> None:
        incidents = self._unique_client_incidents(self._selected_incidents(), lambda _i: True)
        if not incidents:
            return
        target_count = len(incidents)
        target_label = self._incident_target_label(incidents, "user(s)")
        message = f"Ban user {target_label}?" if target_count == 1 else f"Ban {target_label}?"
        if not self._confirm_action("confirm_ban", "Ban User", message):
            return
        self._emit_incident_user_commands("ban", incidents)

    def pause_selected_exam(self) -> None:
        incidents = self._unique_client_incidents(
            self._selected_incidents(),
            lambda incident: self._incident_session_state(incident) == "running",
        )
        if not incidents:
            return
        target_count = len(incidents)
        target_label = self._incident_target_label(incidents, "exam session(s)")
        message = (
            f"Pause exam for {target_label}?" if target_count == 1 else f"Pause {target_label}?"
        )
        if not self._confirm_action("confirm_pause", "Pause Exam", message):
            return
        self._emit_incident_user_commands("pause_exam", incidents)

    def resume_selected_exam(self) -> None:
        incidents = self._unique_client_incidents(
            self._selected_incidents(),
            lambda incident: self._incident_session_state(incident)
            in {"admin_paused", "disconnected_paused"},
        )
        if not incidents:
            return
        self._emit_incident_user_commands("resume_exam", incidents)

    def forgive_selected_violation(self) -> None:
        incidents = self._unique_client_incidents(
            sorted(
                self._selected_incidents(),
                key=lambda incident: (not incident.get("blocking"), str(incident.get("incident_id") or "")),
            ),
            lambda incident: self._incident_session_state(incident) == "violation_paused"
            and bool(incident.get("blocking")),
        )
        if not incidents:
            return
        target_count = len(incidents)
        if target_count == 1:
            label = incidents[0].get("login_id") or incidents[0].get("client_id")
            prompt = f"Forgive blocking violation for {label}?"
        else:
            prompt = f"Forgive blocking violations for {target_count} selected user(s)?"
        reply = QMessageBox.question(
            self,
            "Forgive Violation",
            prompt,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._emit_incident_user_commands("forgive_violation", incidents)

    def _emit_incident_user_commands(self, command: str, incidents: list[dict]) -> None:
        for incident in incidents:
            _emit_command(
                {
                    "cmd": command,
                    "uuid": incident.get("client_id"),
                    "incident_id": incident.get("incident_id"),
                }
            )
        self._append_log(f"[ADMIN] Sent {command} for {len(incidents)} selected user(s)")

    # ------------------------------------------------------------------ admin
    def start_exam_globally(self) -> None:
        _emit_command({"cmd": "start_exam_global"})
        self._append_log("[ADMIN] Enabled exam start globally")

    def finish_exam_globally(self) -> None:
        _emit_command({"cmd": "finish_exam_global"})
        self._append_log("[ADMIN] Requested global exam finish")

    def edit_blacklist(self) -> None:
        _emit_command({"cmd": "edit_blacklist"})
        self._append_log("[ADMIN] Opening process blacklist file")

    def apply_blacklist(self) -> None:
        _emit_command({"cmd": "apply_blacklist"})
        self._append_log("[ADMIN] Applying process blacklist")

    def edit_policy(self) -> None:
        _emit_command({"cmd": "edit_policy"})
        self._append_log("[ADMIN] Opening exam policy file")

    def apply_policy(self) -> None:
        _emit_command({"cmd": "apply_policy"})
        self._append_log("[ADMIN] Applying exam policy")

    def edit_process_definitions(self) -> None:
        _emit_command({"cmd": "edit_process_definitions"})
        self._append_log("[ADMIN] Opening process definitions file")

    def apply_process_definitions(self) -> None:
        _emit_command({"cmd": "apply_process_definitions"})
        self._append_log("[ADMIN] Applying process definitions")

    def edit_incident_rules(self) -> None:
        _emit_command({"cmd": "edit_incident_rules"})
        self._append_log("[ADMIN] Opening incident rules file")

    def apply_incident_rules(self) -> None:
        _emit_command({"cmd": "apply_incident_rules"})
        self._append_log("[ADMIN] Applying incident rules")

    def export_settings(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Settings",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        _emit_command({"cmd": "export_settings", "path": path})
        self._append_log(f"[ADMIN] Exporting settings to {path}")

    def import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Settings",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        _emit_command({"cmd": "import_settings", "path": path})
        self._append_log(f"[ADMIN] Importing settings from {path}")

    def toggle_remember_settings(self, enabled: bool) -> None:
        _emit_command({"cmd": "set_remember_settings", "remember": bool(enabled)})
        self._append_log(
            f"[ADMIN] Remember settings {'enabled' if enabled else 'disabled'}"
        )

    def send_console_command(self) -> None:
        command = self.cmd_entry.text().strip()
        if not command:
            return
        if not command.startswith("/"):
            command = "/" + command
        _emit_command({"type": "console_command", "command": command})
        self.cmd_entry.clear()
        self._append_log(f"[ADMIN] Executing: {command}")

    def _append_log(self, line: str) -> None:
        self.log_text.appendPlainText(line)

    def _confirm_action(self, operator_key: str, title: str, message: str) -> bool:
        operator_defaults = self.server_info.get("operator_defaults", {}) if self.server_info else {}
        if not operator_defaults.get(operator_key, True):
            return True
        reply = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    # ------------------------------------------------------------------ closing
    def closeEvent(self, event):  # noqa: N802 - Qt API
        if self.standalone_mode or self._allow_close:
            event.accept()
            QApplication.instance().quit()
            return
        event.ignore()
        QMessageBox.warning(
            self,
            "Dashboard Protected",
            "The monitoring dashboard is protected while the server session is active.\n\n"
            "Use the Server Manager or server commands to control the session instead of OS close shortcuts.",
        )

    def force_close(self) -> None:
        self._allow_close = True
        try:
            self._tick_timer.stop()
        except Exception:
            pass
        central = self.centralWidget()
        if isinstance(central, StarfieldBackground):
            central.stop_animation()
        self.close()
        QApplication.instance().quit()

    # ------------------------------------------------------------------ IPC inbound
    def log_message(self, client_id: str, message: str) -> None:
        data = self.clients_data.get(client_id, {})
        display_name = data.get("login_id", client_id[:8] if client_id else "?")
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_log(f"[{timestamp}] {display_name}: {message}")

    def process_state_update(self, payload: dict) -> None:
        self.server_info = payload.get("server", {})
        self.remember_check.blockSignals(True)
        self.remember_check.setChecked(bool(self.server_info.get("remember_settings", True)))
        self.remember_check.blockSignals(False)
        self._update_server_info_panel()
        
        settings_snapshot = payload.get("settings", {})
        if isinstance(settings_snapshot, dict) and settings_snapshot:
            self.settings_snapshot = settings_snapshot
            if hasattr(self, 'policy_dialog') and self.policy_dialog and self.policy_dialog.isVisible():
                self.policy_dialog.update_snapshot(settings_snapshot)

        clients = payload.get("clients", [])
        seen_ids: set[str] = set()
        active_count = 0
        for client in clients:
            client_id = client["uuid"]
            seen_ids.add(client_id)
            self.clients_data[client_id] = {
                **client,
                "remaining": int(float(client.get("remaining", 0))),
            }
            if client.get("connection_status") == "Connected":
                active_count += 1

        for client_id in list(self.clients_data.keys()):
            if client_id not in seen_ids:
                self.clients_data.pop(client_id, None)

        self._rebuild_client_table()

        incidents = payload.get("incidents", [])
        self.incidents_data = incidents
        self._rebuild_incident_table()
        self.process_database_data = payload.get("process_database", [])
        self._rebuild_process_database_tree()
        self.incident_rules_data = payload.get("incident_rules_database", [])
        self._rebuild_incident_rules_tree()
        active_warnings = sum(
            1
            for incident in incidents
            if bool(incident.get("active"))
            and str(incident.get("severity", "")).strip().lower() == "warning"
        )

        total = len(clients)
        disconnected = total - active_count
        self.stats_label.setText(
            f"Connections Managed: {total} | Active: {active_count} | "
            f"Disconnected: {disconnected} | "
            f"Active Incidents: {self.server_info.get('active_incident_count', 0)} | "
            f"Active Warnings: {active_warnings}"
        )

    def _update_server_info_panel(self) -> None:
        info = self.server_info
        if not info:
            self.server_info_label.setText("Waiting for server state...")
            self.server_info_detail_button.setEnabled(False)
            return
        has_files = "Yes" if info.get("has_exam_files") else "No"
        exam_phase = str(info.get("exam_phase", "waiting")).title()
        start_enabled = "Open" if info.get("exam_start_enabled") else "Locked"
        all_host_ips = ", ".join(str(ip) for ip in info.get("all_host_ips", []) if str(ip).strip()) or "-"
        self.server_info_detail_button.setEnabled(True)
        self.start_exam_button.setEnabled(info.get("exam_phase") == "waiting")
        self.finish_exam_button.setEnabled(info.get("exam_phase") == "running")
        text = (
            f"ID: {info.get('server_id', '-')}    "
            f"Host: {info.get('host', '-')}    "
            f"Port: {info.get('port', '-')}\n"
            f"All Host IPv4s: {all_host_ips}\n"
            f"Exam Phase: {exam_phase}    "
            f"Exam Start: {start_enabled}    "
            f"Duration: {info.get('exam_duration_minutes', '-')} min\n"
            f"Exam Files: {has_files}    "
            f"Active Incidents: {info.get('active_incident_count', 0)}    "
            f"Total Incidents: {info.get('incident_count', 0)}\n"
            "Use Detailed Info for full configuration."
        )
        self.server_info_label.setText(text)

    def _client_table_rows(self):
        sort_column, descending = self.sort_state.get("clients", ("login_id", False))
        return [
            (
                client_id,
                (
                    str(data.get("login_id", "")),
                    str(data.get("status_label", "Unknown")),
                    _format_remaining(data.get("remaining", 0)),
                    client_window_title(data),
                    str(data.get("ip") or ""),
                    str(client_id),
                ),
            )
            for client_id, data in sorted_client_items(
                self.clients_data,
                self._active_filters("clients"),
                sort_column,
                descending,
            )
        ]

    def _incident_table_rows(self):
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
                        str(incident.get("event_at", "") or ""),
                        str(incident.get("login_id", "") or ""),
                        str(incident.get("severity", "") or ""),
                        str(incident.get("rule_name", "") or ""),
                        str(incident.get("source", "") or ""),
                        str(incident.get("process_name", "") or ""),
                        str(incident.get("pid", "") if incident.get("pid") not in (None, "") else ""),
                        str(incident.get("auto_action_state_label", "") or ""),
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
                    str(row.get("match_count", 0)),
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
                    str(row.get("match_count", 0)),
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

    def _set_table_item_text(self, table: QTableWidget, row: int, column: int, value: str, *, foreground: str | None = None) -> None:
        item = table.item(row, column)
        if item is None:
            item = QTableWidgetItem(value)
            table.setItem(row, column, item)
        elif item.text() != value:
            item.setText(value)
        if foreground:
            item.setForeground(QBrush(QColor(foreground)))

    def _current_table_snapshot(self, table: QTableWidget, key_column: int) -> RowSnapshot:
        rows = []
        for row in range(table.rowCount()):
            key_item = table.item(row, key_column)
            if key_item is None:
                continue
            values = tuple((table.item(row, column).text() if table.item(row, column) else "") for column in range(table.columnCount()))
            rows.append((key_item.text(), values))
        return row_snapshot(rows)

    def _rebuild_client_table(self) -> None:
        selected_id = self._selected_client_id()
        vertical_value = self.client_table.verticalScrollBar().value()
        horizontal_value = self.client_table.horizontalScrollBar().value()
        rows, snapshot, previous, force_rebuild = self._prepare_rows_for_refresh("clients", self._client_table_rows())
        self.client_table.setHorizontalHeaderLabels(self._client_headers())
        if not force_rebuild and same_row_order(previous, snapshot):
            for row in changed_row_indexes(previous, snapshot):
                _client_id, values = rows[row]
                for col, value in enumerate(values):
                    foreground = None
                    if col == 1:
                        data = self.clients_data.get(str(values[5]), {})
                        fg, _bg = STATE_COLORS.get(str(data.get("exam_state", "")).lower(), (M["on_surface_variant"], ""))
                        foreground = fg
                    self._set_table_item_text(self.client_table, row, col, str(value), foreground=foreground)
            self._row_snapshots["clients"] = snapshot
            self._update_selected_client_panel()
            return

        self.client_table.blockSignals(True)
        self._set_table_hover_row(self.client_table, -1)
        self.client_table.setRowCount(len(rows))
        new_row = -1
        for row, (client_id, values) in enumerate(rows):
            for col, value in enumerate(values):
                foreground = None
                if col == 1:
                    data = self.clients_data.get(str(client_id), {})
                    fg, _bg = STATE_COLORS.get(str(data.get("exam_state", "")).lower(), (M["on_surface_variant"], ""))
                    foreground = fg
                self._set_table_item_text(self.client_table, row, col, str(value), foreground=foreground)
            if client_id == selected_id:
                new_row = row
        if new_row >= 0:
            self.client_table.selectRow(new_row)
        else:
            self.client_table.clearSelection()
        self.client_table.blockSignals(False)
        self.client_table.verticalScrollBar().setValue(vertical_value)
        self.client_table.horizontalScrollBar().setValue(horizontal_value)
        self._row_snapshots["clients"] = snapshot
        self._update_selected_client_panel()

    def _rebuild_incident_table(self) -> None:
        selected_ids = set(self._selected_incident_ids())
        vertical_value = self.incident_table.verticalScrollBar().value()
        horizontal_value = self.incident_table.horizontalScrollBar().value()
        rows, snapshot, previous, force_rebuild = self._prepare_rows_for_refresh("incidents", self._incident_table_rows())
        self.incident_table.setHorizontalHeaderLabels(self._incident_headers())
        self._incident_tree_refreshing = True
        try:
            if not force_rebuild and same_row_order(previous, snapshot):
                for row in changed_row_indexes(previous, snapshot):
                    _incident_id, values = rows[row]
                    for col, value in enumerate(values):
                        self._set_table_item_text(self.incident_table, row, col, str(value))
                self._row_snapshots["incidents"] = snapshot
                self._incident_tree_refreshing = False
                self._update_incident_detail()
                return

            self.incident_table.blockSignals(True)
            self._set_table_hover_row(self.incident_table, -1)
            self.incident_table.setRowCount(len(rows))
            restored_rows: list[int] = []
            for row, (incident_id, values) in enumerate(rows):
                for col, value in enumerate(values):
                    self._set_table_item_text(self.incident_table, row, col, str(value))
                if incident_id in selected_ids:
                    restored_rows.append(row)
            self.incident_table.clearSelection()
            for row in restored_rows:
                self.incident_table.selectRow(row)
            self.incident_table.blockSignals(False)
            self.incident_table.verticalScrollBar().setValue(vertical_value)
            self.incident_table.horizontalScrollBar().setValue(horizontal_value)
            self._row_snapshots["incidents"] = snapshot
        finally:
            try:
                self.incident_table.blockSignals(False)
            except Exception:
                pass
            self._incident_tree_refreshing = False
        self._update_incident_detail()

    def _update_incident_detail(self) -> None:
        if self._incident_tree_refreshing:
            return
        incidents = self._selected_incidents()
        rows: list[tuple[str, str]] = []
        if len(incidents) == 1:
            rows = _incident_detail_lines(incidents[0])
        elif incidents:
            rows = _multi_incident_detail_lines(incidents)
        self.incident_detail_table.setRowCount(len(rows))
        for row, (field, value) in enumerate(rows):
            self.incident_detail_table.setItem(row, 0, QTableWidgetItem(field))
            self.incident_detail_table.setItem(row, 1, QTableWidgetItem(value))
        self._sync_incident_buttons(incidents)

    def _sync_incident_buttons(self, incidents: list[dict]) -> None:
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
                button.setEnabled(False)
            return

        self.kill_pid_button.setEnabled(
            any(
                self._incident_connected(incident) and bool(incident.get("kill_available"))
                for incident in incidents
            )
        )
        self.kick_user_button.setEnabled(
            any(self._incident_connected(incident) for incident in incidents)
        )
        self.ban_user_button.setEnabled(True)
        self.pause_exam_button.setEnabled(
            any(self._incident_session_state(incident) == "running" for incident in incidents)
        )
        self.resume_exam_button.setEnabled(
            any(
                self._incident_session_state(incident) in {"admin_paused", "disconnected_paused"}
                for incident in incidents
            )
        )
        self.forgive_violation_button.setEnabled(
            any(
                self._incident_session_state(incident) == "violation_paused"
                and incident.get("blocking")
                for incident in incidents
            )
        )
        self.save_incident_rule_button.setEnabled(len(incidents) == 1)


def _ipc_reader(q: queue.Queue) -> None:
    try:
        for line in iter_stdin_lines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as exc:
                write_text_stderr(f"[DEBUG] GUI IPC Error: {exc}")
                continue
            q.put(msg)
    except (OSError, ValueError):
        pass
    q.put(None)  # sentinel → parent closed


def run() -> int:
    global _IPC_CLIENT
    log_dir = PROJECT_DIR / "data" / "logs" / "server"
    log_dir.mkdir(parents=True, exist_ok=True)
    setup_runtime_logging("server_gui", log_dir)
    _crash_log = log_dir / f"server_gui_crash_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    crash_log_handle = _crash_log.open("w", encoding="utf-8")
    faulthandler.enable(file=crash_log_handle, all_threads=True)
    app = QApplication.instance() or QApplication(sys.argv)
    apply_glass_theme(app)
    use_ws_ipc = should_use_ws_ipc()
    standalone = stdin_is_standalone() and not use_ws_ipc
    gui = ServerGUI(standalone_mode=standalone)
    gui.show()

    ipc_queue: queue.Queue = queue.Queue()
    if use_ws_ipc:
        _IPC_CLIENT = ThreadedIpcClient(
            role="dashboard_gui",
            on_message=lambda message: ipc_queue.put(message.get("data", {}))
            if message.get("channel") == "server.dashboard_state"
            else None,
        )
        if not _IPC_CLIENT.start():
            _IPC_CLIENT = None
            if not stdin_available():
                standalone = True
                gui.standalone_mode = True

    signals = _IPCSignals()
    if not standalone:
        signals.parent_closed.connect(gui.force_close)

    def _poll_ipc() -> None:
        try:
            while True:
                msg = ipc_queue.get_nowait()
                if msg is None:
                    signals.parent_closed.emit()
                    return
                message_type = msg.get("type")
                if message_type == "state_update":
                    gui.process_state_update(msg)
                elif message_type == "client_message":
                    gui.log_message(str(msg.get("uuid") or ""), str(msg.get("text") or ""))
                elif message_type == "settings_result":
                    if hasattr(gui, 'policy_dialog') and gui.policy_dialog:
                        gui.policy_dialog.process_result(bool(msg.get("ok", False)), str(msg.get("message") or ""))
        except queue.Empty:
            pass

    poll_timer = QTimer()
    poll_timer.setInterval(50)
    poll_timer.timeout.connect(_poll_ipc)
    poll_timer.start()

    if stdin_available():
        reader_thread = Thread(target=_ipc_reader, args=(ipc_queue,), daemon=True)
        reader_thread.start()

    try:
        exit_code = app.exec()
    finally:
        if _IPC_CLIENT:
            _IPC_CLIENT.stop()
        try:
            if faulthandler.is_enabled():
                faulthandler.disable()
        finally:
            crash_log_handle.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run())
