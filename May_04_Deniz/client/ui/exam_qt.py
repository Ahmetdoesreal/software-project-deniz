"""Qt client exam timer + submission window.

Mirrors ``client.ui.exam_tk`` and is selected by ``client.gui --ui qt``.
"""

from __future__ import annotations

import faulthandler
import json
import sys
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


try:
    from PySide6.QtCore import Qt, QObject, QTimer, Signal
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QFileDialog,
        QFrame,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QStackedWidget,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover - import guard
    print(_missing_pyside6_message(), file=sys.stderr)
    raise

from client.submission import build_file_preview, format_bytes
from common.runtime_logging import setup_runtime_logging
from ui.widgets import apply_theme, make_button, style_button
from ui.theme import M, TY, apply_typography


def _emit_command(payload: dict) -> None:
    print(json.dumps(payload), flush=True)


def _parse_ipc_line(line: str) -> tuple[str, str]:
    command, _, value = line.partition(":")
    return command, value


def _format_time(seconds: int) -> str:
    minutes, remaining_seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{remaining_seconds:02d}"


def _monospace_font() -> QFont:
    return QFontDatabase.systemFont(QFontDatabase.FixedFont)


class _IPCSignals(QObject):
    sync = Signal(int)
    pause = Signal(int, str)
    resume = Signal(int, str)
    end = Signal()
    reset = Signal()
    error = Signal(str)
    open_finish = Signal(str)
    upload_ok = Signal(str)
    upload_error = Signal(str)
    upload_step = Signal(str)
    parent_closed = Signal()


