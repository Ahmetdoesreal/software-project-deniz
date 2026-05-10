# LLM API And Event Inventory

## HTTP

- `GET /health`: returns health/server identity.
- `POST /login`: body `{login_id, password}` where password may be AD HMAC token; returns `{status, uuid}`.
- `GET /exam/config?id=<uuid>`: returns exam config.
- `GET /exam/files?id=<uuid>`: returns exam ZIP.
- `POST /exam/submission?id=<uuid>`: multipart field `archive`; text checksum fields `sha256`, `archive_sha256`.
- `POST /client/artifact?id=<uuid>`: multipart field `artifact`; text fields `kind`, `metadata`, checksum fields.
- `GET /ws?id=<uuid>`: student runtime WebSocket.

## LAN WebSocket Event Set

Server to client:

- `welcome`, `exam_policy`, `policy_update`, `process_blacklist`, `session_state`, `sync_time`, `pause_exam`, `resume_exam`, `finish_exam`, `exam_end`, `savescreen`, `get_processes`, `incident_received`, `kill_process`, `echo`, `time`, `error`

Client to server:

- `client_info`, `policy_applied`, `start_exam`, `client_monitor_event`, `process_catch`, `incident_report`, `kill_process_result`, `ping`

Security:

- Base envelope is `{"event": str, "data": dict, "checksum": sha256}`.
- Protected events use `common.security.SessionSecurityContext`.
- Protected event payloads include timestamp, nonce, signature, and encrypted/payload body.

## Local IPC Event Set

Envelope:

```json
{"type":"event","role":"<role>","channel":"<channel>","id":"<id>","reply_to":"","seq":0,"data":{}}
```

Channels:

- `manager.console_command`: `{"command": "/gui"}`
- `server.dashboard_state`: existing dashboard payloads such as `{"type":"state_update", ...}`
- `dashboard.command`: existing dashboard command payloads such as `{"cmd":"start_exam_global"}`
- `client.timer_state`: `{"line":"SYNC:2700"}` or other legacy timer command line
- `timer.command`: `{"cmd":"start_exam"}` or `{"cmd":"finish_exam","archive_path":"..."}`
- `process.lifecycle`: reserved
