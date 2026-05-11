# 05. Interface Control Document

## 1. Purpose

This Interface Control Document defines the boundaries between the server, client, local UI processes, persistent files, and operators. It is the authoritative final-report inventory for routes, events, commands, IPC channels, JSON contracts, and data files in `May_04_Deniz`.

## 2. HTTP Interfaces

All HTTP routes are registered by `server.app.create_app`.

| Method | Route | Direction | Purpose | Sensitive data policy |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | Client/launcher to server | Verifies server identity and availability. | Public server metadata only. |
| `GET` | `/auth/status?login_id=<id>` | Client preflight to server | Returns auth requirements, bypass status, server time, and whether login id is allowed. | Does not authenticate the user; used only to decide local preflight behavior. |
| `GET` | `/projector` | Browser to server | Returns read-only projection HTML. | Public-safe only; no controls. |
| `GET` | `/projector/events` | Browser to server | SSE stream of projection-safe state. | Must not include login ids, UUIDs, IPs, process names, window titles, paths, or evidence. |
| `POST` | `/login` | Client to server | Validates login id/password/token and returns session UUID. | Handles credentials; response contains session UUID. |
| `GET` | `/exam/config?id=<uuid>` | Client to server | Returns exam configuration for assigned session. | Requires valid session UUID. |
| `GET` | `/exam/files?id=<uuid>` | Client to server | Streams configured exam materials ZIP. | Requires valid session UUID. |
| `POST` | `/exam/submission?id=<uuid>` | Client to server | Accepts final submission multipart upload. | Requires valid session UUID; stores server-side submission. |
| `POST` | `/client/artifact?id=<uuid>` | Client to server | Accepts runtime artifact or incident evidence multipart upload. | Requires valid session UUID; stores artifact path. |
| `GET` | `/ws?id=<uuid>` | Client to server | Opens LAN WebSocket runtime. | Requires valid session UUID. |

### `/auth/status` Response Fields

The auth status response includes:

- `cats_required`: whether client-side CATS preflight should normally run.
- `ad_required`: whether AD token behavior should normally run.
- `cats_bypass_until`: bypass expiry timestamp when active.
- `ad_bypass_until`: bypass expiry timestamp when active.
- `allowed_user`: whether the login id is present in allowed users.
- `server_time`: server time.
- `reason`: explanatory status text.

If the client cannot fetch this endpoint, it must use strict local auth behavior.

### Upload Contract

Submission and artifact uploads use multipart form data. Upload handlers support optional metadata fields and file parts. The server enforces configured maximum bytes and checksum validation where a checksum is supplied. Unsupported archives, missing file parts, checksum mismatch, or invalid UUIDs return an error response.

## 3. LAN WebSocket Protocol

Messages use the `common.protocol` envelope:

```json
{
  "event": "event_name",
  "data": {},
  "checksum": "sha256"
}
```

`decode` returns `("__decode_error__", {"reason": "..."})` for malformed messages, non-object data, missing checksum, or checksum mismatch.

### Server-To-Client Events

| Event | Constructor | Purpose |
| --- | --- | --- |
| `welcome` | `events.welcome` | Greets client and confirms server id. |
| `echo` | `events.echo` | Reply to ping. |
| `time` | `events.time_broadcast` | Broadcast current server time. |
| `error` | `events.error` | Report server-side protocol or action error. |
| `exam_policy` | `events.exam_policy` | Initial client-enforced policy snapshot. |
| `policy_update` | `events.policy_update` | Runtime policy update after operator changes settings. |
| `savescreen` | `events.savescreen` | Request client replay save. |
| `sync_time` | `events.sync_time` | Authoritative remaining seconds and timer state. |
| `session_state` | `events.session_state` | Authoritative session state for connect/reconnect. |
| `pause_exam` | `events.pause_exam` | Pause one client's exam timer. |
| `resume_exam` | `events.resume_exam` | Resume one client's exam timer. |
| `exam_end` | `events.exam_end` | Notify client timer reached end. |
| `get_processes` | `events.get_processes` | Request immediate process report. |
| `process_blacklist` | `events.process_blacklist` | Send process blacklist entries and version. |
| `incident_received` | `events.incident_received` | Acknowledge incident report and optional artifact path. |
| `kill_process` | `events.kill_process` | Request client to kill a process id. |
| `finish_exam` | `events.finish_exam` | Ask client to open/complete final submission. |

### Client-To-Server Events