class SubmissionWindow(QMainWindow):
    def __init__(
        self,
        *,
        submit_callback,
        close_callback,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent, Qt.Window)
        self._submit_callback = submit_callback
        self._close_callback = close_callback
        self._selected_file: str = ""
        self._allow_close = False
        self._mono = _monospace_font()

        self.setWindowTitle("Finish Exam")
        self.resize(820, 560)
        self.setMinimumSize(720, 500)

        self._build_layout()
        self._show_tree_preview()

    # ------------------------------------------------------------------ layout
    def _build_layout(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        submit_box = QGroupBox("Submission")
        submit_layout = QVBoxLayout(submit_box)

        submit_layout.addWidget(QLabel("Select a file to submit."))
        self.path_label = QLabel("No file selected.")
        self.path_label.setFont(self._mono)
        self.path_label.setWordWrap(True)
        submit_layout.addWidget(self.path_label)

        action_row = QHBoxLayout()
        self.choose_button = make_button("Choose File", "outlined")
        self.choose_button.clicked.connect(self.choose_file)
        action_row.addWidget(self.choose_button, stretch=1)
        self.upload_button = make_button("Upload And Finish", "filled")
        self.upload_button.setEnabled(False)
        self.upload_button.clicked.connect(self._submit_selected_file)
        action_row.addWidget(self.upload_button, stretch=1)
        submit_layout.addLayout(action_row)

        self.summary_label = QLabel("")
        self.summary_label.setFont(self._mono)
        self.summary_label.setWordWrap(True)
        submit_layout.addWidget(self.summary_label)

        self.status_label = QLabel("Choose a file to preview and upload.")
        self.status_label.setWordWrap(True)
        submit_layout.addWidget(self.status_label)

        outer.addWidget(submit_box)

        preview_box = QGroupBox("File Preview")
        preview_layout = QVBoxLayout(preview_box)

        self.preview_stack = QStackedWidget()
        self.preview_tree = QTreeWidget()
        self.preview_tree.setColumnCount(3)
        self.preview_tree.setHeaderLabels(["Name", "Size", "Last Modified"])
        self.preview_tree.setFont(self._mono)
        header = self.preview_tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.preview_stack.addWidget(self.preview_tree)

        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setFont(self._mono)
        self.preview_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.preview_stack.addWidget(self.preview_text)

        preview_layout.addWidget(self.preview_stack)
        outer.addWidget(preview_box, stretch=1)

    # ------------------------------------------------------------------ behaviour
    def closeEvent(self, event):  # noqa: N802 - Qt API
        if self._allow_close:
            event.accept()
            if self._close_callback:
                self._close_callback()
            return
        event.ignore()
        QMessageBox.warning(
            self,
            "Finish Exam",
            "This submission window stays protected while the client session is active.\n\n"
            "Choose a file and upload it from here, or return to the timer window.",
        )

    def force_close(self) -> None:
        self._allow_close = True
        self.close()

    def choose_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Choose file",
            "",
            (
                "All files (*.*);;"
                "Archive files (*.zip *.tar *.tgz *.tar.gz *.tbz2 *.tar.bz2 *.txz *.tar.xz);;"
                "Text files (*.txt *.md *.py *.json *.csv *.log *.yaml *.yml *.xml *.html *.css *.js *.ts)"
            ),
        )
        if not filename:
            return
        self._selected_file = filename
        self.path_label.setText(filename)
        self._load_preview(filename)

    def _load_preview(self, selected_path: str) -> None:
        try:
            preview = build_file_preview(selected_path)
        except Exception as exc:
            self._clear_preview()
            self.summary_label.setText("")
            self.status_label.setText("Preview failed. Choose a valid file before uploading.")
            self.upload_button.setEnabled(False)
            QMessageBox.warning(self, "Preview Failed", str(exc))
            return

        self._populate_preview(preview)
        self.upload_button.setEnabled(True)

    def _populate_preview(self, preview) -> None:
        self._clear_preview()
        self.summary_label.setText(
            f"File: {preview.file_name}    "
            f"Size: {format_bytes(preview.file_size_bytes)}    "
            f"Modified: {preview.file_modified_at}"
        )
        self.status_label.setText(
            preview.preview_message or "Preview loaded. Review it, then upload when ready."
        )

        if preview.preview_kind == "archive":
            self._show_tree_preview()
            root_item = QTreeWidgetItem(
                [
                    preview.file_name,
                    format_bytes(preview.file_size_bytes),
                    preview.file_modified_at,
                ]
            )
            self.preview_tree.addTopLevelItem(root_item)
            for entry in preview.entries:
                self._insert_preview_entry(root_item, entry)
            root_item.setExpanded(True)
            return

        if preview.preview_kind == "text":
            self._show_text_preview()
            self.preview_text.setPlainText(preview.text_preview or "")
            return

        self._show_text_preview()
        self.preview_text.setPlainText(
            "Binary file selected.\n\n"
            f"Name: {preview.file_name}\n"
            f"Size: {format_bytes(preview.file_size_bytes)}\n"
            f"Modified: {preview.file_modified_at}\n"
        )

    def _insert_preview_entry(self, parent_item: QTreeWidgetItem, entry) -> None:
        label = f"{entry.name}/" if entry.is_dir else entry.name
        child = QTreeWidgetItem(
            [
                label,
                "-" if entry.is_dir else format_bytes(entry.size_bytes),
                entry.modified_at,
            ]
        )
        parent_item.addChild(child)
        for grandchild in entry.children:
            self._insert_preview_entry(child, grandchild)
        child.setExpanded(True)

    def _clear_preview(self) -> None:
        self.preview_tree.clear()
        self.preview_text.clear()

    def _submit_selected_file(self) -> None:
        if not self._selected_file:
            QMessageBox.warning(self, "Finish Exam", "Choose a file first.")
            return
        self._submit_callback(self._selected_file)

    def set_uploading(self) -> None:
        self.choose_button.setEnabled(False)
        self.upload_button.setEnabled(False)
        self.status_label.setText("Uploading file...")

    def set_upload_step(self, message: str) -> None:
        self.choose_button.setEnabled(False)
        self.upload_button.setEnabled(False)
        self.status_label.setText(message)

    def set_ready_after_error(self, message: str) -> None:
        self.choose_button.setEnabled(True)
        self.upload_button.setEnabled(True)
        self.status_label.setText(message)

    def _show_tree_preview(self) -> None:
        self.preview_stack.setCurrentIndex(0)

    def _show_text_preview(self) -> None:
        self.preview_stack.setCurrentIndex(1)


