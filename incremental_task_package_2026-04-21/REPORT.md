# Client Monitoring Extension Audit Report

## Scope
Task audited:

> Extend the client monitoring module so that it performs event and violation detection. Instead of only collecting window and process lists, add a client-side layer that tags events such as opening prohibited applications, losing focus, rapid application switching, or starting unexpected processes. Produce structured outputs containing raw logs together with event type, timestamp, and severity level. The goal is not only to collect data, but to generate meaningful violation events that the server can interpret.

Audit date: 2026-04-21
Workspace: `C:\Users\Deniz\Desktop\6064\software-project`

## Final Status
**Completed** for the requested monitoring/violation pipeline, with policy-driven behavior (some rules are configurable and can be disabled by policy).

## Requirement Matrix
| Requirement | Status | Evidence |
|---|---|---|
| Detect prohibited applications | Completed | `client/incidents.py` opens/resolves `process_blacklist` incidents from process snapshots; incidents are sent via `ws_client.py` as `incident_report`. |
| Detect losing focus / out-of-policy focus | Completed | `client/incidents.py` enforces `focused_window_policy` with debounce (`open_after_consecutive`, `resolve_after_consecutive`). |
| Detect rapid app switching (10 changes / 60s) | Completed | `client/incidents.py` implements time-window detection for `rapid_application_switching`; defaults include `max_switches=10`, `window_seconds=60`. |
| Detect unexpected process starts | Completed | `client/incidents.py` implements `unexpected_process` detection and resolution based on known/allowed process sets. |
| Focus poll every 1 second | Completed | `client/ws_client.py` and `focused_window_monitor/core.py` use top-level constants and initialize monitor with 1s polling. |
| Write focus JSONL as differences, periodic full JSON snapshot every 60 checks | Completed | `focused_window_monitor/core.py` writes change entries to `focused_window.jsonl` and full snapshot to `focused_window_snapshot.json` every configured interval. |
| Send focus status to server every 5 seconds | Completed | `client/ws_client.py` throttles monitor telemetry send interval with `FOCUSED_WINDOW_SERVER_SEND_INTERVAL_SECONDS = 5.0`. |
| Warning signal to server for rapid switching threshold | Completed | `client/incidents.py` emits warning incidents; `ws_client.py` forwards incident payloads to server; `server/handlers.py` stores/relays incidents. |
| Extra warning indicator on server dashboard | Completed | `server_gui.py` computes and displays active warning count in stats bar (`Active Warnings`). |
| Structured outputs include event type, timestamp, severity | Completed | Focus logs include `event_type`/`timestamp`/`severity`; process raw logs include `event_type`/`severity`; incident payloads include `event_type`/`timestamp`/`severity`. |
| Configurable values at top / no hardcoded intervals | Completed | Top-level constants in `focused_window_monitor/core.py`, `client/ws_client.py`, and rapid-switch defaults in `client/incidents.py`; server policy config in `server/state.py`. |

## Implemented Data Flow
1. Client monitors continuously:
   - Process snapshots from `custommodules/process_monitor/core.py`
   - Focused window snapshots from `custommodules/focused_window_monitor/core.py`
2. Client-side rule engine (`client/incidents.py`) tags events and produces incident lifecycle events (`opened`, `resolved`) with severity and metadata.
3. Client transport (`client/ws_client.py`) sends:
   - `incident_report` for violations/warnings
   - `client_monitor_event` for periodic focused-window telemetry
4. Server consumes events in `server/handlers.py`, updates user state, persists incidents, and relays concise status to GUI.
5. Dashboard (`server_gui.py`) surfaces incidents and active warnings.

## Key Output Artifacts
- Client runtime:
  - `data/client/<session_uuid>/focused_window.jsonl`
  - `data/client/<session_uuid>/focused_window_snapshot.json`
  - `data/client/<session_uuid>/processes.jsonl`
- Server runtime:
  - `data/server/incidents.jsonl`
- Wire payloads:
  - `client_monitor_event`
  - `incident_report`

## Validation Performed
Executed tests:
- `tests.unit.test_client_incidents`
- `tests.unit.test_focused_window_monitor`
- `tests.unit.test_server_state`
- `tests.unit.test_server_handlers`
- `tests.unit.test_process_monitor`

Result: **PASS** (19 tests)
Raw log copy: `validation/monitoring_test_results_clean.txt`

## Files Included In This Report Package
- `files_changed/` contains changed implementation/test files for this task.
- `files_used/` contains supporting files used for verification/context.
- `files_generated/` and `schemas/` contain generated structured report artifacts and example payload schemas.
- `manifest.json` indexes copied artifacts with hashes.
