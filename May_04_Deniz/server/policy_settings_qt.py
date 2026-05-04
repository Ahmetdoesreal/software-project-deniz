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

SEVERITY_VALUES = ("info", "warning", "violation")
WINDOW_TITLE_MATCH_MODES = ("contains", "exact")

def apply_table_style(tree: QTreeWidget) -> None:
    """Apply standard Sovereign Sentinel styling to a QTreeWidget."""
    tree.setFont(monospace_font())
    tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
    tree.setSelectionBehavior(QAbstractItemView.SelectRows)
    tree.setSelectionMode(QAbstractItemView.SingleSelection)
    tree.setRootIsDecorated(False)


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
        self.status_combo = QComboBox()
        self.status_combo.setEditable(False)
        self.status_combo.setInsertPolicy(QComboBox.NoInsert)
        self.status_combo.addItems(["unknown", "whitelist", "blacklist", "warning"])
        self.status_combo.setCurrentText(str(self.row.get("status") or "unknown"))
        row1.addWidget(self.status_combo)
        
        row1.addSpacing(20)
        row1.addWidget(QLabel("Match Scope:"))
        self.scope_combo = QComboBox()
        self.scope_combo.setEditable(False)
        self.scope_combo.setInsertPolicy(QComboBox.NoInsert)
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
        
        btn_google = make_button("Google Search", "tonal")
        btn_google.clicked.connect(self._on_google)
        row3.addWidget(btn_google)
        
        btn_apply = make_button("Apply Policy", "filled")
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
        header = self.students_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        
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
        header2 = self.prev_tree.header()
        header2.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header2.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header2.setSectionResizeMode(2, QHeaderView.Stretch)
        header2.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header2.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        
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


