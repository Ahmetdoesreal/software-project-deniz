# Server Rebuild Manual

## Server Responsibilities

The server is the authoritative owner of:

- Allowed users and persistent login UUIDs.
- Connected WebSocket clients.
- Exam phase and per-student session state.
- Remaining exam time and pause reasons.
- Exam policy and process blacklist.
- Process definitions and operator process decisions.
- Incident logs and active incident state.
- Submission bundles and runtime artifacts.
- Operator command execution.
- Dashboard state snapshots.
- Graceful shutdown requests.

The server should be written so that the HTTP routes, WebSocket routes, command handlers, and GUI dashboard all operate on the same `ServerState` object. Avoid copying state into independent GUI models. The dashboard should render snapshots; commands should be sent back to the runtime.

## Entry Point: `server.main`

Implement `server.main` as a thin command-line adapter:

1. Configure runtime logging to `data/logs/server`.
2. Parse CLI arguments.
3. Validate port, interval, announce interval, duration, upload size limits, and server ID.
4. Optionally clear persisted user state when `--reset` is supplied.
5. Create the aiohttp app with `server.app.create_app(args)`.
6. Run it with `web.run_app`.

Important CLI arguments:

- `--id`: logical server ID used by discovery.
- `--host`: bind host, default `0.0.0.0`.
- `--port`: HTTP and WebSocket port, default `8080`.
- `--interval`: timer broadcast interval in seconds.
- `--announce`: UDP discovery beacon interval.
- `--exam-duration`: duration in minutes.
- `--exam-files`: optional path to a ZIP file.
- `--max-submission-mb`: upload size cap for final submissions.
- `--max-artifact-mb`: upload size cap for runtime artifacts.
- `--ui {tk,qt}`: companion dashboard backend.
- `--ipc-transport {auto,stdio,ws}`: local manager/dashboard IPC mode.
- `--gui`: launch companion dashboard from the runtime.
- `--reset`: clear used IDs and timers on startup.
- `--auth-secret`: shared secret for AD HMAC token validation and secured message context.

`server.main` should not contain route logic. Its job is startup policy, validation, and running the app.

## App Creation: `server.app.create_app`

`create_app(args)` should:

1. Load persisted users through `state.load_users()`.
2. Create `web.Application(client_max_size=512 * 1024 * 1024)`.
3. Store runtime settings in `app[...]`.
4. Construct `ServerShutdownRoutine(app)`.
5. Register HTTP routes and WebSocket route.
6. Register startup and cleanup callbacks.

Required app keys:

- `server_id`, `host`, `port`
- `server_identity_hosts`
- `broadcast_interval`, `announce_interval`
- `exam_duration`, `exam_files`
- `settings_state`
- `exam_phase`
- `exam_start_enabled`
- `shutdown_grace_seconds`
- `max_submission_bytes`, `max_artifact_bytes`
- `shutdown_routine`
- `gui_module`, `project_dir`, `python_executable`
- `launch_gui_on_start`, `gui_ui`
- `auth_secret`
- `ipc_transport`

Register these routes:

- `GET /health`
- `POST /login`
- `GET /exam/config`
- `GET /exam/files`
- `POST /exam/submission`
- `POST /client/artifact`
- `GET /ws`

Startup tasks:

- Install asyncio exception logging.
- Start `time_broadcaster(app)`.
- Start `console_reader(app)`.
- Start UDP `ServerAnnouncer`.
- Start duplicate-server guard.
- Optionally launch dashboard GUI.

Cleanup tasks:

- Run `ServerShutdownRoutine`.
- Cancel broadcaster, console reader, and duplicate guard.
- Stop UDP announcer.
- Kill dashboard child process if still running.
- Stop local IPC server if active.

## Server State Model

`server.state.ServerState` is the central data owner. A rebuild should implement it before routes.

Persistent data:

- `data/server/server_users.json`: users, UUIDs, session flags, submission metadata, ban state, timer fields.
- `data/server/process_blacklist.txt`: direct blacklist process names.
- `data/server/exam_policy.json`: policy rules except embedded process definitions.
- `data/server/process_definitions.json`: normalized process decision definitions.
- `data/server/incidents.jsonl`: append-only incident events.
- `data/server/session_audit.jsonl`: settings and action audit trail.
- `data/server/submissions/<uuid>/`: uploaded final bundles.
- `data/server/artifacts/<uuid>/<kind>/`: uploaded runtime artifacts and metadata.

In-memory data:

- `clients`: active WebSocket clients keyed by session UUID.
- `users_db`: login ID to persistent user record.
- `allowed_users`: configured allowed login IDs.
- `process_blacklist`, `process_blacklist_version`
- `exam_policy_config`
- `process_definitions`, `process_definitions_version`
- `incidents`, `active_incidents`
- dashboard GUI child process references.

