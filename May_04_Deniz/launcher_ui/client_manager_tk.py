import os
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import messagebox, ttk


PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
os.chdir(PROJECT_DIR)

from common.manager_support import (
    ConsoleWindow,
    ManagedProcessSession,
    apply_dpi_awareness,
    install_close_guard,
)
from client.preflight import auth_status_requires_admin_validation, load_auth_config, resolve_auth_status_sync, run_preflight


class ClientManager(tk.Tk):
    def __init__(self):
        super().__init__()
        self.project_dir = PROJECT_DIR
        self._auth_config = load_auth_config(PROJECT_DIR)
        self.process_session = ManagedProcessSession(
            session_name="client_cli_session",
            log_dir=self.project_dir / "data" / "logs" / "client" / "sessions",
        )
        self.validation_in_progress = False
        self._login_prompt_status = (
            "Client stopped. Start a session to open the timer window and CLI."
        )
        self.console_window = ConsoleWindow(
            self,
            title="Client CLI",
            get_log_path=self._current_log_path,
            get_runtime_log_path=self._current_runtime_log_path,
            is_process_running=self._client_running,
            send_command=self._send_client_command,
            empty_message="Connect a client to begin capturing session output.",
        )

        self.title("Exam Client Manager")
        self.geometry("760x720")
        self.resizable(False, False)
        install_close_guard(self, self.on_close_request, bind_all=True)

        style = ttk.Style(self)
        style.configure("TButton", padding=(10, 6))
        style.configure("TLabelframe.Label", font=("TkDefaultFont", 10, "bold"))
        self.mono_font = tkfont.nametofont("TkFixedFont").copy()
        style.configure("Mono.TLabel", font=self.mono_font)
        self.columnconfigure(1, weight=1)

        self.status_var = tk.StringVar(
            value="Client stopped. Start a session to open the timer window and CLI."
        )
        self.summary_var = tk.StringVar(value="Session Summary: -")
        self.pid_var = tk.StringVar(value="PID: -")
        self.session_log_var = tk.StringVar(value="Session Output: -")
        self.runtime_log_var = tk.StringVar(value="Runtime JSONL: -")

        self._build_layout()
        self._poll_process_state()

    def _build_layout(self):
        ttk.Label(
            self,
            text="Student Details",
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 5))

        ttk.Label(self, text="Login ID:").grid(row=1, column=0, sticky=tk.W, padx=10, pady=6)
        self.v_login = tk.StringVar(value="")
        self.login_entry = ttk.Entry(self, textvariable=self.v_login)
        self.login_entry.grid(
            row=1,
            column=1,
            sticky=tk.EW,
            padx=10,
            pady=6,
        )

        ttk.Label(self, text="Password:").grid(row=2, column=0, sticky=tk.W, padx=10, pady=6)
        self.v_pass = tk.StringVar(value="")
        self.password_entry = ttk.Entry(self, textvariable=self.v_pass, show="*")
        self.password_entry.grid(
            row=2,
            column=1,
            sticky=tk.EW,
            padx=10,
            pady=6,
        )

        ttk.Separator(self, orient=tk.HORIZONTAL).grid(
            row=3,
            column=0,
            columnspan=2,
            sticky=tk.EW,
            padx=10,
            pady=10,
        )

        ttk.Label(
            self,
            text="Server Connection",
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=4, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 5))

        ttk.Label(self, text="Server ID:").grid(row=5, column=0, sticky=tk.W, padx=10, pady=6)
        self.v_id = tk.StringVar(value="default")
        ttk.Entry(self, textvariable=self.v_id).grid(
            row=5,
            column=1,
            sticky=tk.EW,
            padx=10,
            pady=6,
        )

        self.v_adv = tk.BooleanVar(value=False)
        self.advanced_check = ttk.Checkbutton(
            self,
            text="Advanced Networking Options",
            variable=self.v_adv,
            command=self.toggle_advanced,
        )
        self.advanced_check.grid(row=6, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(8, 0))

        self.adv_frame = ttk.Frame(self)
        self.adv_frame.columnconfigure(1, weight=1)
        ttk.Label(self.adv_frame, text="Host IP:").grid(
            row=0,
            column=0,
            sticky=tk.W,
            padx=10,
            pady=6,
        )
        self.v_host = tk.StringVar(value="")
        ttk.Entry(self.adv_frame, textvariable=self.v_host).grid(
            row=0,
            column=1,
            sticky=tk.EW,
            padx=10,
            pady=6,
        )

        ttk.Label(self.adv_frame, text="Port:").grid(
            row=1,
            column=0,
            sticky=tk.W,
            padx=10,
            pady=6,
        )
        self.v_port = tk.IntVar(value=8080)
        ttk.Entry(self.adv_frame, textvariable=self.v_port).grid(
            row=1,
            column=1,
            sticky=tk.EW,
            padx=10,
            pady=6,
        )

        controls = ttk.LabelFrame(self, text="Controls")
        controls.grid(row=8, column=0, columnspan=2, sticky=tk.EW, padx=10, pady=10)
        for column in range(3):
            controls.columnconfigure(column, weight=1)
        self.start_button = ttk.Button(
            controls,
            text="Connect & Login",
            command=self.start_client,
        )
        self.start_button.grid(row=0, column=0, sticky=tk.EW, padx=8, pady=10)
        self.stop_button = ttk.Button(
            controls,
            text="Stop Client",
            command=self.stop_client,
        )
        self.stop_button.grid(row=0, column=1, sticky=tk.EW, padx=8, pady=10)
        self.cli_button = ttk.Button(
            controls,
            text="Open Session CLI",
            command=self.open_cli,
        )
        self.cli_button.grid(row=0, column=2, sticky=tk.EW, padx=8, pady=10)

        status_frame = ttk.LabelFrame(self, text="Session State")
        status_frame.grid(row=9, column=0, columnspan=2, sticky=tk.EW, padx=10, pady=10)
        ttk.Label(status_frame, textvariable=self.summary_var, wraplength=700).pack(
            anchor=tk.W,
            padx=10,
            pady=(10, 4),
        )
        ttk.Label(status_frame, textvariable=self.status_var, wraplength=700).pack(
            anchor=tk.W,
            padx=10,
            pady=(10, 4),
        )
        ttk.Label(status_frame, textvariable=self.pid_var, wraplength=700).pack(
            anchor=tk.W,
            padx=10,
            pady=4,
        )
        ttk.Label(
            status_frame,
            textvariable=self.session_log_var,
            style="Mono.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=700,
        ).pack(
            anchor=tk.W,
            fill=tk.X,
            padx=10,
            pady=4,
        )
        ttk.Label(
            status_frame,
            textvariable=self.runtime_log_var,
            style="Mono.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=700,
        ).pack(
            anchor=tk.W,
            fill=tk.X,
            padx=10,
            pady=(4, 10),
        )

        ttk.Label(
            self,
            text=(
                "The timer window is opened by the managed client process. "
                "The CLI window can be hidden and reopened here without losing output."
            ),
            wraplength=700,
            foreground="#5c4d7d",
        ).grid(row=10, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 10))
        self._setup_widgets = [
            widget
            for widget in self.grid_slaves()
            if 0 <= int(widget.grid_info().get("row", -1)) <= 6
        ]

    def toggle_advanced(self):
        if not self.advanced_check.winfo_ismapped():
            return
        if self.v_adv.get():
            self.adv_frame.grid(row=7, column=0, columnspan=2, sticky=tk.EW)
            self.geometry("760x790")
            return
        self.adv_frame.grid_forget()
        self.geometry("760x720")

    def _client_running(self) -> bool:
        return self.process_session.is_running()

    def _current_log_path(self):
        if not self.process_session.log_path:
            return None
        return str(self.process_session.log_path)

    def _current_runtime_log_path(self):
        return self.process_session.runtime_log_path

    def _build_client_command(self) -> list[str]:
        command = [
            sys.executable,
            "-u",
            "-m",
            "client.main",
            "--login-id",
            self.v_login.get().strip(),
            "--password",
            self.v_pass.get().strip(),
            "--ipc-transport",
            "auto",
        ]
        ad_domain = self._auth_config.get("ad_domain", "")
        auth_secret = self._auth_config.get("auth_secret", "")
        if ad_domain and auth_secret:
            command.extend(["--ad-domain", ad_domain, "--auth-secret", auth_secret])
        server_id = self.v_id.get().strip()
        if server_id:
            command.extend(["--id", server_id])
        if self.v_adv.get():
            host = self.v_host.get().strip()
            if host:
                command.extend(["--host", host])
            command.extend(["--port", str(self.v_port.get())])
        return command

    def _validation_command(self) -> list[str]:
        return [*self._build_client_command(), "--check-login", "--timeout", "3"]

    def _session_summary_text(self) -> str:
        if self.v_adv.get():
            target = f"{self.v_host.get().strip() or 'discovery'}:{self.v_port.get()}"
        else:
            target = f"discovery:{self.v_id.get().strip() or 'default'}"
        return (
            f"Session Summary: login={self.v_login.get().strip() or '-'}    "
            f"server_id={self.v_id.get().strip() or '-'}    "
            f"target={target}"
        )

    def _set_setup_visible(self, visible: bool):
        for widget in self._setup_widgets:
            if visible:
                widget.grid()
            else:
                widget.grid_remove()
        if visible:
            if self.v_adv.get():
                self.adv_frame.grid(row=7, column=0, columnspan=2, sticky=tk.EW)
                self.geometry("760x790")
            else:
                self.adv_frame.grid_remove()
                self.geometry("760x720")
        else:
            self.adv_frame.grid_remove()

    def _validate_form(self) -> bool:
        if self._client_running():
            messagebox.showinfo("Client Running", "Stop the current client session before starting a new one.")
            return False
        if not self.v_login.get().strip() or not self.v_pass.get().strip():
            messagebox.showerror("Validation Error", "Login ID and password are required.")
            return False
        if self.v_adv.get() and not 1 <= self.v_port.get() <= 65535:
            messagebox.showerror("Validation Error", "Port must be between 1 and 65535.")
            return False
        return True

    def start_client(self):
        if not self._validate_form():
            return

        self._login_prompt_status = (
            "Client stopped. Start a session to open the timer window and CLI."
        )
        self.validation_in_progress = True
        self.start_button.config(state=tk.DISABLED, text="Validating...")
        thread = threading.Thread(target=self._run_login_check, daemon=True)
        thread.start()

    def _run_login_check(self):
        login_id   = self.v_login.get().strip()
        password   = self.v_pass.get().strip()
        ad_domain  = self._auth_config.get("ad_domain", "")
        auth_secret = self._auth_config.get("auth_secret", "")

        auth_status = resolve_auth_status_sync(
            login_id,
            server_id=self.v_id.get().strip() or "default",
            host=self.v_host.get().strip() if self.v_adv.get() else None,
            port=int(self.v_port.get()),
            timeout=3.0,
        )

        # Step 1: local preflight — CATS school auth + Windows AD auth in parallel
        preflight_ok, preflight_result = run_preflight(
            login_id, password, ad_domain, auth_secret, auth_status=auth_status
        )
        if not preflight_ok:
            self.after(0, self._handle_validation_error, preflight_result)
            return
        if auth_status_requires_admin_validation(auth_status):
            self.after(0, self._launch_client_process)
            return

        # Step 2: server reachability + token acceptance check
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.project_dir) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONUNBUFFERED"] = "1"
        try:
            result = subprocess.run(
                self._validation_command(),
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                env=env,
            )
        except Exception as exc:
            self.after(0, self._handle_validation_error, str(exc))
            return

        if result.returncode == 0:
            self.after(0, self._launch_client_process)
            return

        output = (result.stdout + "\n" + result.stderr).strip()
        error_message = "Unknown validation error."
        for line in output.splitlines():
            if "[FATAL]" in line or "[!]" in line:
                error_message = line.strip()
                break
        self.after(0, self._handle_validation_error, error_message)

    def _launch_client_process(self):
        self.validation_in_progress = False
        env = {
            "PYTHONPATH": str(self.project_dir)
            + os.pathsep
            + os.environ.get("PYTHONPATH", "")
        }
        try:
            self.process_session.start(
                self._build_client_command(),
                cwd=str(self.project_dir),
                env=env,
            )
        except Exception as exc:
            self._handle_validation_error(str(exc))
            return

        self.start_button.config(text="Connect & Login")
        self.summary_var.set(self._session_summary_text())
        self.status_var.set("Client running under manager control.")
        self._set_setup_visible(False)
        self.open_cli()

    def _return_to_login_prompt(self, message: str | None = None):
        self.validation_in_progress = False
        self.start_button.config(state=tk.NORMAL, text="Connect & Login")
        self._set_setup_visible(True)
        self.summary_var.set("Session Summary: -")
        if message:
            self._login_prompt_status = f"Login failed. {message}"
        self.status_var.set(self._login_prompt_status)
        self.deiconify()
        self.lift()
        self.update_idletasks()
        focus_target = self.password_entry if self.v_login.get().strip() else self.login_entry
        focus_target.focus_set()
        try:
            focus_target.selection_range(0, tk.END)
        except tk.TclError:
            pass

    def _handle_validation_error(self, message: str):
        self._return_to_login_prompt(message)
        messagebox.showerror(
            "Login Failed",
            f"Could not connect or authenticate with the server:\n\n{message}",
        )

    def stop_client(self):
        if not self._client_running():
            messagebox.showinfo("Client Stopped", "There is no active client session to stop.")
            return

        should_stop = messagebox.askyesno(
            "Stop Client",
            "Stop the running client session?",
            default=messagebox.NO,
        )
        if not should_stop:
            return

        self.process_session.stop()
        self._return_to_login_prompt()

    def open_cli(self):
        self.console_window.show_window()

    def _send_client_command(self, command: str) -> bool:
        return self.process_session.send_line(command)

    def _poll_process_state(self):
        running = self._client_running()
        process = self.process_session.process
        returncode = None if process is None else process.poll()

        self.start_button.config(
            state=tk.DISABLED if running or self.validation_in_progress else tk.NORMAL,
        )
        if (
            not running
            and not self.validation_in_progress
            and self.start_button.cget("text") != "Validating..."
        ):
            self.start_button.config(text="Connect & Login")
        self.stop_button.config(state=tk.NORMAL if running else tk.DISABLED)
        self.cli_button.config(
            state=tk.NORMAL if self.process_session.log_path is not None else tk.DISABLED
        )

        if running and process is not None:
            self.status_var.set("Client running under manager control.")
            self.pid_var.set(f"PID: {process.pid}")
        elif process is not None and returncode is not None:
            self.status_var.set(f"Client stopped. Exit code: {returncode}")
            self.pid_var.set(f"PID: {process.pid}")
        else:
            self.status_var.set(self._login_prompt_status)
            self.pid_var.set("PID: -")

        if running or self.validation_in_progress:
            self.summary_var.set(self._session_summary_text())
            self._set_setup_visible(False)
        else:
            self.summary_var.set("Session Summary: -")
            self._set_setup_visible(True)

        self.session_log_var.set(f"Session Output: {self.process_session.log_path or '-'}")
        self.runtime_log_var.set(
            f"Runtime JSONL: {self.process_session.runtime_log_path or '-'}"
        )

        self.after(500, self._poll_process_state)

    def on_close_request(self):
        if self._client_running():
            messagebox.showwarning(
                "Client Manager Locked",
                "The manager stays open while the client is running.\n\n"
                "Use Stop Client first, then close the manager.",
            )
            return

        should_close = messagebox.askyesno(
            "Close Client Manager",
            "Close the client manager?",
            default=messagebox.NO,
        )
        if should_close:
            self.destroy()


if __name__ == "__main__":
    apply_dpi_awareness()
    app = ClientManager()
    app.mainloop()
