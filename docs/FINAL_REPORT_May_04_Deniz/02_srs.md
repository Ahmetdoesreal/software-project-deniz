# 02. Software Requirements Specification

## 1. Introduction

This Software Requirements Specification describes the current `May_04_Deniz` exam runtime. The document follows an IEEE-style structure: purpose, product perspective, users, constraints, functional requirements, non-functional requirements, interfaces, acceptance criteria, and traceability. Requirement IDs are stable references for design, implementation, and validation documents in this final report package.

## 2. Product Perspective

The system is a local-area exam platform made of one authoritative server process and many student client processes. The system also includes local UI processes that communicate with their parent CLIs over local IPC. The client/server runtime protocol is JSON over WebSocket and HTTP; local UI/manager process control is loopback-only WebSocket IPC with stdio fallback. These two communication systems are intentionally separate.

## 3. Users And Characteristics

| User class | Characteristics |
| --- | --- |
| Operator | Runs server, controls exam, reviews incidents, changes policy, exports/imports settings, and collects submissions. |
| Student | Runs client, authenticates, starts exam, sees timer and submission UI, and submits an archive or file. |
| Administrator | Prepares allowed users, auth configuration, network settings, and deployment environment. |
| Maintainer | Reads logs, tests, and docs to debug or extend system behavior. |

## 4. Functional Requirements

### 4.1 Server Runtime

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-SRV-001 | The server shall start from `server.main` with configurable server id, host, port, broadcast interval, discovery interval, exam duration, exam files, upload limits, UI backend, IPC transport, GUI launch flag, reset flag, and auth secret. | Invalid ports, intervals, upload limits, shutdown grace, or empty server id are rejected before runtime starts. |
| FR-SRV-002 | The server shall reject duplicate servers with the same server id when discovery indicates an existing instance. | Startup checks for existing announcements and exits before binding when a duplicate is detected. |
| FR-SRV-003 | The server shall expose HTTP routes for health, auth status, login, exam config, exam files, submission upload, artifact upload, projector HTML, projector SSE, and WebSocket runtime. | Routes are registered in `server.app.create_app`. |
| FR-SRV-004 | The server shall load and persist users, incidents, process blacklist, exam policy, process definitions, and incident rules under `data/server`. | State methods initialize missing files and save normalized content. |
| FR-SRV-005 | The server shall maintain authoritative per-user session state including waiting, running, paused, awaiting submission, submitted, banned, kicked, finished, and disconnected-derived status. | Dashboard state and WebSocket session-state messages are derived from the same user state model. |
| FR-SRV-006 | The server shall broadcast time/session updates at the configured interval. | Running sessions receive remaining time updates; GUI state snapshots are pushed without requiring manual refresh. |
| FR-SRV-007 | The server shall provide admin commands for clients, savescreen, exam status, add time, pause, resume, kill pid, global start, global finish, GUI open, policy/blacklist/definition/rule editing, settings import/export, temporary auth disable plus admin validation, kick, ban, unban, forgive violation, security, and help. | Commands are parsed by `handle_admin_command` and shared by CLI and GUI request dispatch. |
| FR-SRV-008 | The server shall skip banned users during global finish. | `/finishexam` leaves banned users banned and reports skipped banned count. |
| FR-SRV-009 | The server shall use WebSocket close messages that fit the close-frame byte limit. | Long reasons are trimmed without splitting UTF-8. |

### 4.2 Client Runtime

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-CLI-001 | The client shall start from `client.main` with configurable login id, password, server id, direct host, port, discovery timeout, reconnect delay, recorder flag, check-login mode, UI backend, IPC transport, AD domain, and auth secret. | Invalid reconnect delay or connection arguments are rejected before runtime. |
| FR-CLI-002 | The client shall resolve its server by direct host/port or discovery. | Direct host skips discovery; discovery uses the configured server id and timeout. |
| FR-CLI-003 | The client shall check server health and perform login before opening the WebSocket runtime. | Login returns a session UUID used for subsequent routes and `/ws?id=<uuid>`. |
| FR-CLI-004 | The client shall fetch exam configuration and materials after login. | Config and materials are requested using the assigned session UUID. |
| FR-CLI-005 | The client shall extract exam materials safely to `Desktop/Exam/DD-MM-YYYY` and keep a ZIP copy under client data. | Unsafe ZIP paths are rejected; managed folders use a manifest; unmarked user content is not deleted. |
| FR-CLI-006 | The client shall open a timer/submission UI and synchronize it with server session state. | UI receives timer state, start permission, pause/resume, finish prompts, upload status, and exam-folder information. |
| FR-CLI-007 | The client shall keep local monitoring and logging alive during transient WebSocket disconnects. | Disconnect changes network state but does not stop process, focus, idle, hardware, exam-state, GUI, replay, or incident components. |
| FR-CLI-008 | The client shall reconnect automatically until final submission, intentional shutdown, or process exit. | Main loop waits the configured reconnect delay and starts a new WebSocket attempt. |
| FR-CLI-009 | The client shall support check-login mode for launchers. | Check-login validates server connection and credentials then exits without running the full exam session. |

