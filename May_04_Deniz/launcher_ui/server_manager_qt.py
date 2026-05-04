"""Qt Exam Server manager.

Mirrors ``launcher_ui.server_manager_tk`` and is selected by
``server_launcher.py --ui qt``.
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
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
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSpinBox,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover - import guard
    print(_missing_pyside6_message(), file=sys.stderr)
    raise

from common.discovery import ServerAnnouncer, _candidate_ipv4_hosts
from common.manager_support import ManagedProcessSession
from common.manager_support_qt import ConsoleWindow, install_close_guard, monospace_font
from common.server_ports import detect_port_conflict
from client.preflight import load_auth_config
from ui.widgets import apply_theme, make_button
from ui.theme import M


def _extract_startup_failure(output: str) -> Optional[str]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        normalized = line.removeprefix("[ERROR] ").strip()
        lower = normalized.lower()
        if "server with id" in lower and "already running" in lower:
            advice = ""
            if index + 1 < len(lines) and lines[index + 1].startswith("[ERROR]"):
                advice = " " + lines[index + 1].removeprefix("[ERROR] ").strip()
            return normalized + advice
        if "port" in lower and ("already in use" in lower or "already used" in lower):
            return normalized
    return None


class ServerManager(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.project_dir = PROJECT_DIR
        self.process_session = ManagedProcessSession(
            session_name="server_cli_session",
            log_dir=self.project_dir / "data" / "logs" / "server" / "sessions",
        )
        self.console_window = ConsoleWindow(
            title="Server CLI",
            get_log_path=self._current_log_path,
            get_runtime_log_path=self._current_runtime_log_path,
            is_process_running=self._server_running,
            send_command=self._send_server_command,
            empty_message="Start the server to begin capturing session output.",
        )
        self._auth_config = load_auth_config(PROJECT_DIR)
        self._last_known_returncode: Optional[int] = None
        self._startup_failure_reported = False
        self._server_prompt_status = "Server stopped."

        self.setWindowTitle("Exam Server Manager")
        self.resize(920, 760)
        install_close_guard(self, self.on_close_request)

        self.local_ip = ServerAnnouncer._get_local_ip()
        self.host_options = self._host_options()
        self.local_port = self._get_free_port()

        self._build_layout()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._poll_process_state)
        self._poll_timer.start()
        self._poll_process_state()

    # ------------------------------------------------------------------ layout
    def _build_layout(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        bold = QFont()
        bold.setBold(True)

        info_box = QGroupBox("Network Target")
        info_layout = QVBoxLayout(info_box)
        ip_label = QLabel(f"Preferred IP: {self.local_ip}")
        ip_label.setFont(bold)
        info_layout.addWidget(ip_label)
        all_ips_label = QLabel(f"Available IPv4s: {', '.join(self.host_options)}")
        all_ips_label.setWordWrap(True)
        info_layout.addWidget(all_ips_label)
        port_label = QLabel(f"Suggested Port: {self.local_port}")
        port_label.setFont(bold)
        info_layout.addWidget(port_label)
        info_blurb = QLabel(
            "The manager keeps the server alive and preserves CLI output even "
            "when the CLI window is hidden."
        )
        info_blurb.setWordWrap(True)
        info_layout.addWidget(info_blurb)
        outer.addWidget(info_box)

        self._setup_widgets: list[QWidget] = []

        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(8)

        self.id_entry = QLineEdit("default")
        form_layout.addRow("Server ID:", self.id_entry)

        self.duration_entry = QSpinBox()
        self.duration_entry.setRange(1, 24 * 60)
        self.duration_entry.setValue(45)
        form_layout.addRow("Exam Duration (m):", self.duration_entry)

        self.host_entry = QComboBox()
        self.host_entry.setEditable(False)
        self.host_entry.setInsertPolicy(QComboBox.NoInsert)
        self.host_entry.addItems(self.host_options)
        self.host_entry.setCurrentText("0.0.0.0")
        self.host_entry.setMinimumHeight(32)
        self.host_entry.setStyleSheet("QComboBox { padding: 4px 10px; } QComboBox::drop-down { width: 26px; }")
        form_layout.addRow("Host:", self.host_entry)

        self.port_entry = QSpinBox()
        self.port_entry.setRange(1, 65535)
        self.port_entry.setValue(self.local_port)
        form_layout.addRow("Port:", self.port_entry)

        file_row = QWidget()
        file_layout = QHBoxLayout(file_row)
        file_layout.setContentsMargins(0, 0, 0, 0)
        self.file_entry = QLineEdit()
        self.file_entry.setReadOnly(True)
        file_layout.addWidget(self.file_entry, stretch=1)
        browse_button = make_button("Browse", "outlined")
        browse_button.clicked.connect(self.browse_file)
        file_layout.addWidget(browse_button)
        form_layout.addRow("Exam ZIP File:", file_row)
        outer.addWidget(form_widget)
        self._setup_widgets.append(form_widget)

        self.reset_check = QCheckBox("Reset Runtime State On Start")
        self.reset_check.setChecked(True)
        outer.addWidget(self.reset_check)
        self._setup_widgets.append(self.reset_check)

        secret_widget = QWidget()
        secret_layout = QFormLayout(secret_widget)
        secret_layout.setContentsMargins(0, 0, 0, 0)
        self.secret_entry = QLineEdit(self._auth_config.get("auth_secret", ""))
        self.secret_entry.setEchoMode(QLineEdit.Password)
        secret_layout.addRow("Auth Secret:", self.secret_entry)
        outer.addWidget(secret_widget)
        self._setup_widgets.append(secret_widget)

        controls_box = QGroupBox("Controls")
        controls_layout = QHBoxLayout(controls_box)
        self.start_button = make_button("Start Server", "filled")
        self.start_button.clicked.connect(self.start_server)
        controls_layout.addWidget(self.start_button)
        self.stop_button = make_button("Stop Server", "outlined")
        self.stop_button.clicked.connect(self.stop_server)
        controls_layout.addWidget(self.stop_button)
        self.cli_button = make_button("Open Session CLI", "text")
        self.cli_button.clicked.connect(self.open_cli)
        controls_layout.addWidget(self.cli_button)
        self.gui_button = make_button("Open Dashboard", "tonal")
        self.gui_button.clicked.connect(self.open_dashboard)
        controls_layout.addWidget(self.gui_button)
        outer.addWidget(controls_box)

        status_box = QGroupBox("Session State")
        status_layout = QVBoxLayout(status_box)
        self.summary_label = QLabel("Session Summary: -")
        self.summary_label.setWordWrap(True)
        status_layout.addWidget(self.summary_label)
        self.status_label = QLabel("Server stopped.")
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label)
        self.pid_label = QLabel("PID: -")
        self.pid_label.setWordWrap(True)
        status_layout.addWidget(self.pid_label)
        mono = monospace_font()
        self.session_log_label = QLabel("Session Output: -")
        self.session_log_label.setFont(mono)
        self.session_log_label.setWordWrap(True)
        status_layout.addWidget(self.session_log_label)
        self.runtime_log_label = QLabel("Runtime JSONL: -")
        self.runtime_log_label.setFont(mono)
        self.runtime_log_label.setWordWrap(True)
        status_layout.addWidget(self.runtime_log_label)
        outer.addWidget(status_box)

        hint = QLabel(
            "Window close shortcuts only show warnings here while the server is active. "
            "Use Stop Server from the manager when you really want to end the session."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {M['on_surface_variant']}; font-size: 11px;")
        outer.addWidget(hint)
        outer.addStretch(1)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _get_free_port() -> int:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("", 8080))
            sock.close()
            return 8080
        except OSError:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.bind(("", 0))
                port = sock.getsockname()[1]
                sock.close()
                return port
            except Exception:
                return 8080

    def _host_options(self) -> list[str]:
        options = ["0.0.0.0", self.local_ip, *_candidate_ipv4_hosts()]
        deduped: list[str] = []
        seen: set[str] = set()
        for host in options:
            value = str(host or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped

    def _selected_host(self) -> str:
        return self.host_entry.currentText().strip() or "0.0.0.0"

    def browse_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Exam Materials",
            "",
            "Zip files (*.zip);;All files (*)",
        )
        if filename:
            self.file_entry.setText(filename)


    def _server_running(self) -> bool:
        return self.process_session.is_running()

    def _current_log_path(self) -> Optional[str]:
        if not self.process_session.log_path:
            return None
        return str(self.process_session.log_path)

    def _current_runtime_log_path(self) -> Optional[str]:
        return self.process_session.runtime_log_path

    def _build_server_command(self) -> list[str]:
        command = [
            sys.executable,
            "-u",
            "-m",
            "server.main",
            "--ui",
            "qt",
            "--id",
            self.id_entry.text().strip(),
            "--host",
            self._selected_host(),
            "--port",
            str(self.port_entry.value()),
            "--exam-duration",
            str(self.duration_entry.value()),
        ]
        exam_file = self.file_entry.text().strip()
        if exam_file:
            command.extend(["--exam-files", exam_file])
        if self.reset_check.isChecked():
            command.append("--reset")
        secret = self.secret_entry.text().strip()
        if secret:
            command.extend(["--auth-secret", secret])
        return command

    def _session_summary_text(self) -> str:
        exam_file = self.file_entry.text().strip() or "-"
        return (
            f"Session Summary: id={self.id_entry.text().strip() or '-'}    "
            f"host={self._selected_host()}    "
            f"port={self.port_entry.value()}    "
            f"duration={self.duration_entry.value()} min    "
            f"exam_zip={exam_file}"
        )

    def _set_setup_visible(self, visible: bool) -> None:
        for widget in self._setup_widgets:
            widget.setVisible(visible)

    def _validate_form(self) -> bool:
        if self._server_running():
            QMessageBox.information(
                self,
                "Server Running",
                "Stop the current server before starting a new one.",
            )
            return False
        if not self.id_entry.text().strip():
            QMessageBox.critical(self, "Validation Error", "Server ID cannot be empty.")
            return False
        if self.duration_entry.value() <= 0:
            QMessageBox.critical(
                self,
                "Validation Error",
                "Exam duration must be greater than 0.",
            )
            return False
        if not 1 <= self.port_entry.value() <= 65535:
            QMessageBox.critical(
                self,
                "Validation Error",
                "Port must be between 1 and 65535.",
            )
            return False
        conflict = detect_port_conflict(
            self._selected_host(),
            self.port_entry.value(),
            self.id_entry.text().strip(),
        )
        if conflict:
            self._return_to_server_prompt(conflict)
            QMessageBox.critical(self, "Server Start Blocked", conflict)
            return False
        return True

    # --------------------------------------------------------------- behaviour
    def start_server(self) -> None:
        if not self._validate_form():
            return

        env = {
            "PYTHONPATH": str(self.project_dir)
            + os.pathsep
            + os.environ.get("PYTHONPATH", "")
        }
        try:
            self.process_session.start(
                self._build_server_command(),
                cwd=str(self.project_dir),
                env=env,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Launch Error", str(exc))
            return

        self._last_known_returncode = None
        self._startup_failure_reported = False
        self._server_prompt_status = "Server stopped."
        self.summary_label.setText(self._session_summary_text())
        self.status_label.setText("Server starting...")
        self._set_setup_visible(False)

    def _return_to_server_prompt(self, message: Optional[str] = None) -> None:
        self._set_setup_visible(True)
        self.summary_label.setText("Session Summary: -")
        if message:
            self._server_prompt_status = message
        self.status_label.setText(self._server_prompt_status)
        self.show()
        self.raise_()
        self.port_entry.setFocus()
        self.port_entry.selectAll()

    def stop_server(self) -> None:
        if not self._server_running():
            QMessageBox.information(
                self,
                "Server Stopped",
                "There is no active server session to stop.",
            )
            return

        reply = QMessageBox.question(
            self,
            "Stop Server",
            "Stop the running server session?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.process_session.stop()
        self.status_label.setText("Stopping server...")

    def open_cli(self) -> None:
        self.console_window.show_window()

    def open_dashboard(self) -> None:
        if not self._server_running():
            QMessageBox.warning(
                self,
                "Dashboard Unavailable",
                "Start the server first, then open the dashboard.",
            )
            return
        if not self._send_server_command("/gui"):
            QMessageBox.warning(
                self,
                "Dashboard Unavailable",
                "The dashboard command could not be sent to the server process.",
            )

    def _send_server_command(self, command: str) -> bool:
        if not command.startswith("/"):
            command = "/" + command
        return self.process_session.send_line(command)

    def _poll_process_state(self) -> None:
        running = self._server_running()
        process = self.process_session.process
        returncode = None if process is None else process.poll()

        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.gui_button.setEnabled(running)
        self.cli_button.setEnabled(self.process_session.log_path is not None)

        if running and process is not None:
            self.status_label.setText("Server running under manager control.")
            self.pid_label.setText(f"PID: {process.pid}")
        elif process is not None and returncode is not None:
            startup_failure = _extract_startup_failure(self.process_session.read_output_text())
            if startup_failure:
                self._server_prompt_status = startup_failure
                self._return_to_server_prompt(startup_failure)
                if not self._startup_failure_reported:
                    self._startup_failure_reported = True
                    QMessageBox.critical(self, "Server Start Failed", startup_failure)
            else:
                self.status_label.setText(f"Server stopped. Exit code: {returncode}")
            self.pid_label.setText(f"PID: {process.pid}")
        else:
            self.status_label.setText(self._server_prompt_status)
            self.pid_label.setText("PID: -")

        if running:
            self.summary_label.setText(self._session_summary_text())
            self._set_setup_visible(False)
        else:
            self.summary_label.setText("Session Summary: -")
            self._set_setup_visible(True)

        session_output = self.process_session.log_path
        self.session_log_label.setText(f"Session Output: {session_output or '-'}")
        self.runtime_log_label.setText(
            f"Runtime JSONL: {self.process_session.runtime_log_path or '-'}"
        )

        if (
            self._last_known_returncode is None
            and returncode is not None
            and self.process_session.log_path is not None
        ):
            self._last_known_returncode = returncode

    def on_close_request(self) -> None:
        if self._server_running():
            QMessageBox.warning(
                self,
                "Server Manager Locked",
                "The manager stays open while the server is running.\n\n"
                "Use Stop Server first, then close the manager.",
            )
            return

        reply = QMessageBox.question(
            self,
            "Close Server Manager",
            "Close the server manager?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            QApplication.instance().quit()


def run() -> int:
    os.chdir(PROJECT_DIR)
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    manager = ServerManager()
    manager.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
