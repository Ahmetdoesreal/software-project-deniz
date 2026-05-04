# Owner Confirmation

Rule used: files with ambiguous direct ownership are tagged `needs-owner-confirmation` and listed here for your confirmation.

Status key:
- `pending`: needs your explicit owner tag decision.
- `confirmed`: decided by you.

## Pending Confirmation List

| path | feature_id | current_tags | status | note |
|---|---|---|---|---|
| `server/main.py` | F02 | `shared-core`, `needs-owner-confirmation` | pending | Server CLI entrypoint in baseline runtime. |
| `server/app.py` | F02 | `shared-core`, `needs-owner-confirmation` | pending | App wiring, startup/cleanup, discovery guard. |
| `server/handlers.py` | F02, F08 | `shared-core`, `needs-owner-confirmation` | pending | HTTP/WS handlers + upload endpoints. |
| `server/tasks.py` | F02 | `shared-core`, `needs-owner-confirmation` | pending | Runtime timers, operator commands, GUI bridge. |
| `server/state.py` | F02 | `shared-core`, `needs-owner-confirmation` | pending | Persistent/volatile server state model. |
| `server/session_state.py` | F02 | `shared-core`, `needs-owner-confirmation` | pending | Session-state transitions and policy helpers. |
| `server/shutdown.py` | F02 | `shared-core`, `needs-owner-confirmation` | pending | Graceful shutdown routine. |
| `server/submissions.py` | F02, F08 | `shared-core`, `needs-owner-confirmation` | pending | Submission/artifact paths and safety helpers. |
| `client/main.py` | F03 | `shared-core`, `needs-owner-confirmation` | pending | Client entrypoint and reconnect loop. |
| `client/auth.py` | F03 | `shared-core`, `needs-owner-confirmation` | pending | Login/health flow helpers. |
| `client/exam.py` | F03 | `shared-core`, `needs-owner-confirmation` | pending | Exam config/files prep fetch. |
| `client/ws_client.py` | F03, F07, F08 | `shared-core`, `needs-owner-confirmation` | pending | Main websocket runtime orchestration. |
| `client/exam_state.py` | F03 | `shared-core`, `needs-owner-confirmation` | pending | Exam state logging. |
| `client/incidents.py` | F06 | `shared-core`, `needs-owner-confirmation` | pending | Incident engine and policy application logic. |
| `common/process_users.py` | F06 | `shared-core`, `needs-owner-confirmation` | pending | Process-user normalization/filtering helper. |
| `client/custommodules/process_monitor/core.py` | F07 | `shared-core`, `needs-owner-confirmation` | pending | Process monitor runtime + snapshot/export logic. |
| `client/custommodules/process_monitor/psutil_collector.py` | F07 | `shared-core`, `needs-owner-confirmation` | pending | Process list collector implementation. |
| `client/custommodules/focused_window_monitor/core.py` | F07 | `shared-core`, `needs-owner-confirmation` | pending | Focused-window monitor runtime. |
| `client/custommodules/focused_window_monitor/windows.py` | F07 | `shared-core`, `needs-owner-confirmation` | pending | Windows focused-window adapter. |
| `client/custommodules/hardware_monitor/core.py` | F07 | `shared-core`, `needs-owner-confirmation` | pending | Hardware monitor runtime and diffing. |
| `client/custommodules/hardware_monitor/psutil_snapshot.py` | F07 | `shared-core`, `needs-owner-confirmation` | pending | Hardware snapshot collector. |
| `client/custommodules/hardware_monitor/windows.py` | F07 | `shared-core`, `needs-owner-confirmation` | pending | Windows-specific disk enrichment. |
| `client/custommodules/replay_recorder/core.py` | F07 | `shared-core`, `needs-owner-confirmation` | pending | Replay recorder wrapper. |
| `client/transfers.py` | F08 | `shared-core`, `needs-owner-confirmation` | pending | Bundle building + transfer upload. |
| `client/submission.py` | F08 | `shared-core`, `needs-owner-confirmation` | pending | Submission file validation + preview. |
| `common/manager_support.py` | F09 | `shared-core`, `needs-owner-confirmation` | pending | GUI process/session management utility. |
| `client/gui.py` | F09 | `shared-core`, `needs-owner-confirmation` | pending | Client operator GUI. |
| `server/gui.py` | F09 | `shared-core`, `needs-owner-confirmation` | pending | Server dashboard GUI. |
| `client_launcher.py` | F09 | `shared-core`, `needs-owner-confirmation` | pending | Client manager launcher. |
| `server_launcher.py` | F09 | `shared-core`, `needs-owner-confirmation` | pending | Server manager launcher. |

## Already Tagged With Evidence-Based Owner Lineage
- `common/protocol.py` -> includes `ahmet` lineage tag via `third_iteration` protocol mapping.
- `common/events.py` -> includes `ahmet` lineage tag via `third_iteration` events mapping.
- `common/discovery.py`, `common/discovery_v2.py` -> include `engin` lineage tag.
- `common/security.py` -> includes `naz` lineage tag.