### User Defaults

Every user record should contain:

- `uuid`
- `exam_started`, `exam_finished`
- `start_time`, `end_time`
- `paused_remaining_seconds`
- `session_state`
- `session_state_reason`
- `last_disconnect_at`
- `blocking_incident_id`
- `blocking_rule_id`
- `violation_forgiven_*`
- `banned`
- `submitted_at`, `submission_name`, `submission_path`, `submission_size_bytes`
- metadata such as IP, computer name, policy version, and last action.

Call `state.ensure_user_defaults(user)` whenever a user is loaded, logged in, reconnected, or mutated by a command.

## Session State Machine

Use these canonical states:

- `waiting`: user has not started the exam.
- `running`: timer is actively decrementing.
- `admin_paused`: operator paused the student.
- `disconnected_paused`: running student disconnected; timer is frozen.
- `violation_paused`: policy incident paused the student.
- `awaiting_submission`: exam finished; upload is required.
- `submitted`: final upload accepted.
- `banned`: student is not allowed to continue.

State transitions should be made through `session_state.set_state`. This method updates the canonical state and synchronizes legacy flags such as `exam_started`, `exam_finished`, `admin_paused`, and `banned`.

Reconnect logic:

1. If state is `disconnected_paused` and policy `auto_resume_on_reconnect` is true, move to `running`.
2. If state is `awaiting_submission`, reconnect and immediately request upload.
3. If state is any paused state, reconnect paused and send pause state.
4. If state is `submitted` or `banned`, reject or prevent further runtime progress.

## HTTP Routes

### `GET /health`

Return a JSON health object:

```json
{
  "status": "ok",
  "server_id": "default",
  "clients_connected": 3
}
```

Use this for manager preflight and client post-login sanity checks.

### `POST /login`

Input:

```json
{
  "login_id": "student1",
  "password": "raw-password-or-hmac-token"
}
```

Required logic:

1. Reject invalid JSON.
2. Validate non-empty `login_id` and `password`.
3. Reject users not in `allowed_users`.
4. If `auth_secret` is configured, validate HMAC token with the current 60-second time window and one neighboring window on each side.
5. Reject finished, submitted, banned, duplicate active, or IP-guard-blocked logins.
6. If this is a new valid user, allocate and persist UUID.
7. Return `{"status": "ok", "uuid": "<session_uuid>"}`.

### `GET /exam/config`

Return:

```json
{
  "exam_duration_seconds": 2700,
  "has_files": true
}
```

The route is intentionally small. The client uses it before opening the runtime WebSocket.

### `GET /exam/files`

Return configured exam ZIP with `web.FileResponse`. Reject missing files with 404. Reject directories because directory serving is intentionally not implemented.

### `POST /exam/submission?id=<uuid>`

Accept multipart field `archive`.

Required validations:

1. Query `id` must be a valid session UUID.
2. User must exist and not be banned.
3. User must have started, or the global exam phase must be finished.
4. User must not already have a submission.
5. Multipart must include file field `archive`.
6. Saved byte count must be greater than zero.
7. Archive must be supported ZIP or TAR.
8. Uploaded SHA-256 field must match the saved file.
9. Size must not exceed `max_submission_bytes`.

After success:

1. Set session state to `submitted`.
2. Fill submission metadata on user record.
3. Save users.
4. Return status, message, relative path, and size.

### `POST /client/artifact?id=<uuid>`

Accept multipart field `artifact` plus optional `kind`, `metadata`, and `sha256`.

Required validations:

1. Query `id` must be a valid session UUID.
2. User must exist and not be banned.
3. Multipart must include file field `artifact`.
4. File must be non-empty.
5. Checksum must match.
6. Size must not exceed `max_artifact_bytes`.

Store under `data/server/artifacts/<uuid>/<kind>/` and write a sibling metadata JSON containing client ID, login ID, kind, saved time, relative path, size, checksum, and parsed metadata.

## WebSocket Route: `GET /ws?id=<uuid>`

The WebSocket route is the runtime channel for a single student session.

Connection handshake:

1. Validate `id`.
2. Reject banned, submitted, finished-before-start, and duplicate active clients.
3. Prepare `web.WebSocketResponse`.
4. Add client record to `state.clients`.
5. Register IP ownership through `ip_guard`.
6. Build session security context from session UUID and `auth_secret`.
7. Send `welcome`.
8. Send `exam_policy`.
9. Send `process_blacklist`.
10. Send `session_state`.
11. If needed, send `finish_exam`, `sync_time`, or `pause_exam` based on current session state.

Receive loop:

