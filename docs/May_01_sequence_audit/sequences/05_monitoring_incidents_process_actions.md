# Monitoring, Incidents, And Process Actions

This page explains how the client watches the exam environment and how the server reacts when something suspicious is reported.

## In One Sentence

The client continuously watches processes, focused windows, and hardware; when a policy rule is violated, it reports the incident immediately and uploads evidence in the background.

## Who Is Involved

- `ProcessMonitor`, `FocusedWindowMonitor`, and `HardwareMonitor`.
- `ClientIncidentEngine`, which turns monitor snapshots into incidents.
- `client.ws_client`, which reports incidents and uploads evidence.
- `server.handlers`, which stores incidents and applies automatic actions.
- Server GUI/settings code, which lets operators classify process behavior.

## Monitoring: What Happens

When the WebSocket session starts, the client starts three monitors:

- Process monitor: watches running processes and writes process diffs/full snapshots.
- Focused-window monitor: watches the active window and writes changes.
- Hardware monitor: watches hardware-related snapshots and changes.

Timer changes are also written into these logs so evidence can be read with exam state context.

## Incident Detection

Each monitor snapshot is passed through `ClientIncidentEngine`.

The engine checks rules such as:

- blacklisted process.
- known/unknown process definitions.
- unexpected process.
- focused-window policy.
- rapid application switching.

If a rule opens or escalates an incident, the client sends an `incident_report`.

## Evidence Handling

Incidents that need evidence now use a two-step flow:

1. The client immediately sends the incident with `evidence_status="pending"`.
2. In the background, the client gathers process reports, replay when available, hardware/focus snapshots, and builds an incident bundle.
3. The client uploads that bundle as an `incident_bundle` artifact.
4. The client sends a second incident update with `status="evidence_uploaded"` and the artifact path.

If evidence upload fails, the client sends `status="evidence_failed"` and schedules a retry.

## Server Response

When the server receives an opened incident:

1. It adds client id, login id, and received timestamp.
2. It stores the incident.
3. If policy says this violation should pause the exam, the server moves the user to `violation_paused`.
4. If configured, it can request process actions such as kill PID, pause, kick, or ban.
5. It sends `incident_received`.

Evidence-only updates do not rerun auto actions. They only attach artifact information to the active incident.

## Process Decision Flow

The server GUI can build a process database from saved definitions and incident history.

An operator can:

- mark a process as known.
- add it to the blacklist.
- classify it by executable path or directory.
- apply live actions such as kill, pause, kick, or ban.

When policy changes, the server broadcasts updates and clients apply the new rules immediately.

## Common Failure Clues

- Incident appears without evidence: evidence may still be pending or upload failed.
- Violation did not pause the exam: check rule severity and `auto_violation_pause`.
- Kill PID did not work: check `kill_process_result` and OS permission errors.
- Unexpected process noise: review known process names and known directory paths.

## Tests

- `tests/unit/test_client_incidents.py`
- `tests/unit/test_client_incident_reporting.py`
- `tests/unit/test_server_handlers.py`
- `tests/unit/test_process_database.py`
- `tests/unit/test_settings_service.py`
- `tests/unit/test_focused_window_monitor.py`
- `tests/unit/test_process_monitor.py`
