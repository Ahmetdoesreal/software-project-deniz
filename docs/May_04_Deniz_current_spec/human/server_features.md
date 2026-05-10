# Server-Side Feature Spec

Source root: `May_04_Deniz/`

## Runtime Entry Points

- `python -m server.main`: starts the aiohttp HTTP/WebSocket server.
- `server_launcher.py`: starts the manager UI, which launches `server.main` as a managed process.
- `python -m server.gui`: starts the server dashboard UI directly.

## Server Features

- HTTP routes:
  - `GET /health`: health and server identity.
  - `POST /login`: validates login credentials or AD HMAC token and returns the persistent session UUID.
  - `GET /exam/config`: returns exam runtime configuration for a session.
  - `GET /exam/files`: downloads the configured exam ZIP.
  - `POST /exam/submission`: receives final submission bundles.
  - `POST /client/artifact`: receives runtime evidence artifacts.
  - `GET /ws?id=<uuid>`: accepts authenticated student runtime WebSocket connections.
- Session lifecycle:
  - Tracks `waiting`, `running`, `admin_paused`, `disconnected_paused`, `violation_paused`, `awaiting_submission`, `submitted`, and `banned`.
  - Persists user/session state in `data/server/server_users.json`.
  - Auto-resumes disconnected clients when policy allows it.
  - Moves users to awaiting submission when the exam is globally finished.
- Operator commands:
  - `/clients`, `/exam`, `/startexam`, `/finishexam`
  - `/addtime`, `/pauseexam`, `/resumeexam`, `/forgiveviolation`
  - `/savescreen`, `/killpid`, `/kick`, `/ban`, `/unban`
  - `/editpolicy`, `/applypolicy`, `/editdefinitions`, `/applydefinitions`
  - `/exportsettings`, `/importsettings`, `/remembersettings`
- Policy and incident handling:
  - Maintains process blacklist, focused-window rules, rapid switching rules, unexpected-process rules, and process definitions.
  - Broadcasts policy updates to connected clients.
  - Records incidents in `data/server/incidents.jsonl` and active incident state in memory.
  - Applies configured process actions: kill PID, pause, kick, and ban.
- Dashboard support:
  - Builds dashboard state snapshots containing server info, settings, clients, incidents, and process database rows.
  - Supports both Tk and Qt dashboard backends.
  - Uses local WebSocket IPC when available, with stdin/stdout fallback preserved.
- Discovery and duplicate-server guard:
  - Announces servers over UDP discovery.
  - Checks for duplicate server IDs before and during runtime.
  - Keeps loopback probing for local server/port conflict detection.
- Shutdown:
  - Requests process reports and replay saves before shutdown.
  - Waits for a configurable grace window before cleanup.

## Persistence

- `data/server/server_users.json`: user/session state.
- `data/server/process_blacklist.txt`: direct blacklist entries.
- `data/server/exam_policy.json`: policy config excluding process definitions.
- `data/server/process_definitions.json`: normalized process decision definitions.
- `data/server/incidents.jsonl`: incident log.
- `data/server/session_audit.jsonl`: settings/action audit events.
- `data/server/submissions/<uuid>/`: final submission bundles.
- `data/server/artifacts/<uuid>/<kind>/`: runtime evidence artifacts.
