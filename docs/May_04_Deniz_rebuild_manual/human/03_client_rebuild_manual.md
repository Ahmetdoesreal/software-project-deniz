# Client Rebuild Manual

## Client Responsibilities

The client runtime owns local student behavior:

- Discover or directly connect to the server.
- Authenticate and obtain a persistent session UUID.
- Download exam configuration and optional ZIP materials.
- Maintain a WebSocket session and reconnect after connection loss.
- Launch and control the timer/submission GUI.
- Start monitors and collect runtime evidence.
- Apply server policy locally and report incidents.
- Save replay artifacts on request.
- Package and upload final submission.
- Exit only after accepted submission or explicit terminal condition.

The client must never be the authority for final exam state. It follows server `session_state`, `sync_time`, `pause_exam`, `resume_exam`, and `finish_exam` events.

## Entry Point: `client.main`

`client.main` is the orchestration entrypoint. It should:

1. Configure runtime logging to `data/logs/client`.
2. Parse CLI arguments.
3. Validate network and reconnect arguments.
4. Create `RecorderManager`.
5. Create `IncidentBuffer`.
6. Enter a reconnect loop.

Important CLI arguments:

- `--login-id`: student login ID.
- `--password`: raw password or token string, depending on auth mode.
- `--id`: target server ID for discovery.
- `--host`: explicit server host; skips discovery.
- `--port`: server port.
- `--timeout`: discovery timeout.
- `--reconnect`: delay before reconnect attempts.
- `--no-record`: disable replay recorder.
- `--check-login`: validate login and exit.
- `--ui {tk,qt}`: timer/submission GUI backend.
- `--ipc-transport {auto,stdio,ws}`: local runtime-to-GUI IPC.
- `--ad-domain`: enables AD validation mode.
- `--auth-secret`: shared auth secret for server token verification and secured event context.

## Reconnect Loop

The main loop should continue until final submission succeeds:

1. Resolve server target:
   - If `--host` exists, use it.
   - If `--check-login`, perform one discovery attempt and fail fast.
   - Otherwise keep discovering until a matching server appears.
2. Build base URL and WebSocket URL.
3. Perform login.
4. Start or resync replay recorder for returned session UUID.
5. Fetch exam config and exam files.
6. Run WebSocket session through `run_ws`.
7. If `run_ws` returns submission complete, exit.
8. On connection error, sleep `--reconnect` seconds and repeat.
9. In `finally`, stop recorder.

This design keeps the client resilient to server restarts and transient network failures while preserving the same session UUID.

## Authentication Flow

Authentication is split between manager preflight and runtime server login.

Manager preflight can perform:

- CATS school auth using `requests` and `beautifulsoup4`.
- Windows AD credential validation.
- Server login check by running `client.main --check-login`.

Runtime `/login` does the authoritative server-side validation. In AD token mode, the client sends a token generated from login ID, secret, and a 60-second time window. The server validates the current, previous, and next window to tolerate clock skew.

## Exam Preparation

Before opening WebSocket:

1. `client.auth.perform_login` posts `/login`.
2. `client.exam.fetch_exam_prep` gets `/exam/config`.
3. If `has_files` is true, download `/exam/files`.
4. `client.auth.check_health` verifies `/health`.

Exam files are intentionally expected as a ZIP from the server. Directory serving is not implemented.

## WebSocket Runtime: `client.ws_client`

`run_ws(ws_url, base_url, session_uuid, auth_secret, recorder, gui_ui, ipc_transport, incident_buffer)` should:

1. Build a `SessionSecurityContext` if an auth secret is supplied.
2. Launch the timer GUI process.
3. Start local IPC server or stdio pipe for GUI control.
4. Create monitor instances.
5. Create `ClientIncidentEngine`.
6. Open aiohttp WebSocket connection.
7. Start listener and input/GUI command tasks.
8. Apply policy and session events from server.
9. Send monitor telemetry and incidents.
10. Coordinate final submission.
11. Return `True` only when submission is accepted.

Important objects:

- `TimerGuiBridge`: sends timer commands to GUI and receives GUI commands.
- `ReplaySaveQueue`: serializes replay save requests and prevents optional requests from starving mandatory ones.
- `ClientIncidentEngine`: local policy evaluator.
- `IncidentBuffer`: records unacknowledged incidents for resend.

## Timer And Submission GUI

The GUI must be a child process rather than code inside the WebSocket loop. This keeps UI event loops from blocking network work.

GUI commands from runtime to window are line-oriented strings in stdio mode and IPC channel payloads in WebSocket IPC mode:

- `SYNC:<seconds>`
- `PAUSE:<message>`
- `RESUME:<seconds>`
- `END:`
- `RESET:`
- `ERROR:<message>`
- `OPEN_FINISH:<message>`
- `UPLOAD_OK:<message>`
- `UPLOAD_ERROR:<message>`
- `UPLOAD_STEP:<message>`

GUI commands back to runtime:

- `{"cmd": "start_exam"}`
- `{"cmd": "finish_exam", "path": "<selected-file>"}`