### 4.3 Monitoring And Incident Detection

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-MON-001 | The client shall collect process snapshots and detect process blacklist or process definition violations. | Process monitor emits full/diff logs and incident candidates. |
| FR-MON-002 | The client shall collect focused-window snapshots and normalize title text before matching. | Unicode/invisible titlebar characters are sanitized before persistence and policy matching. |
| FR-MON-003 | The client shall detect focused-window policy violations using legacy allowed/blocked lists and definition-based incident rules. | Legacy lists remain supported; incident rules can whitelist New Tab or configured browser titles. |
| FR-MON-004 | The client shall collect idle state and report idle warning/critical incidents when enabled. | Idle thresholds are configurable in policy settings. |
| FR-MON-005 | The client shall collect hardware snapshots and log changes. | Hardware logs are included in runtime bundles when available. |
| FR-MON-006 | The client shall maintain a replay recorder when enabled. | Server `savescreen` requests can produce replay artifacts; recorder survives reconnect attempts. |

### 4.4 Incident Rules, Policy, And Actions

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-INC-001 | The system shall normalize incident rules with statuses `unknown`, `whitelist`, `warning`, and `blacklist`. | Rules are normalized by `common.incident_rules`. |
| FR-INC-002 | Whitelist incident rules shall suppress matching incidents before warning or blacklist rules. | Best matching whitelist returns no incident to report. |
| FR-INC-003 | Warning and blacklist incident rules shall override severity and attach matched rule/action metadata. | Incident payload includes `matched_incident_rule`, `matched_incident_rule_id`, and `configured_actions`. |
| FR-INC-004 | The server shall persist incident rules in `data/server/incident_rules.json` and include them in settings import/export. | Load/save/export/import paths include version changes. |
| FR-INC-005 | The dashboard shall include an Incident Rules tab and Save as Rule flow from incident history. | Tk and Qt dashboards expose incident rule rows and decision dialogs. |
| FR-INC-006 | The server shall apply configured actions for opened incidents where supported. | Ban, kick, pause, and kill-pid actions are applied only when context allows them. |
| FR-POL-001 | The server shall maintain exam policy rules for process blacklist, focused window, rapid switching, idle, unexpected process, process definitions, incident rules, and path clarification. | Policy is normalized with defaults and broadcast to clients. |
| FR-POL-002 | Policy settings shall be editable through Tk/Qt settings windows and CLI file edit/apply commands. | GUI save requests and CLI commands use the same state update paths. |

### 4.5 Reconnect, Buffering, And Evidence

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-REC-001 | Incident reports generated while disconnected shall be persisted with stable `seq`, `queued_at`, and `buffered=true`. | `IncidentBuffer` writes packet/index files and restores unacked entries. |
| FR-REC-002 | The client shall flush buffered incidents in order after reconnect. | Unacked packets are retried sequentially and kept until server acknowledgement. |
| FR-REC-003 | Evidence upload status shall be persisted and retried after reconnect. | Pending evidence entries survive process reconnect attempts. |
| FR-REC-004 | Repeated reconnects shall not duplicate restored queued incidents. | Restore logic deduplicates by sequence/incident identity. |

### 4.6 Submission And Artifact Transfer

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-SUB-001 | The client shall validate and preview selected submission files in the timer UI. | Archive trees and text previews are supported where possible. |
| FR-SUB-002 | The client shall build a submission bundle containing student work and runtime evidence files. | Bundle manifest records included files and metadata. |
| FR-SUB-003 | The client shall upload submissions via multipart HTTP with checksum metadata. | Server verifies supported archive type, size, and checksum where provided. |
| FR-SUB-004 | The client shall upload incident/replay artifacts separately when requested or generated. | Server stores artifacts under `data/server/artifacts` and acknowledges incident receipt. |

### 4.7 Authentication

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-AUTH-001 | The client shall support CATS and AD preflight behavior as configured. | Preflight checks server auth status and falls back to strict local behavior if status cannot be fetched. |
| FR-AUTH-002 | The server shall expose read-only auth status for a login id. | `GET /auth/status?login_id=<id>` returns whether CATS/AD are required, whether a temporary disable window is active, and whether admin validation is pending, approved, or denied. |
| FR-AUTH-003 | The server shall support temporary CATS and AD disable commands with default 60 seconds and bounded duration. | `/disablecatsauth`, `/disableadauth`, `/enablecatsauth`, `/enableadauth`, and `/authstatus` operate at runtime only. |
| FR-AUTH-004 | A login affected by disabled CATS or AD auth shall enter an admin-managed validation state before the session is allowed. | `/authrequests` lists attempts; `/approveauth <login_id> [seconds]` briefly allows the login; `/denyauth <login_id> [reason]` rejects it. Passwords are not stored in the validation queue. |

