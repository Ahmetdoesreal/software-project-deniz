# Clean Iteration

This folder is a trimmed copy of the active project.

Kept:

- `client/`
- `server/`
- `common/`
- `custommodules/`
- `tests/`
- `mytask_workspace/`
- launch/setup files and `requirements.txt`

Left out:

- old archive folders
- generated runtime data
- copied external projects
- cache files
- unused demo/template extras

The main cleanup in this iteration is `client/incidents.py`. It keeps the same public API:

- `ClientIncidentEngine`
- `apply_policy`
- `observe_processes`
- `observe_focused_window`
- `incident_for_id`

But the internal names are more direct:

- `clean_name`
- `process_basename`
- `split_process`
- `FocusTracker`
- `SwitchTracker`
- `note_unexpected_processes`
- `note_fast_switching`
- `note_focus_violation`

Run the local checks from this folder with:

```powershell
python -m unittest tests.unit.test_client_incidents tests.unit.test_process_monitor tests.unit.test_security
python -m unittest test_client_incidents.py
python custommodules/process_monitor/core.py --limit 1
```
