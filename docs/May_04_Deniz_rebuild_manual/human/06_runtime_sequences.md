# Runtime Sequences

This document describes behavior as ordered runtime stories. Use it to rebuild orchestration and tests. Each sequence identifies the actor, state owner, transport, and expected side effects.

## Sequence 1: Server Startup

Actors: operator, server manager, server runtime, aiohttp app, discovery announcer, optional dashboard.

1. Operator starts `server_launcher.py` or runs `python -m server.main`.
2. If using a manager, manager collects server ID, port, duration, exam ZIP, UI mode, and IPC mode.
3. Manager starts a local IPC server when WebSocket IPC is selected or available.
4. Manager launches `server.main` as a child process.
5. `server.main` configures runtime logging.
6. `server.main` parses CLI args and validates them.
7. If `--reset` is supplied, persisted user/session state is cleared.
8. `server.app.create_app(args)` loads users, creates aiohttp app, fills runtime keys, and registers routes.
9. aiohttp startup runs `start_background_tasks`.
10. Startup installs asyncio exception logging.
11. `time_broadcaster(app)` starts.
12. `console_reader(app)` starts.
13. UDP `ServerAnnouncer` starts broadcasting server ID, host, and port.
14. `duplicate_server_guard(app)` starts and checks for same server ID on another host/port.
15. If `--gui` is active, runtime launches `server.gui` with selected UI backend.
16. Runtime sends dashboard state snapshots through local IPC or stdio.
17. Dashboard renders initial empty clients, incidents, settings, and server info.

Critical state owner: `server.state.state` plus `app[...]`.

Failure behavior:

- Invalid CLI args should fail before network bind.
- Duplicate server ID should trigger graceful exit.
- Dashboard launch failure should not kill the server unless manager policy requires it.

## Sequence 2: Client Manager Login And Runtime Launch

Actors: student, client manager, CATS auth, AD auth, server preflight, client runtime.

1. Student opens `client_launcher.py`.
2. Manager shows login ID/password and optional advanced server settings.
3. Manager may run CATS authentication.
4. Manager may run Windows AD authentication and generate HMAC token.
5. Manager runs `client.main --check-login` with selected server ID or host/port.
6. `client.main --check-login` discovers server or uses direct host.
7. Runtime posts `/login`.
8. Server validates allowed user, token, duplicate active session, ban state, submission state, and IP guard.
9. Runtime exits success if credentials are valid.
10. Manager launches full `client.main` child process.
11. Manager passes UI mode, IPC mode, login credentials/token, server ID/host, and auth secret.
12. Manager captures runtime stdout/stderr for logs and status.

Critical state owner: manager owns launch state only. Server owns actual login acceptance.

Failure behavior:

- CATS or AD preflight failure should block launch.
- Server preflight failure should display a clear reason.
- Runtime launch failure should keep manager open for retry.

## Sequence 3: Client Runtime Login, Prep, And WebSocket Connect

Actors: client runtime, server HTTP routes, replay recorder, WebSocket runtime.

1. Runtime enters reconnect loop.
2. If `--host` exists, runtime uses direct host and port.
3. Otherwise runtime discovers server by ID using UDP discovery with local fallback.
4. Runtime builds `base_url`.
5. Runtime posts `/login`.
6. Server returns session UUID.
7. Runtime starts or resyncs replay recorder under `data/client/<uuid>/`.
8. Runtime fetches `/exam/config`.
9. If config says files exist, runtime downloads `/exam/files`.
10. Runtime checks `/health`.
11. Runtime calls `run_ws` with `ws://<host>:<port>/ws?id=<uuid>`.
12. `run_ws` launches timer GUI.
13. `run_ws` opens LAN WebSocket.
14. Server accepts WebSocket and registers client.
15. Server sends `welcome`.
16. Server sends `exam_policy`.
17. Server sends `process_blacklist`.
18. Server sends `session_state`.
19. Server may also send `sync_time`, `pause_exam`, or `finish_exam` based on reconnect state.
20. Client starts monitor modules after policy/session setup is ready.

Critical state owner: server owns UUID and session state. Client owns local recorder and evidence paths.

## Sequence 4: Policy Sync And Apply

Actors: server state, WebSocket, client incident engine, monitors.

