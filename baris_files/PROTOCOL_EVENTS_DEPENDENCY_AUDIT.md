# Protocol / Events Dependency Audit

Scope checked: active codebase folders `client`, `server`, `common`, `custommodules`, and `tests`.

Baris report concern:

Ahmet's `protocol.py` and `events.py` should not break when Engin's reliability fields are present:

- `seq`
- `session_id`
- `buffered`
- `queued_at`

## Active Dependency Map

`common/events.py` depends directly on `common/protocol.py`.

All event constructors call `protocol.encode(...)`, so every event message gets the same checksum shape:

```json
{
  "event": "...",
  "data": {...},
  "checksum": "..."
}
```

Main active users:

- `client/ws_client.py`
  - sends events through `events.*`
  - receives messages through `security.decode_wire_message(...)`
  - handles event constants such as `WELCOME`, `SYNC_TIME`, `SESSION_STATE`, `INCIDENT_RECEIVED`, `KILL_PROCESS`

- `server/handlers.py`
  - receives client WebSocket messages through `security.decode_wire_message(...)`
  - routes by event constants such as `PING`, `START_EXAM`, `PROCESS_CATCH`, `INCIDENT_REPORT`
  - sends server events through `events.*`

- `server/tasks.py`
  - sends command-triggered server events such as `sync_time`, `pause_exam`, `resume_exam`, `finish_exam`, `savescreen`, `get_processes`, `kill_process`

- `common/security.py`
  - wraps and unwraps secured events
  - calls `protocol.decode(...)` before deciding whether an event should be protected
  - re-encodes protected payloads with `protocol.encode(...)`

- `custommodules/*`
  - mostly uses `protocol.now_iso()`
  - process monitor emits matches through callbacks, but the actual WebSocket event is sent later by `client/ws_client.py`

- `tests/unit`
  - directly tests protocol/security/event behavior

## Active Checksum Behavior

The active `common/protocol.py` is strict:

- checksum is calculated over only `{"event": event, "data": data}`
- top-level unknown fields are ignored by checksum validation
- any extra field inside `data` changes the checksum and is rejected unless it was present when encoded

This means:

- If Engin's fields arrive as top-level fields beside `event`, `data`, and `checksum`, active protocol decoding will currently ignore them and the checksum will still pass.
- If Engin's fields are inserted into `data` after the checksum is created, active decoding will reject the message with `message checksum mismatch`.
- If Engin's fields are included in `data` before `protocol.encode(...)`, active decoding will accept them.

## Current Active App Risk

Low for the existing app as-is.

I found no active-code usage of `seq`, `session_id`, `buffered`, or `queued_at` in the client/server protocol flow. The active app currently uses:

- `incident_report` for policy/violation incidents
- `process_catch` for blacklisted process matches
- `session_state` / `sync_time` for exam state
- security wrapping through `common/security.py`

So Baris' report issue is real for the experimental Baris/Engin integration, but it is not currently exercised by the active root app unless those reliability fields are ported in.

## Compatibility Work Done Here

This folder's local `protocol.py` has been patched for the Baris/Ahmet task:

- accepts normal checksum first
- tolerates `seq`, `session_id`, `buffered`, and `queued_at` if they were added after checksum creation
- preserves those fields in the decoded payload
- still rejects unrelated payload mutation

Coverage:

- `test_protocol_compat.py`

Run with:

```powershell
cd baris_files
python -m unittest test_protocol_compat.py
```

## Recommendation

Do not patch the active root `common/protocol.py` yet unless Engin's reliability layer is also ported into the active client/server path.

If it is ported later, add the same compatibility tests under `tests/unit` first, because `common/security.py` depends on protocol decoding before it can unwrap secured messages.