class ExamTimerGUI(QMainWindow):
    def __init__(self, *, standalone_mode: bool = False) -> None:
        super().__init__()
        self.standalone_mode = standalone_mode
        self._allow_close = False
        self.remaining = 0
        self.active = True
        self.started = False
        self.timer_state = "idle"
        self.pause_reason = ""
        self.submission_window: Optional[SubmissionWindow] = None
        self.finish_in_progress = False

        self.setWindowTitle("Exam Timer")
        self.resize(500, 320)
        self.setMinimumSize(460, 290)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        self._build_widgets()

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start()

    # ------------------------------------------------------------------ layout
    def _build_widgets(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        status_box = QGroupBox("Exam Status")
        status_layout = QVBoxLayout(status_box)
        self.timer_label = QLabel("Waiting")
        apply_typography(self.timer_label, "display_large")
        self.timer_label.setAlignment(Qt.AlignCenter)
        self.timer_label.setStyleSheet(
            f"color: {M['primary']}; background: transparent;"
        )
        status_layout.addWidget(self.timer_label)

        self.status_label = QLabel("Waiting for exam start.")
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label)
        outer.addWidget(status_box)

        commands_box = QGroupBox("Commands")
        commands_layout = QVBoxLayout(commands_box)
        self.start_button = make_button("Request Start", "tonal")
        self.start_button.clicked.connect(self.on_start_click)
        commands_layout.addWidget(self.start_button)
        self.finish_button = make_button("Finish Exam", "filled")
        self.finish_button.setEnabled(False)
        self.finish_button.clicked.connect(self.open_finish_window)
        self.finish_button.hide()
        commands_layout.addWidget(self.finish_button)
        outer.addWidget(commands_box)

        self.footer_label = QLabel("Ready.")
        self.footer_label.setContentsMargins(6, 3, 6, 3)
        self.footer_label.setStyleSheet(
            f"color: {M['on_surface_variant']}; background: transparent; font-size: 11px;"
        )
        outer.addWidget(self.footer_label)

    # ------------------------------------------------------------------ behaviour
    def closeEvent(self, event):  # noqa: N802 - Qt API
        if self._allow_close or self.standalone_mode:
            event.accept()
            QApplication.instance().quit()
            return

        if self.finish_in_progress:
            event.ignore()
            self._focus_submission_window()
            QMessageBox.warning(
                self,
                "Upload In Progress",
                "A submission upload is currently in progress.\n\n"
                "Wait for it to finish before trying to close anything.",
            )
            return

        event.ignore()
        if self.submission_window is not None and self.submission_window.isVisible():
            self.submission_window.showMinimized()
        self.showMinimized()

    def force_close(self) -> None:
        """Close the timer window unconditionally (parent process disappeared)."""
        self._allow_close = True
        self._tick_timer.stop()
        self.close_submission_window()
        self.close()
        QApplication.instance().quit()

    def on_start_click(self) -> None:
        _emit_command({"cmd": "start_exam"})
        self.start_button.setEnabled(False)
        self.timer_label.setText("Starting")
        self.status_label.setText("Start request sent. Waiting for server confirmation.")
        self.footer_label.setText("Waiting for approval.")

    def _on_tick(self) -> None:
        if self.active and self.started and self.timer_state != "paused":
            if self.remaining > 0:
                self.timer_label.setText(_format_time(self.remaining))
                self.remaining -= 1
            elif self.remaining == 0:
                self.timer_label.setText("00:00")

    def set_remaining(self, seconds: int) -> None:
        if seconds < 0:
            self.force_close()
            return

        self.remaining = seconds
        if self.timer_state != "paused":
            self.timer_label.setText(_format_time(self.remaining))
            self.status_label.setText("Exam is running.")
            self.footer_label.setText("Timer synchronized.")
        if self.started:
            return

        self.started = True
        self.timer_state = "running"
        self.start_button.hide()
        self.finish_button.show()
        self.finish_button.setEnabled(True)
        self.status_label.setText("Exam is running.")
        self.footer_label.setText("Exam started.")

    def reset_to_ready(self) -> None:
        if self.started:
            return
        self.start_button.setEnabled(True)
        self.timer_label.setText("Waiting")
        self.status_label.setText("Waiting for exam start.")
        self.footer_label.setText("Ready.")

    def show_error_popup(self, message: str) -> None:
        self.reset_to_ready()
        self.footer_label.setText(message or "Request failed.")
        title = "Exam Finished" if "finished" in message.lower() else "Exam Not Started"
        QMessageBox.critical(self, title, message)

    def open_finish_window(self) -> None:
        if not self.started:
            return
        if self.finish_in_progress:
            return
        if self.submission_window is not None and self.submission_window.isVisible():
            self.submission_window.raise_()
            self.submission_window.activateWindow()
            return

        self.submission_window = SubmissionWindow(
            submit_callback=self.submit_file,
            close_callback=self._clear_submission_window,
            parent=self,
        )
        self.submission_window.show()

    def submit_file(self, selected_file: str) -> None:
        self.finish_in_progress = True
        self.finish_button.setEnabled(False)
        if self.submission_window is not None:
            self.submission_window.set_uploading()
        _emit_command({"cmd": "finish_exam", "archive_path": selected_file})

    def prompt_finish_from_server(self, message: str) -> None:
        self.started = True
        self.timer_state = "submission_only"
        self.start_button.hide()
        self.finish_button.show()
        self.finish_button.setEnabled(not self.finish_in_progress)
        self.timer_label.setText("Finish")
        self.status_label.setText("Upload your file to finish the exam.")
        self.footer_label.setText("Submission required.")
        self.open_finish_window()
        if message:
            QMessageBox.information(self, "Finish Exam", message)

    def handle_upload_success(self, message: str) -> None:
        self.finish_in_progress = False
        self.close_submission_window()
        QMessageBox.information(
            self,
            "Submission Uploaded",
            message or "Submission uploaded successfully.",
        )
        self.force_close()

    def handle_upload_error(self, message: str) -> None:
        self.finish_in_progress = False
        self.finish_button.setEnabled(True)
        self.footer_label.setText(message or "Upload failed.")
        if self.submission_window is not None and self.submission_window.isVisible():
            self.submission_window.set_ready_after_error(message)
        QMessageBox.critical(self, "Upload Failed", message)

    def handle_upload_step(self, message: str) -> None:
        text = (message or "").strip()
        if not text:
            return
        self.footer_label.setText(text)
        if self.submission_window is not None and self.submission_window.isVisible():
            self.submission_window.set_upload_step(text)

    def pause_timer(self, remaining_seconds: int, reason: str = "") -> None:
        self.started = True
        self.timer_state = "paused"
        self.pause_reason = reason
        self.remaining = max(0, int(remaining_seconds))
        self.start_button.hide()
        self.finish_button.show()
        self.finish_button.setEnabled(not self.finish_in_progress)
        self.timer_label.setText(_format_time(self.remaining))
        self.status_label.setText(reason or "Exam paused by administrator.")
        self.footer_label.setText("Timer paused.")

    def resume_timer(self, remaining_seconds: int, reason: str = "") -> None:
        self.started = True
        self.timer_state = "running"
        self.pause_reason = ""
        self.remaining = max(0, int(remaining_seconds))
        self.start_button.hide()
        self.finish_button.show()
        self.finish_button.setEnabled(not self.finish_in_progress)
        self.timer_label.setText(_format_time(self.remaining))
        self.status_label.setText(reason or "Exam resumed.")
        self.footer_label.setText("Timer resumed.")

    def close_submission_window(self) -> None:
        if self.submission_window is None:
            return
        try:
            self.submission_window.force_close()
        except Exception:
            pass
        self.submission_window = None

    def _clear_submission_window(self) -> None:
        self.submission_window = None
        if not self.finish_in_progress and self.started:
            self.finish_button.setEnabled(True)

    def _focus_submission_window(self) -> None:
        if self.submission_window is None or not self.submission_window.isVisible():
            return
        self.submission_window.raise_()
        self.submission_window.activateWindow()


