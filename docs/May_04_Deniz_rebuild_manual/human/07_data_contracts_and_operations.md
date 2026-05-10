# Data Contracts And Operations

## HTTP Contracts

### `GET /health`

Response:

```json
{
  "status": "ok",
  "server_id": "default",
  "clients_connected": 0
}
```

Use for preflight, health checks, and post-login sanity checks.

### `POST /login`

Request:

```json
{
  "login_id": "student1",
  "password": "password-or-token"
}
```

Success:

```json
{
  "status": "ok",
  "uuid": "session-uuid"
}
```

Common failures:

- 400 invalid JSON or missing fields.
- 403 not allowed, banned, invalid token.
- 409 already active, already finished, duplicate login, IP guard conflict.

### `GET /exam/config`

Response:

```json
{
  "exam_duration_seconds": 2700,
  "has_files": true
}
```

### `GET /exam/files`

Response is the configured ZIP file. Missing file returns 404. Directory path returns 400.

### `POST /exam/submission?id=<uuid>`

Multipart fields:

- `archive`: required file field.
- `sha256`: required checksum field from client uploader.

Success:

```json
{
  "status": "ok",
  "message": "Submission uploaded successfully.",
  "path": "data/server/submissions/<uuid>/file.zip",
  "size_bytes": 12345
}
```

### `POST /client/artifact?id=<uuid>`

Multipart fields:

- `artifact`: required file field.
- `sha256`: required checksum field.
- `kind`: optional artifact kind.
- `metadata`: optional JSON string.

Success:

```json
{
  "status": "ok",
  "message": "Artifact uploaded successfully.",
  "path": "data/server/artifacts/<uuid>/<kind>/file.zip",
  "size_bytes": 12345
}
```

## LAN WebSocket Envelope

All LAN WebSocket messages are JSON strings from `common.protocol.encode`:

```json
{
  "event": "session_state",
  "data": {},
  "checksum": "sha256"
}
```

The checksum is SHA-256 of a canonical JSON object containing `event` and `data`. `protocol.decode` rejects missing or mismatched checksums. Reliability metadata fields such as `seq`, `session_id`, `buffered`, and `queued_at` are tolerated when added around buffered messages.

## Secured LAN Events

Selected event payloads are HMAC-signed and optionally encrypted by `common.security`:

- `exam_policy`
- `policy_update`
- `session_state`
- `incident_report`
- `kill_process`
- `pause_exam`
- `resume_exam`

Secured payload fields:

- `_secured`
- `timestamp`
- `nonce`
- `encrypted`
- `signature`
- `ciphertext` or `payload`

The receiving side must verify signature, timestamp replay window, nonce uniqueness, encryption validity, and decoded JSON object shape.

## LAN Event Inventory

Server to client:

- `welcome`: session UUID and server ID.
- `echo`: ping response.
- `time`: wall-clock time broadcast.
- `error`: protocol or command error.
- `exam_policy`: initial policy.
- `policy_update`: changed policy.
- `savescreen`: request replay save.
- `sync_time`: authoritative remaining seconds.
- `session_state`: authoritative state and pause metadata.
- `pause_exam`: pause timer.
- `resume_exam`: resume timer.
- `exam_end`: timer depleted.
- `get_processes`: request immediate process report.
- `process_blacklist`: direct blacklist entries and version.
- `incident_received`: acknowledgement for incident report.
- `kill_process`: request PID termination.
- `finish_exam`: request final upload.

Client to server:

- `ping`: test message.
- `client_info`: computer name and metadata.
- `policy_applied`: policy apply acknowledgement.
- `start_exam`: student requested start.
- `process_catch`: legacy blacklist catch report.
- `client_monitor_event`: structured monitor telemetry.
- `incident_report`: incident lifecycle event.
- `kill_process_result`: PID termination result.

## Local IPC Contract

Local IPC envelope:

```json
{
  "type": "event",
  "role": "timer_gui",
  "channel": "timer.command",
  "id": "hex",
  "reply_to": "",
  "seq": 0,
  "data": {}
}
```

Channels:

- `manager.console_command`
- `server.dashboard_state`
- `dashboard.command`
- `client.timer_state`
- `timer.command`
- `process.lifecycle`

Security:

- Bind `127.0.0.1`.
- Use random token.
- Reject non-loopback peer.
- Reject invalid token.
- Validate JSON object, channel, and data object.

## Persistent Storage

Server:

- `data/server/server_users.json`
- `data/server/process_blacklist.txt`
- `data/server/exam_policy.json`
- `data/server/process_definitions.json`
- `data/server/incidents.jsonl`
- `data/server/session_audit.jsonl`
- `data/server/submissions/<uuid>/`
- `data/server/artifacts/<uuid>/<kind>/`
- `data/logs/server/*.jsonl`

