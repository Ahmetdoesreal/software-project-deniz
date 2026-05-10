# IPC Inventory And Loopback WebSocket Migration

## Previous App-Owned IPC

Before this migration, local app process communication used `subprocess.PIPE`:

- Launcher managers wrote text commands to `server.main` / `client.main` stdin.
- Server process wrote dashboard JSON state to `server.gui` stdin.
- Dashboard GUI wrote action JSON back through stdout.
- Client runtime wrote timer commands such as `SYNC:<seconds>` to `client.gui` stdin.
- Timer GUI wrote action JSON back through stdout.

This was not a Windows named-pipe implementation; it was inherited subprocess stdin/stdout communication.

## New IPC Module

`May_04_Deniz/common/ipc_ws.py` adds loopback-only WebSocket IPC:

- Uses existing `aiohttp`; no new `websockets` dependency.
- Binds to `127.0.0.1` on an ephemeral port.
- Requires a random per-process token.
- Rejects missing/invalid tokens.
- Rejects non-loopback peers.
- Uses one envelope shape for all local IPC messages.

## Envelope

```json
{
  "type": "event",
  "role": "server",
  "channel": "server.dashboard_state",
  "id": "<message-id>",
  "reply_to": "",
  "seq": 0,
  "data": {}
}
```

Optional field: `error`.

## Transport Selection

Transport selection is available through:

- CLI flag: `--ipc-transport {auto,stdio,ws}`
- Env vars:
  - `EXAM_LOCAL_IPC_URL`
  - `EXAM_LOCAL_IPC_TOKEN`
  - `EXAM_LOCAL_IPC_ROLE`
  - `EXAM_LOCAL_IPC_TRANSPORT`

Default behavior is `auto`:

- If IPC env vars are present, WebSocket IPC is used first.
- If IPC env vars are absent, stdin/stdout behavior remains available.
- If WebSocket delivery fails, existing stdin/stdout fallback remains for compatibility.

## Migrated Channels

- Manager to CLI process:
  - `ManagedProcessSession` starts a local IPC server and passes env vars to the child process.
  - `server.tasks.console_reader` and `client.ws_client.StdinBridge` consume `manager.console_command`.
- Server to dashboard:
  - `server.tasks._launch_server_gui` starts a local IPC server and passes env vars to `server.gui`.
  - Dashboard Tk/Qt backends receive `server.dashboard_state`.
  - Dashboard actions send `dashboard.command`.
- Client to timer GUI:
  - `client.ws_client.ClientGUIBridge` starts a local IPC server and passes env vars to `client.gui`.
  - Timer Tk/Qt backends receive `client.timer_state`.
  - Timer actions send `timer.command`.

## Explicitly Out Of Scope

- LAN-facing client/server WebSocket events.
- FFmpeg stdin control in the replay recorder.
- Browser/network-exposed IPC.
