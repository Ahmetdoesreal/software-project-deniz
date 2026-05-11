"""Qt-native implementation of policy settings and process decision windows.

Mirrors PolicySettingsMixin and DashboardPopupMixin for the Qt GUI.
"""

import json
import webbrowser
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.theme import M
from ui.widgets import make_button, monospace_font
from common.process_definitions import build_google_search_url
from server.ui.process_database_helpers import (
    build_incident_rule_decision_payload,
    incident_rule_field_text,
    incident_rule_observed_window_title,
    split_multiline_values,
)

SEVERITY_VALUES = ("info", "warning", "violation")
WINDOW_TITLE_MATCH_MODES = ("contains", "exact")
CONTROL_WIDTH = 190
CONTROL_HEIGHT = 32
BUTTON_WIDTH = 170
COMBO_STYLE = "QComboBox { padding: 4px 10px; } QComboBox::drop-down { width: 26px; }"


def style_combo(combo: QComboBox) -> QComboBox:
    combo.setEditable(False)
    combo.setInsertPolicy(QComboBox.NoInsert)
    combo.setMinimumWidth(CONTROL_WIDTH)
    combo.setMinimumHeight(CONTROL_HEIGHT)
    combo.setStyleSheet(COMBO_STYLE)
    return combo


def style_action_button(button: QPushButton, width: int = BUTTON_WIDTH) -> QPushButton:
    button.setMinimumWidth(width)
    button.setMinimumHeight(CONTROL_HEIGHT)
    return button

def apply_table_style(tree: QTreeWidget) -> None:
    """Apply standard Sovereign Sentinel styling to a QTreeWidget."""
    tree.setFont(monospace_font())
    tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
    tree.setSelectionBehavior(QAbstractItemView.SelectRows)
    tree.setSelectionMode(QAbstractItemView.SingleSelection)
    tree.setRootIsDecorated(False)


def configure_tree_columns(tree: QTreeWidget, widths: tuple[tuple[int, int], ...]) -> None:
    header = tree.header()
    header.setSectionsMovable(False)
    header.setStretchLastSection(False)
    header.setMinimumSectionSize(70)
    minimums: dict[int, int] = {}
    for index, (width, minimum) in enumerate(widths):
        minimums[index] = minimum
        header.setSectionResizeMode(index, QHeaderView.Interactive)
        header.resizeSection(index, max(width, minimum))

    def _clamp_section(index: int, _old_size: int, new_size: int) -> None:
        minimum = minimums.get(index, 70)
        if new_size >= minimum:
            return
        header.blockSignals(True)
        try:
            header.resizeSection(index, minimum)
        finally:
            header.blockSignals(False)

    header.sectionResized.connect(_clamp_section)


def process_row_google_search_url(row: dict) -> str:
    return build_google_search_url(row.get("process_name", ""), row.get("process_path", ""))


