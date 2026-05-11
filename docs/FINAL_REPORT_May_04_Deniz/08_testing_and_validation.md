# 08. Testing And Validation

## 1. Validation Strategy

The test strategy combines unit, integration, system, compile, and manual smoke validation. Unit tests cover pure logic such as protocol integrity, settings normalization, incident matching, buffer restore, safe file handling, and UI refresh helpers. Integration tests cover multi-module behavior such as client main flow, discovery, and local IPC. System tests cover higher-level authentication and communication scenarios.

The final validation commands are:

```powershell
python -m compileall -q .
python -m unittest discover -s tests
```

These commands are run from `May_04_Deniz/`.

## 2. Automated Test Inventory

### Unit Tests

| Test file | Coverage area |
| --- | --- |
| `test_auth_bypass.py` | Temporary CATS/AD bypass commands and status behavior. |
| `test_client_incident_reporting.py` | Client incident reporting behavior and required runtime fields. |
| `test_client_incidents.py` | Incident engine, policy matching, focused-window rules, process definitions, incident rules, browser New Tab whitelist, CATS-style configurable whitelist, and Unicode title normalization. |
| `test_exam_files.py` | Safe exam material extraction, desktop target selection, manifest behavior, and unsafe ZIP rejection. |
| `test_focused_window_monitor.py` | Focused-window snapshot capture, sanitization, and monitor logging behavior. |
| `test_incident_buffer.py` | Buffered incident restore, stable seq behavior, and pending evidence retry metadata. |
| `test_incident_rules.py` | Incident rule normalization, matching, priority, whitelist behavior, and incident-to-rule conversion. |
| `test_ipc_ws.py` | IPC envelope validation, token rejection, loopback-only behavior, and transport selection. |
| `test_manager_support.py` | Manager support behavior and console handling. |
| `test_process_database.py` | Process definition database, incident rules database, settings persistence, and decision application. |
| `test_process_monitor.py` | Process monitor snapshots, blacklist matching, reports, and logging. |
| `test_projector.py` | Projector-safe payloads, generic notification mapping, `/projector`, and `/projector/events`. |
| `test_protocol_integrity_fields.py` | Checksum behavior with reliability metadata. |
| `test_replay_recorder.py` | Replay segment capture, save behavior, MP4 checks, fallback, timeout, and cleanup. |
| `test_replay_save_queue.py` | Replay save queue ordering, expiry, capacity, and callbacks. |
| `test_row_refresh.py` | Stable row snapshots, changed-row detection, and reorder preservation. |
| `test_savescreen_event.py` | Savescreen event shape and request metadata. |
| `test_security.py` | Secured payload signing/encryption/decode behavior. |
| `test_server_app.py` | App creation and route/background assumptions. |
| `test_server_handlers.py` | Server handlers, protected malformed-process errors, close message behavior, and incident handling. |
| `test_server_main.py` | Server CLI argument validation. |
| `test_server_shutdown.py` | Graceful shutdown behavior. |
| `test_server_state.py` | State defaults, policy normalization, session policy, and reconnect resume behavior. |
| `test_server_tasks.py` | Admin commands, finish-exam banned skip, close message trimming, and task helpers. |
| `test_settings_service.py` | Settings update service and policy mutation behavior. |
| `test_setup.py` | Setup and dependency assumptions. |
| `test_transfers.py` | Submission/artifact bundle construction and runtime file collection. |
| `test_upload_multipart_order.py` | Multipart parser behavior for upload field ordering. |

### Integration Tests

| Test file | Coverage area |
| --- | --- |
| `integration/test_client_main.py` | Client main loop and session setup integration behavior. |
| `integration/test_discovery.py` | Server discovery and duplicate detection behavior. |
| `integration/test_local_ipc.py` | Manager-to-CLI, server-dashboard, and client-timer IPC behavior. |

### System Tests

| Test file | Coverage area |
| --- | --- |
| `system/test_auth.py` | Authentication system behavior. |
| `system/test_comm.py` | Communication system behavior. |

## 3. Requirements Acceptance Matrix