Client:

- `data/client/<uuid>/process_report.json`
- `data/client/<uuid>/processes.jsonl`
- `data/client/<uuid>/focused_window_snapshot.json`
- `data/client/<uuid>/focused_window.jsonl`
- `data/client/<uuid>/hardware_snapshot.json`
- `data/client/<uuid>/hardware_changes.jsonl`
- `data/client/<uuid>/idle_monitor.jsonl`
- `data/client/<uuid>/exam_state.jsonl`
- `data/client/<uuid>/submission_bundle/`
- `data/client/<uuid>/incident_bundles/`
- `data/client/<uuid>/recordings/`
- `data/logs/client/*.jsonl`

## Setup

Supported target is Windows. Python 3.10+ is recommended. Required Python dependencies are listed in `May_04_Deniz/requirements.txt`:

- `aiohttp`
- `psutil`
- `cryptography`
- `requests`
- `beautifulsoup4`
- `PySide6`

FFmpeg must be installed and available on PATH for replay recording. `setup.py` checks Python packages and attempts FFmpeg install through `winget` when available.

## Test Strategy

Minimum validation after changes:

```powershell
python -m compileall -q .
python -m unittest discover -s tests
```

Targeted suites:

- Protocol and security: `tests/unit/test_protocol_integrity_fields.py`, `tests/unit/test_security.py`.
- Server state and handlers: `tests/unit/test_server_state.py`, `tests/unit/test_server_handlers.py`.
- Settings and process database: `tests/unit/test_settings_service.py`, `tests/unit/test_process_database.py`.
- Client incidents: `tests/unit/test_client_incidents.py`, `tests/unit/test_client_incident_reporting.py`.
- Monitors: `tests/unit/test_process_monitor.py`, `tests/unit/test_focused_window_monitor.py`.
- Replay: `tests/unit/test_replay_recorder.py`, `tests/unit/test_replay_save_queue.py`.
- IPC: `tests/unit/test_ipc_ws.py`, `tests/integration/test_local_ipc.py`.
- Discovery and main loops: `tests/integration/test_discovery.py`, `tests/integration/test_client_main.py`.
- Upload contracts: `tests/unit/test_upload_multipart_order.py`, `tests/unit/test_transfers.py`.

## Manual Smoke Checklist

Server:

1. Run `python server_launcher.py --ui tk`.
2. Run `python server_launcher.py --ui qt`.
3. Launch server with `--gui`.
4. Open policy settings.
5. Confirm idle policy fields appear in Tk and Qt.
6. Save settings and verify policy version changes.
7. Run `/startexam`, `/pauseexam`, `/resumeexam`, `/finishexam`.

Client:

1. Run `python client_launcher.py --ui tk`.
2. Run `python client_launcher.py --ui qt`.
3. Validate login preflight.
4. Start runtime and timer GUI.
5. Request start.
6. Trigger a controlled policy incident.
7. Confirm incident appears on dashboard.
8. Finish exam and upload file.
9. Confirm server stores submission bundle.

IPC:

1. Run with `--ipc-transport auto`.
2. Confirm manager-to-runtime command delivery.
3. Confirm dashboard receives server state.
4. Confirm timer GUI receives sync/pause/finish commands.
5. Run direct CLI without manager and confirm stdio/manual mode still works.

Windows installed/windowed:

1. Launch Qt server dashboard without console.
2. Launch Qt client timer without console.
3. Confirm no crash from missing stdin/stdout/stderr.
4. Confirm crash log files are created only when needed and handles do not destabilize the app.

## Rebuild Checklist

Use this list as the acceptance plan for a new implementation:

1. Shared protocol can encode/decode and reject corrupted checksum.
2. Secured payloads sign, encrypt when possible, reject replayed nonce, and reject stale timestamp.
3. Server can start, announce, and reject duplicate server IDs.
4. `/login`, `/exam/config`, `/exam/files`, `/exam/submission`, `/client/artifact`, and `/ws` exist.
5. Server state persists users, policy, blacklist, definitions, incidents, and submissions.
6. Client can discover, login, fetch config/files, connect WebSocket, and reconnect.
7. Server sends welcome, policy, blacklist, session state, and timer sync.
8. Client applies policy and acknowledges version.
9. Process, focused-window, hardware, idle, and replay modules produce expected files.
10. Incident engine emits opened/resolved/evidence events.
11. Server records incidents and applies configured actions.
12. Dashboard shows clients, incidents, settings, process database, and can send commands.
13. Timer GUI shows waiting/running/paused/upload states and can send start/finish.
14. Final submission is bundled, checksummed, uploaded, stored, and marks user submitted.
15. Local WebSocket IPC works on loopback with token rejection tests.
16. Stdio fallback works for terminal/manual workflows.
17. Full test suite passes.