| Event | Constructor | Purpose |
| --- | --- | --- |
| `ping` | `events.ping` | Client heartbeat or manual ping. |
| `client_info` | `events.client_info` | Machine metadata and runtime identity. |
| `policy_applied` | `events.policy_applied` | Client acknowledges policy version. |
| `start_exam` | `events.start_exam` | Student starts local exam timer after server enables start. |
| `process_catch` | `events.process_catch` | Legacy blacklisted process match report. |
| `incident_report` | `events.incident_report` | Incident lifecycle event, including buffered incidents. |
| `client_monitor_event` | `events.client_monitor_event` | Structured monitor telemetry. |
| `kill_process_result` | `events.kill_process_result` | Result of a kill-process command. |

### Secured Events

By default these events are signed and encrypted when a session security context exists:

- `exam_policy`
- `policy_update`
- `session_state`
- `incident_report`
- `kill_process`
- `pause_exam`
- `resume_exam`

The secured envelope is nested inside the `data` field and contains `_secured`, timestamp, nonce, encrypted flag, signature, and payload/ciphertext.

## 4. Loopback IPC Interfaces

### Environment Variables

| Variable | Purpose |
| --- | --- |
| `EXAM_LOCAL_IPC_URL` | WebSocket URL for local IPC, normally `ws://127.0.0.1:<ephemeral>/ipc`. |
| `EXAM_LOCAL_IPC_TOKEN` | Per-process random token required to connect. |
| `EXAM_LOCAL_IPC_ROLE` | Role name for the child process. |
| `EXAM_LOCAL_IPC_TRANSPORT` | Transport selection: `auto`, `stdio`, or `ws`. |

### Transport Selection

| Value | Behavior |
| --- | --- |
| `auto` | Use WebSocket IPC when URL and token env vars exist; otherwise use stdio. |
| `stdio` | Force stdin/stdout compatibility path. |
| `ws` | Force loopback WebSocket IPC. |

### Envelope Shape

```json
{
  "type": "event",
  "role": "server_dashboard",
  "channel": "server.dashboard_state",
  "id": "uuid-hex",
  "reply_to": "",
  "seq": 0,
  "data": {},
  "error": "optional error text"
}
```

Messages without a nonempty `channel` or object `data` are ignored by IPC decoders.

### Channels

| Channel | Direction | Purpose |
| --- | --- | --- |
| `manager.console_command` | Manager UI to CLI process | Sends operator-entered console commands to server/client CLI. |
| `server.dashboard_state` | Server CLI to dashboard UI | Pushes dashboard state, command output, settings snapshots, and tables. |
| `dashboard.command` | Dashboard UI to server CLI | Sends structured dashboard actions such as save settings or apply decisions. |
| `client.timer_state` | Client CLI to timer UI | Pushes timer state, upload status, finish prompts, and exam-folder info. |
| `timer.command` | Timer UI to client CLI | Sends student start/finish/submission commands. |
| `process.lifecycle` | Parent/child process supervision | Sends lifecycle notifications where supported. |

## 5. Operator CLI Commands

Commands are parsed by `server.tasks.handle_admin_command`. Commands must start with `/`.

| Command | Purpose |
| --- | --- |
| `/clients` | List connected clients. |
| `/savescreen <id>` | Request replay save from one client. |
| `/savescreen all` | Request replay save from all clients. |
| `/exam` | Print exam state summary. |
| `/addtime <id> <minutes>` | Add time to a specific user/client. |
| `/pauseexam <id>` | Pause a specific user's timer. |
| `/resumeexam <id>` | Resume a specific user's timer. |
| `/killpid <id> <pid>` | Ask a client to terminate a process id. |
| `/startexam` | Enable exam start globally. |
| `/finishexam` | Finish all started non-banned exams and open submission flow. |
| `/gui` | Open or reopen server dashboard UI. |
| `/editblacklist` | Open process blacklist file. |
| `/applyblacklist` | Reload and broadcast process blacklist. |
| `/editpolicy` | Open exam policy file. |
| `/applypolicy` | Reload and broadcast exam policy. |
| `/editdefinitions` | Open process definitions file. |
| `/applydefinitions` | Reload and broadcast process definitions. |
| `/editincidentrules` | Open incident rules file. |
| `/applyincidentrules` | Reload and broadcast incident rules. |
| `/exportsettings <path>` | Export settings bundle. |
| `/importsettings <path>` | Import settings bundle. |
| `/remembersettings on|off` | Toggle remembered policy settings. |
| `/disablecatsauth [seconds]` | Temporarily disable CATS preflight, default 60 seconds. |
| `/disableadauth [seconds]` | Temporarily disable AD token auth for allowed users, default 60 seconds. |
| `/enablecatsauth` | Re-enable CATS preflight. |
| `/enableadauth` | Re-enable AD token auth. |
| `/authstatus` | Print current auth bypass status. |
| `/kick <id>` | Disconnect and mark a user kicked. |
| `/ban <id>` | Disconnect and mark a user banned. |
| `/unban <id>` | Clear banned state. |
| `/forgiveviolation <id>` | Clear violation pause/ban style state where allowed. |
| `/security ...` | Delegate security command handling to IP/security guard. |
| `/help` | Print command help. |

