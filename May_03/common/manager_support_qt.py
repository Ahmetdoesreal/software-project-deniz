"""Qt counterparts for the manager support helpers.

Reuses the GUI-agnostic ``ManagedProcessSession`` from ``manager_support`` and
provides a PySide6-based ``ConsoleWindow`` plus convenience helpers for the Qt
launchers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.widgets import make_button, make_console, style_button
from ui.theme import M


def install_close_guard(window: QWidget, handler: Callable[[], None]) -> None:
    """Re-route window close requests (X button, Cmd/Ctrl+W, Cmd/Ctrl+Q) to ``handler``."""

    original_close_event = window.closeEvent

    def close_event(event):
        handler()
        event.ignore()

    window.closeEvent = close_event  # type: ignore[assignment]
    window._original_close_event = original_close_event  # type: ignore[attr-defined]

    for sequence in ("Ctrl+W", "Ctrl+Q", "Meta+W", "Meta+Q"):
        shortcut = QShortcut(QKeySequence(sequence), window)
        shortcut.setContext(Qt.ApplicationShortcut)
        shortcut.activated.connect(handler)


def monospace_font() -> QFont:
    return QFontDatabase.systemFont(QFontDatabase.FixedFont)


class ConsoleWindow(QWidget):
    """Qt mirror of the Tkinter console window used by the launcher managers."""

    def __init__(
        self,
        *,
        title: str,
        get_log_path: Callable[[], Optional[str]],
        get_runtime_log_path: Callable[[], Optional[str]],
        is_process_running: Callable[[], bool],
        send_command: Callable[[str], bool],
        empty_message: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.get_log_path = get_log_path
        self.get_runtime_log_path = get_runtime_log_path
        self.is_process_running = is_process_running
        self.send_command = send_command
        self.empty_message = empty_message
        self._active_log_path: Optional[str] = None
        self._read_offset: int = 0

        self.setWindowTitle(title)
        self.resize(980, 620)
        self.hide()
        install_close_guard(self, self._hide_window)

        self._build_widgets()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._poll_output)
        self._poll_timer.start()

    def _build_widgets(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.status_label = QLabel("No active session.")
        layout.addWidget(self.status_label)

        mono = monospace_font()
        self.path_label = QLabel("Session output: -")
        self.path_label.setFont(mono)
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)

        self.runtime_log_label = QLabel("Runtime JSONL: -")
        self.runtime_log_label.setFont(mono)
        self.runtime_log_label.setWordWrap(True)
        layout.addWidget(self.runtime_log_label)

        self.output_text = make_console()
        layout.addWidget(self.output_text, stretch=1)

        command_row = QHBoxLayout()
        command_row.addWidget(QLabel("Send Input:"))
        self.command_entry = QLineEdit()
        self.command_entry.returnPressed.connect(self._send_command)
        command_row.addWidget(self.command_entry, stretch=1)

        self.send_button = make_button("Send", "filled")
        self.send_button.clicked.connect(self._send_command)
        command_row.addWidget(self.send_button)

        hide_button = make_button("Hide Window", "outlined")
        hide_button.clicked.connect(self._hide_window)
        command_row.addWidget(hide_button)

        layout.addLayout(command_row)

    def show_window(self) -> None:
        self._refresh_full_output()
        self._update_labels()
        self.show()
        self.raise_()
        self.activateWindow()

    def _hide_window(self) -> None:
        self.hide()

    def _send_command(self) -> None:
        command = self.command_entry.text().strip()
        if not command:
            return
        if self.send_command(command):
            self.command_entry.clear()
            return
        QMessageBox.warning(
            self,
            "Command Unavailable",
            "The managed process is not running, so the command could not be sent.",
        )

    def _update_labels(self) -> None:
        log_path = self.get_log_path()
        runtime_log_path = self.get_runtime_log_path()
        running = self.is_process_running()
        state_label = "Running" if running else "Stopped"
        self.status_label.setText(f"Process state: {state_label}")
        self.path_label.setText(f"Session output: {log_path or '-'}")
        self.runtime_log_label.setText(f"Runtime JSONL: {runtime_log_path or '-'}")
        self.send_button.setEnabled(running)
        self.command_entry.setEnabled(running)

    def _refresh_full_output(self) -> None:
        log_path = self.get_log_path()
        self._active_log_path = log_path
        self._read_offset = 0
        self.output_text.clear()

        if not log_path or not Path(log_path).exists():
            self.output_text.setPlainText(self.empty_message)
            return

        try:
            text = Path(log_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            text = self.empty_message

        self.output_text.setPlainText(text)
        self.output_text.moveCursor(QTextCursor.MoveOperation.End)
        try:
            self._read_offset = Path(log_path).stat().st_size
        except OSError:
            self._read_offset = 0

    def _poll_output(self) -> None:
        self._update_labels()
        if not self.isVisible():
            return
        current_log_path = self.get_log_path()
        if current_log_path != self._active_log_path:
            self._refresh_full_output()
        else:
            self._append_new_output()

    def _append_new_output(self) -> None:
        log_path = self.get_log_path()
        if not log_path:
            return

        path = Path(log_path)
        if not path.exists():
            return

        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(self._read_offset)
                chunk = handle.read()
                self._read_offset = handle.tell()
        except Exception:
            return

        if not chunk:
            return

        self.output_text.moveCursor(QTextCursor.MoveOperation.End)
        self.output_text.insertPlainText(chunk)
        self.output_text.moveCursor(QTextCursor.MoveOperation.End)