| Requirement group | Primary tests |
| --- | --- |
| `FR-SRV-*` | `test_server_app`, `test_server_handlers`, `test_server_tasks`, `test_server_state`, `test_server_main`, `test_server_shutdown` |
| `FR-CLI-*` | `integration/test_client_main`, `test_exam_files`, `test_client_incident_reporting` |
| `FR-MON-*` | `test_process_monitor`, `test_focused_window_monitor`, `test_client_incidents` |
| `FR-INC-*` | `test_incident_rules`, `test_process_database`, `test_client_incidents` |
| `FR-POL-*` | `test_server_state`, `test_settings_service`, `test_process_database` |
| `FR-REC-*` | `test_incident_buffer`, `test_client_incident_reporting`, `integration/test_client_main` |
| `FR-SUB-*` | `test_transfers`, `test_upload_multipart_order`, `test_server_handlers` |
| `FR-AUTH-*` | `test_auth_bypass`, `system/test_auth` |
| `FR-IPC-*` | `test_ipc_ws`, `integration/test_local_ipc` |
| `FR-UI-*` | `test_row_refresh`, `test_process_database` plus manual GUI smoke |
| `FR-PROJ-*` | `test_projector` |
| `NFR-SEC-*` | `test_security`, `test_ipc_ws`, `test_exam_files` |
| `NFR-PRIV-*` | `test_projector` |
| `NFR-REL-*` | `test_incident_buffer`, `test_client_incident_reporting`, `test_replay_recorder` |

## 4. Manual Smoke Checklist

### Server

- Start server with Tk manager and direct CLI.
- Start server with Qt manager if PySide6 is installed.
- Open dashboard through manager and `/gui`.
- Verify `/health` returns server status.
- Open `http://<server>:<port>/projector`.
- Run `/clients`, `/exam`, `/authstatus`, and `/help`.

### Client

- Start client manager in Tk.
- Start client manager in Qt if PySide6 is installed.
- Validate login with check-login mode.
- Connect to server by discovery.
- Connect to server by explicit host/port.
- Verify timer UI opens and receives ready state.
- Verify Exam Folder button appears after materials are extracted.

### Exam Flow

- Run `/startexam`.
- Start exam from client timer UI.
- Verify timer counts down and dashboard remaining time updates smoothly.
- Pause and resume one client.
- Add time to one client.
- Run `/finishexam`.
- Submit an archive from client UI.
- Confirm server stores submission and dashboard shows submitted state.

### Incident Flow

- Trigger a process blacklist or process definition incident.
- Confirm incident appears in dashboard history.
- Confirm active warning/violation counts update.
- Save an incident as an incident rule.
- Apply an incident rule decision.
- Verify policy update reaches client.
- Verify New Tab whitelist suppresses browser New Tab incidents.
- Add a CATS title whitelist rule and verify matching browser title suppression.

### Reconnect Flow

- Start exam and disconnect server network/WebSocket.
- Confirm client UI shows reconnecting/paused state.
- Confirm process/focused-window/hardware/idle/exam-state logs continue growing.
- Generate an incident while disconnected.
- Reconnect.
- Confirm buffered incident flushes and evidence retry completes.

### Projector

- Open `/projector` at 1280x720 and 1024x768.
- Trigger exam start, warning, violation, resolution, finish/submission states.
- Confirm text is readable and notification messages are generic.
- Confirm no names, login IDs, UUIDs, IPs, paths, process names, window titles, or evidence details appear.

## 5. Regression Focus Areas

- `/finishexam` must not forgive banned users.
- WebSocket close reasons must stay below close-frame byte limits without UTF-8 splitting.
- Secured malformed process-catch errors must remain protected.
- Titlebar normalization must handle invisible Unicode and localized browser New Tab titles.
- Dashboard list refresh must not teleport scroll or clear selection every second.
- Client reconnect must not stop local logging.
- Incident buffer restore must not duplicate queued entries.
- Exam ZIP extraction must not delete unmarked user folders.
- Auth bypass must expire and remain server-authorized.
- Projector payload must remain public-safe.

## 6. Validation Record Location

The executed validation for this package is recorded in `VALIDATION.md`.