class PolicySettingsDialog(QDialog):
    settings_saved = Signal(dict)
    export_requested = Signal()
    import_requested = Signal()
    edit_policy_requested = Signal()
    apply_policy_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Policy Settings")
        self.resize(1120, 760)
        self.setMinimumSize(980, 660)
        
        self.snapshot: dict = {}
        self.vars: dict[str, QWidget] = {}
        self._dirty = False
        self._loading = False
        
        self._build_layout()

    def _build_layout(self):
        layout = QVBoxLayout(self)
        
        # Toolbar
        toolbar = QHBoxLayout()
        self.btn_save = make_button("Save Settings", "filled")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._on_save)
        toolbar.addWidget(self.btn_save)
        
        btn_reload = make_button("Reload", "tonal")
        btn_reload.clicked.connect(self._on_reload)
        toolbar.addWidget(btn_reload)
        
        toolbar.addStretch()
        
        btn_export = make_button("Export", "outlined")
        btn_export.clicked.connect(self.export_requested.emit)
        toolbar.addWidget(btn_export)
        
        btn_import = make_button("Import", "outlined")
        btn_import.clicked.connect(self.import_requested.emit)
        toolbar.addWidget(btn_import)
        
        btn_edit = make_button("Open Policy File", "tonal")
        btn_edit.clicked.connect(self.edit_policy_requested.emit)
        toolbar.addWidget(btn_edit)
        
        btn_apply = make_button("Apply Policy File", "tonal")
        btn_apply.clicked.connect(self.apply_policy_requested.emit)
        toolbar.addWidget(btn_apply)
        layout.addLayout(toolbar)
        
        self.lbl_status = QLabel("Waiting for server settings...")
        layout.addWidget(self.lbl_status)
        
        # Tabs
        self.tabs = QTabWidget()
        self._build_runtime_tab()
        self._build_session_tab()
        self._build_blacklist_tab()
        self._build_focused_tab()
        self._build_rapid_tab()
        self._build_unexpected_tab()
        self._build_definitions_tab()
        self._build_path_tab()
        self._build_operator_tab()
        layout.addWidget(self.tabs, stretch=1)

    def _mark_dirty(self):
        if self._loading:
            return
        self._dirty = True
        self._refresh_status()

    def _refresh_status(self, extra: str = ""):
        version = str(self.snapshot.get("policy_version", "") or "")
        blacklist_version = str(self.snapshot.get("process_blacklist_version", "") or "")
        label = f"Policy {version[:12] or '-'} | Blacklist {blacklist_version[:12] or '-'}"
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
        entry.textChanged.connect(self._mark_dirty)
        self.vars[key] = entry
        row.addWidget(entry)
        row.addStretch()
        layout.addLayout(row)
        return entry

    def _add_combo(self, layout, key: str, label: str, items: list[str]) -> QComboBox:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        combo = QComboBox()
        combo.setEditable(False)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.addItems(items)
        combo.currentTextChanged.connect(self._mark_dirty)
        self.vars[key] = combo
        row.addWidget(combo)
        row.addStretch()
        layout.addLayout(row)
        return combo

    def _add_text(self, layout, key: str, label: str) -> QPlainTextEdit:
        layout.addWidget(QLabel(label))
        text = QPlainTextEdit()
        text.setFont(monospace_font())
        text.textChanged.connect(self._mark_dirty)
        self.vars[key] = text
        layout.addWidget(text, stretch=1)
        return text

    def _build_runtime_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._add_entry(layout, "runtime.exam_duration", "Exam Duration (min):")
        
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
        layout.addLayout(row)
        
        layout.addStretch()
        self.tabs.addTab(tab, "Runtime")

    def _on_browse_files(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose Exam Files", "", "ZIP Files (*.zip);;All Files (*)")
        if path:
            self.vars["runtime.exam_files"].setText(path)

    def _build_session_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._add_check(layout, "session.auto_resume_on_reconnect", "Auto resume on reconnect")
        self._add_check(layout, "session.remember_settings", "Remember settings")
        layout.addStretch()
        self.tabs.addTab(tab, "Session")

    def _build_blacklist_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._add_check(layout, "rules.process_blacklist.enabled", "Enabled")
        self._add_combo(layout, "rules.process_blacklist.severity", "Severity:", list(SEVERITY_VALUES))
        self._add_check(layout, "rules.process_blacklist.auto_violation_pause", "Auto pause on violation")
        self._add_check(layout, "rules.process_blacklist.allow_remote_kill", "Allow remote kill")
        self._add_text(layout, "process_blacklist.entries", "Blacklisted process names, one per line:")
        self._add_text(layout, "rules.process_blacklist.process_usernames", "Monitored process usernames, one per line:")
        self.tabs.addTab(tab, "Blacklist")

    def _build_focused_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._add_check(layout, "rules.focused_window.enabled", "Enabled")
        self._add_combo(layout, "rules.focused_window.severity", "Severity:", list(SEVERITY_VALUES))
        self._add_combo(layout, "rules.focused_window.window_title_match_mode", "Titlebar Match:", list(WINDOW_TITLE_MATCH_MODES))
        self._add_entry(layout, "rules.focused_window.open_after_consecutive", "Open After:")
        self._add_entry(layout, "rules.focused_window.resolve_after_consecutive", "Resolve After:")
        self._add_check(layout, "rules.focused_window.auto_violation_pause", "Auto pause on violation")
        self._add_text(layout, "rules.focused_window.allowed_process_names", "Allowed process names, one per line:")
        self._add_text(layout, "rules.focused_window.allowed_window_titles", "Allowed titlebar text, one per line:")
        self._add_text(layout, "rules.focused_window.blocked_process_names", "Blocked process names, one per line:")
        self._add_text(layout, "rules.focused_window.blocked_window_titles", "Blocked titlebar text, one per line:")
        self.tabs.addTab(tab, "Focused Window")

    def _build_rapid_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._add_check(layout, "rules.rapid_application_switching.enabled", "Enabled")
        self._add_combo(layout, "rules.rapid_application_switching.severity", "Severity:", list(SEVERITY_VALUES))
        self._add_entry(layout, "rules.rapid_application_switching.max_switches", "Max Switches:")
        self._add_entry(layout, "rules.rapid_application_switching.window_seconds", "Window Seconds:")
        self._add_entry(layout, "rules.rapid_application_switching.window_observations", "Window Observations:")
        self._add_check(layout, "rules.rapid_application_switching.auto_violation_pause", "Auto pause on violation")
        layout.addStretch()
        self.tabs.addTab(tab, "Rapid Switch")

    def _build_unexpected_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._add_check(layout, "rules.unexpected_process.enabled", "Enabled")
        self._add_combo(layout, "rules.unexpected_process.severity", "Severity:", list(SEVERITY_VALUES))
        self._add_check(layout, "rules.unexpected_process.baseline_existing_processes", "Baseline existing processes")
        self._add_check(layout, "rules.unexpected_process.auto_violation_pause", "Auto pause on violation")
        self._add_text(layout, "rules.unexpected_process.known_process_names", "Known process names, one per line:")
        self._add_text(layout, "rules.unexpected_process.known_directory_paths", "Known directory paths, one per line:")
        self._add_text(layout, "rules.unexpected_process.allowed_process_names", "Allowed process names, one per line:")
        self.tabs.addTab(tab, "Unexpected Process")

    def _build_definitions_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._add_check(layout, "rules.process_definitions.enabled", "Enabled")
        self._add_combo(layout, "rules.process_definitions.severity", "Severity:", list(SEVERITY_VALUES))
        self._add_check(layout, "rules.process_definitions.detect_unknown_processes", "Detect unknown processes")
        self._add_combo(layout, "rules.process_definitions.unknown_severity", "Unknown Severity:", list(SEVERITY_VALUES))
        self._add_check(layout, "rules.process_definitions.baseline_existing_processes", "Baseline existing processes")
        self._add_check(layout, "rules.process_definitions.auto_violation_pause", "Auto pause on violation")
        self._add_check(layout, "rules.process_definitions.allow_remote_kill", "Allow remote kill")
        self._add_text(layout, "rules.process_definitions.definitions", "Definitions JSON:")
        self.tabs.addTab(tab, "Process Definitions")

    def _build_path_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._add_check(layout, "rules.process_path_clarification.enabled", "Enabled")
        self._add_combo(layout, "rules.process_path_clarification.severity", "Severity:", list(SEVERITY_VALUES))
        self._add_check(layout, "rules.process_path_clarification.auto_violation_pause", "Auto pause on violation")
        self._add_check(layout, "rules.process_path_clarification.allow_remote_kill", "Allow remote kill")
        layout.addStretch()
        self.tabs.addTab(tab, "Path Clarification")

    def _build_operator_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._add_check(layout, "operator_defaults.confirm_kill_pid", "Confirm kill PID")
        self._add_check(layout, "operator_defaults.confirm_kick", "Confirm kick")
        self._add_check(layout, "operator_defaults.confirm_ban", "Confirm ban")
        self._add_check(layout, "operator_defaults.confirm_pause", "Confirm pause")
        layout.addStretch()
        self.tabs.addTab(tab, "Operator Confirmations")

    def set_val(self, key: str, value):
        w = self.vars.get(key)
        if not w: return
        if isinstance(w, QCheckBox):
            w.setChecked(bool(value))
        elif isinstance(w, QComboBox):
            w.setCurrentText(str(value))
        elif isinstance(w, QLineEdit):
            w.setText(str(value))
        elif isinstance(w, QPlainTextEdit):
            w.setPlainText(str(value))

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
            self.set_val("rules.process_definitions.definitions", json.dumps(pd.get("definitions", []), indent=2, ensure_ascii=False))

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
            
        self.lbl_status.setText("Saving settings...")
        self.settings_saved.emit(payload)

    def _collect_payload(self) -> dict:
        exam_files = self.get_str("runtime.exam_files").strip()
        
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
                        "definitions": self.get_json_list("rules.process_definitions.definitions", "Process definitions JSON"),
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
