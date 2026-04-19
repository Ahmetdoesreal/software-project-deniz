# MyTask Workspace

This folder is a focused copy for the client-monitoring event detection task.
It does not modify the active app files or any teammate files.

## Contents

- `mytask.txt`: original task text.
- `incidents.py`: working copy of the client incident engine.
- `test_client_incidents.py`: focused tests for this workspace.

## What Changed

The copied `ClientIncidentEngine` now emits structured incidents for:

- `process_blacklist`: existing prohibited-application behavior.
- `focused_window_policy`: existing focus-loss / out-of-policy behavior.
- `rapid_application_switching`: new detector for too many focused-window changes.
- `unexpected_process`: new detector for newly observed processes outside known or allowed lists.

New incidents keep the existing server-compatible shape:

- `incident_id`
- `policy_version`
- `rule_id`
- `rule_name`
- `severity`
- `status`
- `summary`
- `event_at`
- `needs_evidence`

The new detectors also include event-specific metadata such as `event_type`,
`recent_switches`, `switch_count`, `pid`, `process_name`, and raw process lists.

## How To Test

From this folder:

```powershell
python -m unittest test_client_incidents.py
python -m py_compile incidents.py test_client_incidents.py
```

