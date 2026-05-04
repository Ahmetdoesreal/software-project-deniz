# Qt Feature Parity Implementation Tasks

- `[x]` 1. Create `server/policy_settings_qt.py` with `PolicySettingsDialog` covering all 9 settings tabs.
- `[x]` 2. Add `ProcessDecisionDialog` matching the Tkinter Process Decision window features.
- `[x]` 3. Style the table components (Students, Previous Entries) in `ProcessDecisionDialog` to match the existing `process_tree` / `incident_table`.
- `[x]` 4. Update `gui_qt.py`'s `open_policy_settings_window` to open the new `PolicySettingsDialog`.
- `[x]` 5. Update `gui_qt.py`'s `_on_process_options_clicked` to open the new `ProcessDecisionDialog` instead of the basic `_DetailsDialog`.
- `[x]` 6. Wire settings snapshot updates and save results from `gui_qt.py` to the new settings dialog.
- `[x]` 7. Verify the JSON payloads emitted match the required format for IPC.
