# Third Iteration

This folder is organized by owner while keeping Baris's original flat imports working.

## Owner Folders

- `baris/`
  - `activity_monitor.py`
  - `payload_builder.py`
  - `monitor_loop.py`
  - `server_core.py`
  - `school_service.py`
- `naz/`
  - `security_layer.py`
  - `auth_client.py`
  - `instructor_auth.py`
  - `test_naz_modules.py`
- `engin/`
  - `network_sender.py`
  - `discovery.py`
  - `runtime_logging.py`
- `mert/`
  - `db_manager.py`
- `ahmet/`
  - `protocol.py`
  - `events.py`
- `mytask/`
  - `incident_engine.py`
  - `process_users.py`
  - `mytask_payload_adapter.py`

## Compatibility Shims

The small `.py` files in the root of this folder are only import bridges. For example:

- root `security_layer.py` imports from `naz.security_layer`
- root `protocol.py` imports from `ahmet.protocol`
- root `payload_builder.py` imports from `baris.payload_builder`
- root `incident_engine.py` imports from `mytask.incident_engine`

This lets copied teammate files keep their original imports, such as `from security_layer import ...`, without editing their contents.

## Mytask Coverage

The mytask adapter supports:

- blacklisted processes
- process-owner/user filtering
- focused-window policy
- rapid application switching
- unexpected newly started processes
- legacy idle warnings
- legacy exam-closed and focus-lost flags

`MytaskPayloadAdapter.build_from_snapshot()` returns Baris-compatible fields:

- `student_id`
- `student_name`
- `hostname`
- `timestamp`
- `active_window`
- `open_apps`
- `exam_running`
- `idle_seconds`
- `flags`

It also adds richer fields:

- `incidents`
- `processes`

## Checks

Run from this folder:

```powershell
python -m unittest discover -s tests
python -m py_compile baris/activity_monitor.py baris/payload_builder.py baris/monitor_loop.py baris/server_core.py naz/security_layer.py naz/auth_client.py naz/instructor_auth.py engin/network_sender.py engin/discovery.py engin/runtime_logging.py mert/db_manager.py ahmet/protocol.py ahmet/events.py mytask/incident_engine.py mytask/process_users.py mytask/mytask_payload_adapter.py
```
