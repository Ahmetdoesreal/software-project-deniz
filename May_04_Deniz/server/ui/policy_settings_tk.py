import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


SEVERITY_VALUES = ("info", "warning", "violation")
WINDOW_TITLE_MATCH_MODES = ("contains", "exact")
SETTINGS_TAB_LABELS = {
    "General": "General",
    "Process Lists": "Process Lists",
    "Window Rules": "Window Rules",
    "Process Definitions": "Process Definitions",
}


class PolicySettingsMixin:
    def _init_policy_settings(self):
        self.settings_snapshot: dict = {}
        self.settings_vars: dict[str, tk.Variable] = {}
        self.settings_text_widgets: dict[str, tk.Text] = {}
        self._settings_window = None
        self._settings_loading = False
        self._settings_dirty = False
        self._settings_last_loaded_key = None
        self.save_settings_button = None
        self.settings_notebook = None
        self.settings_status_var = tk.StringVar(value="Waiting for server settings...")

    def _build_policy_settings_window(self, parent):
        self.settings_vars = {}
        self.settings_text_widgets = {}
        self._settings_last_loaded_key = None
        self._settings_dirty = False
        self.save_settings_button = None
        self.settings_notebook = None

        container = ttk.Frame(parent)
        container.pack(fill=tk.BOTH, expand=True)

        toolbar = ttk.Frame(container, padding=(10, 10, 10, 0))
        toolbar.pack(fill=tk.X)
        toolbar.columnconfigure(0, weight=1)
        toolbar.columnconfigure(1, weight=0)

        save_group = ttk.Frame(toolbar)
        save_group.grid(row=0, column=0, sticky=tk.W)

        file_group = ttk.Frame(toolbar)
        file_group.grid(row=0, column=1, sticky=tk.E)

        self.save_settings_button = ttk.Button(
            save_group,
            text="Save Settings",
            command=self.save_settings,
            state=tk.DISABLED,
            width=16,
        )
        self.save_settings_button.pack(side=tk.LEFT)

        ttk.Button(save_group, text="Reload", command=self.reload_settings_form, width=12).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(file_group, text="Export", command=self.export_settings, width=10).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(file_group, text="Import", command=self.import_settings, width=10).pack(side=tk.LEFT)
        ttk.Label(toolbar, textvariable=self.settings_status_var).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))

        self.settings_notebook = ttk.Notebook(container)
        self.settings_notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self._build_general_settings_section()
        self._build_process_lists_settings_section()
        self._build_window_rules_settings_section()
        self._build_process_definition_settings_section()

    def _settings_section(self, title: str):
        frame = ttk.Frame(self.settings_notebook, padding=12)
        self.settings_notebook.add(frame, text=SETTINGS_TAB_LABELS.get(title, title))
        for column in range(4):
            frame.columnconfigure(column, weight=1)
        return frame

    def _setting_var(self, key: str, value="", *, boolean: bool = False):
        var = tk.BooleanVar(value=bool(value)) if boolean else tk.StringVar(value=str(value or ""))
        var.trace_add("write", lambda *_args: self._mark_settings_dirty())
        self.settings_vars[key] = var
        return var

    def _settings_check(self, parent, key: str, text: str, row: int, column: int, columnspan: int = 1):
        check = ttk.Checkbutton(
            parent,
            text=text,
            variable=self._setting_var(key, False, boolean=True),
        )
        check.grid(row=row, column=column, columnspan=columnspan, sticky=tk.W, padx=(0, 12), pady=3)
        return check

    def _settings_entry(self, parent, label: str, key: str, row: int, column: int, width: int = 16):
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky=tk.W, padx=(0, 6), pady=3)
        entry = ttk.Entry(parent, textvariable=self._setting_var(key), width=width)
        entry.grid(row=row, column=column + 1, sticky=tk.EW, padx=(0, 12), pady=3)
        return entry

    def _settings_combo(self, parent, label: str, key: str, row: int, column: int, values: tuple[str, ...], width: int = 18):
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky=tk.W, padx=(0, 6), pady=3)
        combo = ttk.Combobox(
            parent,
            textvariable=self._setting_var(key),
            values=values,
            state="readonly",
            width=width,
        )
        combo.grid(row=row, column=column + 1, sticky=tk.EW, padx=(0, 12), pady=3)
        return combo

    def _settings_text(self, parent, label: str, key: str, row: int, height: int = 4):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, columnspan=4, sticky=tk.EW, pady=(6, 2))
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=label).grid(row=0, column=0, sticky=tk.W)
        text = tk.Text(frame, height=height, wrap=tk.NONE, font=self.mono_font)
        text.grid(row=1, column=0, sticky=tk.EW, pady=(2, 0))
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        scroll.grid(row=1, column=1, sticky=tk.NS, pady=(2, 0))
        text.configure(yscrollcommand=scroll.set)
        text.bind("<KeyRelease>", lambda _event: self._mark_settings_dirty())
        text.bind("<<Paste>>", lambda _event: self.after(0, self._mark_settings_dirty))
        text.bind("<<Cut>>", lambda _event: self.after(0, self._mark_settings_dirty))
        self.settings_text_widgets[key] = text
        return text

    def _settings_group(self, parent, title: str, row: int, column: int = 0, columnspan: int = 4):
        group = ttk.LabelFrame(parent, text=title, padding=10)
        group.grid(row=row, column=column, columnspan=columnspan, sticky=tk.NSEW, padx=(0, 10), pady=(0, 10))
        for grid_column in range(4):
            group.columnconfigure(grid_column, weight=1)
        return group

    def _build_general_settings_section(self):
        frame = self._settings_section("General")
        frame.rowconfigure(0, weight=1)

        runtime = self._settings_group(frame, "Runtime", 0)
        self._settings_entry(runtime, "Exam Duration (min)", "runtime.exam_duration", 0, 0, width=12)
        ttk.Label(runtime, text="Exam Files").grid(row=1, column=0, sticky=tk.W, padx=(0, 6), pady=3)
        entry = ttk.Entry(runtime, textvariable=self._setting_var("runtime.exam_files"))
        entry.grid(row=1, column=1, sticky=tk.EW, padx=(0, 8), pady=3)
        ttk.Button(runtime, text="Browse", command=self.browse_exam_files).grid(row=1, column=2, sticky=tk.EW, padx=(0, 8), pady=3)
        ttk.Button(runtime, text="Clear", command=lambda: self._set_settings_var("runtime.exam_files", "")).grid(row=1, column=3, sticky=tk.EW, pady=3)

        session = self._settings_group(frame, "Session", 1, column=0, columnspan=2)
        self._settings_check(session, "session.auto_resume_on_reconnect", "Auto resume on reconnect", 0, 0, columnspan=2)
        self._settings_check(session, "session.remember_settings", "Remember settings", 1, 0, columnspan=2)

        confirmations = self._settings_group(frame, "Operator Confirmations", 1, column=2, columnspan=2)
        self._settings_check(confirmations, "operator_defaults.confirm_kill_pid", "Confirm kill PID", 0, 0, columnspan=2)
        self._settings_check(confirmations, "operator_defaults.confirm_kick", "Confirm kick", 0, 2, columnspan=2)
        self._settings_check(confirmations, "operator_defaults.confirm_ban", "Confirm ban", 1, 0, columnspan=2)
        self._settings_check(confirmations, "operator_defaults.confirm_pause", "Confirm pause", 1, 2, columnspan=2)

    def _build_process_lists_settings_section(self):
        frame = self._settings_section("Process Lists")
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(0, weight=1)

        blacklist = self._settings_group(frame, "Process Blacklist", 0, column=0, columnspan=2)
        self._settings_combo(blacklist, "Severity", "rules.process_blacklist.severity", 0, 0, SEVERITY_VALUES)
        self._settings_text(blacklist, "Blacklisted process names, one per line", "process_blacklist.entries", 1, height=5)
        self._settings_text(blacklist, "Monitored process usernames, one per line", "rules.process_blacklist.process_usernames", 2, height=3)
        blacklist_options = self._settings_group(blacklist, "Options", 3)
        self._settings_check(blacklist_options, "rules.process_blacklist.enabled", "Enabled", 0, 0)
        self._settings_check(blacklist_options, "rules.process_blacklist.auto_violation_pause", "Auto pause on violation", 0, 1, columnspan=2)
        self._settings_check(blacklist_options, "rules.process_blacklist.allow_remote_kill", "Allow remote kill", 1, 0, columnspan=2)

        unexpected = self._settings_group(frame, "Unexpected Process", 0, column=2, columnspan=2)
        self._settings_combo(unexpected, "Severity", "rules.unexpected_process.severity", 0, 0, SEVERITY_VALUES)
        self._settings_text(unexpected, "Known process names, one per line", "rules.unexpected_process.known_process_names", 1, height=4)
        self._settings_text(unexpected, "Known directory paths, one per line", "rules.unexpected_process.known_directory_paths", 2, height=4)
        self._settings_text(unexpected, "Allowed process names, one per line", "rules.unexpected_process.allowed_process_names", 3, height=3)
        unexpected_options = self._settings_group(unexpected, "Options", 4)
        self._settings_check(unexpected_options, "rules.unexpected_process.enabled", "Enabled", 0, 0)
        self._settings_check(unexpected_options, "rules.unexpected_process.baseline_existing_processes", "Baseline existing processes", 0, 1, columnspan=2)
        self._settings_check(unexpected_options, "rules.unexpected_process.auto_violation_pause", "Auto pause on violation", 1, 0, columnspan=2)

    def _build_window_rules_settings_section(self):
        frame = self._settings_section("Window Rules")
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        focused = self._settings_group(frame, "Focused Window", 0, column=0, columnspan=2)
        self._settings_combo(focused, "Severity", "rules.focused_window.severity", 0, 0, SEVERITY_VALUES)
        self._settings_combo(focused, "Titlebar Match", "rules.focused_window.window_title_match_mode", 0, 2, WINDOW_TITLE_MATCH_MODES)
        self._settings_entry(focused, "Open After", "rules.focused_window.open_after_consecutive", 1, 0, width=12)
        self._settings_entry(focused, "Resolve After", "rules.focused_window.resolve_after_consecutive", 1, 2, width=12)
        self._settings_text(focused, "Allowed process names, one per line", "rules.focused_window.allowed_process_names", 2, height=2)
        self._settings_text(focused, "Allowed titlebar text, one per line", "rules.focused_window.allowed_window_titles", 3, height=2)
        self._settings_text(focused, "Blocked process names, one per line", "rules.focused_window.blocked_process_names", 4, height=2)
        self._settings_text(focused, "Blocked titlebar text, one per line", "rules.focused_window.blocked_window_titles", 5, height=2)
        focused_options = self._settings_group(focused, "Options", 6)
        self._settings_check(focused_options, "rules.focused_window.enabled", "Enabled", 0, 0)
        self._settings_check(focused_options, "rules.focused_window.auto_violation_pause", "Auto pause on violation", 0, 1, columnspan=2)

        switching = self._settings_group(frame, "Switching And Path Checks", 0, column=2, columnspan=2)
        self._settings_combo(switching, "Rapid Severity", "rules.rapid_application_switching.severity", 0, 0, SEVERITY_VALUES)
        self._settings_entry(switching, "Max Switches", "rules.rapid_application_switching.max_switches", 1, 0, width=12)
        self._settings_entry(switching, "Window Seconds", "rules.rapid_application_switching.window_seconds", 2, 0, width=12)
        self._settings_entry(switching, "Window Observations", "rules.rapid_application_switching.window_observations", 3, 0, width=12)
        self._settings_combo(switching, "Path Severity", "rules.process_path_clarification.severity", 4, 0, SEVERITY_VALUES)
        switching_options = self._settings_group(switching, "Options", 5)
        self._settings_check(switching_options, "rules.rapid_application_switching.enabled", "Rapid switch enabled", 0, 0, columnspan=2)
        self._settings_check(switching_options, "rules.rapid_application_switching.auto_violation_pause", "Rapid switch auto pause", 1, 0, columnspan=2)
        self._settings_check(switching_options, "rules.process_path_clarification.enabled", "Path clarification enabled", 2, 0, columnspan=2)
        self._settings_check(switching_options, "rules.process_path_clarification.auto_violation_pause", "Path clarification auto pause", 3, 0, columnspan=2)
        self._settings_check(switching_options, "rules.process_path_clarification.allow_remote_kill", "Path clarification remote kill", 4, 0, columnspan=2)

        idle = self._settings_group(frame, "Idle Monitor", 1, column=0, columnspan=4)
        self._settings_check(idle, "rules.idle_policy.enabled", "Enabled", 0, 0)
        self._settings_entry(idle, "Warn Threshold (s)", "rules.idle_policy.warn_threshold_seconds", 1, 0, width=8)
        self._settings_entry(idle, "Critical Threshold (s)", "rules.idle_policy.critical_threshold_seconds", 1, 2, width=8)

    def _build_process_definition_settings_section(self):
        frame = self._settings_section("Process Definitions")
        self._settings_combo(frame, "Severity", "rules.process_definitions.severity", 0, 0, SEVERITY_VALUES)
        self._settings_combo(frame, "Unknown Severity", "rules.process_definitions.unknown_severity", 0, 2, SEVERITY_VALUES)
        file_actions = ttk.LabelFrame(frame, text="Definition File", padding=10)
        file_actions.grid(row=1, column=0, columnspan=4, sticky=tk.EW, pady=(0, 10))
        ttk.Button(
            file_actions,
            text="Open Definitions File",
            command=self.edit_process_definitions,
            width=22,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            file_actions,
            text="Apply Definitions File",
            command=self.apply_process_definitions,
            width=22,
        ).pack(side=tk.LEFT)
        options = self._settings_group(frame, "Options", 2)
        self._settings_check(options, "rules.process_definitions.enabled", "Enabled", 0, 0)
        self._settings_check(options, "rules.process_definitions.detect_unknown_processes", "Detect unknown processes", 0, 1, columnspan=2)
        self._settings_check(options, "rules.process_definitions.baseline_existing_processes", "Baseline existing processes", 1, 0, columnspan=2)
        self._settings_check(options, "rules.process_definitions.auto_violation_pause", "Auto pause on violation", 1, 2, columnspan=2)
        self._settings_check(options, "rules.process_definitions.allow_remote_kill", "Allow remote kill", 2, 0, columnspan=2)

    def open_policy_settings_window(self):
        window = self._settings_window
        if window is not None and window.winfo_exists():
            window.lift()
            window.focus_force()
            return

        top = tk.Toplevel(self)
        top.title("Policy Settings")
        top.geometry("1180x820")
        top.minsize(1060, 720)
        self._settings_window = top
        top.protocol("WM_DELETE_WINDOW", self._close_policy_settings_window)
        top.bind("<Destroy>", lambda event: self._forget_policy_settings_window(top) if event.widget is top else None)
        self._build_policy_settings_window(top)
        self._populate_settings_form_from_snapshot(force=True)

    def show_settings_tab(self):
        self.open_policy_settings_window()

    def _close_policy_settings_window(self):
        if self._settings_dirty and not messagebox.askyesno(
            "Close Policy Settings",
            "Close policy settings and discard unsaved changes?",
        ):
            return
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.destroy()

    def _forget_policy_settings_window(self, window):
        if self._settings_window is window:
            self._settings_window = None
            self.save_settings_button = None
            self.settings_notebook = None
            self.settings_vars = {}
            self.settings_text_widgets = {}
            self._settings_dirty = False
            self._settings_last_loaded_key = None

    def update_settings_snapshot(self, snapshot: dict):
        self.settings_snapshot = snapshot
        window = self._settings_window
        if window is None or not window.winfo_exists():
            self._refresh_settings_status()
            return
        if self.save_settings_button is not None:
            self.save_settings_button.config(state=tk.NORMAL)
        self._populate_settings_form_from_snapshot()

    def browse_exam_files(self):
        path = filedialog.askopenfilename(
            title="Choose Exam Files",
            filetypes=[("ZIP Files", "*.zip"), ("All Files", "*.*")],
        )
        if path:
            self._set_settings_var("runtime.exam_files", path)

    def reload_settings_form(self):
        if self._settings_dirty and not messagebox.askyesno(
            "Reload Settings",
            "Discard unsaved settings changes and reload the current server settings?",
        ):
            return
        self._populate_settings_form_from_snapshot(force=True)

    def save_settings(self):
        if not self.settings_snapshot:
            messagebox.showinfo("Settings", "No server settings are available yet.")
            return
        try:
            payload = self._collect_settings_payload()
        except ValueError as exc:
            messagebox.showerror("Settings", str(exc))
            return

        self._emit_command(payload)
        self._settings_dirty = False
        self.settings_status_var.set("Saving settings...")
        self._append_log("[ADMIN] Saving GUI settings")

    def process_settings_result(self, payload: dict):
        ok = bool(payload.get("ok", False))
        message = str(payload.get("message") or ("Settings saved." if ok else "Settings were not saved."))
        errors = payload.get("errors", [])
        if ok:
            self._settings_dirty = False
            self._append_log(f"[SETTINGS] {message}")
        else:
            error_text = "\n".join(str(error) for error in errors) or message
            messagebox.showerror("Settings", error_text)
            self._append_log(f"[SETTINGS] Failed: {message}")
        self._refresh_settings_status(extra=message)

    def _mark_settings_dirty(self):
        if self._settings_loading:
            return
        self._settings_dirty = True
        self._refresh_settings_status()

    def _refresh_settings_status(self, *, extra: str = ""):
        version = str(self.settings_snapshot.get("policy_version", "") or "")
        blacklist_version = str(self.settings_snapshot.get("process_blacklist_version", "") or "")
        definitions_version = str(self.settings_snapshot.get("process_definitions_version", "") or "")
        label = (
            f"Policy {version[:12] or '-'} | "
            f"Blacklist {blacklist_version[:12] or '-'} | "
            f"Definitions {definitions_version[:12] or '-'}"
        )
        if self._settings_dirty:
            label += " | Unsaved changes"
        if extra:
            label += f" | {extra}"
        self.settings_status_var.set(label)

    def _settings_loaded_key(self, snapshot: dict):
        runtime = snapshot.get("runtime", {}) if isinstance(snapshot.get("runtime"), dict) else {}
        return (
            str(snapshot.get("policy_version", "") or ""),
            str(snapshot.get("process_blacklist_version", "") or ""),
            str(snapshot.get("process_definitions_version", "") or ""),
            str(runtime.get("exam_duration", "") or ""),
            str(runtime.get("exam_files", "") or ""),
        )

    def _populate_settings_form_from_snapshot(self, *, force: bool = False):
        snapshot = self.settings_snapshot
        if not snapshot:
            self.settings_status_var.set("Waiting for server settings...")
            return
        if self.save_settings_button is not None:
            self.save_settings_button.config(state=tk.NORMAL)

        loaded_key = self._settings_loaded_key(snapshot)
        if not force and self._settings_dirty:
            self._refresh_settings_status()
            return
        if not force and loaded_key == self._settings_last_loaded_key:
            self._refresh_settings_status()
            return

        policy = snapshot.get("exam_policy", {}) if isinstance(snapshot.get("exam_policy"), dict) else {}
        rules = policy.get("rules", {}) if isinstance(policy.get("rules"), dict) else {}
        session = policy.get("session", {}) if isinstance(policy.get("session"), dict) else {}
        operator_defaults = (
            policy.get("operator_defaults", {})
            if isinstance(policy.get("operator_defaults"), dict)
            else {}
        )
        runtime = snapshot.get("runtime", {}) if isinstance(snapshot.get("runtime"), dict) else {}

        process_blacklist = rules.get("process_blacklist", {}) if isinstance(rules.get("process_blacklist"), dict) else {}
        focused_window = rules.get("focused_window", {}) if isinstance(rules.get("focused_window"), dict) else {}
        rapid_switching = (
            rules.get("rapid_application_switching", {})
            if isinstance(rules.get("rapid_application_switching"), dict)
            else {}
        )
        unexpected_process = rules.get("unexpected_process", {}) if isinstance(rules.get("unexpected_process"), dict) else {}
        process_definitions = rules.get("process_definitions", {}) if isinstance(rules.get("process_definitions"), dict) else {}
        path_clarification = (
            rules.get("process_path_clarification", {})
            if isinstance(rules.get("process_path_clarification"), dict)
            else {}
        )
        idle_policy = rules.get("idle_policy", {}) if isinstance(rules.get("idle_policy"), dict) else {}

        self._settings_loading = True
        try:
            self._set_settings_var("runtime.exam_duration", runtime.get("exam_duration", ""))
            self._set_settings_var("runtime.exam_files", runtime.get("exam_files") or "")

            self._set_settings_var("session.auto_resume_on_reconnect", session.get("auto_resume_on_reconnect", True))
            self._set_settings_var("session.remember_settings", session.get("remember_settings", True))

            self._set_rule_common("rules.process_blacklist", process_blacklist, default_enabled=True, default_severity="violation")
            self._set_settings_var("rules.process_blacklist.allow_remote_kill", process_blacklist.get("allow_remote_kill", True))
            self._set_settings_text("process_blacklist.entries", "\n".join(snapshot.get("process_blacklist", [])))
            self._set_settings_text(
                "rules.process_blacklist.process_usernames",
                "\n".join(process_blacklist.get("process_usernames", [])),
            )

            self._set_rule_common("rules.focused_window", focused_window, default_enabled=False, default_severity="warning")
            self._set_settings_var(
                "rules.focused_window.window_title_match_mode",
                focused_window.get("window_title_match_mode", "contains"),
            )
            self._set_settings_var(
                "rules.focused_window.open_after_consecutive",
                focused_window.get("open_after_consecutive", 3),
            )
            self._set_settings_var(
                "rules.focused_window.resolve_after_consecutive",
                focused_window.get("resolve_after_consecutive", 2),
            )
            for key in (
                "allowed_process_names",
                "allowed_window_titles",
                "blocked_process_names",
                "blocked_window_titles",
            ):
                self._set_settings_text(f"rules.focused_window.{key}", "\n".join(focused_window.get(key, [])))

            self._set_rule_common(
                "rules.rapid_application_switching",
                rapid_switching,
                default_enabled=False,
                default_severity="warning",
            )
            self._set_settings_var("rules.rapid_application_switching.max_switches", rapid_switching.get("max_switches", 10))
            self._set_settings_var("rules.rapid_application_switching.window_seconds", rapid_switching.get("window_seconds", 60))
            self._set_settings_var(
                "rules.rapid_application_switching.window_observations",
                rapid_switching.get("window_observations", 10),
            )

            self._set_rule_common("rules.unexpected_process", unexpected_process, default_enabled=False, default_severity="warning")
            self._set_settings_var(
                "rules.unexpected_process.baseline_existing_processes",
                unexpected_process.get("baseline_existing_processes", False),
            )
            for key in ("known_process_names", "known_directory_paths", "allowed_process_names"):
                self._set_settings_text(f"rules.unexpected_process.{key}", "\n".join(unexpected_process.get(key, [])))

            self._set_rule_common("rules.process_definitions", process_definitions, default_enabled=True, default_severity="violation")
            self._set_settings_var(
                "rules.process_definitions.detect_unknown_processes",
                process_definitions.get("detect_unknown_processes", True),
            )
            self._set_settings_var(
                "rules.process_definitions.unknown_severity",
                process_definitions.get("unknown_severity", "warning"),
            )
            self._set_settings_var(
                "rules.process_definitions.baseline_existing_processes",
                process_definitions.get("baseline_existing_processes", True),
            )
            self._set_settings_var(
                "rules.process_definitions.allow_remote_kill",
                process_definitions.get("allow_remote_kill", True),
            )
            self._set_rule_common(
                "rules.process_path_clarification",
                path_clarification,
                default_enabled=True,
                default_severity="warning",
            )
            self._set_settings_var(
                "rules.process_path_clarification.allow_remote_kill",
                path_clarification.get("allow_remote_kill", True),
            )

            self._set_settings_var("rules.idle_policy.enabled", idle_policy.get("enabled", False))
            self._set_settings_var("rules.idle_policy.warn_threshold_seconds", idle_policy.get("warn_threshold_seconds", 80))
            self._set_settings_var("rules.idle_policy.critical_threshold_seconds", idle_policy.get("critical_threshold_seconds", 150))

            for key, default in (
                ("confirm_kill_pid", True),
                ("confirm_kick", True),
                ("confirm_ban", True),
                ("confirm_pause", True),
            ):
                self._set_settings_var(f"operator_defaults.{key}", operator_defaults.get(key, default))
        finally:
            self._settings_loading = False

        self._settings_dirty = False
        self._settings_last_loaded_key = loaded_key
        self._refresh_settings_status()

    def _set_rule_common(self, prefix: str, config: dict, *, default_enabled: bool, default_severity: str):
        self._set_settings_var(f"{prefix}.enabled", config.get("enabled", default_enabled))
        self._set_settings_var(f"{prefix}.severity", config.get("severity", default_severity))
        self._set_settings_var(f"{prefix}.auto_violation_pause", config.get("auto_violation_pause", False))

    def _set_settings_var(self, key: str, value):
        var = self.settings_vars.get(key)
        if var is not None:
            var.set(value)

    def _settings_var_value(self, key: str):
        var = self.settings_vars.get(key)
        return var.get() if var is not None else ""

    def _settings_bool(self, key: str) -> bool:
        return bool(self._settings_var_value(key))

    def _set_settings_text(self, key: str, value: str):
        widget = self.settings_text_widgets.get(key)
        if widget is None:
            return
        widget.delete("1.0", tk.END)
        if value:
            widget.insert("1.0", str(value))

    def _settings_text_value(self, key: str) -> str:
        widget = self.settings_text_widgets.get(key)
        if widget is None:
            return ""
        return widget.get("1.0", tk.END).strip()

    def _settings_text_lines(self, key: str) -> list[str]:
        return [line.strip() for line in self._settings_text_value(key).splitlines() if line.strip()]

    def _settings_json_list(self, key: str, label: str) -> list[dict]:
        raw = self._settings_text_value(key)
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} must be valid JSON: {exc}") from exc
        if not isinstance(value, list):
            raise ValueError(f"{label} must be a JSON list.")
        return value

    def _positive_int_setting(self, key: str, label: str) -> int:
        raw = str(self._settings_var_value(key)).strip()
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be a positive integer.") from exc
        if value <= 0:
            raise ValueError(f"{label} must be greater than 0.")
        return value

    def _collect_settings_payload(self) -> dict:
        title_match_mode = str(self._settings_var_value("rules.focused_window.window_title_match_mode") or "contains").strip().lower()
        if title_match_mode not in WINDOW_TITLE_MATCH_MODES:
            raise ValueError("Titlebar match must be contains or exact.")

        exam_policy = {
            "session": {
                "auto_resume_on_reconnect": self._settings_bool("session.auto_resume_on_reconnect"),
                "remember_settings": self._settings_bool("session.remember_settings"),
            },
            "rules": {
                "process_blacklist": {
                    "enabled": self._settings_bool("rules.process_blacklist.enabled"),
                    "severity": str(self._settings_var_value("rules.process_blacklist.severity") or "violation").strip(),
                    "process_usernames": self._settings_text_lines("rules.process_blacklist.process_usernames"),
                    "auto_violation_pause": self._settings_bool("rules.process_blacklist.auto_violation_pause"),
                    "allow_remote_kill": self._settings_bool("rules.process_blacklist.allow_remote_kill"),
                },
                "focused_window": {
                    "enabled": self._settings_bool("rules.focused_window.enabled"),
                    "severity": str(self._settings_var_value("rules.focused_window.severity") or "warning").strip(),
                    "allowed_process_names": self._settings_text_lines("rules.focused_window.allowed_process_names"),
                    "allowed_window_titles": self._settings_text_lines("rules.focused_window.allowed_window_titles"),
                    "blocked_process_names": self._settings_text_lines("rules.focused_window.blocked_process_names"),
                    "blocked_window_titles": self._settings_text_lines("rules.focused_window.blocked_window_titles"),
                    "window_title_match_mode": title_match_mode,
                    "open_after_consecutive": self._positive_int_setting(
                        "rules.focused_window.open_after_consecutive",
                        "Focused-window open-after count",
                    ),
                    "resolve_after_consecutive": self._positive_int_setting(
                        "rules.focused_window.resolve_after_consecutive",
                        "Focused-window resolve-after count",
                    ),
                    "auto_violation_pause": self._settings_bool("rules.focused_window.auto_violation_pause"),
                },
                "rapid_application_switching": {
                    "enabled": self._settings_bool("rules.rapid_application_switching.enabled"),
                    "severity": str(self._settings_var_value("rules.rapid_application_switching.severity") or "warning").strip(),
                    "max_switches": self._positive_int_setting(
                        "rules.rapid_application_switching.max_switches",
                        "Rapid-switch max switches",
                    ),
                    "window_seconds": self._positive_int_setting(
                        "rules.rapid_application_switching.window_seconds",
                        "Rapid-switch window seconds",
                    ),
                    "window_observations": self._positive_int_setting(
                        "rules.rapid_application_switching.window_observations",
                        "Rapid-switch window observations",
                    ),
                    "auto_violation_pause": self._settings_bool("rules.rapid_application_switching.auto_violation_pause"),
                },
                "unexpected_process": {
                    "enabled": self._settings_bool("rules.unexpected_process.enabled"),
                    "severity": str(self._settings_var_value("rules.unexpected_process.severity") or "warning").strip(),
                    "known_process_names": self._settings_text_lines("rules.unexpected_process.known_process_names"),
                    "known_directory_paths": self._settings_text_lines("rules.unexpected_process.known_directory_paths"),
                    "allowed_process_names": self._settings_text_lines("rules.unexpected_process.allowed_process_names"),
                    "baseline_existing_processes": self._settings_bool("rules.unexpected_process.baseline_existing_processes"),
                    "auto_violation_pause": self._settings_bool("rules.unexpected_process.auto_violation_pause"),
                },
                "process_definitions": {
                    "enabled": self._settings_bool("rules.process_definitions.enabled"),
                    "severity": str(self._settings_var_value("rules.process_definitions.severity") or "violation").strip(),
                    "detect_unknown_processes": self._settings_bool("rules.process_definitions.detect_unknown_processes"),
                    "unknown_severity": str(self._settings_var_value("rules.process_definitions.unknown_severity") or "warning").strip(),
                    "baseline_existing_processes": self._settings_bool("rules.process_definitions.baseline_existing_processes"),
                    "auto_violation_pause": self._settings_bool("rules.process_definitions.auto_violation_pause"),
                    "allow_remote_kill": self._settings_bool("rules.process_definitions.allow_remote_kill"),
                },
                "process_path_clarification": {
                    "enabled": self._settings_bool("rules.process_path_clarification.enabled"),
                    "severity": str(self._settings_var_value("rules.process_path_clarification.severity") or "warning").strip(),
                    "auto_violation_pause": self._settings_bool("rules.process_path_clarification.auto_violation_pause"),
                    "allow_remote_kill": self._settings_bool("rules.process_path_clarification.allow_remote_kill"),
                },
                "idle_policy": {
                    "enabled": self._settings_bool("rules.idle_policy.enabled"),
                    "warn_threshold_seconds": self._positive_int_setting("rules.idle_policy.warn_threshold_seconds", "Idle warn threshold"),
                    "critical_threshold_seconds": self._positive_int_setting("rules.idle_policy.critical_threshold_seconds", "Idle critical threshold"),
                },
            },
            "operator_defaults": {
                "confirm_kill_pid": self._settings_bool("operator_defaults.confirm_kill_pid"),
                "confirm_kick": self._settings_bool("operator_defaults.confirm_kick"),
                "confirm_ban": self._settings_bool("operator_defaults.confirm_ban"),
                "confirm_pause": self._settings_bool("operator_defaults.confirm_pause"),
            },
        }

        exam_files = str(self._settings_var_value("runtime.exam_files") or "").strip()
        return {
            "cmd": "save_settings",
            "runtime": {
                "exam_duration": self._positive_int_setting("runtime.exam_duration", "Exam duration"),
                "exam_files": exam_files or None,
            },
            "exam_policy": exam_policy,
            "process_blacklist": {
                "entries": self._settings_text_lines("process_blacklist.entries"),
            },
        }
