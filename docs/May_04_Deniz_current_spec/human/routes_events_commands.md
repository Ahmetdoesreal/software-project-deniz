# Routes, Events, And Commands

## HTTP Routes

| Route | Direction | Purpose |
|---|---|---|
| `GET /health` | client -> server | Health check and server identity. |
| `POST /login` | client -> server | Login ID plus password/token to session UUID. |
| `GET /exam/config` | client -> server | Exam duration and exam-file availability. |
| `GET /exam/files` | client -> server | Download configured exam materials ZIP. |
| `POST /exam/submission` | client -> server | Upload final submission bundle. |
| `POST /client/artifact` | client -> server | Upload replay/process/incident artifacts. |
| `GET /ws?id=<uuid>` | client -> server | Live exam WebSocket session. |

## LAN WebSocket Events

| Event | Direction | Purpose |
|---|---|---|
| `welcome` | server -> client | Confirms accepted WebSocket and assigned UUID. |
| `client_info` | client -> server | Sends computer name. |
| `exam_policy` | server -> client | Initial policy payload. |
| `policy_update` | server -> client | Runtime policy change. |
| `policy_applied` | client -> server | Policy apply acknowledgement. |
| `process_blacklist` | server -> client | Direct blacklist payload. |
| `start_exam` | client -> server | Student requests exam start. |
| `session_state` | server -> client | Authoritative session state. |
| `sync_time` | server -> client | Authoritative remaining seconds. |
| `pause_exam` / `resume_exam` | server -> client | Pause/resume this student timer. |
| `finish_exam` | server -> client | Open final submission flow. |
| `exam_end` | server -> client | Legacy end signal. |
| `savescreen` | server -> client | Save replay evidence. |
| `get_processes` | server -> client | Export/upload process report. |
| `client_monitor_event` | client -> server | Focused-window and monitor telemetry. |
| `process_catch` | client -> server | Legacy direct blacklist match. |
| `incident_report` | client -> server | Incident lifecycle/evidence status. |
| `incident_received` | server -> client | Incident acknowledgement. |
| `kill_process` | server -> client | Ask client to kill PID. |
| `kill_process_result` | client -> server | PID termination result. |
| `ping` / `echo` | client <-> server | Manual connectivity test. |
| `time` | server -> client | Periodic server time. |
| `error` | both | Protocol or state rejection. |

## Local IPC Channels

| Channel | Direction | Purpose |
|---|---|---|
| `manager.console_command` | launcher manager -> managed CLI | Sends CLI-style command text such as `/gui`. |
| `server.dashboard_state` | server process -> dashboard GUI | Sends state snapshots, client messages, and settings results. |
| `dashboard.command` | dashboard GUI -> server process | Sends GUI action payloads and console commands. |
| `client.timer_state` | client runtime -> timer GUI | Sends timer/submission UI state updates. |
| `timer.command` | timer GUI -> client runtime | Sends start and finish actions. |
| `process.lifecycle` | reserved | Future process start/stop/health events. |

## Operator Commands

Server commands are still accepted from terminal stdin and from local WebSocket IPC:

`/clients`, `/exam`, `/startexam`, `/finishexam`, `/addtime`, `/pauseexam`, `/resumeexam`, `/forgiveviolation`, `/savescreen`, `/killpid`, `/kick`, `/ban`, `/unban`, `/editblacklist`, `/applyblacklist`, `/editpolicy`, `/applypolicy`, `/editdefinitions`, `/applydefinitions`, `/exportsettings`, `/importsettings`, `/remembersettings`, `/security`, `/help`.