## 6. Dashboard GUI Commands

Dashboard GUIs send structured requests through `dashboard.command`. The server dispatch path supports at least:

- `save_settings`
- `apply_blacklist`
- `apply_policy`
- `apply_process_definitions`
- `edit_blacklist`
- `edit_policy`
- `edit_definitions`
- `apply_process_decision`
- `edit_incident_rules`
- `apply_incident_rules`
- `apply_incident_rule_decision`
- global and selected-user exam commands that map to admin commands

The design intent is that GUI commands should call server-side handlers rather than duplicating business logic in the GUI process.

## 7. Policy And Rule Data Contracts

### Exam Policy

The normalized exam policy includes:

- `session.auto_resume_on_reconnect`
- `session.remember_settings`
- `rules.process_blacklist`
- `rules.focused_window`
- `rules.rapid_application_switching`
- `rules.idle_policy`
- `rules.unexpected_process`
- `rules.process_definitions`
- `rules.incident_rules`
- `rules.process_path_clarification`
- `operator_defaults.confirm_kill_pid`
- `operator_defaults.confirm_kick`
- `operator_defaults.confirm_ban`
- `operator_defaults.confirm_pause`

Each rule has an `enabled` flag, severity, and action controls where applicable.

### Incident Rule

An incident rule contains normalized fields:

- `definition_id`
- `rule_key`
- `name`
- `status`
- `actions`
- `rule_id`
- `event_type`
- `source`
- `process_names`
- `browser_process_names`
- `window_title_patterns`
- `match_mode`
- `priority`
- source/decision metadata

Statuses are `unknown`, `whitelist`, `warning`, and `blacklist`. Match modes are `contains` and `exact`.

### Process Definition

Process definitions are normalized in `common.process_definitions`. They support process identity, path context, status/decision state, student-specific action availability, and action toggles such as ban, kick, pause, and kill-pid where context allows.

## 8. Persistent File Interfaces

| Path | Owner | Purpose |
| --- | --- | --- |
| `data/server/users.json` | Server | Registered users, UUIDs, session flags, submissions, and state. |
| `data/server/incidents.json` | Server | Incident history. |
| `data/server/process_blacklist.txt` | Server/operator | Legacy process blacklist entries. |
| `data/server/exam_policy.json` | Server/operator | Normalized policy configuration. |
| `data/server/process_definitions.json` | Server/operator | Process definition database. |
| `data/server/incident_rules.json` | Server/operator | Incident rule database. |
| `data/server/submissions/*` | Server | Final student submissions. |
| `data/server/artifacts/*` | Server | Runtime artifacts and evidence uploads. |
| `data/logs/server/*` | Server | Runtime stdout/stderr/process logs. |
| `data/client/{uuid}/exam_files/*` | Client | Downloaded exam ZIP copy and metadata. |
| `data/client/{uuid}/buffer/*` | Client | Buffered incidents and pending evidence status. |
| `data/client/{uuid}/recordings/*` | Client | Replay cache and saved replay files. |
| `data/client/{uuid}/processes.jsonl` | Client | Process monitor log. |
| `data/client/{uuid}/focused_window.jsonl` | Client | Focused-window log. |
| `data/client/{uuid}/hardware.jsonl` | Client | Hardware monitor log. |
| `data/client/{uuid}/exam_state.jsonl` | Client | Timer/session state log. |
| `Desktop/Exam/DD-MM-YYYY` | Client/student | Extracted exam materials for the student. |

## 9. Projector SSE Payload

`GET /projector/events` sends SSE records in this format:

```json
{
  "server_time": "2026-05-11T00:00:00+00:00",
  "exam_phase": "waiting",
  "exam_start_enabled": false,
  "connection_status": "live",
  "counts": {
    "total_users": 0,
    "connected": 0,
    "disconnected": 0,
    "active_incidents": 0,
    "active_warnings": 0,
    "active_violations": 0,
    "submitted": 0,
    "awaiting_submission": 0
  },
  "notifications": [
    {
      "kind": "system",
      "severity": "system",
      "message": "Waiting for exam start",
      "time": "2026-05-11T00:00:00+00:00"
    }
  ]
}
```

Allowed notification messages are generic, such as "New violation incident opened", "Warning resolved", "Exam is running", or "Waiting for exam start".

## 10. Compatibility Rules

- Legacy focused-window allowed/blocked lists remain supported.
- Stdio IPC remains supported for manual operation.
- FFmpeg stdin control remains outside app IPC.
- CATS whitelist behavior is configurable through incident rules; only New Tab browser title patterns are shipped as default whitelist.
- LAN WebSocket event schemas should not be changed casually because both server and client depend on `common.events`.
