# LLM Rebuild Context Pack

## Identity

Project: `May_04_Deniz`

Purpose: LAN exam server/client with monitoring, policy incidents, replay/artifact capture, final submission upload, dashboard and timer GUIs, and loopback-only local IPC.

Current date of this documentation snapshot: 2026-05-10.

## Non-Negotiable Architecture

- Server owns authoritative session state, policy, submissions, incidents, and commands.
- Client owns local monitoring, evidence collection, GUI timer, and upload attempts.
- LAN WebSocket protocol is `common.protocol` plus `common.events`.
- Local parent/child IPC is `common.ipc_ws` plus stdio fallback.
- Local IPC must bind only to `127.0.0.1` and require random token.
- GUI processes must tolerate missing stdio on Windows windowed builds.
- FFmpeg stdin control is not app IPC.

## Main Entry Points

Server:

- `server_launcher.py`
- `python -m server.main`
- `python -m server.gui`

Client:

- `client_launcher.py`
- `python -m client.main`
- `python -m client.gui`

## Shared Contracts

`common.protocol.encode(event, data)` returns JSON with `event`, `data`, and checksum. `decode(raw)` returns `(event, data)` or `("__decode_error__", {"reason": ...})`.

`common.events` defines LAN events:

- server to client: `welcome`, `echo`, `time`, `error`, `exam_policy`, `policy_update`, `savescreen`, `sync_time`, `session_state`, `pause_exam`, `resume_exam`, `exam_end`, `get_processes`, `process_blacklist`, `incident_received`, `kill_process`, `finish_exam`.
- client to server: `ping`, `client_info`, `policy_applied`, `start_exam`, `process_catch`, `client_monitor_event`, `incident_report`, `kill_process_result`.

`common.security` protects selected events with HMAC, nonce, timestamp replay window, and optional Fernet encryption.

`common.ipc_ws` defines:

- env vars: `EXAM_LOCAL_IPC_URL`, `EXAM_LOCAL_IPC_TOKEN`, `EXAM_LOCAL_IPC_ROLE`, `EXAM_LOCAL_IPC_TRANSPORT`.
- transport choices: `auto`, `stdio`, `ws`.
- envelope fields: `type`, `role`, `channel`, `id`, `reply_to`, `seq`, `data`, optional `error`.
- channels: `manager.console_command`, `server.dashboard_state`, `dashboard.command`, `client.timer_state`, `timer.command`, `process.lifecycle`.

## Server Build Summary

Implement `server.state.ServerState` first:

- load/save users
- allowed users
- process blacklist/version
- exam policy config normalization
- process definitions/version
- current client-facing policy/version
- incidents and active incidents
- settings bundle import/export

Implement `server.session_state`:

- states: `waiting`, `running`, `admin_paused`, `disconnected_paused`, `violation_paused`, `awaiting_submission`, `submitted`, `banned`.
- methods: derive, ensure defaults, set state, reconnect policy, running timer, pause source, display name.

Implement `server.app.create_app`:

- add routes `/health`, `/login`, `/exam/config`, `/exam/files`, `/exam/submission`, `/client/artifact`, `/ws`.
- start tasks: time broadcaster, console reader, UDP announcer, duplicate guard, optional GUI.
- cleanup: shutdown routine, cancel tasks, stop announcer, stop GUI IPC.

Implement `server.handlers`:

- HTTP validation and upload size/checksum validation.
- WebSocket connect/reject/register/send initial policy.
- Dispatch client events.
- On disconnect freeze timer if running.

Implement `server.tasks`:

- command parser.
- dashboard snapshots.
- policy/blacklist broadcasts.
- timer broadcaster.
- process actions.
- GUI launch and IPC.

## Client Build Summary

Implement `client.main`:

- parse args.
- resolve server target by host or discovery.
- login.
- fetch exam prep.
- start recorder by session.
- run WebSocket session.
- reconnect on network errors until submission complete.

Implement `client.ws_client`:

- launch timer GUI with IPC.
- open WebSocket.
- decode/dispatch server events.
- send start, incident, telemetry, kill result, policy applied.
- coordinate monitors.
- run replay queue.
- handle finish upload.

Implement monitors:

- process monitor: process list JSONL/report.
- focused-window monitor: current window JSONL/snapshot and final snapshot on stop.
- hardware monitor: hardware snapshot/changes.
- idle monitor: idle seconds JSONL.
- replay recorder: FFmpeg segments and replay save.

Implement `client.incidents`:

- apply policy.
- process blacklist.
- process definitions.
- path clarification.
- unexpected process.
- focused window debounce.
- rapid switching.
- idle warning/critical.

Implement transfers:

- build submission ZIP with manifest.
- build incident ZIP.
- upload multipart with `sha256`.
- retry transient upload errors.

## Policy Rules

Rules in current policy list:

- `process_blacklist`: enabled default true, severity violation, entries, process usernames, auto pause, remote kill.
- `focused_window_policy`: focused-window allow/block lists, contains/exact matching, debounce counters.
- `rapid_application_switching`: max switches, window seconds, observations.
- `idle_policy`: warn seconds, critical seconds, warning/violation behavior.
- `unexpected_process`: known/allowed names, known directories, baseline behavior.
- `process_definitions`: normalized definitions with status/actions.
- `process_path_clarification`: path mismatch evidence rule.

## Critical Sequences

Server startup:

`server.main` -> `create_app` -> startup tasks -> announcer -> console reader -> optional dashboard.

Client startup:

manager -> preflight -> `client.main` -> discovery -> `/login` -> `/exam/config` -> `/exam/files` -> `/ws`.

Policy:

server `current_exam_policy` -> `exam_policy`/`policy_update` -> client `apply_policy` -> `policy_applied`.

Timer:

GUI start -> local IPC -> client `start_exam` -> server state running -> `session_state` + `sync_time` -> GUI sync.

Incident:

monitor snapshot -> incident engine -> `incident_report` -> server persist/ack/action -> async evidence upload -> evidence update.

Submission:

finish event -> GUI file selection -> local IPC -> bundle -> checksum upload -> server mark submitted -> client exits.

IPC:

parent starts loopback token server -> child env -> child connects -> envelopes by channel -> stdio fallback.

