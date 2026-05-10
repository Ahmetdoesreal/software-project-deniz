# System Architecture

## Product Purpose

`May_04_Deniz` is an exam-control and monitoring system intended for a controlled LAN environment. The server is run by an operator or instructor. Each student runs a client manager that authenticates the student, launches the runtime, displays the exam timer, records selected runtime evidence, reports policy incidents, and uploads the final submission.

The system is not a single monolithic GUI. It is a multi-process application. Manager windows launch CLI runtime processes. Runtime processes may launch companion GUI windows. Local manager-to-runtime and runtime-to-GUI communication is app-owned IPC. LAN server-to-client communication is a separate WebSocket protocol.

This separation is central to the design:

- LAN traffic handles exam state, student policy, monitoring telemetry, incident reports, process actions, artifacts, and submission upload.
- Local IPC handles same-machine control between parent and child processes, such as manager commands, dashboard state updates, and timer window commands.
- FFmpeg stdin control is not treated as app IPC because it controls a third-party child process.

## Top-Level Processes

Server side:

1. `server_launcher.py` chooses Tk or Qt manager UI.
2. The server manager launches `python -m server.main`.
3. `server.main` creates an aiohttp app through `server.app.create_app`.
4. If `--gui` is active, the server runtime launches `python -m server.gui`.
5. The dashboard GUI receives server state snapshots and sends dashboard commands.

Client side:

1. `client_launcher.py` chooses Tk or Qt manager UI.
2. The client manager collects login credentials and optional server target settings.
3. The manager can run preflight checks and `client.main --check-login`.
4. The manager launches `python -m client.main`.
5. `client.main` logs in, prepares exam files, starts the replay recorder, and calls `client.ws_client.run_ws`.
6. `client.ws_client` launches `python -m client.gui`.
7. The timer/submission GUI receives timer state and sends start/finish/upload commands.

## Package Responsibilities

### `common`

The `common` package is the contract layer. It must stay free of server-only or client-only side effects. Rebuild it first because both sides depend on it.

- `protocol.py`: encodes and decodes JSON event envelopes with SHA-256 checksums.
- `events.py`: names LAN WebSocket events and provides constructors.
- `security.py`: wraps selected event payloads in HMAC-signed and optionally encrypted secured envelopes.
- `discovery.py` and `discovery_v2.py`: UDP discovery and duplicate-server detection.
- `server_ports.py`: port helpers.
- `process_definitions.py`: normalized process identity, process definition matching, action normalization, and stable process keys.
- `process_users.py`: current Windows process username helpers.
- `ipc_ws.py`: loopback-only authenticated WebSocket IPC for local parent/child process communication.
- `stdio_compat.py`: safe stdio helpers for console and Windows windowed builds.
- `runtime_logging.py`: JSONL runtime logging, stdout/stderr teeing, and async exception logging.
- `manager_support.py` and `manager_support_qt.py`: close guards and launcher UI behavior shared by manager windows.

### `server`

The `server` package owns authoritative exam state and operator actions.

- `main.py`: parses CLI args, validates them, optionally resets persisted state, and runs aiohttp.
- `app.py`: creates the aiohttp app, registers routes, starts and stops background tasks.
- `handlers.py`: implements HTTP endpoints and LAN WebSocket event handling.
- `state.py`: persists and normalizes users, policy, blacklist, process definitions, incidents, and audit-oriented state.
- `session_state.py`: provides the canonical session state machine.
- `tasks.py`: implements background time sync, console/IPC command processing, dashboard state building, policy broadcasts, process actions, and global exam commands.
- `settings_service.py`: validates settings changes, normalizes policy patches, updates process definitions, and writes audit entries.
- `shutdown.py`: coordinates graceful server shutdown by requesting final client artifacts before cleanup.
- `submissions.py`: builds safe server paths for submissions and artifacts.
- `ui/`: Tk and Qt dashboard implementations plus policy settings windows and dashboard helper modules.