The GUI should prevent accidental close during managed mode. In standalone/manual mode, close should be allowed. On Windows installed/windowed builds, stdio may be absent, so GUI code must use safe stdio helpers and switch to standalone close behavior if local IPC cannot connect.

## Client Monitors

### Process Monitor

Purpose:

- Periodically collect process list.
- Include PID, executable name, owner username when available, and process path when available.
- Write JSONL process history and a current process report.
- Feed `ClientIncidentEngine.observe_processes`.

Required outputs:

- `data/client/<uuid>/processes.jsonl`
- `data/client/<uuid>/process_report.json`

### Focused Window Monitor

Purpose:

- Poll the active foreground window.
- Record initial snapshot, changes, and periodic full snapshots.
- Export current snapshot for incident and submission evidence.
- Feed focused-window and rapid-application-switching policy logic.

Required outputs:

- `focused_window.jsonl`
- `focused_window_snapshot.json`

On stop, write a final focused-window snapshot so shutdown and tests do not depend on timing of the last periodic poll.

### Hardware Monitor

Purpose:

- Capture hardware state and selected changes.
- Export current hardware snapshot for incidents and submission.

Required outputs:

- `hardware_snapshot.json`
- `hardware_changes.jsonl`

### Idle Monitor

Purpose:

- Poll OS idle seconds.
- Emit snapshots with `idle_seconds`, timestamp, event type, and severity.
- Feed `ClientIncidentEngine.observe_idle`.

Required outputs:

- `idle_monitor.jsonl`

Windows implementation should use user32 last-input APIs. Non-Windows fallback may use available platform tools where present.

### Replay Recorder

Purpose:

- Run FFmpeg to maintain recent screen recording segments.
- Save requested replay windows as MP4 when possible.
- Fall back to MPEG-TS when MP4 stitching fails or is incomplete.
- Stop FFmpeg carefully with quit, terminate, and kill escalation.

FFmpeg stdin is third-party process control and must remain outside the app IPC abstraction.

## Incident Engine

The client incident engine receives server policy and local monitor observations. It emits incident dictionaries. Each incident should include:

- `incident_id`
- `policy_version`
- `rule_id`
- `rule_name`
- `source`
- `severity`
- `status`
- `summary`
- `event_type`
- `event_at`
- `timestamp`
- `needs_evidence`
- rule-specific details such as PID, process name, window title, idle seconds, or process path.

Rules handled locally:

- `process_blacklist`
- `process_definitions`
- `process_path_clarification`
- `unexpected_process`
- `focused_window_policy`
- `rapid_application_switching`
- `idle_policy`

When an opened incident needs evidence, the client should:

1. Send incident immediately.
2. Capture focused window and hardware snapshots.
3. Request/save a replay if recorder is active.
4. Build incident bundle.
5. Upload artifact to `/client/artifact`.
6. Send `evidence_uploaded` or `evidence_failed` update.
7. Retry failed evidence upload in background where appropriate.

## Submission Flow

Final submission starts when:

- Server sends `finish_exam`.
- Server sends `exam_end`.
- Student manually presses finish after allowed state.
- Console/manual command `finish <path>` is accepted.

Implementation steps:

1. Prevent concurrent submissions.
2. Notify GUI upload is starting.
3. Record timer transition `submission_upload`.
4. Export hardware snapshot.
5. Export focused-window snapshot.
6. Request best-effort final replay.
7. Build local submission bundle with `build_submission_bundle`.
8. Compute SHA-256.
9. Upload multipart field `archive` to `/exam/submission?id=<uuid>`.
10. On success, show GUI success, record submitted state, and exit.
11. On failure, show actionable error and allow retry.

Submission bundle layout:

- `student_submission/<original-file-name>`
- `manifest.json`
- `runtime/process_report.json`
- `runtime/processes.jsonl`
- `runtime/focused_window_snapshot.json`
- `runtime/focused_window.jsonl`
- `runtime/hardware_snapshot.json`
- `runtime/hardware_changes.jsonl`
- optional replay files and incident evidence.

The manifest should include per-file checksums so the server or reviewer can verify what was uploaded.

## Minimal Client Pseudocode

```python
async def main_loop(args):
    recorder_manager = RecorderManager(args.record)
    incident_buffer = IncidentBuffer()
    while True:
        host, port = await resolve_server_target(args)
        base_url = f"http://{host}:{port}"
        try:
            uuid = await perform_login(base_url, args.login_id, args.password)
            await recorder_manager.sync_session(uuid)
            await fetch_exam_prep(base_url, uuid)
            await check_health(base_url)
            done = await run_ws(
                f"ws://{host}:{port}/ws?id={uuid}",
                base_url,
                uuid,
                args.auth_secret or "",
                recorder_manager.recorder,
                gui_ui=args.ui,
                ipc_transport=args.ipc_transport,
                incident_buffer=incident_buffer,
            )
            if done:
                return
        except network_errors:
            await asyncio.sleep(args.reconnect)
```

