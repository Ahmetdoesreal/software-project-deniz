# Client Startup, WebSocket, And Policy Sync

This page explains how a student client finds the server, logs in, starts local recording/monitoring, and receives the first policy state.

## In One Sentence

The client discovers the server, logs in for a session UUID, prepares exam files, starts the replay recorder, opens a WebSocket, and applies the server's current exam policy.

## Who Is Involved

- Student client CLI or launcher.
- `client.main`, the main startup loop.
- `client.auth`, for login and health checks.
- `client.exam`, for exam config and file download.
- `client.ws_client`, for live WebSocket behavior.
- `server.handlers`, for HTTP and WebSocket responses.

## Startup: What Happens

1. The client reads login id, password, server id, host/port, timeout, reconnect delay, and recording flag.
2. If the host was not provided, the client searches for the server on the local network.
3. The client calls `POST /login`.
4. The server checks:
   - Is this user allowed?
   - Is the password correct?
   - Is the user banned?
   - Has this user already submitted?
   - Is the same login already connected?
5. If login succeeds, the server returns the student's session UUID.
6. The client creates a replay recorder for that session.
7. If recording is enabled, FFmpeg starts writing rolling replay segments.
8. The client fetches exam config, downloads exam files when available, and checks server health.
9. The client opens `GET /ws?id=<session_uuid>`.

## WebSocket: What Happens First

After the WebSocket opens, the server sends the initial state:

1. `welcome`: confirms the connection.
2. `exam_policy`: sends monitoring and rule settings.
3. `process_blacklist`: sends direct blacklist data.
4. `session_state`: tells the client whether it is waiting, running, paused, submitted, or awaiting submission.
5. Depending on state, the server may also send `sync_time`, `pause_exam`, or `finish_exam`.

The client replies to `welcome` with `client_info`, applies policy, updates its local monitors, and sends `policy_applied`.

## Security Note

Sensitive messages such as policy, session state, incidents, pause/resume, and kill-process requests are protected by the session security layer when available.

Some operational events, like savescreen and get-processes, are not currently wrapped by that layer. That is listed as a low-severity follow-up in the risk register.

## Files You May See

- `data/client/<session_uuid>/exam_files/`
- `data/client/<session_uuid>/recordings/cache/`
- `data/client/<session_uuid>/processes.jsonl`
- `data/client/<session_uuid>/focused_window.jsonl`
- `data/client/<session_uuid>/hardware_changes.jsonl`
- `data/client/<session_uuid>/exam_state.jsonl`

## Common Failure Clues

- Client cannot find server: discovery failed or server id/port differs.
- Login rejected: check allowed users, password, ban state, or duplicate connection.
- Recorder inactive: FFmpeg may be missing, unsupported, or exited immediately.
- Policy apply failed: the client sends `policy_applied` with failure details.

## Tests

- `tests/integration/test_client_main.py`
- `tests/system/test_auth.py`
- `tests/system/test_comm.py`
- `tests/unit/test_security.py`
- `tests/unit/test_savescreen_event.py`
