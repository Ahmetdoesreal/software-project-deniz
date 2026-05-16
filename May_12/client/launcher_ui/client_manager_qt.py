"""Qt Exam Client manager.

Mirrors ``launcher_ui.client_manager_tk`` and is selected by
``client_launcher.py --ui qt``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
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
    from PySide6.QtCore import QObject, Qt, QTimer, Signal
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QFormLayout,
        QFrame,
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

from common.manager_support import ManagedProcessSession
from common.manager_support_qt import ConsoleWindow, install_close_guard, monospace_font
from ui.widgets import apply_theme, make_button, make_divider
from ui.theme import M
from client.preflight import (
    auth_status_display_message,
    auth_status_requires_admin_validation,
    load_auth_config,
    resolve_auth_status_sync,
    run_preflight,
)


class _LoginCheckSignals(QObject):
    """Holds Qt signals used to marshal background results back to the UI thread."""

    succeeded = Signal(str)
    failed = Signal(str)


class ClientManager(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.project_dir = PROJECT_DIR
        self._auth_config = load_auth_config(PROJECT_DIR)
        self.process_session = ManagedProcessSession(
            session_name="client_cli_session",
            log_dir=self.project_dir / "data" / "logs" / "client" / "sessions",
        )
        self._pending_client_command: list[str] | None = None
        self._pending_summary_text = ""
        self.validation_in_progress = False
        self._auth_status_notice = ""
        self._login_prompt_status = (
            "Client stopped. Start a session to open the timer window and CLI."
        )
        self._signals = _LoginCheckSignals(self)
        self._signals.succeeded.connect(self._launch_client_process)
        self._signals.failed.connect(self._handle_validation_error)

        self.console_window = ConsoleWindow(
            title="Client CLI",
            get_log_path=self._current_log_path,
            get_runtime_log_path=self._current_runtime_log_path,
            is_process_running=self._client_running,
            send_command=self._send_client_command,
            empty_message="Connect a client to begin capturing session output.",
        )

        self.setWindowTitle("Exam Client Manager")
        self.resize(760, 720)
        install_close_guard(self, self.on_close_request)

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

        student_header = QLabel("Student Details")
        student_header.setFont(bold)
        outer.addWidget(student_header)

        self._setup_widgets: list[QWidget] = [student_header]

        student_form = QFormLayout()
        student_form.setLabelAlignment(Qt.AlignLeft)
        student_form.setHorizontalSpacing(12)
        student_form.setVerticalSpacing(6)

        self.login_entry = QLineEdit()
        student_form.addRow("Login ID:", self.login_entry)

        self.password_entry = QLineEdit()
        self.password_entry.setEchoMode(QLineEdit.Password)
        student_form.addRow("Password:", self.password_entry)
        self._add_form_to_layout(outer, student_form)

        separator = make_divider()
        outer.addWidget(separator)
        self._setup_widgets.append(separator)

        connection_header = QLabel("Server Connection")
        connection_header.setFont(bold)
        outer.addWidget(connection_header)
        self._setup_widgets.append(connection_header)

        connection_form = QFormLayout()
        connection_form.setHorizontalSpacing(12)
        connection_form.setVerticalSpacing(6)
        self.id_entry = QLineEdit("default")
        connection_form.addRow("Server ID:", self.id_entry)
        self._add_form_to_layout(outer, connection_form)

        self.advanced_check = QCheckBox("Advanced Networking Options")
        self.advanced_check.toggled.connect(self.toggle_advanced)
        outer.addWidget(self.advanced_check)
        self._setup_widgets.append(self.advanced_check)

        self.advanced_widget = QWidget()
        self.advanced_widget.setVisible(False)
        advanced_form = QFormLayout(self.advanced_widget)
        advanced_form.setHorizontalSpacing(12)
        advanced_form.setVerticalSpacing(6)
        self.host_entry = QLineEdit()
        advanced_form.addRow("Host IP:", self.host_entry)
        self.port_entry = QSpinBox()
        self.port_entry.setRange(1, 65535)
        self.port_entry.setValue(8080)
        advanced_form.addRow("Port:", self.port_entry)
        outer.addWidget(self.advanced_widget)

        controls_box = QGroupBox("Controls")
        controls_layout = QHBoxLayout(controls_box)
        self.start_button = make_button("Connect && Login", "filled")
        self.start_button.clicked.connect(self.start_client)
        controls_layout.addWidget(self.start_button)
        self.stop_button = make_button("Stop Client", "outlined")
        self.stop_button.clicked.connect(self.stop_client)
        controls_layout.addWidget(self.stop_button)
        self.cli_button = make_button("Open Session CLI", "text")
        self.cli_button.clicked.connect(self.open_cli)
        controls_layout.addWidget(self.cli_button)
        outer.addWidget(controls_box)

        status_box = QGroupBox("Session State")
        status_layout = QVBoxLayout(status_box)
        self.summary_label = QLabel("Session Summary: -")
        self.summary_label.setWordWrap(True)
        status_layout.addWidget(self.summary_label)
        self.status_label = QLabel(self._login_prompt_status)
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
            "The timer window is opened by the managed client process. "
            "The CLI window can be hidden and reopened here without losing output."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {M['on_surface_variant']}; font-size: 11px;")
        outer.addWidget(hint)
        outer.addStretch(1)

    def _add_form_to_layout(self, outer: QVBoxLayout, form: QFormLayout) -> None:
        wrapper = QWidget()
        wrapper.setLayout(form)
        outer.addWidget(wrapper)
        self._setup_widgets.append(wrapper)

    # ------------------------------------------------------------------ helpers
    def toggle_advanced(self, checked: bool) -> None:
        self.advanced_widget.setVisible(checked)
        if checked:
            self.resize(760, 790)
        else:
            self.resize(760, 720)

    def _client_running(self) -> bool:
        return self.process_session.is_running()

    def _current_log_path(self) -> Optional[str]:
        if not self.process_session.log_path:
            return None
        return str(self.process_session.log_path)

    def _current_runtime_log_path(self) -> Optional[str]:
        return self.process_session.runtime_log_path

    def _build_client_command(self) -> list[str]:
        command = [
            sys.executable,
            "-u",
            "-m",
            "client.main",
            "--ui",
            "qt",
            "--login-id",
            self.login_entry.text().strip(),
            "--password",
            self.password_entry.text().strip(),
            "--ipc-transport",
            "auto",
        ]
        ad_domain = self._auth_config.get("ad_domain", "")
        auth_secret = self._auth_config.get("auth_secret", "")
        if ad_domain and auth_secret:
            command.extend(["--ad-domain", ad_domain, "--auth-secret", auth_secret])
        server_id = self.id_entry.text().strip()
        if server_id:
            command.extend(["--id", server_id])
        if self.advanced_check.isChecked():
            host = self.host_entry.text().strip()
            if host:
                command.extend(["--host", host])
            command.extend(["--port", str(self.port_entry.value())])
        return command

    def _validation_command(self) -> list[str]:
        return [*self._build_client_command(), "--check-login", "--timeout", "3"]

    def _session_summary_text(self) -> str:
        if self.advanced_check.isChecked():
            target = f"{self.host_entry.text().strip() or 'discovery'}:{self.port_entry.value()}"
        else:
            target = f"discovery:{self.id_entry.text().strip() or 'default'}"
        return (
            f"Session Summary: login={self.login_entry.text().strip() or '-'}    "
            f"server_id={self.id_entry.text().strip() or '-'}    "
            f"target={target}"
        )

    def _set_setup_visible(self, visible: bool) -> None:
        for widget in self._setup_widgets:
            widget.setVisible(visible)
        if visible and self.advanced_check.isChecked():
            self.advanced_widget.setVisible(True)
        elif not visible:
            self.advanced_widget.setVisible(False)

    def _validate_form(self) -> bool:
        if self._client_running():
            QMessageBox.information(
                self,
                "Client Running",
                "Stop the current client session before starting a new one.",
            )
            return False
        if not self.login_entry.text().strip() or not self.password_entry.text().strip():
            QMessageBox.critical(
                self,
                "Validation Error",
                "Login ID and password are required.",
            )
            return False
        if self.advanced_check.isChecked() and not 1 <= self.port_entry.value() <= 65535:
            QMessageBox.critical(
                self,
                "Validation Error",
                "Port must be between 1 and 65535.",
            )
            return False
        return True

    # --------------------------------------------------------------- behaviour
    def start_client(self) -> None:
        if not self._validate_form():
            return

        login_context = {
            "login_id": self.login_entry.text().strip(),
            "password": self.password_entry.text().strip(),
            "server_id": self.id_entry.text().strip() or "default",
            "advanced": self.advanced_check.isChecked(),
            "host": self.host_entry.text().strip(),
            "port": int(self.port_entry.value()),
            "ad_domain": self._auth_config.get("ad_domain", ""),
            "auth_secret": self._auth_config.get("auth_secret", ""),
            "client_command": self._build_client_command(),
            "summary_text": self._session_summary_text(),
        }
        login_context["validation_command"] = [
            *login_context["client_command"],
            "--check-login",
            "--timeout",
            "3",
        ]
        self._pending_client_command = list(login_context["client_command"])
        self._pending_summary_text = str(login_context["summary_text"])
        self._login_prompt_status = (
            "Client stopped. Start a session to open the timer window and CLI."
        )
        self.validation_in_progress = True
        self.start_button.setEnabled(False)
        self.start_button.setText("Validating...")
        thread = threading.Thread(target=self._run_login_check, args=(login_context,), daemon=True)
        thread.start()

    def _run_login_check(self, context: dict) -> None:
        login_id = str(context["login_id"])
        password = str(context["password"])
        ad_domain = str(context["ad_domain"])
        auth_secret = str(context["auth_secret"])

        auth_status = resolve_auth_status_sync(
            login_id,
            server_id=str(context["server_id"]),
            host=str(context["host"]) if context["advanced"] else None,
            port=int(context["port"]),
            timeout=3.0,
        )
        auth_notice = auth_status_display_message(auth_status)

        # Step 1: local preflight — CATS school auth + Windows AD auth in parallel
        preflight_ok, preflight_result = run_preflight(
            login_id, password, ad_domain, auth_secret, auth_status=auth_status
        )
        if not preflight_ok:
            self._signals.failed.emit(preflight_result)
            return
        if auth_status_requires_admin_validation(auth_status):
            self._signals.succeeded.emit(auth_notice)
            return

        # Step 2: server reachability + token acceptance check
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.project_dir) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONUNBUFFERED"] = "1"
        try:
            result = subprocess.run(
                context["validation_command"],
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                env=env,
            )
        except Exception as exc:
            self._signals.failed.emit(str(exc))
            return

        if result.returncode == 0:
            self._signals.succeeded.emit("")
            return

        output = (result.stdout + "\n" + result.stderr).strip()
        error_message = "Unknown validation error."
        for line in output.splitlines():
            if "[FATAL]" in line or "[!]" in line:
                error_message = line.strip()
                break
        self._signals.failed.emit(error_message)

    def _launch_client_process(self, auth_notice: str = "") -> None:
        self.validation_in_progress = False
        self._auth_status_notice = str(auth_notice or "").strip()
        client_command = self._pending_client_command or self._build_client_command()
        summary_text = self._pending_summary_text or self._session_summary_text()
        env = {
            "PYTHONPATH": str(self.project_dir)
            + os.pathsep
            + os.environ.get("PYTHONPATH", "")
        }
        try:
            self.process_session.start(
                client_command,
                cwd=str(self.project_dir),
                env=env,
            )
        except Exception as exc:
            self._handle_validation_error(str(exc))
            return

        self.start_button.setText("Connect && Login")
        self.summary_label.setText(summary_text)
        self.status_label.setText(self._auth_status_notice or "Client running under manager control.")
        self._set_setup_visible(False)
        self.open_cli()

    def _return_to_login_prompt(self, message: Optional[str] = None) -> None:
        self.validation_in_progress = False
        self._auth_status_notice = ""
        self._pending_client_command = None
        self._pending_summary_text = ""
        self.start_button.setEnabled(True)
        self.start_button.setText("Connect && Login")
        self._set_setup_visible(True)
        self.summary_label.setText("Session Summary: -")
        if message:
            self._login_prompt_status = f"Login failed. {message}"
        self.status_label.setText(self._login_prompt_status)
        self.show()
        self.raise_()
        focus_target = self.password_entry if self.login_entry.text().strip() else self.login_entry
        focus_target.setFocus()
        focus_target.selectAll()

    def _handle_validation_error(self, message: str) -> None:
        self._return_to_login_prompt(message)
        QMessageBox.critical(
            self,
            "Login Failed",
            f"Could not connect or authenticate with the server:\n\n{message}",
        )

    def stop_client(self) -> None:
        if not self._client_running():
            QMessageBox.information(
                self,
                "Client Stopped",
                "There is no active client session to stop.",
            )
            return

        reply = QMessageBox.question(
            self,
            "Stop Client",
            "Stop the running client session?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.process_session.stop()
        self.status_label.setText("Stopping client...")

    def open_cli(self) -> None:
        self.console_window.show_window()

    def _send_client_command(self, command: str) -> bool:
        return self.process_session.send_line(command)

    def _poll_process_state(self) -> None:
        running = self._client_running()
        process = self.process_session.process
        returncode = None if process is None else process.poll()

        self.start_button.setEnabled(not running and not self.validation_in_progress)
        if (
            not running
            and not self.validation_in_progress
            and self.start_button.text() != "Validating..."
        ):
            self.start_button.setText("Connect && Login")
        self.stop_button.setEnabled(running)
        self.cli_button.setEnabled(self.process_session.log_path is not None)

        if running and process is not None:
            self.status_label.setText(self._auth_status_notice or "Client running under manager control.")
            self.pid_label.setText(f"PID: {process.pid}")
        elif process is not None and returncode is not None:
            self.status_label.setText(f"Client stopped. Exit code: {returncode}")
            self.pid_label.setText(f"PID: {process.pid}")
        else:
            self.status_label.setText(self._login_prompt_status)
            self.pid_label.setText("PID: -")

        if running or self.validation_in_progress:
            self.summary_label.setText(self._session_summary_text())
            self._set_setup_visible(False)
        else:
            self.summary_label.setText("Session Summary: -")
            self._set_setup_visible(True)

        self.session_log_label.setText(
            f"Session Output: {self.process_session.log_path or '-'}"
        )
        self.runtime_log_label.setText(
            f"Runtime JSONL: {self.process_session.runtime_log_path or '-'}"
        )

    def on_close_request(self) -> None:
        if self._client_running():
            QMessageBox.warning(
                self,
                "Client Manager Locked",
                "The manager stays open while the client is running.\n\n"
                "Use Stop Client first, then close the manager.",
            )
            return

        reply = QMessageBox.question(
            self,
            "Close Client Manager",
            "Close the client manager?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            QApplication.instance().quit()


def run() -> int:
    os.chdir(PROJECT_DIR)
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    manager = ClientManager()
    manager.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