1. For each text message, decode through `security.decode_wire_message`.
2. On decode failure, send `error`.
3. Dispatch known events:
   - `ping`
   - `client_info`
   - `start_exam`
   - `process_catch`
   - `policy_applied`
   - `client_monitor_event`
   - `incident_report`
   - `kill_process_result`
4. Unknown events return `error`.

Disconnect handling:

1. Remove client from `state.clients`.
2. If user was `running`, set `disconnected_paused` with frozen remaining time.
3. If user was `waiting`, mark last action as disconnected.
4. Save users.

## Operator Commands

Commands are accepted from console stdin and from local manager/dashboard IPC. Implement them in `server.tasks.handle_admin_command`.

Core commands:

- `/clients`: print or refresh connected clients.
- `/exam`: print exam phase and timer state.
- `/startexam`: enable exam start globally and notify waiting clients.
- `/finishexam`: move active clients to awaiting submission and request finish upload.
- `/addtime <target> <minutes>`: add time to a client or all clients.
- `/pauseexam <target> [reason]`: set admin pause.
- `/resumeexam <target>`: resume from admin/disconnect pause when legal.
- `/forgiveviolation <target> [incident_id]`: clear violation pause.
- `/savescreen <target>`: request replay save and artifact upload.
- `/killpid <target> <pid>`: request client process termination.
- `/kick <target>`: disconnect client.
- `/ban <target>` and `/unban <login>`: update ban state.
- `/editpolicy`, `/applypolicy`: open and reload policy file.
- `/editdefinitions`, `/applydefinitions`: open and reload process definitions.
- `/exportsettings <path>`, `/importsettings <path>`: move settings bundles.
- `/remembersettings <on|off>`: update session policy.

Targets should accept login ID, UUID, short UUID, or `all` where the command supports it.

## Time Broadcaster

`time_broadcaster(app)` is a long-running task. On each tick:

1. Calculate elapsed time for running users.
2. If time remains, send `sync_time`.
3. If time reaches zero, set `awaiting_submission` and send `exam_end`/`finish_exam`.
4. Update dashboard state.

Time should be derived from stored start/end timestamps and paused remaining seconds, not from GUI clocks.

## Settings Service

`settings_service.py` exists to centralize settings validation and audit. Do not let UI code directly mutate `ServerState`.

Important methods:

- `get_settings_snapshot(state, app=None)`: returns policy, current client-facing policy, blacklist, versions, definitions version, operator defaults, session settings, and runtime settings.
- `update_exam_policy(state, patch, actor=...)`: deep-merges a policy patch, normalizes it, handles optional embedded process definitions, saves files, and appends audit.
- `update_process_blacklist(state, action, entries, actor=...)`: add, remove, or replace direct blacklist entries.
- `update_known_processes`, `update_allowed_processes`, and similar helpers: update list fields inside policy rules.
- `apply_incident_policy_action`: convert an incident to a process definition or policy action.
- `update_session_settings`: patch session policy.
- `update_runtime_settings`: mutate runtime `exam_duration` and `exam_files`.

The service returns `SettingsResult` so GUI and console paths can show consistent messages.

## Dashboard Snapshots

The dashboard should receive derived snapshots, not raw internal objects. A snapshot should include:

- `server_info`: server ID, port, exam phase, policy version, counts, files, duration.
- `settings`: full settings snapshot.
- `clients`: connected and known students with state, remaining time, last action, IP, focus/process metadata, and blocking incident fields.
- `incidents`: active and recent incidents.
- `process_database`: process definition rows and live evidence.

Build snapshots in `server.tasks` because it can combine state, connected clients, and app runtime settings.

## Shutdown Routine

Server shutdown should not abruptly discard useful evidence. `ServerShutdownRoutine.run()` should:

1. Request process reports from connected clients.
2. Request replay saves from connected clients.
3. Wait a configurable grace period.
4. Continue cleanup even if some clients do not respond.
5. Stop local IPC and child GUI processes.

## Minimal Server Pseudocode

```python
def main():
    args = parse_args()
    validate_args(args)
    if args.reset:
        state.reset_users()
    app = create_app(args)
    web.run_app(app, host=args.host, port=args.port)

def create_app(args):
    state.load_users()
    app = web.Application(client_max_size=MAX)
    fill_app_runtime_keys(app, args)
    register_routes(app)
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    return app

async def websocket_handler(request):
    client_id = request.query["id"]
    reject_invalid_or_duplicate_client(client_id)
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    register_client(client_id, ws)
    await send_initial_policy_and_state(ws, client_id)
    try:
        async for message in ws:
            event, data = decode_wire_message(message.data, security_context(client_id))
            await dispatch_client_event(event, data)
    finally:
        unregister_client_and_freeze_timer_if_running(client_id)
```

