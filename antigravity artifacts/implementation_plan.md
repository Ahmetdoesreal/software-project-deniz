# Qt Feature Parity: Policy Settings + Process Decision

The Qt server dashboard inherits `PolicySettingsMixin` and `DashboardPopupMixin`, but both are 100% Tkinter code (`tk.Toplevel`, `ttk.Checkbutton`, `tk.Text`, `messagebox`, etc.). The Qt GUI currently stubs `open_policy_settings_window` with a "use Tk" message.

## Features to Port

### 1. Policy Settings Window (currently stubbed)
A tabbed settings editor with 9 tabs:
- **Runtime** — exam duration, exam files browser
- **Session** — auto-resume, remember settings
- **Blacklist** — enabled/severity/auto-pause, blacklist entries text area
- **Focused Window** — match mode, thresholds, allowed/blocked lists
- **Rapid Switch** — max switches, window seconds
- **Unexpected Process** — baseline, known processes
- **Process Definitions** — definitions JSON editor
- **Path Clarification** — enabled/severity
- **Operator Confirmations** — confirm kill/kick/ban/pause checkboxes

Plus toolbar: Save, Reload, Export, Import, Open/Apply Policy File buttons.

All form data is collected → serialized to JSON → printed to stdout (IPC to server).

### 2. Process Decision Window (partially stubbed)
Already has a basic info dialog via `_on_process_options_clicked`. Needs the full decision form with:
- Status/Scope dropdowns, action checkboxes, save-to-policy toggle
- Student action state table
- Previous matching entries table
- Google search + Apply Policy buttons

## Proposed Approach

### [NEW] `server/policy_settings_qt.py`
Qt implementation of the entire Policy Settings window as a `QDialog` with `QTabWidget`. Mirrors every field from `PolicySettingsMixin._collect_settings_payload()` exactly so the server backend doesn't need changes.

### [MODIFY] `server/gui_qt.py`
- Replace the `open_policy_settings_window` stub with a call to the new Qt dialog
- Replace `_on_process_options_clicked` with the full process decision dialog
- Wire `process_settings_result` and `update_settings_snapshot` to the Qt settings window
- Handle `settings_result` IPC messages (already wired in the IPC reader)

### No backend changes needed
The settings payload format is identical — only the widget toolkit changes.

> [!IMPORTANT]
> This is ~800-1000 lines of new Qt form code. It ports the exact same data model — just with `QCheckBox`, `QComboBox`, `QPlainTextEdit`, `QLineEdit`, `QFileDialog` instead of the Tk equivalents.

## Verification
- Launch server with `--ui qt`
- Open Policy Settings → verify all 9 tabs render
- Modify a setting → verify "unsaved changes" indicator
- Save → verify JSON payload is correct on stdout
- Open Process Decision on a process → verify full form renders
