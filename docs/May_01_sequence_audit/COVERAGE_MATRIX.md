# Coverage Matrix

Use this as a lookup page. If you see a route, event, command, or GUI action in the code or logs, this tells you which sequence guide explains it.

## HTTP Routes

| If you see this | What it does | Read this |
|---|---|---|
| `GET /health` | Client checks that the server is alive. | [Client startup, WebSocket, and policy sync](sequences/02_client_startup_ws_policy.md) |
| `POST /login` | Client exchanges login id and password for a session UUID. | [Client startup, WebSocket, and policy sync](sequences/02_client_startup_ws_policy.md) |
| `GET /exam/config` | Client asks for exam duration and whether exam files exist. | [Client startup, WebSocket, and policy sync](sequences/02_client_startup_ws_policy.md) |
| `GET /exam/files` | Client downloads the configured exam zip. | [Client startup, WebSocket, and policy sync](sequences/02_client_startup_ws_policy.md) |
| `GET /ws?id=<uuid>` | Client opens the live WebSocket connection. | [Client startup, WebSocket, and policy sync](sequences/02_client_startup_ws_policy.md), [Exam timer and session state](sequences/03_exam_timer_session.md) |
| `POST /client/artifact` | Client uploads runtime evidence: replay, process report, incident bundle. | [Replay, savescreen, and artifacts](sequences/04_replay_savescreen_artifacts.md), [Monitoring, incidents, and process actions](sequences/05_monitoring_incidents_process_actions.md) |
| `POST /exam/submission` | Client uploads the final submission bundle. | [Final submission and uploads](sequences/06_submission_uploads.md) |

## WebSocket Events

| Event | Direction | Plain-English meaning | Read this |
|---|---|---|---|
| `welcome` | server to client | Connection accepted; client can introduce itself. | [Client startup](sequences/02_client_startup_ws_policy.md) |
| `client_info` | client to server | Client sends computer name. | [Client startup](sequences/02_client_startup_ws_policy.md) |
| `exam_policy` | server to client | Initial monitoring and exam policy. | [Client startup](sequences/02_client_startup_ws_policy.md) |
| `policy_update` | server to client | Policy changed while clients are connected. | [Monitoring and incidents](sequences/05_monitoring_incidents_process_actions.md) |
| `policy_applied` | client to server | Client confirms policy apply success or failure. | [Client startup](sequences/02_client_startup_ws_policy.md) |
| `process_blacklist` | server to client | Legacy/direct blacklist update. | [Monitoring and incidents](sequences/05_monitoring_incidents_process_actions.md) |
| `start_exam` | client to server | Student is ready to begin. | [Exam timer](sequences/03_exam_timer_session.md) |
| `sync_time` | server to client | Authoritative remaining time and timer state. | [Exam timer](sequences/03_exam_timer_session.md) |
| `session_state` | server to client | Full state such as waiting, running, paused, awaiting submission. | [Exam timer](sequences/03_exam_timer_session.md) |
| `pause_exam` | server to client | Pause this student. | [Exam timer](sequences/03_exam_timer_session.md) |
| `resume_exam` | server to client | Resume this student. | [Exam timer](sequences/03_exam_timer_session.md) |
| `finish_exam` | server to client | Open final submission flow. | [Exam timer](sequences/03_exam_timer_session.md), [Final submission](sequences/06_submission_uploads.md) |
| `exam_end` | server to client | Legacy/direct exam-end signal. | [Exam timer](sequences/03_exam_timer_session.md) |
| `savescreen` | server to client | Save recent replay evidence. | [Replay and savescreen](sequences/04_replay_savescreen_artifacts.md) |
| `get_processes` | server to client | Export and upload current process list. | [Replay and artifacts](sequences/04_replay_savescreen_artifacts.md) |
| `incident_report` | client to server | Client reports an incident or evidence status update. | [Monitoring and incidents](sequences/05_monitoring_incidents_process_actions.md) |
| `incident_received` | server to client | Server acknowledges the incident update. | [Monitoring and incidents](sequences/05_monitoring_incidents_process_actions.md) |
| `client_monitor_event` | client to server | Live monitor telemetry, mainly focused-window status. | [Monitoring and incidents](sequences/05_monitoring_incidents_process_actions.md) |
| `process_catch` | client to server | Blacklisted process was detected. | [Monitoring and incidents](sequences/05_monitoring_incidents_process_actions.md) |
| `kill_process` | server to client | Server asks client to terminate a PID. | [Monitoring and incidents](sequences/05_monitoring_incidents_process_actions.md) |
| `kill_process_result` | client to server | Client reports whether PID termination worked. | [Monitoring and incidents](sequences/05_monitoring_incidents_process_actions.md) |
| `ping` / `echo` | client to server / server to client | Manual connectivity check. | [Client startup](sequences/02_client_startup_ws_policy.md) |
| `time` | server to client | Heartbeat-style time broadcast. | [Exam timer](sequences/03_exam_timer_session.md) |
| `error` | both | Something was rejected or could not be decoded. | Relevant sequence based on context. |

## Commands And GUI Actions

| Entry point | What it means | Read this |
|---|---|---|
| `python -m server.main`, `server_cli.py` | Start the server. | [Server startup and shutdown](sequences/01_server_startup_shutdown.md) |
| `python -m client.main`, `client_cli.py` | Start a student client. | [Client startup](sequences/02_client_startup_ws_policy.md) |
| `/startexam`, GUI start all | Let students start. | [Exam timer](sequences/03_exam_timer_session.md) |
| `/finishexam`, GUI finish all | Move students to final submission. | [Exam timer](sequences/03_exam_timer_session.md), [Final submission](sequences/06_submission_uploads.md) |
| `/pauseexam`, `/resumeexam`, add time, forgive | Change a student's timer/session state. | [Exam timer](sequences/03_exam_timer_session.md) |
| `/savescreen`, GUI savescreen | Ask one or more clients to save replay evidence. | [Replay and savescreen](sequences/04_replay_savescreen_artifacts.md) |
| Process decision buttons | Mark known, blacklist, kill, pause, kick, ban. | [Monitoring and incidents](sequences/05_monitoring_incidents_process_actions.md) |
| Client start button | Student asks to begin the exam. | [Exam timer](sequences/03_exam_timer_session.md) |
| Client finish button | Student uploads final work. | [Final submission](sequences/06_submission_uploads.md) |
