"""PySide6 reimplementation of the server monitor dashboard.

Mirrors the behaviour of ``server/gui_tk.py`` but uses Qt widgets.
Selected at runtime by ``server/gui.py --ui qt``.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from threading import Thread
from typing import Optional


PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


def _missing_pyside6_message() -> str:
    return (
        "PySide6 is required for the Qt UI. Install it with:\n"
        "    pip install PySide6\n"
        "Or run the legacy interface with: --ui tk"
    )


try:
    from PySide6.QtCore import Qt, QObject, QTimer, Signal
    from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase
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
except ImportError:  # pragma: no cover - import guard
    print(_missing_pyside6_message(), file=sys.stderr)
    raise

from common.runtime_logging import setup_runtime_logging
from ui.widgets import apply_theme, make_button, style_button
from ui.theme import M, STATE_COLORS
from ui.styles import state_badge_style


def _monospace_font() -> QFont:
    return QFontDatabase.systemFont(QFontDatabase.FixedFont)


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
        ("Blacklist Version", str(info.get("process_blacklist_version", "-"))),
        ("Blacklist File", str(info.get("process_blacklist_file", "-"))),
        ("Policy Version", str(info.get("policy_version", "-"))),
        ("Policy File", str(info.get("policy_file", "-"))),
        ("Remember Settings", "Yes" if info.get("remember_settings", True) else "No"),
        ("Incidents", str(info.get("incident_count", 0))),
        ("Active Incidents", str(info.get("active_incident_count", 0))),
    ]


def _emit_command(payload: dict) -> None:
    print(json.dumps(payload), flush=True)


class _IPCSignals(QObject):
    state_update = Signal(dict)
    client_message = Signal(str, str)
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
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
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


class ServerGUI(QMainWindow):
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
        self.server_info: dict = {}
        self._open_dialogs: dict[tuple[str, str], QDialog] = {}
        self._mono = _monospace_font()
        self._allow_close = False
        self._incident_tree_refreshing = False

        self.setWindowTitle("Server Monitor Dashboard")
        self.resize(1200, 760)
        self.setMinimumSize(1000, 680)

        self._build_layout()

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick_running_timers)
        self._tick_timer.start()

    # ------------------------------------------------------------------ layout
    def _build_layout(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 10, 10, 10)

        self.tabs = QTabWidget(self)
        outer.addWidget(self.tabs, stretch=1)

        self.overview_tab = QWidget()
        self.rules_tab = QWidget()
        self.tabs.addTab(self.overview_tab, "Overview")
        self.tabs.addTab(self.rules_tab, "Rule Breakings")
        self._build_overview_tab()
        self._build_rule_breakings_tab()

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
        info_layout.addLayout(action_row)

        grid = QGridLayout()
        self.edit_blacklist_button = make_button("Edit Blacklist", "tonal")
        self.edit_blacklist_button.clicked.connect(self.edit_blacklist)
        grid.addWidget(self.edit_blacklist_button, 0, 0)
        self.apply_blacklist_button = make_button("Apply Blacklist", "tonal")
        self.apply_blacklist_button.clicked.connect(self.apply_blacklist)
        grid.addWidget(self.apply_blacklist_button, 0, 1)
        self.edit_policy_button = make_button("Edit Policy", "tonal")
        self.edit_policy_button.clicked.connect(self.edit_policy)
        grid.addWidget(self.edit_policy_button, 0, 2)
        self.apply_policy_button = make_button("Apply Policy", "tonal")
        self.apply_policy_button.clicked.connect(self.apply_policy)
        grid.addWidget(self.apply_policy_button, 1, 0)
        self.export_settings_button = make_button("Export Settings", "text")
        self.export_settings_button.clicked.connect(self.export_settings)
        grid.addWidget(self.export_settings_button, 1, 1)
        self.import_settings_button = make_button("Import Settings", "text")
        self.import_settings_button.clicked.connect(self.import_settings)
        grid.addWidget(self.import_settings_button, 1, 2)
        info_layout.addLayout(grid)

        self.remember_check = QCheckBox("Remember Settings")
        self.remember_check.setChecked(True)
        self.remember_check.toggled.connect(self.toggle_remember_settings)
        info_layout.addWidget(self.remember_check)

        detail_row = QHBoxLayout()
        self.server_info_detail_button = make_button("Detailed Info", "text")
        self.server_info_detail_button.setEnabled(False)
        self.server_info_detail_button.clicked.connect(self.show_server_info_details)
        detail_row.addWidget(self.server_info_detail_button)
        detail_row.addStretch(1)
        info_layout.addLayout(detail_row)

        self.server_info_label = QLabel("Waiting for server state...")
        self.server_info_label.setFont(self._mono)
        self.server_info_label.setWordWrap(True)
        info_layout.addWidget(self.server_info_label)

        parent_layout.addWidget(info_box)

    def _build_client_tree_area(self, parent_layout: QVBoxLayout) -> None:
        self.client_table = QTableWidget(0, 4)
        self.client_table.setHorizontalHeaderLabels(["Login ID", "Status", "Remaining Time", "UUID"])
        self.client_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.client_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.client_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.client_table.verticalHeader().setVisible(False)
        self.client_table.setFont(self._mono)
        header = self.client_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
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
        info_btn = make_button("Show Info", "tonal")
        info_btn.clicked.connect(self.show_info)
        action_layout.addWidget(info_btn)
        options_btn = make_button("Options", "filled")
        options_btn.clicked.connect(self.show_options)
        action_layout.addWidget(options_btn)
        action_layout.addStretch(1)
        layout.addWidget(action_box)

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
        actions_layout.addStretch(1)
        layout.addWidget(actions_box)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        layout.addWidget(center, stretch=1)

        history_box = QGroupBox("Incident History")
        history_layout = QVBoxLayout(history_box)
        self.incident_table = QTableWidget(0, len(self.INCIDENT_COLUMNS))
        self.incident_table.setHorizontalHeaderLabels([label for _, label in self.INCIDENT_COLUMNS])
        self.incident_table.setColumnHidden(0, True)
        self.incident_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.incident_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.incident_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.incident_table.verticalHeader().setVisible(False)
        self.incident_table.setFont(self._mono)
        header = self.incident_table.horizontalHeader()
        for index in range(1, len(self.INCIDENT_COLUMNS)):
            header.setSectionResizeMode(index, QHeaderView.ResizeToContents)
        self.incident_table.itemSelectionChanged.connect(self._update_incident_detail)
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
        detail_header = self.incident_detail_table.horizontalHeader()
        detail_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        detail_header.setSectionResizeMode(1, QHeaderView.Stretch)
        details_layout.addWidget(self.incident_detail_table)
        center_layout.addWidget(details_box, stretch=1)

    def _action_button(self, layout: QVBoxLayout, label: str, slot) -> QPushButton:
        btn = make_button(label, "outlined")
        btn.setEnabled(False)
        btn.clicked.connect(slot)
        layout.addWidget(btn)
        return btn

    # ------------------------------------------------------------------ selection
    def _selected_client_id(self) -> Optional[str]:
        rows = self.client_table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.client_table.item(rows[0].row(), 3)
        return item.text() if item else None

    def _selected_client_data(self) -> tuple[Optional[str], Optional[dict]]:
        client_id = self._selected_client_id()
        if not client_id:
            return None, None
        return client_id, self.clients_data.get(client_id)

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
    def _tick_running_timers(self) -> None:
        for row in range(self.client_table.rowCount()):
            uuid_item = self.client_table.item(row, 3)
            remaining_item = self.client_table.item(row, 2)
            if not uuid_item or not remaining_item:
                continue
            data = self.clients_data.get(uuid_item.text())
            if not data:
                continue
            if data.get("exam_state") != "Running":
                continue
            if data.get("remaining", 0) <= 0:
                continue
            data["remaining"] -= 1
            remaining_item.setText(_format_remaining(data["remaining"]))

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
        self.server_info_detail_button.setEnabled(True)
        self.start_exam_button.setEnabled(info.get("exam_phase") == "waiting")
        self.finish_exam_button.setEnabled(info.get("exam_phase") == "running")
        text = (
            f"ID: {info.get('server_id', '-')}    "
            f"Host: {info.get('host', '-')}    "
            f"Port: {info.get('port', '-')}\n"
            f"Exam Phase: {exam_phase}    "
            f"Exam Start: {start_enabled}    "
            f"Duration: {info.get('exam_duration_minutes', '-')} min\n"
            f"Exam Files: {has_files}    "
            f"Active Incidents: {info.get('active_incident_count', 0)}    "
            f"Total Incidents: {info.get('incident_count', 0)}\n"
            "Use Detailed Info for full configuration."
        )
        self.server_info_label.setText(text)

    def _rebuild_client_table(self) -> None:
        selected_id = self._selected_client_id()
        ordered = sorted(self.clients_data.items(), key=lambda item: item[1].get("login_id", ""))
        self.client_table.setRowCount(len(ordered))
        new_row = -1
        for row, (client_id, data) in enumerate(ordered):
            self.client_table.setItem(row, 0, QTableWidgetItem(str(data.get("login_id", ""))))
            status_item = QTableWidgetItem(str(data.get("status_label", "Unknown")))
            exam_state = str(data.get("exam_state", "")).lower()
            fg, _bg = STATE_COLORS.get(exam_state, (M["on_surface_variant"], ""))
            status_item.setForeground(QBrush(QColor(fg)))
            self.client_table.setItem(row, 1, status_item)
            self.client_table.setItem(row, 2, QTableWidgetItem(_format_remaining(data.get("remaining", 0))))
            self.client_table.setItem(row, 3, QTableWidgetItem(str(client_id)))
            if client_id == selected_id:
                new_row = row
        if new_row >= 0:
            self.client_table.selectRow(new_row)

    def _rebuild_incident_table(self) -> None:
        selected_ids = set(self._selected_incident_ids())
        self._incident_tree_refreshing = True
        try:
            self.incident_table.setRowCount(len(self.incidents_data))
            restored_rows: list[int] = []
            for row, incident in enumerate(self.incidents_data):
                incident_id = str(incident.get("incident_id", "") or "")
                status_text = str(incident.get("status", "") or "")
                if incident.get("active"):
                    status_text = f"{status_text} (active)"
                values = [
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
                ]
                for col, value in enumerate(values):
                    self.incident_table.setItem(row, col, QTableWidgetItem(value))
                if incident_id in selected_ids:
                    restored_rows.append(row)
            self.incident_table.clearSelection()
            for row in restored_rows:
                self.incident_table.selectRow(row)
        finally:
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


def _ipc_reader(signals: _IPCSignals) -> None:
    try:
        for line in iter(sys.stdin.readline, ""):
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"[DEBUG] GUI IPC Error: {exc}", file=sys.stderr)
                continue
            message_type = msg.get("type")
            if message_type == "state_update":
                signals.state_update.emit(msg)
            elif message_type == "client_message":
                signals.client_message.emit(str(msg.get("uuid") or ""), str(msg.get("text") or ""))
    except (OSError, ValueError):
        pass
    signals.parent_closed.emit()


def run() -> int:
    setup_runtime_logging(
        "server_gui",
        PROJECT_DIR / "data" / "logs" / "server",
    )
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    standalone = sys.stdin.isatty()
    gui = ServerGUI(standalone_mode=standalone)
    gui.show()

    signals = _IPCSignals()
    signals.state_update.connect(gui.process_state_update)
    signals.client_message.connect(gui.log_message)
    if not standalone:
        signals.parent_closed.connect(gui.force_close)

    reader_thread = Thread(target=_ipc_reader, args=(signals,), daemon=True)
    reader_thread.start()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
