# Local IPC And GUI Transport

## Purpose

Local IPC is for same-machine app-owned process communication. It connects managers, runtime CLI processes, and GUI child windows without exposing control commands to the LAN.

It does not replace:

- The LAN `/ws` server/client WebSocket protocol.
- HTTP upload routes.
- UDP discovery.
- FFmpeg stdin control.

## Transport Modes

Each runtime accepts `--ipc-transport {auto,stdio,ws}`.

- `stdio`: use newline-delimited JSON or line commands through child stdin/stdout.
- `ws`: require local WebSocket IPC.
- `auto`: use local WebSocket when IPC environment variables are present; otherwise use stdio.

This preserves manual terminal workflows. A developer can run `python -m server.main` or `python -m client.main` directly without a manager and still type commands or use console output.

## Environment Variables

Local IPC uses:

- `EXAM_LOCAL_IPC_URL`: WebSocket URL, for example `ws://127.0.0.1:49152/ipc`.
- `EXAM_LOCAL_IPC_TOKEN`: per-process random token.
- `EXAM_LOCAL_IPC_ROLE`: child role such as `server_cli`, `client_cli`, `dashboard_gui`, or `timer_gui`.
- `EXAM_LOCAL_IPC_TRANSPORT`: `auto`, `stdio`, or `ws`.

Parents create a `ThreadedIpcServer`, then add `child_env(role, transport)` to the child process environment. Children create a `ThreadedIpcClient` and connect if `should_use_ws_ipc()` returns true.

## Security Rules

The IPC server must:

1. Bind only to `127.0.0.1`.
2. Use an ephemeral OS-assigned port by default.
3. Generate a random token with sufficient entropy.
4. Reject missing or wrong token with 401.
5. Reject non-loopback peers with 403.
6. Accept token through query string or `X-Exam-IPC-Token`.
7. Treat every envelope as untrusted JSON and validate shape.

The token is process-local trust. It is not a LAN credential and should never be reused as the student auth secret.

## Envelope Shape

Every IPC message is a JSON object:

```json
{
  "type": "event",
  "role": "dashboard_gui",
  "channel": "dashboard.command",
  "id": "uuid-hex",
  "reply_to": "",
  "seq": 0,
  "data": {},
  "error": "optional error text"
}
```

Required semantics:

- `channel` is mandatory and routes the message.
- `data` must be an object.
- `id` is unique per envelope.
- `reply_to` is reserved for request/reply expansions.
- `seq` is reserved for ordering or debugging.
- `role` identifies sender role.
- `type` defaults to `event`.

## Channels

### `manager.console_command`

Manager UI to server/client CLI runtime. The data payload should contain a command line or structured command equivalent.

Example:

```json
{
  "channel": "manager.console_command",
  "data": {
    "line": "/startexam"
  }
}
```

### `server.dashboard_state`

Server runtime to dashboard GUI. Carries state snapshots, client messages, and settings results.

Common data payloads:

- `{"type": "state_update", ...}`
- `{"type": "client_message", "uuid": "...", "text": "..."}`
- `{"type": "settings_result", "ok": true, "message": "..."}`

### `dashboard.command`

Dashboard GUI to server runtime. Payloads mirror existing GUI command JSON:

- `{"cmd": "save_settings", ...}`
- `{"cmd": "apply_policy"}`
- `{"cmd": "export_settings", "path": "..."}`
- `{"cmd": "process_decision", ...}`

### `client.timer_state`

Client runtime to timer/submission GUI. Data wraps the legacy line command:

```json
{
  "line": "SYNC:1200"
}
```

The GUI can reuse the same parser used for stdin fallback.

### `timer.command`

Timer/submission GUI to client runtime:

```json
{"cmd": "start_exam"}
```

or:

```json
{"cmd": "finish_exam", "path": "C:/Users/student/Desktop/answer.zip"}
```

### `process.lifecycle`

Reserved for parent/child lifecycle messages such as started, ready, stopping, exited, or crash metadata.

## Stdio Compatibility

Windowed Windows builds can have `sys.stdin`, `sys.stdout`, and `sys.stderr` set to `None`. GUI entrypoints must never directly call:

- `sys.stdin.isatty()`
- `iter(sys.stdin.readline, "")`
- `for line in sys.stdin`
- `print(..., flush=True)` for command output
- `print(..., file=sys.stderr)` for required error paths

Use `common.stdio_compat`:

- `stdin_available()`
- `stdin_is_standalone()`
- `iter_stdin_lines()`
- `write_json_stdout(payload)`
- `write_text_stderr(message)`

Standalone close behavior should be true when no stdin exists and local IPC is unavailable. If IPC env vars exist but connection fails, the GUI should switch back to standalone close behavior rather than trapping the user in a managed window with no parent.

## Runtime Logging

Runtime logging tees stdout/stderr to JSONL. In windowed builds the original streams may be absent. `TeeStream` must tolerate `None`, closed streams, and stream write errors. The log file remains the reliable diagnostic output.

Qt GUIs also enable `faulthandler` to a crash log file. Keep the file handle alive for the whole app lifetime and disable faulthandler before closing the handle.

## GUI Process Launch Pattern

Parent runtime:

1. Create local IPC server if transport allows WebSocket.
2. Launch child with `stdin=PIPE`, `stdout=PIPE` for stdio fallback and logs.
3. Pass IPC env vars when WebSocket IPC is enabled.
4. Keep stdout capture for logs even when command IPC uses WebSocket.
5. Pump child stdout logs and parse command JSON only for fallback paths.

Child GUI:

1. Configure runtime logging.
2. Decide `use_ws_ipc = should_use_ws_ipc()`.
3. Decide `standalone = stdin_is_standalone() and not use_ws_ipc`.
4. Start `ThreadedIpcClient` if WebSocket IPC is selected.
5. If IPC fails and no stdin is available, set `standalone_mode = True`.
6. Start stdin reader only when stdin is available.
7. On GUI command, first try IPC send; if it fails, write JSON to stdout.
8. On parent-closed sentinel in managed stdio mode, force-close GUI.

## Tk And Qt Parity

Every policy or command exposed by Tk must be exposed by Qt, and the payload shape must match. Differences should be visual only. For this project that means both dashboards must support:

- Runtime settings.
- Session settings.
- Operator confirmations.
- Process blacklist.
- Unexpected process policy.
- Focused-window policy.
- Rapid switching policy.
- Idle policy.
- Process definitions.
- Process path clarification.
- Export/import.
- Apply/open policy and definitions files.
- Process decision actions.

## IPC Pseudocode

```python
server = ThreadedIpcServer(role="server_manager", on_message=handle_child_message)
env = server.start()
env.update(server.child_env("server_cli", transport=args.ipc_transport))
process = Popen(command, env=env, stdin=PIPE, stdout=PIPE)

client = ThreadedIpcClient(role="dashboard_gui", on_message=handle_parent_message)
if should_use_ws_ipc() and client.start():
    ipc_active = True
else:
    ipc_active = False

def emit_command(payload):
    if ipc_active and client.send("dashboard.command", payload):
        return
    write_json_stdout(payload)
```

