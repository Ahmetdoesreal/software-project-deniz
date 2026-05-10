# Runtime Sequences

## 1. Server Startup And Shutdown

1. Operator opens `server_launcher.py` or runs `python -m server.main`.
2. Server validates CLI args and optionally clears `server_users.json` with `--reset`.
3. Duplicate-server discovery check runs for the configured server ID.
4. aiohttp app starts routes and background tasks.
5. UDP discovery announcer starts.
6. Console reader listens to stdin and, when manager env exists, local WebSocket IPC.
7. On shutdown, server requests process reports, requests replay saves, waits the grace period, stops announcer, closes dashboard, and stops local IPC.

## 2. Client Startup, Login, And WebSocket Policy Sync

1. Client manager collects login ID/password and optional advanced server target.
2. Manager preflight runs CATS and AD checks.
3. Client validates server reachability with `--check-login`.
4. Managed client process starts.
5. Client discovers server or uses explicit host/port.
6. Client posts `/login` and receives session UUID.
7. Client fetches `/exam/config`, `/exam/files`, and `/health`.
8. Client opens `/ws?id=<uuid>`.
9. Server sends `welcome`, `exam_policy`, `process_blacklist`, and current `session_state`.
10. Client starts monitors, applies policy, sends `client_info`, and waits for start.

## 3. Exam Timer And Session State

1. Student presses start in timer GUI or types `start`.
2. Client sends `start_exam`.
3. Server accepts only if global start is enabled and state allows it.
4. Server sets user state to `running`, sends `session_state` and `sync_time`.
5. Time broadcaster updates running timers and sends periodic `sync_time`.
6. Pause/resume/admin actions update session state and push timer changes.
7. Disconnect while running moves the user to `disconnected_paused`.
8. Reconnect resumes automatically when policy allows it.

## 4. Monitoring, Incidents, And Process Actions

1. Client monitors process list, focused window, hardware, idle state, and replay.
2. Client incident engine applies policy rules locally.
3. Client sends `incident_report` immediately when an incident opens or resolves.
4. If evidence is needed, client uploads an incident bundle asynchronously.
5. Server records incident state, updates dashboard snapshots, and may apply configured actions.
6. Server can send `kill_process`; client replies with `kill_process_result`.
7. Dashboard process decisions can update policy, process definitions, and live actions.

## 5. Replay, Savescreen, And Artifacts

1. Server sends `savescreen` or `get_processes`.
2. Client queues replay save requests with priorities.
3. Replay recorder saves recent segments through FFmpeg, with timeout fallback.
4. Client uploads generated replay/process artifacts to `/client/artifact`.
5. Server stores artifacts under `data/server/artifacts/<uuid>/<kind>/`.

## 6. Final Submission

1. Server sends `finish_exam` or global `/finishexam` moves users to awaiting submission.
2. Client opens the protected finish window.
3. Student selects a file.
4. Client validates and previews the file.
5. Client saves best-effort replay evidence.
6. Client stages selected file and runtime logs into `submission_package_<timestamp>/`.
7. Client writes `manifest.json`, creates `submission_bundle_<timestamp>.zip`, computes SHA-256, and uploads to `/exam/submission`.
8. Server verifies state, size, checksum, and stores the bundle.
9. Server marks the user submitted and sends updated session state.
10. Client shows upload success and exits.

## 7. Settings

1. Operator edits settings in dashboard or files.
2. GUI sends `dashboard.command` or console command.
3. Server normalizes policy, blacklist, or process definitions.
4. Server saves files and appends audit entries.
5. Server broadcasts `policy_update` and `process_blacklist` when needed.
6. Clients apply policy and respond with `policy_applied`.

## 8. Local IPC

1. Parent process starts a loopback IPC server and random token.
2. Parent passes IPC URL/token/role/transport through env vars.
3. Child connects to `ws://127.0.0.1:<port>/ipc?token=<token>`.
4. Parent and child exchange channel-specific envelopes.
5. Existing stdin/stdout paths remain as compatibility fallback.