### 4.8 Local IPC And GUI

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-IPC-001 | App-owned local process communication shall use loopback WebSocket IPC when env/transport selection requires it. | `common.ipc_ws` binds `127.0.0.1`, uses random tokens, and validates loopback peers. |
| FR-IPC-002 | Manual terminal usage shall continue to work through stdio fallback. | Transport `auto` uses WebSocket when IPC env exists, otherwise stdio. |
| FR-IPC-003 | The local IPC envelope shall include type, role, channel, id, reply_to, seq, data, and optional error. | Envelope normalization rejects missing channels or non-object data. |
| FR-UI-001 | Tk and Qt dashboards shall provide equivalent operator workflows. | Both implementations expose clients, incidents, process database, incident rules, settings, folder info, and commands. |
| FR-UI-002 | Dashboard tables shall avoid disruptive timer-refresh rebuilds. | Stable row fingerprints allow in-place updates and preserve scroll/selection. |
| FR-UI-003 | Client timer UIs shall expose exam-folder information after material extraction. | Tk and Qt timer windows show an Exam Folder button when available. |

### 4.9 Projector

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-PROJ-001 | The server shall serve a read-only projector page at `/projector`. | Route returns self-contained HTML/CSS/JS. |
| FR-PROJ-002 | The server shall serve a read-only SSE feed at `/projector/events`. | Browser receives JSON state payloads and auto-reconnects if the stream disconnects. |
| FR-PROJ-003 | Projection payloads shall include exam phase, start state, counts, server time, connection status, and recent generic notifications. | Payload is constructed by `server.projector.build_projection_state`. |
| FR-PROJ-004 | Projector data shall be public-safe by construction. | Payload does not expose login ids, UUIDs, IPs, process names, window titles, artifact paths, submission paths, or evidence details. |

## 5. Non-Functional Requirements

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| NFR-SEC-001 | Local IPC shall not accept non-loopback peers. | Server returns 403 for non-loopback peer addresses. |
| NFR-SEC-002 | Local IPC shall require a per-process random token. | Missing or wrong token returns 401. |
| NFR-SEC-003 | Sensitive LAN events shall be signable/encryptable with session-specific context. | Secured events use HMAC, timestamp, nonce, optional Fernet encryption, and replay-window checks. |
| NFR-PRIV-001 | Public display endpoints shall avoid personally identifying or evidentiary data. | Projector tests assert sensitive tokens are not in payloads. |
| NFR-REL-001 | Reconnect shall be treated as a network condition, not a local logging shutdown. | Local monitors and replay continue until final submission, intentional shutdown, or process exit. |
| NFR-REL-002 | Persistent state files shall be normalized on load. | State methods repair missing defaults and version stamps. |
| NFR-OBS-001 | Runtime logs shall exist for server/client process output and client monitoring data. | `common.runtime_logging` and monitor JSONL files capture activity. |
| NFR-UX-001 | Low-resolution projection shall remain readable from distance. | Projector page uses large type, high contrast, and minimal dense content. |
| NFR-UX-002 | Dashboard live updates shall preserve user interaction state. | Scroll, selection, and focus are preserved during unavoidable rebuilds. |
| NFR-OPS-001 | The project shall be rebuildable using only Python dependencies in `requirements.txt`. | Operations manual lists setup and run commands. |

## 6. External Interface Requirements

External interfaces are defined in `05_interface_control_document.md`. At minimum the system shall expose:

- HTTP routes: `/health`, `/auth/status`, `/projector`, `/projector/events`, `/login`, `/exam/config`, `/exam/files`, `/exam/submission`, `/client/artifact`, `/ws`.
- LAN WebSocket events defined by `common.events`.
- Local IPC channels: `manager.console_command`, `server.dashboard_state`, `dashboard.command`, `client.timer_state`, `timer.command`, and `process.lifecycle`.
- Persistent state files under `data/server` and `data/client/{uuid}`.
- CLI commands handled by `server.tasks.handle_admin_command`.

## 7. Acceptance Matrix

| Capability | Primary acceptance |
| --- | --- |
| Server starts | `python -m server.main --id default --port 8080` can bind when no duplicate exists. |
| Client connects | `python -m client.main --login-id <id> --password <pw>` logs in and opens WebSocket when allowed. |
| Exam starts | `/startexam` enables clients to start and sends timer/session state. |
| Incidents persist | Generated incident reports appear in incident history and active incident state. |
| Reconnect survives | Disconnect does not stop local logs; queued incidents flush after reconnect. |
| Submission stores | Final upload is stored under server submissions with checksum handling. |
| Projector safe | `/projector/events` payload contains only aggregate public-safe fields. |
| GUI parity | Tk and Qt dashboard/client flows expose the same core controls. |
| Validation passes | `python -m compileall -q .` and `python -m unittest discover -s tests` pass. |
