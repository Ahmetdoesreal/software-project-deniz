# LLM Sequence Index

Use this file to map a behavior to the correct implementation area.

| Sequence | Main Files | Key Routes/Events/Channels |
|---|---|---|
| Server startup/shutdown | `server/main.py`, `server/app.py`, `server/tasks.py`, `server/shutdown.py` | UDP discovery, duplicate guard, `get_processes`, `savescreen` |
| Client startup/login | `client/main.py`, `client/auth.py`, `client/exam.py`, `common/discovery_v2.py` | `/login`, `/health`, `/exam/config`, `/exam/files` |
| WebSocket policy sync | `server/handlers.py`, `client/ws_client.py`, `common/events.py`, `common/security.py` | `/ws`, `welcome`, `exam_policy`, `process_blacklist`, `policy_applied` |
| Timer/session state | `server/session_state.py`, `server/tasks.py`, `server/handlers.py`, `client/ws_client.py` | `start_exam`, `session_state`, `sync_time`, `pause_exam`, `resume_exam`, `finish_exam` |
| Monitoring/incidents | `client/incidents.py`, `client/custommodules/*`, `server/handlers.py`, `server/settings_service.py` | `client_monitor_event`, `incident_report`, `incident_received`, `kill_process`, `kill_process_result` |
| Replay/artifacts | `client/custommodules/replay_recorder/core.py`, `client/transfers.py`, `server/handlers.py`, `server/submissions.py` | `savescreen`, `get_processes`, `/client/artifact` |
| Final submission | `client/ws_client.py`, `client/submission.py`, `client/transfers.py`, `server/handlers.py` | `finish_exam`, `/exam/submission` |
| Settings/process decisions | `server/settings_service.py`, `server/ui/*`, `common/process_definitions.py` | `dashboard.command`, `policy_update`, `process_blacklist` |
| Local IPC | `common/ipc_ws.py`, `common/manager_support.py`, `server/tasks.py`, `client/ws_client.py`, GUI backend files | `manager.console_command`, `server.dashboard_state`, `dashboard.command`, `client.timer_state`, `timer.command` |