1. Server builds current policy through `state.current_exam_policy()`.
2. Server includes `policy_version` derived from stable JSON hash.
3. Server sends `exam_policy` on initial connect.
4. Client decodes and optionally unprotects event.
5. Client calls `ClientIncidentEngine.apply_policy(policy)`.
6. Client normalizes rules by `rule_id`.
7. Client resets local incident debounce state.
8. Client extracts process definitions from the `process_definitions` rule.
9. Client sends `policy_applied` with version and `ok=true`.
10. Server records `applied_policy_version` on the user.
11. Later settings changes trigger `policy_update`.
12. Client repeats apply/ack flow.

Failure behavior:

- Missing policy version or invalid rules list causes `policy_applied ok=false`.
- Server dashboard should show policy apply status where available.

## Sequence 5: Student Starts Exam

Actors: timer GUI, client runtime, server WebSocket handler, session state.

1. Timer GUI shows waiting state.
2. Student presses Request Start.
3. GUI sends `{"cmd": "start_exam"}` to runtime through local IPC or stdout.
4. Runtime sends LAN event `start_exam`.
5. Server verifies global `exam_start_enabled` or accepts according to configured start behavior.
6. Server verifies user is allowed and not terminal.
7. Server sets state to `running`.
8. Server calculates remaining seconds from configured duration.
9. Server sends `session_state running`.
10. Server sends `sync_time`.
11. Client updates local timer state.
12. Runtime sends `SYNC:<seconds>` and `RESUME:<seconds>` or equivalent to GUI.
13. GUI begins visual countdown.

Critical state owner: server. GUI countdown is presentation only and is corrected by `sync_time`.

## Sequence 6: Pause, Resume, Disconnect, And Reconnect

Pause:

1. Operator clicks pause or enters `/pauseexam <target>`.
2. Server command handler resolves target.
3. Server calculates current remaining seconds.
4. Server sets `admin_paused` with reason.
5. Server sends `pause_exam` and `session_state`.
6. Client records timer transition.
7. Client GUI shows paused state.

Resume:

1. Operator enters `/resumeexam <target>` or dashboard command.
2. Server verifies state is resumable.
3. Server sets `running`.
4. Server sends `resume_exam`, `session_state`, and `sync_time`.
5. Client GUI resumes countdown.

Disconnect:

1. WebSocket closes unexpectedly.
2. Server unregisters client.
3. If user was running, server sets `disconnected_paused` with frozen remaining time.
4. Runtime reconnect loop sleeps and discovers/connects again.

Reconnect:

1. Client logs in again and receives same UUID.
2. Client opens WebSocket.
3. Server sees `disconnected_paused`.
4. If `auto_resume_on_reconnect`, server sets `running` and sends resume state.
5. Otherwise server sends paused state and waits for operator.

## Sequence 7: Monitoring And Incident Detection

Actors: monitors, client incident engine, server incident handler, dashboard.

1. Process monitor polls process list.
2. Focused-window monitor polls active window.
3. Hardware monitor records current hardware state.
4. Idle monitor polls idle seconds.
5. Each monitor writes local JSONL or snapshot files.
6. Client feeds observations into `ClientIncidentEngine`.
7. Engine opens or resolves incidents based on current policy.
8. Runtime sends each incident as `incident_report`.
9. Server persists incident in `incidents.jsonl`.
10. Server updates `active_incidents`.
11. Server sends `incident_received`.
12. Runtime clears incident buffer entry when acknowledgement is received.
13. Dashboard snapshot includes updated incident list and client summary.

Critical rule: incident reporting must not wait for evidence upload.

## Sequence 8: Incident Evidence Upload

Actors: client runtime, focused-window monitor, hardware monitor, replay save queue, transfers, server artifact route.

1. Runtime notices incident with `needs_evidence=true`.
2. Runtime schedules background evidence task.
3. Task exports focused-window snapshot.
4. Task exports hardware snapshot.
5. Task requests replay save if recorder is active.
6. Replay save queue serializes request with priority.
7. Task builds incident bundle ZIP with manifest and evidence.
8. Task uploads ZIP to `/client/artifact?id=<uuid>` with `kind=incident_evidence`.
9. Server validates UUID, checksum, size, and file field.
10. Server stores artifact and metadata JSON.
11. Client sends incident update `evidence_uploaded` with artifact path.
12. If upload fails, client sends or schedules `evidence_failed`.