class ProcessDecisionDialog(QDialog):
    decision_applied = Signal(dict)

    def __init__(self, row: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.row = row
        title = row.get("process_name") or row.get("normalized_process_name") or "Unknown"
        self.setWindowTitle(f"Process Decision: {title}")
        self.resize(1040, 760)
        self.setMinimumSize(920, 660)

        self._build_layout()

    def _build_layout(self):
        layout = QVBoxLayout(self)
        
        # Identity
        identity_box = QGroupBox("Process")
        id_layout = QVBoxLayout(identity_box)
        rows = [
            ("Executable", self.row.get("process_name") or self.row.get("normalized_process_name") or "-"),
            ("Path", self.row.get("process_path") or self.row.get("normalized_process_path") or "-"),
            ("Directory", self.row.get("process_dir") or self.row.get("normalized_process_dir") or "-"),
            ("Status", self.row.get("status") or "-"),
            ("Students Opened", ", ".join(self.row.get("opened_students", [])) or "-"),
            ("Students Closed / Resolved", ", ".join(self.row.get("closed_students", [])) or "-"),
        ]
        for label, value in rows:
            row_layout = QHBoxLayout()
            lbl = QLabel(f"{label}:")
            lbl.setFixedWidth(180)
            val = QLabel(str(value))
            val.setFont(monospace_font())
            val.setWordWrap(True)
            row_layout.addWidget(lbl)
            row_layout.addWidget(val, stretch=1)
            id_layout.addLayout(row_layout)
        layout.addWidget(identity_box)

        # Decision
        controls_box = QGroupBox("Decision")
        controls_layout = QVBoxLayout(controls_box)
        
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Status:"))
        self.status_combo = style_combo(QComboBox())
        self.status_combo.addItems(["unknown", "whitelist", "blacklist", "warning"])
        self.status_combo.setCurrentText(str(self.row.get("status") or "unknown"))
        row1.addWidget(self.status_combo)
        
        row1.addSpacing(20)
        row1.addWidget(QLabel("Match Scope:"))
        self.scope_combo = style_combo(QComboBox())
        self.scope_combo.addItems(["path", "directory", "name"])
        self.scope_combo.setCurrentText(str(self.row.get("match_scope") or "path"))
        row1.addWidget(self.scope_combo)
        row1.addStretch()
        controls_layout.addLayout(row1)

        row2 = QHBoxLayout()
        actions = self.row.get("actions", {})
        self.chk_ban = QCheckBox("Ban")
        self.chk_ban.setChecked(bool(actions.get("ban", False)))
        self.chk_kick = QCheckBox("Kick")
        self.chk_kick.setChecked(bool(actions.get("kick", False)))
        self.chk_pause = QCheckBox("Pause Exam")
        self.chk_pause.setChecked(bool(actions.get("pause_exam", False)))
        self.chk_kill = QCheckBox("Kill PID")
        self.chk_kill.setChecked(bool(actions.get("kill_pid", False)))
        row2.addWidget(self.chk_ban)
        row2.addWidget(self.chk_kick)
        row2.addWidget(self.chk_pause)
        row2.addWidget(self.chk_kill)
        row2.addStretch()
        controls_layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.chk_save = QCheckBox("Save decision to policy")
        self.chk_save.setChecked(True)
        row3.addWidget(self.chk_save)
        row3.addStretch()
        
        btn_google = style_action_button(make_button("Google Search", "tonal"))
        btn_google.clicked.connect(self._on_google)
        row3.addWidget(btn_google)
        
        btn_apply = style_action_button(make_button("Apply Policy", "filled"))
        btn_apply.clicked.connect(self._on_apply)
        row3.addWidget(btn_apply)
        controls_layout.addLayout(row3)
        layout.addWidget(controls_box)

        # Students
        students_box = QGroupBox("Matching Students And Action State")
        students_layout = QVBoxLayout(students_box)
        self.students_tree = QTreeWidget()
        self.students_tree.setColumnCount(5)
        self.students_tree.setHeaderLabels(["Student", "Session", "PID", "Active", "Action State"])
        apply_table_style(self.students_tree)
        configure_tree_columns(
            self.students_tree,
            ((150, 100), (135, 95), (85, 65), (85, 65), (470, 180)),
        )
        
        for student in self.row.get("action_states", []):
            item = QTreeWidgetItem([
                student.get("login_id") or student.get("client_id") or "-",
                student.get("session_state") or "-",
                str(student.get("pid") or "-"),
                "Yes" if student.get("active") else "No",
                self._format_student_action_state(student)
            ])
            self.students_tree.addTopLevelItem(item)
        students_layout.addWidget(self.students_tree)
        layout.addWidget(students_box, stretch=1)

        # Previous
        prev_box = QGroupBox("Previous Matching Entries / Definitions")
        prev_layout = QVBoxLayout(prev_box)
        self.prev_tree = QTreeWidget()
        self.prev_tree.setColumnCount(5)
        self.prev_tree.setHeaderLabels(["Status", "Scope", "Path / Directory", "Actions", "Decided"])
        apply_table_style(self.prev_tree)
        configure_tree_columns(
            self.prev_tree,
            ((105, 80), (90, 70), (420, 180), (170, 110), (150, 110)),
        )
        
        for previous in self.row.get("previous_matching_entries", []):
            actions_str = ", ".join(name for name, enabled in previous.get("actions", {}).items() if enabled) or "-"
            item = QTreeWidgetItem([
                previous.get("status") or "-",
                previous.get("match_scope") or "-",
                previous.get("process_path") or previous.get("process_dir") or "-",
                actions_str,
                previous.get("decided_at") or previous.get("updated_at") or "-"
            ])
            self.prev_tree.addTopLevelItem(item)
        prev_layout.addWidget(self.prev_tree)
        layout.addWidget(prev_box, stretch=1)

    def _format_student_action_state(self, student: dict) -> str:
        parts = []
        for action in ("ban", "kick", "pause_exam", "kill_pid"):
            action_state = student.get("actions", {}).get(action, {})
            state_name = str(action_state.get("state", "not_possible") or "not_possible")
            reason = str(action_state.get("reason", "") or "")
            label = action.replace("_", " ")
            parts.append(f"{label}: {state_name}{f' ({reason})' if reason else ''}")
        return "; ".join(parts)

    def _on_google(self):
        webbrowser.open(process_row_google_search_url(self.row))

    def _on_apply(self):
        status = self.status_combo.currentText()
        match_scope = self.scope_combo.currentText()
        actions = {
            "ban": self.chk_ban.isChecked(),
            "kick": self.chk_kick.isChecked(),
            "pause_exam": self.chk_pause.isChecked(),
            "kill_pid": self.chk_kill.isChecked(),
        }
        
        payload = {
            "cmd": "apply_process_decision",
            "definition": {
                "definition_id": self.row.get("definition_id", ""),
                "process_key": self.row.get("process_key", ""),
                "process_name": self.row.get("process_name", ""),
                "normalized_process_name": self.row.get("normalized_process_name", ""),
                "process_path": self.row.get("process_path", ""),
                "normalized_process_path": self.row.get("normalized_process_path", ""),
                "process_dir": self.row.get("process_dir", ""),
                "normalized_process_dir": self.row.get("normalized_process_dir", ""),
                "match_scope": match_scope,
                "status": status,
                "actions": actions,
                "source_incident_id": self.row.get("source_incident_id", ""),
                "matching_history": list(self.row.get("matching_history", [])),
                "previous_matching_entries": list(self.row.get("previous_matching_entries", [])),
            },
            "status": status,
            "match_scope": match_scope,
            "actions": actions,
            "save_policy": self.chk_save.isChecked(),
        }
        self.decision_applied.emit(payload)
        self.accept()


class IncidentRuleDecisionDialog(QDialog):
    decision_applied = Signal(dict)

    def __init__(self, row: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.row = row
        title = row.get("name") or row.get("rule_id") or "Incident Rule"
        self.setWindowTitle(f"Incident Rule: {title}")
        self.resize(1040, 760)
        self.setMinimumSize(920, 660)

        self._build_layout()

    def _build_layout(self):
        layout = QVBoxLayout(self)

        identity_box = QGroupBox("Rule Match")
        identity_layout = QVBoxLayout(identity_box)
        rows = [
            ("Name", self.row.get("name") or "-"),
            ("Rule ID", self.row.get("rule_id") or "-"),
            ("Event Type", self.row.get("event_type") or "-"),
            ("Source", self.row.get("source") or "-"),
            ("Observed Title", incident_rule_observed_window_title(self.row) or "-"),
            ("Matches", str(self.row.get("match_count", 0) or len(self.row.get("matching_history", [])))),
        ]
        for label, value in rows:
            row_layout = QHBoxLayout()
            lbl = QLabel(f"{label}:")
            lbl.setFixedWidth(180)
            val = QLabel(str(value))
            val.setFont(monospace_font())
            val.setWordWrap(True)
            row_layout.addWidget(lbl)
            row_layout.addWidget(val, stretch=1)
            identity_layout.addLayout(row_layout)
        layout.addWidget(identity_box)

        match_box = QGroupBox("Saved Match Fields")
        match_layout = QVBoxLayout(match_box)

        title_row = QHBoxLayout()
        title_label = QLabel("Title Patterns:")
        title_label.setFixedWidth(180)
        self.title_patterns_edit = QPlainTextEdit()
        self.title_patterns_edit.setPlainText(incident_rule_field_text(self.row, "window_title_patterns"))
        self.title_patterns_edit.setMinimumHeight(76)
        self.title_patterns_edit.setFont(monospace_font())
        title_row.addWidget(title_label)
        title_row.addWidget(self.title_patterns_edit, stretch=1)
        match_layout.addLayout(title_row)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Match Mode:"))
        self.match_mode_combo = style_combo(QComboBox())
        self.match_mode_combo.addItems(["contains", "exact"])
        self.match_mode_combo.setCurrentText(str(self.row.get("match_mode") or "contains"))
        mode_row.addWidget(self.match_mode_combo)
        mode_row.addStretch()
        match_layout.addLayout(mode_row)

        process_row = QHBoxLayout()
        process_label = QLabel("Processes:")
        process_label.setFixedWidth(180)
        self.process_names_edit = QPlainTextEdit()
        self.process_names_edit.setPlainText(incident_rule_field_text(self.row, "process_names"))
        self.process_names_edit.setMinimumHeight(56)
        self.process_names_edit.setFont(monospace_font())
        process_row.addWidget(process_label)
        process_row.addWidget(self.process_names_edit, stretch=1)
        match_layout.addLayout(process_row)

        browser_row = QHBoxLayout()
        browser_label = QLabel("Browser Processes:")
        browser_label.setFixedWidth(180)
        self.browser_process_names_edit = QPlainTextEdit()
        self.browser_process_names_edit.setPlainText(incident_rule_field_text(self.row, "browser_process_names"))
        self.browser_process_names_edit.setMinimumHeight(56)
        self.browser_process_names_edit.setFont(monospace_font())
        browser_row.addWidget(browser_label)
        browser_row.addWidget(self.browser_process_names_edit, stretch=1)
        match_layout.addLayout(browser_row)

        layout.addWidget(match_box)

        controls_box = QGroupBox("Decision")
        controls_layout = QVBoxLayout(controls_box)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Status:"))
        self.status_combo = style_combo(QComboBox())
        self.status_combo.addItems(["unknown", "whitelist", "warning", "blacklist"])
        self.status_combo.setCurrentText(str(self.row.get("status") or "unknown"))
        row1.addWidget(self.status_combo)

        row1.addSpacing(20)
        row1.addWidget(QLabel("Priority:"))
        self.priority_entry = QLineEdit(str(self.row.get("priority", 0) or 0))
        self.priority_entry.setMinimumWidth(90)
        self.priority_entry.setMinimumHeight(CONTROL_HEIGHT)
        row1.addWidget(self.priority_entry)
        row1.addStretch()
        controls_layout.addLayout(row1)

        row2 = QHBoxLayout()
        actions = self.row.get("actions", {})
        self.chk_ban = QCheckBox("Ban")
        self.chk_ban.setChecked(bool(actions.get("ban", False)))
        self.chk_kick = QCheckBox("Kick")
        self.chk_kick.setChecked(bool(actions.get("kick", False)))
        self.chk_pause = QCheckBox("Pause Exam")
        self.chk_pause.setChecked(bool(actions.get("pause_exam", False)))
        self.chk_kill = QCheckBox("Kill PID")
        self.chk_kill.setChecked(bool(actions.get("kill_pid", False)))
        row2.addWidget(self.chk_ban)
        row2.addWidget(self.chk_kick)
        row2.addWidget(self.chk_pause)
        row2.addWidget(self.chk_kill)
        row2.addStretch()
        controls_layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.chk_save = QCheckBox("Save decision to policy")
        self.chk_save.setChecked(True)
        row3.addWidget(self.chk_save)
        row3.addStretch()
        btn_apply = style_action_button(make_button("Apply Rule", "filled"))
        btn_apply.clicked.connect(self._on_apply)
        row3.addWidget(btn_apply)
        controls_layout.addLayout(row3)
        layout.addWidget(controls_box)

        history_box = QGroupBox("Matching Incidents")
        history_layout = QVBoxLayout(history_box)
        self.history_tree = QTreeWidget()
        self.history_tree.setColumnCount(6)
        self.history_tree.setHeaderLabels(["Student", "Rule", "Status", "PID", "Active", "Summary"])
        apply_table_style(self.history_tree)
        configure_tree_columns(
            self.history_tree,
            ((140, 95), (165, 110), (95, 75), (80, 60), (80, 60), (460, 180)),
        )
        for incident in self.row.get("matching_history", []):
            item = QTreeWidgetItem([
                incident.get("login_id") or incident.get("client_id") or "-",
                incident.get("rule_id") or "-",
                incident.get("status") or "-",
                str(incident.get("pid") or "-"),
                "Yes" if incident.get("active") else "No",
                incident.get("summary") or "-",
            ])
            self.history_tree.addTopLevelItem(item)
        history_layout.addWidget(self.history_tree)
        layout.addWidget(history_box, stretch=1)

    def _on_apply(self):
        try:
            priority = int(str(self.priority_entry.text() or "0").strip())
        except ValueError:
            QMessageBox.warning(self, "Incident Rule", "Priority must be an integer.")
            return
        actions = {
            "ban": self.chk_ban.isChecked(),
            "kick": self.chk_kick.isChecked(),
            "pause_exam": self.chk_pause.isChecked(),
            "kill_pid": self.chk_kill.isChecked(),
        }
        payload = build_incident_rule_decision_payload(
            self.row,
            status=self.status_combo.currentText(),
            actions=actions,
            save_policy=self.chk_save.isChecked(),
            priority=priority,
            process_names=split_multiline_values(self.process_names_edit.toPlainText(), split_commas=True),
            browser_process_names=split_multiline_values(
                self.browser_process_names_edit.toPlainText(),
                split_commas=True,
            ),
            window_title_patterns=split_multiline_values(self.title_patterns_edit.toPlainText()),
            match_mode=self.match_mode_combo.currentText(),
        )
        self.decision_applied.emit(payload)
        self.accept()


class PolicySettingsDialog(QDialog):
    settings_saved = Signal(dict)
    export_requested = Signal()
    import_requested = Signal()
    edit_policy_requested = Signal()
    apply_policy_requested = Signal()
    edit_definitions_requested = Signal()
    apply_definitions_requested = Signal()
    edit_incident_rules_requested = Signal()
    apply_incident_rules_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Policy Settings")
        self.resize(1180, 820)
        self.setMinimumSize(1060, 720)
        
        self.snapshot: dict = {}
        self.vars: dict[str, QWidget] = {}
        self._dirty = False
        self._loading = False
        
        self._build_layout()

    def _build_layout(self):
        layout = QVBoxLayout(self)
        
        # Toolbar
        toolbar = QHBoxLayout()
        self.btn_save = style_action_button(make_button("Save Settings", "filled"))
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._on_save)
        toolbar.addWidget(self.btn_save)
        
        btn_reload = style_action_button(make_button("Reload", "tonal"), 120)
        btn_reload.clicked.connect(self._on_reload)
        toolbar.addWidget(btn_reload)
        
        toolbar.addStretch()
        
        btn_export = style_action_button(make_button("Export", "outlined"), 120)
        btn_export.clicked.connect(self.export_requested.emit)
        toolbar.addWidget(btn_export)
        
        btn_import = style_action_button(make_button("Import", "outlined"), 120)
        btn_import.clicked.connect(self.import_requested.emit)
        toolbar.addWidget(btn_import)
        layout.addLayout(toolbar)
        
        self.lbl_status = QLabel("Waiting for server settings...")
        layout.addWidget(self.lbl_status)
        
        # Tabs
        self.tabs = QTabWidget()
        self._build_general_tab()
        self._build_process_lists_tab()
        self._build_window_rules_tab()
        self._build_definitions_tab()
        self._build_incident_rules_tab()
        layout.addWidget(self.tabs, stretch=1)

    def _mark_dirty(self):
        if self._loading:
            return
        self._dirty = True
        self._refresh_status()

    def _refresh_status(self, extra: str = ""):
        version = str(self.snapshot.get("policy_version", "") or "")
        blacklist_version = str(self.snapshot.get("process_blacklist_version", "") or "")
        definitions_version = str(self.snapshot.get("process_definitions_version", "") or "")
        incident_rules_version = str(self.snapshot.get("incident_rules_version", "") or "")
        label = (
            f"Policy {version[:12] or '-'} | "
            f"Blacklist {blacklist_version[:12] or '-'} | "
            f"Definitions {definitions_version[:12] or '-'} | "
            f"Incident Rules {incident_rules_version[:12] or '-'}"
        )
        if self._dirty:
            label += " | Unsaved changes"
        if extra:
            label += f" | {extra}"
        self.lbl_status.setText(label)

    def _add_check(self, layout, key: str, text: str) -> QCheckBox:
        chk = QCheckBox(text)
        chk.stateChanged.connect(self._mark_dirty)
        self.vars[key] = chk
        layout.addWidget(chk)
        return chk

    def _add_entry(self, layout, key: str, label: str) -> QLineEdit:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        entry = QLineEdit()
        entry.setMinimumWidth(CONTROL_WIDTH)
        entry.setMinimumHeight(CONTROL_HEIGHT)
        entry.textChanged.connect(self._mark_dirty)
        self.vars[key] = entry
        row.addWidget(entry)
        row.addStretch()
        layout.addLayout(row)
        return entry

    def _add_combo(self, layout, key: str, label: str, items: list[str]) -> QComboBox:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        combo = style_combo(QComboBox())
        combo.addItems(items)
        combo.currentTextChanged.connect(self._mark_dirty)
        self.vars[key] = combo
        row.addWidget(combo)
        row.addStretch()
        layout.addLayout(row)
        return combo

    def _add_text(self, layout, key: str, label: str, *, height: int = 82) -> QPlainTextEdit:
        layout.addWidget(QLabel(label))
        text = QPlainTextEdit()
        text.setFont(monospace_font())
        text.setFixedHeight(height)
        text.textChanged.connect(self._mark_dirty)
        self.vars[key] = text
        layout.addWidget(text)
        return text

    def _add_group(self, parent_layout, title: str) -> QVBoxLayout:
        box = QGroupBox(title)
        group_layout = QVBoxLayout(box)
        parent_layout.addWidget(box)
        return group_layout

    def _build_general_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        runtime = self._add_group(layout, "Runtime")
        self._add_entry(runtime, "runtime.exam_duration", "Exam Duration (min):")
        
        row = QHBoxLayout()
        row.addWidget(QLabel("Exam Files:"))
        entry = QLineEdit()
        entry.textChanged.connect(self._mark_dirty)
        self.vars["runtime.exam_files"] = entry
        row.addWidget(entry, stretch=1)
        
        btn_browse = make_button("Browse", "tonal")
        btn_browse.clicked.connect(self._on_browse_files)
        row.addWidget(btn_browse)
        
        btn_clear = make_button("Clear", "text")
        btn_clear.clicked.connect(lambda: entry.setText(""))
        row.addWidget(btn_clear)
        runtime.addLayout(row)

        layout.addStretch()
        checks = QHBoxLayout()
        session = self._add_group(checks, "Session")
        self._add_check(session, "session.auto_resume_on_reconnect", "Auto resume on reconnect")
        self._add_check(session, "session.remember_settings", "Remember settings")

        confirmations = self._add_group(checks, "Operator Confirmations")
        self._add_check(confirmations, "operator_defaults.confirm_kill_pid", "Confirm kill PID")
        self._add_check(confirmations, "operator_defaults.confirm_kick", "Confirm kick")
        self._add_check(confirmations, "operator_defaults.confirm_ban", "Confirm ban")
        self._add_check(confirmations, "operator_defaults.confirm_pause", "Confirm pause")
        layout.addLayout(checks)
        self.tabs.addTab(tab, "General")

    def _on_browse_files(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose Exam Files", "", "ZIP Files (*.zip);;All Files (*)")
        if path:
            self.vars["runtime.exam_files"].setText(path)

    def _build_process_lists_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        columns = QHBoxLayout()
        blacklist = self._add_group(columns, "Process Blacklist")
        self._add_combo(blacklist, "rules.process_blacklist.severity", "Severity:", list(SEVERITY_VALUES))
        self._add_text(blacklist, "process_blacklist.entries", "Blacklisted process names, one per line:")
        self._add_text(blacklist, "rules.process_blacklist.process_usernames", "Monitored process usernames, one per line:")
        blacklist_options = self._add_group(blacklist, "Options")
        self._add_check(blacklist_options, "rules.process_blacklist.enabled", "Enabled")
        self._add_check(blacklist_options, "rules.process_blacklist.auto_violation_pause", "Auto pause on violation")
        self._add_check(blacklist_options, "rules.process_blacklist.allow_remote_kill", "Allow remote kill")

        unexpected = self._add_group(columns, "Unexpected Process")
        self._add_combo(unexpected, "rules.unexpected_process.severity", "Severity:", list(SEVERITY_VALUES))
        self._add_text(unexpected, "rules.unexpected_process.known_process_names", "Known process names, one per line:")
        self._add_text(unexpected, "rules.unexpected_process.known_directory_paths", "Known directory paths, one per line:")
        self._add_text(unexpected, "rules.unexpected_process.allowed_process_names", "Allowed process names, one per line:")
        unexpected_options = self._add_group(unexpected, "Options")
        self._add_check(unexpected_options, "rules.unexpected_process.enabled", "Enabled")
        self._add_check(unexpected_options, "rules.unexpected_process.baseline_existing_processes", "Baseline existing processes")
        self._add_check(unexpected_options, "rules.unexpected_process.auto_violation_pause", "Auto pause on violation")
        layout.addLayout(columns)
        self.tabs.addTab(tab, "Process Lists")

    def _build_window_rules_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        columns = QHBoxLayout()
        focused = self._add_group(columns, "Focused Window")
        self._add_combo(focused, "rules.focused_window.severity", "Severity:", list(SEVERITY_VALUES))
        self._add_combo(focused, "rules.focused_window.window_title_match_mode", "Titlebar Match:", list(WINDOW_TITLE_MATCH_MODES))
        self._add_entry(focused, "rules.focused_window.open_after_consecutive", "Open After:")
        self._add_entry(focused, "rules.focused_window.resolve_after_consecutive", "Resolve After:")
        self._add_text(focused, "rules.focused_window.allowed_process_names", "Allowed process names, one per line:", height=54)
        self._add_text(focused, "rules.focused_window.allowed_window_titles", "Allowed titlebar text, one per line:", height=54)
        self._add_text(focused, "rules.focused_window.blocked_process_names", "Blocked process names, one per line:", height=54)
        self._add_text(focused, "rules.focused_window.blocked_window_titles", "Blocked titlebar text, one per line:", height=54)
        focused_options = self._add_group(focused, "Options")
        self._add_check(focused_options, "rules.focused_window.enabled", "Enabled")
        self._add_check(focused_options, "rules.focused_window.auto_violation_pause", "Auto pause on violation")

        switching = self._add_group(columns, "Switching And Path Checks")
        self._add_combo(switching, "rules.rapid_application_switching.severity", "Rapid Severity:", list(SEVERITY_VALUES))
        self._add_entry(switching, "rules.rapid_application_switching.max_switches", "Max Switches:")
        self._add_entry(switching, "rules.rapid_application_switching.window_seconds", "Window Seconds:")
        self._add_entry(switching, "rules.rapid_application_switching.window_observations", "Window Observations:")
        self._add_combo(switching, "rules.process_path_clarification.severity", "Path Severity:", list(SEVERITY_VALUES))
        switching.addStretch()
        switching_options = self._add_group(switching, "Options")
        self._add_check(switching_options, "rules.rapid_application_switching.enabled", "Rapid switch enabled")
        self._add_check(switching_options, "rules.rapid_application_switching.auto_violation_pause", "Rapid switch auto pause")
        self._add_check(switching_options, "rules.process_path_clarification.enabled", "Path clarification enabled")
        self._add_check(switching_options, "rules.process_path_clarification.auto_violation_pause", "Path clarification auto pause")
        self._add_check(switching_options, "rules.process_path_clarification.allow_remote_kill", "Path clarification remote kill")

        idle = self._add_group(columns, "Idle Policy")
        self._add_combo(idle, "rules.idle_policy.severity", "Severity:", list(SEVERITY_VALUES))
        self._add_entry(idle, "rules.idle_policy.warn_threshold_seconds", "Warn After (sec):")
        self._add_entry(idle, "rules.idle_policy.critical_threshold_seconds", "Critical After (sec):")
        idle_options = self._add_group(idle, "Options")
        self._add_check(idle_options, "rules.idle_policy.enabled", "Enabled")
        self._add_check(idle_options, "rules.idle_policy.auto_violation_pause", "Auto pause on critical idle")
        layout.addLayout(columns)
        self.tabs.addTab(tab, "Window Rules")

    def _build_definitions_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._add_combo(layout, "rules.process_definitions.severity", "Severity:", list(SEVERITY_VALUES))
        self._add_combo(layout, "rules.process_definitions.unknown_severity", "Unknown Severity:", list(SEVERITY_VALUES))
        actions = QHBoxLayout()
        btn_edit = style_action_button(make_button("Open Definitions File", "tonal"), 210)
        btn_edit.clicked.connect(self.edit_definitions_requested.emit)
        actions.addWidget(btn_edit)
        btn_apply = style_action_button(make_button("Apply Definitions File", "outlined"), 210)
        btn_apply.clicked.connect(self.apply_definitions_requested.emit)
        actions.addWidget(btn_apply)
        actions.addStretch()
        layout.addLayout(actions)
        options = self._add_group(layout, "Options")
        self._add_check(options, "rules.process_definitions.enabled", "Enabled")
        self._add_check(options, "rules.process_definitions.detect_unknown_processes", "Detect unknown processes")
        self._add_check(options, "rules.process_definitions.baseline_existing_processes", "Baseline existing processes")
        self._add_check(options, "rules.process_definitions.auto_violation_pause", "Auto pause on violation")
        self._add_check(options, "rules.process_definitions.allow_remote_kill", "Allow remote kill")
        self.tabs.addTab(tab, "Process Definitions")

    def _build_incident_rules_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._add_combo(layout, "rules.incident_rules.severity", "Severity:", list(SEVERITY_VALUES))
        actions = QHBoxLayout()
        btn_edit = style_action_button(make_button("Open Incident Rules File", "tonal"), 230)
        btn_edit.clicked.connect(self.edit_incident_rules_requested.emit)
        actions.addWidget(btn_edit)
        btn_apply = style_action_button(make_button("Apply Incident Rules File", "outlined"), 230)
        btn_apply.clicked.connect(self.apply_incident_rules_requested.emit)
        actions.addWidget(btn_apply)
        actions.addStretch()
        layout.addLayout(actions)
        options = self._add_group(layout, "Options")
        self._add_check(options, "rules.incident_rules.enabled", "Enabled")
        self._add_check(options, "rules.incident_rules.auto_violation_pause", "Auto pause on violation")
        self._add_check(options, "rules.incident_rules.allow_remote_kill", "Allow remote kill")
        layout.addStretch()
        self.tabs.addTab(tab, "Incident Rules")

    def set_val(self, key: str, value):
        w = self.vars.get(key)
        if not w: return
        if isinstance(w, QCheckBox):
            w.setChecked(bool(value))
        elif isinstance(w, QComboBox):
            w.setCurrentText("" if value is None else str(value))
        elif isinstance(w, QLineEdit):
            w.setText("" if value is None else str(value))
        elif isinstance(w, QPlainTextEdit):
            w.setPlainText("" if value is None else str(value))

    def get_bool(self, key: str) -> bool:
        w = self.vars.get(key)
        return w.isChecked() if isinstance(w, QCheckBox) else False

    def get_str(self, key: str) -> str:
        w = self.vars.get(key)
        if isinstance(w, QComboBox): return w.currentText()
        if isinstance(w, QLineEdit): return w.text()
        if isinstance(w, QPlainTextEdit): return w.toPlainText()
        return ""

    def get_int(self, key: str, label: str) -> int:
        val = self.get_str(key).strip()
        try:
            res = int(val)
        except ValueError:
            raise ValueError(f"{label} must be a positive integer.")
        if res <= 0:
            raise ValueError(f"{label} must be greater than 0.")
        return res

    def get_lines(self, key: str) -> list[str]:
        return [line.strip() for line in self.get_str(key).splitlines() if line.strip()]

    def get_json_list(self, key: str, label: str) -> list[dict]:
        val = self.get_str(key).strip()
        if not val: return []
        try:
            res = json.loads(val)
        except json.JSONDecodeError as e:
            raise ValueError(f"{label} must be valid JSON: {e}")
        if not isinstance(res, list):
            raise ValueError(f"{label} must be a JSON list.")
        return res

    def _on_reload(self):
        if self._dirty:
            reply = QMessageBox.question(self, "Reload Settings", "Discard unsaved settings changes and reload?", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No: return
        self.update_snapshot(self.snapshot, force=True)

    def update_snapshot(self, snapshot: dict, force: bool = False):
        self.snapshot = snapshot
        if not snapshot:
            self.lbl_status.setText("Waiting for server settings...")
            return
            
        self.btn_save.setEnabled(True)
        if not force and self._dirty:
            self._refresh_status()
            return
            
        self._loading = True
        try:
            policy = snapshot.get("exam_policy", {}) or {}
            rules = policy.get("rules", {}) or {}
            session = policy.get("session", {}) or {}
            op_def = policy.get("operator_defaults", {}) or {}
            runtime = snapshot.get("runtime", {}) or {}

            self.set_val("runtime.exam_duration", runtime.get("exam_duration", ""))
            self.set_val("runtime.exam_files", runtime.get("exam_files", ""))

            self.set_val("session.auto_resume_on_reconnect", session.get("auto_resume_on_reconnect", True))
            self.set_val("session.remember_settings", session.get("remember_settings", True))

            bl = rules.get("process_blacklist", {}) or {}
            self.set_val("rules.process_blacklist.enabled", bl.get("enabled", True))
            self.set_val("rules.process_blacklist.severity", bl.get("severity", "violation"))
            self.set_val("rules.process_blacklist.auto_violation_pause", bl.get("auto_violation_pause", False))
            self.set_val("rules.process_blacklist.allow_remote_kill", bl.get("allow_remote_kill", True))
            self.set_val("process_blacklist.entries", "\n".join(snapshot.get("process_blacklist", [])))
            self.set_val("rules.process_blacklist.process_usernames", "\n".join(bl.get("process_usernames", [])))

            fw = rules.get("focused_window", {}) or {}
            self.set_val("rules.focused_window.enabled", fw.get("enabled", False))
            self.set_val("rules.focused_window.severity", fw.get("severity", "warning"))
            self.set_val("rules.focused_window.window_title_match_mode", fw.get("window_title_match_mode", "contains"))
            self.set_val("rules.focused_window.open_after_consecutive", fw.get("open_after_consecutive", 3))
            self.set_val("rules.focused_window.resolve_after_consecutive", fw.get("resolve_after_consecutive", 2))
            self.set_val("rules.focused_window.auto_violation_pause", fw.get("auto_violation_pause", False))
            self.set_val("rules.focused_window.allowed_process_names", "\n".join(fw.get("allowed_process_names", [])))
            self.set_val("rules.focused_window.allowed_window_titles", "\n".join(fw.get("allowed_window_titles", [])))
            self.set_val("rules.focused_window.blocked_process_names", "\n".join(fw.get("blocked_process_names", [])))
            self.set_val("rules.focused_window.blocked_window_titles", "\n".join(fw.get("blocked_window_titles", [])))

            rs = rules.get("rapid_application_switching", {}) or {}
            self.set_val("rules.rapid_application_switching.enabled", rs.get("enabled", False))
            self.set_val("rules.rapid_application_switching.severity", rs.get("severity", "warning"))
            self.set_val("rules.rapid_application_switching.max_switches", rs.get("max_switches", 10))
            self.set_val("rules.rapid_application_switching.window_seconds", rs.get("window_seconds", 60))
            self.set_val("rules.rapid_application_switching.window_observations", rs.get("window_observations", 10))
            self.set_val("rules.rapid_application_switching.auto_violation_pause", rs.get("auto_violation_pause", False))

            idle = rules.get("idle_policy", {}) or {}
            self.set_val("rules.idle_policy.enabled", idle.get("enabled", False))
            self.set_val("rules.idle_policy.severity", idle.get("severity", "warning"))
            self.set_val("rules.idle_policy.warn_threshold_seconds", idle.get("warn_threshold_seconds", 80))
            self.set_val("rules.idle_policy.critical_threshold_seconds", idle.get("critical_threshold_seconds", 150))
            self.set_val("rules.idle_policy.auto_violation_pause", idle.get("auto_violation_pause", False))

            up = rules.get("unexpected_process", {}) or {}
            self.set_val("rules.unexpected_process.enabled", up.get("enabled", False))
            self.set_val("rules.unexpected_process.severity", up.get("severity", "warning"))
            self.set_val("rules.unexpected_process.baseline_existing_processes", up.get("baseline_existing_processes", False))
            self.set_val("rules.unexpected_process.auto_violation_pause", up.get("auto_violation_pause", False))
            self.set_val("rules.unexpected_process.known_process_names", "\n".join(up.get("known_process_names", [])))
            self.set_val("rules.unexpected_process.known_directory_paths", "\n".join(up.get("known_directory_paths", [])))
            self.set_val("rules.unexpected_process.allowed_process_names", "\n".join(up.get("allowed_process_names", [])))

            pd = rules.get("process_definitions", {}) or {}
            self.set_val("rules.process_definitions.enabled", pd.get("enabled", True))
            self.set_val("rules.process_definitions.severity", pd.get("severity", "violation"))
            self.set_val("rules.process_definitions.detect_unknown_processes", pd.get("detect_unknown_processes", True))
            self.set_val("rules.process_definitions.unknown_severity", pd.get("unknown_severity", "warning"))
            self.set_val("rules.process_definitions.baseline_existing_processes", pd.get("baseline_existing_processes", True))
            self.set_val("rules.process_definitions.auto_violation_pause", pd.get("auto_violation_pause", False))
            self.set_val("rules.process_definitions.allow_remote_kill", pd.get("allow_remote_kill", True))
            ir = rules.get("incident_rules", {}) or {}
            self.set_val("rules.incident_rules.enabled", ir.get("enabled", True))
            self.set_val("rules.incident_rules.severity", ir.get("severity", "warning"))
            self.set_val("rules.incident_rules.auto_violation_pause", ir.get("auto_violation_pause", False))
            self.set_val("rules.incident_rules.allow_remote_kill", ir.get("allow_remote_kill", True))
            pc = rules.get("process_path_clarification", {}) or {}
            self.set_val("rules.process_path_clarification.enabled", pc.get("enabled", True))
            self.set_val("rules.process_path_clarification.severity", pc.get("severity", "warning"))
            self.set_val("rules.process_path_clarification.auto_violation_pause", pc.get("auto_violation_pause", False))
            self.set_val("rules.process_path_clarification.allow_remote_kill", pc.get("allow_remote_kill", True))

            self.set_val("operator_defaults.confirm_kill_pid", op_def.get("confirm_kill_pid", True))
            self.set_val("operator_defaults.confirm_kick", op_def.get("confirm_kick", True))
            self.set_val("operator_defaults.confirm_ban", op_def.get("confirm_ban", True))
            self.set_val("operator_defaults.confirm_pause", op_def.get("confirm_pause", True))
        finally:
            self._loading = False
            self._dirty = False
            self._refresh_status()

    def _on_save(self):
        try:
            payload = self._collect_payload()
        except ValueError as e:
            QMessageBox.warning(self, "Settings Error", str(e))
            return

        self._dirty = False
        self.lbl_status.setText("Saving settings...")
        self.settings_saved.emit(payload)

    def _collect_payload(self) -> dict:
        exam_files = self.get_str("runtime.exam_files").strip()
        idle_warn_threshold = self.get_int("rules.idle_policy.warn_threshold_seconds", "Idle warning threshold")
        idle_critical_threshold = self.get_int("rules.idle_policy.critical_threshold_seconds", "Idle critical threshold")
        if idle_critical_threshold < idle_warn_threshold:
            raise ValueError("Idle critical threshold must be greater than or equal to the warning threshold.")
        
        payload = {
            "cmd": "save_settings",
            "runtime": {
                "exam_duration": self.get_int("runtime.exam_duration", "Exam duration"),
                "exam_files": exam_files if exam_files else None,
            },
            "process_blacklist": {
                "entries": self.get_lines("process_blacklist.entries")
            },
            "exam_policy": {
                "session": {
                    "auto_resume_on_reconnect": self.get_bool("session.auto_resume_on_reconnect"),
                    "remember_settings": self.get_bool("session.remember_settings"),
                },
                "operator_defaults": {
                    "confirm_kill_pid": self.get_bool("operator_defaults.confirm_kill_pid"),
                    "confirm_kick": self.get_bool("operator_defaults.confirm_kick"),
                    "confirm_ban": self.get_bool("operator_defaults.confirm_ban"),
                    "confirm_pause": self.get_bool("operator_defaults.confirm_pause"),
                },
                "rules": {
                    "process_blacklist": {
                        "enabled": self.get_bool("rules.process_blacklist.enabled"),
                        "severity": self.get_str("rules.process_blacklist.severity"),
                        "auto_violation_pause": self.get_bool("rules.process_blacklist.auto_violation_pause"),
                        "allow_remote_kill": self.get_bool("rules.process_blacklist.allow_remote_kill"),
                        "process_usernames": self.get_lines("rules.process_blacklist.process_usernames"),
                    },
                    "focused_window": {
                        "enabled": self.get_bool("rules.focused_window.enabled"),
                        "severity": self.get_str("rules.focused_window.severity"),
                        "window_title_match_mode": self.get_str("rules.focused_window.window_title_match_mode"),
                        "open_after_consecutive": self.get_int("rules.focused_window.open_after_consecutive", "Focused window open-after"),
                        "resolve_after_consecutive": self.get_int("rules.focused_window.resolve_after_consecutive", "Focused window resolve-after"),
                        "auto_violation_pause": self.get_bool("rules.focused_window.auto_violation_pause"),
                        "allowed_process_names": self.get_lines("rules.focused_window.allowed_process_names"),
                        "allowed_window_titles": self.get_lines("rules.focused_window.allowed_window_titles"),
                        "blocked_process_names": self.get_lines("rules.focused_window.blocked_process_names"),
                        "blocked_window_titles": self.get_lines("rules.focused_window.blocked_window_titles"),
                    },
                    "rapid_application_switching": {
                        "enabled": self.get_bool("rules.rapid_application_switching.enabled"),
                        "severity": self.get_str("rules.rapid_application_switching.severity"),
                        "max_switches": self.get_int("rules.rapid_application_switching.max_switches", "Rapid-switch max switches"),
                        "window_seconds": self.get_int("rules.rapid_application_switching.window_seconds", "Rapid-switch window seconds"),
                        "window_observations": self.get_int("rules.rapid_application_switching.window_observations", "Rapid-switch window observations"),
                        "auto_violation_pause": self.get_bool("rules.rapid_application_switching.auto_violation_pause"),
                    },
                    "idle_policy": {
                        "enabled": self.get_bool("rules.idle_policy.enabled"),
                        "severity": self.get_str("rules.idle_policy.severity"),
                        "warn_threshold_seconds": idle_warn_threshold,
                        "critical_threshold_seconds": idle_critical_threshold,
                        "auto_violation_pause": self.get_bool("rules.idle_policy.auto_violation_pause"),
                    },
                    "unexpected_process": {
                        "enabled": self.get_bool("rules.unexpected_process.enabled"),
                        "severity": self.get_str("rules.unexpected_process.severity"),
                        "baseline_existing_processes": self.get_bool("rules.unexpected_process.baseline_existing_processes"),
                        "auto_violation_pause": self.get_bool("rules.unexpected_process.auto_violation_pause"),
                        "known_process_names": self.get_lines("rules.unexpected_process.known_process_names"),
                        "known_directory_paths": self.get_lines("rules.unexpected_process.known_directory_paths"),
                        "allowed_process_names": self.get_lines("rules.unexpected_process.allowed_process_names"),
                    },
                    "process_definitions": {
                        "enabled": self.get_bool("rules.process_definitions.enabled"),
                        "severity": self.get_str("rules.process_definitions.severity"),
                        "detect_unknown_processes": self.get_bool("rules.process_definitions.detect_unknown_processes"),
                        "unknown_severity": self.get_str("rules.process_definitions.unknown_severity"),
                        "baseline_existing_processes": self.get_bool("rules.process_definitions.baseline_existing_processes"),
                        "auto_violation_pause": self.get_bool("rules.process_definitions.auto_violation_pause"),
                        "allow_remote_kill": self.get_bool("rules.process_definitions.allow_remote_kill"),
                    },
                    "incident_rules": {
                        "enabled": self.get_bool("rules.incident_rules.enabled"),
                        "severity": self.get_str("rules.incident_rules.severity"),
                        "auto_violation_pause": self.get_bool("rules.incident_rules.auto_violation_pause"),
                        "allow_remote_kill": self.get_bool("rules.incident_rules.allow_remote_kill"),
                    },
                    "process_path_clarification": {
                        "enabled": self.get_bool("rules.process_path_clarification.enabled"),
                        "severity": self.get_str("rules.process_path_clarification.severity"),
                        "auto_violation_pause": self.get_bool("rules.process_path_clarification.auto_violation_pause"),
                        "allow_remote_kill": self.get_bool("rules.process_path_clarification.allow_remote_kill"),
                    }
                }
            }
        }
        return payload

    def process_result(self, ok: bool, message: str):
        if ok:
            self._dirty = False
            self._refresh_status(message)
        else:
            QMessageBox.warning(self, "Settings Failed", message)
            self._refresh_status(f"Failed: {message}")

    def closeEvent(self, event):
        if self._dirty:
            reply = QMessageBox.question(self, "Close Policy Settings", "Close and discard unsaved changes?", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                event.ignore()
                return
        super().closeEvent(event)