def _ipc_reader(signals: _IPCSignals) -> None:
    try:
        for line in iter(sys.stdin.readline, ""):
            command, value = _parse_ipc_line(line.strip())
            try:
                if command == "SYNC":
                    signals.sync.emit(int(value))
                elif command == "PAUSE":
                    payload = json.loads(value) if value else {}
                    signals.pause.emit(
                        int(payload.get("remaining_seconds", 0) or 0),
                        str(payload.get("reason", "") or ""),
                    )
                elif command == "RESUME":
                    payload = json.loads(value) if value else {}
                    signals.resume.emit(
                        int(payload.get("remaining_seconds", 0) or 0),
                        str(payload.get("reason", "") or ""),
                    )
                elif command == "END":
                    signals.end.emit()
                elif command == "RESET":
                    signals.reset.emit()
                elif command == "ERROR":
                    signals.error.emit(value)
                elif command == "OPEN_FINISH":
                    signals.open_finish.emit(value)
                elif command == "UPLOAD_OK":
                    signals.upload_ok.emit(value)
                elif command == "UPLOAD_ERROR":
                    signals.upload_error.emit(value)
                elif command == "UPLOAD_STEP":
                    signals.upload_step.emit(value)
            except Exception:
                pass
    except (OSError, ValueError):
        pass
    signals.parent_closed.emit()


def run() -> int:
    log_dir = PROJECT_DIR / "data" / "logs" / "client"
    log_dir.mkdir(parents=True, exist_ok=True)
    setup_runtime_logging("client_gui", log_dir)
    _crash_log = log_dir / f"client_gui_crash_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    faulthandler.enable(file=_crash_log.open("w", encoding="utf-8"), all_threads=True)
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    standalone = sys.stdin.isatty()
    gui = ExamTimerGUI(standalone_mode=standalone)
    gui.show()

    signals = _IPCSignals()
    signals.sync.connect(gui.set_remaining)
    signals.pause.connect(gui.pause_timer)
    signals.resume.connect(gui.resume_timer)
    signals.end.connect(lambda: gui.set_remaining(-1))
    signals.reset.connect(gui.reset_to_ready)
    signals.error.connect(gui.show_error_popup)
    signals.open_finish.connect(gui.prompt_finish_from_server)
    signals.upload_ok.connect(gui.handle_upload_success)
    signals.upload_error.connect(gui.handle_upload_error)
    signals.upload_step.connect(gui.handle_upload_step)
    if not standalone:
        signals.parent_closed.connect(gui.force_close)

    reader_thread = Thread(target=_ipc_reader, args=(signals,), daemon=True)
    reader_thread.start()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