Failure behavior:

- Replay save timeout should not prevent incident update forever.
- Missing optional evidence should be reflected in manifest or logs.
- Failed upload can be retried.

## Sequence 9: Process Decision From Dashboard

Actors: dashboard, server settings service, process definitions, connected clients.

1. Dashboard shows a process row or incident row.
2. Operator opens process decision dialog.
3. Operator chooses status: whitelist, blacklist, warning, or unknown.
4. Operator chooses match scope: name, path, or directory.
5. Operator chooses actions: ban, kick, pause exam, kill PID.
6. Dashboard sends `dashboard.command` with process decision payload.
7. Server normalizes the process definition.
8. Server saves it to `process_definitions.json`.
9. Server may apply immediate actions to matching active clients.
10. Server broadcasts updated policy to clients.
11. Clients apply policy and acknowledge version.
12. Future process observations use the saved definition.

Critical detail: process identity must be normalized before stable key generation, otherwise duplicate definitions will appear for equivalent paths.

## Sequence 10: Save Screen And Replay Artifact

Actors: operator, server, client replay queue, transfers.

1. Operator sends `/savescreen <target>` or dashboard action.
2. Server sends LAN `savescreen` event with request ID.
3. Client enqueues replay save request.
4. Replay recorder asks FFmpeg to stitch recent segments.
5. If MP4 succeeds and has required metadata, keep MP4.
6. If MP4 fails or lacks moov atom, fall back to MPEG-TS.
7. Client uploads replay as `/client/artifact`.
8. Server stores under artifact kind.
9. Dashboard shows artifact activity through logs and incident metadata where applicable.

## Sequence 11: Final Exam Finish And Submission

Actors: server, client runtime, timer/submission GUI, transfers, submission route.

1. Operator sends `/finishexam`, a per-client finish command, or timer reaches zero.
2. Server sets active users to `awaiting_submission`.
3. Server sends `finish_exam`.
4. Client opens protected finish window.
5. Student chooses a file.
6. GUI previews file.
7. Student clicks upload.
8. GUI sends `{"cmd": "finish_exam", "path": "<file>"}`.
9. Runtime prevents duplicate upload.
10. Runtime exports final hardware and focused-window snapshots.
11. Runtime requests final replay where possible.
12. Runtime stages student file and runtime evidence.
13. Runtime writes manifest and ZIP.
14. Runtime uploads ZIP to `/exam/submission?id=<uuid>`.
15. Server validates session, duplicate submission, archive, size, and checksum.
16. Server stores file and marks user `submitted`.
17. Server returns success.
18. Runtime tells GUI upload succeeded.
19. GUI shows success and closes.
20. `run_ws` returns submission complete.
21. `client.main` exits.

## Sequence 12: Settings Update

Actors: dashboard, server command handler, settings service, state, clients.

1. Operator opens policy settings.
2. Dashboard displays latest `settings` snapshot.
3. Operator edits runtime, session, policy, blacklist, idle, or process definition fields.
4. Dashboard validates local obvious fields such as positive integers.
5. Dashboard sends `cmd=save_settings`.
6. Server command handler calls settings service methods.
7. Service normalizes policy and stores files.
8. Service appends audit entries.
9. Server broadcasts `policy_update` and `process_blacklist` if changed.
10. Server returns `settings_result` to dashboard.
11. Dashboard clears dirty flag and refreshes status.

## Sequence 13: Local IPC Startup

Actors: parent manager/runtime, child runtime/GUI.

1. Parent creates `ThreadedIpcServer`.
2. Server binds `127.0.0.1:0`.
3. OS assigns ephemeral port.
4. Parent generates random token.
5. Parent launches child with IPC env vars.
6. Child calls `should_use_ws_ipc`.
7. Child connects to `EXAM_LOCAL_IPC_URL?token=<token>`.
8. Parent validates loopback peer and token.
9. Child and parent exchange channel envelopes.
10. If WebSocket IPC is unavailable in auto mode, fallback paths use stdio.

