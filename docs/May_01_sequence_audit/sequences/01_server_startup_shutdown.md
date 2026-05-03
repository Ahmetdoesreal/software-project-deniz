# Server Startup And Shutdown

This page explains what happens when the exam server starts and stops.

## In One Sentence

The server starts an aiohttp app, announces itself on the network, watches for duplicate servers, optionally launches the GUI, and on shutdown asks connected clients for one last set of reports and replays.

## Who Is Involved

- The operator who starts or stops the server.
- `server.main`, which parses CLI options and starts the app.
- `server.app`, which creates routes and background tasks.
- `server.tasks`, which handles operator commands and periodic timer sync.
- `server.shutdown`, which runs the final evidence flush.
- Connected clients, if any exist during shutdown.

## Startup: What Happens

1. The operator starts `python -m server.main`, `server_cli.py`, or a launcher.
2. The server reads its settings: server id, host, port, timer interval, exam duration, upload limits, GUI flag, and shutdown grace.
3. If `--reset` is used, the server clears persisted user/session state.
4. Before binding the port, the server listens for another server with the same id.
5. If no duplicate is found, the aiohttp app is created.
6. The app registers all HTTP and WebSocket routes.
7. Background tasks start:
   - time broadcaster.
   - console reader.
   - UDP discovery announcer.
   - duplicate-server guard.
   - optional server GUI.

## Duplicate Server Guard

This protects classrooms from accidentally running two servers with the same id.

If the guard hears another server with the same id and it is not this same host/port, the server exits. If it hears itself, it ignores the beacon.

## Shutdown: What Happens

1. Server cleanup begins.
2. If no clients are connected, shutdown skips the client flush.
3. If clients are connected, the server broadcasts `get_processes`.
4. Then it broadcasts `savescreen` with `source="server_shutdown"`.
5. The server waits for `shutdown_grace_seconds`.
6. Background tasks are cancelled.
7. The discovery announcer stops.
8. The GUI process is killed if it is still running.

## Why The Shutdown Wait Matters

A replay save is not instant. The client may need to copy FFmpeg segments, merge them, fall back to TS if MP4 fails, and upload the result. A 2-second wait was too short for real evidence. The default is now 60 seconds.

## Files You May See

- `data/server/server_users.json`
- `data/server/incidents.jsonl`
- `data/server/session_audit.jsonl`
- `data/server/artifacts/<client_id>/...`
- `data/logs/server/...`

## Common Failure Clues

- Duplicate server found: startup exits before the app is served.
- Port already in use: the server prints a port conflict message.
- Shutdown replay missing: check whether the server waited long enough and whether the client was still connected.
- No shutdown artifacts: there may have been no connected clients.

## Tests

- `tests/unit/test_server_main.py`
- `tests/unit/test_server_app.py`
- `tests/unit/test_server_shutdown.py`
- `tests/integration/test_discovery.py`