### `client`

The `client` package owns student runtime behavior.

- `main.py`: orchestrates discovery, login, exam preparation, reconnection, recorder lifetime, and `run_ws`.
- `auth.py`: performs `/login` and health checks.
- `exam.py`: fetches exam config and exam files.
- `ws_client.py`: owns the LAN WebSocket runtime, timer GUI process, monitors, incident engine, replay save queue, artifact upload, and submission flow.
- `incidents.py`: evaluates policy rules locally and emits incident lifecycle payloads.
- `incident_buffer.py` and `outbound_buffer.py`: keep unacknowledged events reliable across reconnects.
- `transfers.py`: creates submission and incident bundles, computes checksums, and uploads multipart files.
- `submission.py`: builds file previews for GUI display.
- `exam_state.py`: writes timer/session transition logs.
- `custommodules/`: process, focused-window, hardware, idle, and replay recorder modules.
- `ui/`: Tk and Qt timer/submission windows.

### `launcher_ui`

The launcher UI package contains server and client manager windows. Managers should be treated as supervisors: they collect configuration, launch runtime child processes, display logs/status, and expose start/stop controls. They should not duplicate server state or client monitoring logic.

### `ui`

The shared `ui` package contains visual theme, widgets, styles, background effects, and reusable assets for Qt/Tk surfaces.

## Architectural Rules To Preserve

1. The server is the only authority for exam state, remaining time, bans, submissions, and policy version.
2. The client can detect and report policy incidents, but it cannot decide final punishment. Server policy and operator commands decide pause, kill, kick, or ban.
3. Local GUI state is derived state. A GUI can request commands, but the runtime process owns the action.
4. Policy is normalized before storage and versioned from the client-facing payload, not from arbitrary admin input.
5. All LAN WebSocket messages must use `common.protocol.encode` and `common.protocol.decode`.
6. Sensitive LAN events should pass through `common.security.protect_wire_message` and `decode_wire_message` when a session context exists.
7. Local IPC must bind only to `127.0.0.1`, use a random token, and fall back to stdio for manual terminal workflows.
8. Long-running monitor and recorder operations must not block the WebSocket receive loop.
9. Uploads must use checksums and size limits.
10. Persisted files must be safe to read on restart and tolerant of missing or old schema fields.

## Dependency Model

The core runtime dependencies are:

- `aiohttp` for HTTP, LAN WebSocket, local WebSocket IPC, and multipart uploads.
- `psutil` for process and hardware monitoring.
- `cryptography` for optional protected event encryption.
- `requests` and `beautifulsoup4` for CATS school authentication preflight.
- `PySide6` for Qt UI mode.
- FFmpeg as an external executable for replay recording.

Tk is provided by the Python installation on supported Windows environments. Qt is optional at runtime but required for `--ui qt`.

## Data Flow Summary

The normal student data flow is:

1. Client manager authenticates locally enough to decide whether to launch runtime.
2. Client runtime discovers server or uses explicit host/port.
3. Client posts login credentials or an AD HMAC token to `/login`.
4. Server returns a persistent session UUID.
5. Client fetches exam config and exam file ZIP.
6. Client connects to `/ws?id=<uuid>`.
7. Server sends welcome, policy, blacklist, and session state.
8. Client starts monitoring modules and reports telemetry/incidents.
9. Server records incidents and may send process actions.
10. Server finishes exam or timer reaches end.
11. Client builds submission ZIP, uploads it, and exits after success.

## Rebuild Principle

When rebuilding from this manual, treat every module as a contract boundary. Implement the simplest correct version of each contract first, then enrich behavior. For example, implement `protocol.encode/decode` and basic WebSocket events before implementing secured payloads. Implement process monitor snapshots before process definition decisions. Implement submission upload before adding final replay capture. This preserves testability and prevents GUI work from hiding incomplete runtime behavior.

