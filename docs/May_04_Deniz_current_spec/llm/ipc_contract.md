# LLM IPC Contract

## Module

`May_04_Deniz/common/ipc_ws.py`

## Hard Requirements

- Bind IPC servers only to `127.0.0.1`.
- Use ephemeral ports.
- Require `EXAM_LOCAL_IPC_TOKEN`.
- Reject missing or invalid token.
- Reject non-loopback peer addresses.
- Use `aiohttp`; do not introduce a new WebSocket package.
- Preserve stdin/stdout fallback for manual runs and tests.
- Do not modify LAN-facing `common.events` protocol for this local IPC.

## Env Vars

- `EXAM_LOCAL_IPC_URL`
- `EXAM_LOCAL_IPC_TOKEN`
- `EXAM_LOCAL_IPC_ROLE`
- `EXAM_LOCAL_IPC_TRANSPORT`

## CLI Flag

`--ipc-transport {auto,stdio,ws}`

Semantics:

- `auto`: use WebSocket IPC when env vars are present; otherwise use stdio.
- `stdio`: force legacy stdio behavior.
- `ws`: require WebSocket IPC path where the caller supports it.

## Implemented Bridges

- `common.manager_support.ManagedProcessSession`
  - Starts `ThreadedIpcServer(role="manager")`.
  - Sends `manager.console_command`.
  - Falls back to child stdin.
- `server.tasks.console_reader`
  - Reads stdin and local IPC command messages.
- `server.tasks._launch_server_gui`
  - Starts `ThreadedIpcServer(role="server")`.
  - Sends `server.dashboard_state`.
  - Receives `dashboard.command`.
- `server.ui.dashboard_tk` and `server.ui.dashboard_qt`
  - Receive dashboard state over local IPC.
  - Send commands over local IPC with stdout fallback.
- `client.ws_client.StdinBridge`
  - Reads stdin and local IPC command messages from the launcher manager.
- `client.ws_client.ClientGUIBridge`
  - Starts `ThreadedIpcServer(role="client")`.
  - Sends `client.timer_state`.
  - Receives `timer.command`.
- `client.ui.exam_tk` and `client.ui.exam_qt`
  - Receive timer state over local IPC.
  - Send start/finish commands over local IPC with stdout fallback.

## Out Of Scope

- FFmpeg process stdin.
- aiohttp LAN WebSocket `/ws`.
- Browser or remote integrations.
