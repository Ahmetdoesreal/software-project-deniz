# Software Requirements Specification

Project: `May_04_Deniz` Exam Monitoring and Management Platform

Document type: Whole-project SRS

Prepared for: course/project review, implementation handoff, and Overleaf conversion

Source baseline: current `May_04_Deniz/` implementation

Date: 2026-05-12

## Revision History

| Version | Date | Description |
| --- | --- | --- |
| 1.0 | 2026-05-12 | Initial standalone whole-project SRS generated from the current implementation and final report package. |

## 1. Introduction

### 1.1 Purpose

This Software Requirements Specification defines the required behavior of the
`May_04_Deniz` exam monitoring and management platform. The document captures
functional requirements, non-functional requirements, external interfaces,
persistence contracts, operational constraints, and acceptance criteria.

The SRS is written so that a reader can understand what the system must do
without reading source code first. Implementation details are referenced only
where they clarify an existing requirement or provide traceability.

### 1.2 Scope

The system is a local-area exam platform consisting of:

- one authoritative server runtime,
- multiple student client runtimes,
- Tk and Qt graphical user interfaces,
- launcher and manager interfaces,
- local inter-process communication,
- LAN HTTP and WebSocket communication,
- process, focus, idle, hardware, replay, and submission monitoring,
- incident history and incident-rule management,
- authentication preflight and admin validation controls,
- a read-only projector notification page,
- offline installer support for Windows.

The scope of this SRS is the current `May_04_Deniz` implementation. Previous
snapshots are not authoritative for requirements.

### 1.3 Definitions, Acronyms, and Abbreviations

| Term | Meaning |
| --- | --- |
| AD | Active Directory authentication or token generation path. |
| CATS | School authentication/preflight service used before client login. |
| Client | Student-side runtime that connects to the server and performs monitoring. |
| Dashboard | Server-side operator GUI implemented in Tk and Qt. |
| Incident | A policy-relevant event such as a blacklisted process, blocked title, idle state, or evidence upload state. |
| IPC | Inter-process communication between local app-owned processes. |
| LAN WebSocket | Student/server runtime protocol exposed by the server at `/ws`. |
| Loopback IPC | Local-only WebSocket IPC bound to `127.0.0.1` with token authentication. |
| Projector | Read-only public display page for aggregate exam notifications. |
| Server | Authoritative exam controller and persistence owner. |
| SRS | Software Requirements Specification. |

### 1.4 References

- `docs/FINAL_REPORT_May_04_Deniz/02_srs.md`
- `docs/FINAL_REPORT_May_04_Deniz/05_interface_control_document.md`
- `docs/FINAL_REPORT_May_04_Deniz/08_testing_and_validation.md`
- `May_04_Deniz/server`
- `May_04_Deniz/client`
- `May_04_Deniz/common`
- `May_04_Deniz/tests`

### 1.5 Overview

Section 2 describes the product context. Section 3 gives overall constraints and
assumptions. Section 4 defines functional requirements. Section 5 defines
non-functional requirements. Section 6 defines external interface requirements.
Section 7 lists data and persistence requirements. Section 8 defines acceptance
and traceability.

## 2. Overall Description

### 2.1 Product Perspective

The platform is not a cloud service. It is a local exam system intended to run
inside a controlled network. The server is the authority for user state, exam
state, policy, submissions, artifacts, incident history, and operator commands.
Clients are responsible for student-side monitoring and submission packaging.

The architecture intentionally separates three communication domains:

| Domain | Purpose | Security Boundary |
| --- | --- | --- |
| LAN HTTP | Login, exam config, exam files, submissions, artifact uploads, projector page. | Server validates UUIDs for protected routes; projector is public-safe. |
| LAN WebSocket | Live server/client runtime events. | Session UUID plus optional secured event envelope. |
| Loopback IPC | Local GUI/manager process communication. | Bound to `127.0.0.1`; token required; stdio fallback for manual usage. |

### 2.2 Product Functions

At a high level, the system shall:

- start a server with validated runtime configuration,
- discover or directly connect clients to the selected server,
- authenticate or validate students before admission,
- distribute exam configuration and materials,
- synchronize timer and session state,
- monitor client processes, focused window titles, idle state, hardware state,
  and replay evidence,
- detect policy violations and record incidents,
- support admin decisions through dashboard tabs and CLI commands,
- tolerate transient disconnects without stopping local logging,
- collect final submissions and evidence artifacts,
- provide projection-safe aggregate notifications,
- support offline Windows installation.

### 2.3 User Classes

| User Class | Description | Primary Needs |
| --- | --- | --- |
| Operator | Exam supervisor using CLI or GUI. | Start/finish exam, review incidents, control users, update rules. |
| Student | Person taking the exam through a client runtime. | Authenticate, receive materials, view timer, submit files. |
| Administrator | Person preparing machines and policies. | Configure users, auth, installer, Python, FFmpeg, network settings. |
| Maintainer | Developer or support engineer. | Debug, test, extend, and rebuild the system. |
| Audience | People viewing the projector page. | See large public-safe exam notifications. |

### 2.4 Operating Environment

The primary target environment is Windows 11 on x64 machines. The implementation
uses Python, `aiohttp`, `psutil`, `cryptography`, `requests`,
`beautifulsoup4`, and optionally `PySide6`. FFmpeg is used for replay recording
and artifact generation.

The offline installer is intended to install a shared Python virtual environment
under `C:\ProgramData\May_04_Deniz\python_env` rather than installing packages
into machine-wide Python `site-packages`.

### 2.5 Design and Implementation Constraints

- The server must remain the source of truth for exam state.
- LAN WebSocket event schemas must remain compatible between server and client.
- Loopback IPC must not be treated as LAN student/server communication.
- Projector output must be public-safe and read-only.
- Authentication bypass must be temporary and admin-managed.
- Manual terminal workflows must continue to work through stdio fallback.
- FFmpeg stdin control remains third-party process control, not app IPC.
- The installer must avoid package conflicts with other machine-wide Python use.

### 2.6 Assumptions and Dependencies

- The server and clients run on the same controlled network unless direct host
  mode is configured.
- `allowed_users.json` and auth configuration are prepared before an exam.
- Operators have administrative authority over exam policy and incident action.
- FFmpeg is available when replay recording is enabled.
- PySide6 may be unavailable; Tk remains an available GUI backend.
- Offline installation requires a prebuilt wheelhouse compatible with the target
  Python version and Windows x64 platform.

## 3. Specific Requirements

### 3.1 Server Runtime Requirements

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| FR-SRV-001 | The server shall start from the server runtime entry point with configurable server id, host, port, broadcast interval, discovery interval, exam duration, upload limits, UI backend, IPC transport, GUI launch flag, reset flag, and auth secret. | Invalid ports, intervals, upload limits, shutdown grace, and empty server ids are rejected before runtime starts. |
| FR-SRV-002 | The server shall reject duplicate active servers using the same server id. | Startup discovery checks for an existing matching server and exits before binding when a duplicate is detected. |
| FR-SRV-003 | The server shall expose HTTP routes for health, auth status, login, exam config, exam files, submission upload, artifact upload, projector HTML, projector SSE, and WebSocket runtime. | Routes are registered by the server application factory and covered by HTTP/unit tests. |
| FR-SRV-004 | The server shall persist users, incidents, exam policy, process blacklist, process definitions, and incident rules under `data/server`. | Missing files are initialized or normalized on load. |
| FR-SRV-005 | The server shall maintain authoritative user session state. | Waiting, running, paused, awaiting submission, submitted, banned, kicked, finished, and disconnected-derived states are visible in dashboard state. |
| FR-SRV-006 | The server shall broadcast timer and session updates at the configured interval. | Connected clients receive time/session events without manual operator refresh. |
| FR-SRV-007 | The server shall parse and execute admin commands from CLI and dashboard command dispatch. | Supported commands include exam control, user control, policy/rule editing, settings import/export, auth validation, process kill, and help. |
| FR-SRV-008 | Global finish shall not forgive or reset banned users. | `/finishexam` skips banned users and reports the skipped count. |
| FR-SRV-009 | WebSocket close reasons shall respect WebSocket close-frame byte limits. | Long close messages are trimmed without splitting UTF-8 characters. |

### 3.2 Client Runtime Requirements

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| FR-CLI-001 | The client shall start with configurable login id, password, server id, direct host, port, discovery timeout, reconnect delay, recorder flag, login-check mode, UI backend, IPC transport, AD domain, and auth secret. | Invalid startup arguments fail before runtime connection. |
| FR-CLI-002 | The client shall resolve the server by direct host/port or discovery. | Direct host mode bypasses discovery; discovery uses configured server id and timeout. |
| FR-CLI-003 | The client shall perform server health check and login before opening the WebSocket runtime. | Successful login returns a session UUID used for protected routes. |
| FR-CLI-004 | The client shall fetch exam configuration and files after login. | Exam config and materials are requested with the assigned session UUID. |
| FR-CLI-005 | The client shall safely extract exam materials to `Desktop/Exam/DD-MM-YYYY`. | Unsafe ZIP members are rejected; managed folders are marked; unmarked user data is not deleted. |
| FR-CLI-006 | The client shall open a timer/submission UI and keep it synchronized with server session state. | UI receives start permission, pause/resume, remaining time, finish prompts, upload status, and exam-folder information. |
| FR-CLI-007 | The client shall keep local logging alive during transient WebSocket disconnects. | Process, focus, idle, hardware, exam-state, incident, GUI, and replay components do not stop solely because the socket disconnects. |
| FR-CLI-008 | The client shall reconnect automatically until final submission, intentional shutdown, or process exit. | Main loop waits the configured reconnect delay and starts a new WebSocket attempt. |
| FR-CLI-009 | The client shall support launcher check-login mode. | Check-login verifies connectivity and credentials, then exits without starting a full exam runtime. |

### 3.3 Monitoring and Incident Requirements

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| FR-MON-001 | The client shall collect process snapshots and detect process blacklist or process definition violations. | Full or diff process logs are written and matching candidates become incidents. |
| FR-MON-002 | Process executable matching shall support exact, contains, and wildcard-style entries where supported by definitions. | A reusable entry can match variants such as desktop app executable names. |
| FR-MON-003 | The client shall collect focused-window snapshots and normalize title text before matching. | Unicode control and invisible title characters are sanitized before matching and persistence. |
| FR-MON-004 | Focused-window matching shall support legacy allowed/blocked lists and definition-based incident rules. | Existing policy files remain valid while incident rules add whitelist, warning, and blacklist definitions. |
| FR-MON-005 | Saved titlebar rules shall default to reusable title patterns instead of full observed titles. | A saved rule for `whatsapp` can match browser titles containing WhatsApp across Chrome, Edge, Yandex, and similar browsers. |
| FR-MON-006 | The client shall collect idle state and report idle warning or critical events when enabled. | Idle thresholds and actions are configurable in policy settings. |
| FR-MON-007 | The client shall collect hardware snapshots and log hardware state. | Hardware logs are included in runtime data where available. |
| FR-MON-008 | The client shall run replay recording when enabled. | Replay requests can produce evidence artifacts and recorder state survives reconnect attempts. |

### 3.4 Incident Rules, Decisions, and Actions

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| FR-INC-001 | The system shall normalize incident rules with statuses `unknown`, `whitelist`, `warning`, and `blacklist`. | Rule data is normalized by common incident-rule logic. |
| FR-INC-002 | Whitelist rules shall suppress matching incident candidates before warning or blacklist rules are applied. | Browser New Tab and configured approved titles can suppress focused-window incidents. |
| FR-INC-003 | Warning and blacklist rules shall override severity and attach matched rule/action metadata. | Incident payloads include matched rule id and configured actions. |
| FR-INC-004 | The server shall persist incident rules in `data/server/incident_rules.json`. | Load, save, export, import, and version fields are supported. |
| FR-INC-005 | Tk and Qt dashboards shall expose an Incident Rules tab. | Operators can view rules, affected students, saved actions, and action availability. |
| FR-INC-006 | Incident History shall provide Save as Rule behavior. | Decision dialogs can prefill candidates from selected incidents and optionally save decisions to policy. |
| FR-INC-007 | The server shall apply configured incident actions where context allows. | Ban, kick, pause exam, and kill-pid actions are applied only with valid target context. |

### 3.5 Policy and Settings Requirements

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| FR-POL-001 | The server shall maintain normalized exam policy for process, focused-window, rapid switching, idle, unexpected process, process definitions, incident rules, and path clarification. | Policy load fills missing defaults and broadcasts version changes. |
| FR-POL-002 | Policy shall be editable through CLI and Tk/Qt settings windows. | GUI save requests and CLI apply commands use server-side update paths. |
| FR-POL-003 | Idle policy settings shall be present in policy configuration windows. | Operators can configure idle warning/critical thresholds and actions in UI. |
| FR-POL-004 | Policy export/import shall include process definitions and incident rules. | Settings bundles preserve relevant policy databases. |

### 3.6 Reconnect and Offline Buffering Requirements

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| FR-REC-001 | Disconnect shall be treated as network state, not as local runtime shutdown. | Local monitors, recorder, GUI bridge, and incident engine stay active. |
| FR-REC-002 | Incident reports generated while disconnected shall be persisted with stable sequence metadata. | Buffered incidents include `seq`, `queued_at`, and `buffered=true`. |
| FR-REC-003 | Buffered incidents shall flush in order after reconnect. | Unacknowledged entries remain on disk until the server sends acknowledgement. |
| FR-REC-004 | Pending evidence uploads shall persist and retry after reconnect. | Evidence status is not lost when the WebSocket reconnects. |
| FR-REC-005 | Restore logic shall avoid duplicate in-memory queue entries. | Repeated reconnects do not duplicate buffered incidents. |

### 3.7 Submission and Artifact Requirements

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| FR-SUB-001 | The client shall let students choose and preview final submission files. | Timer UI supports archive tree or text preview where possible. |
| FR-SUB-002 | The client shall build a submission bundle containing student work and runtime evidence. | Bundle manifest records included files and metadata. |
| FR-SUB-003 | The client shall upload final submissions by HTTP multipart request. | Server validates UUID, size, file type, and checksum where supplied. |
| FR-SUB-004 | The client shall upload runtime artifacts separately from final submissions. | Server stores artifacts and links them to incidents where applicable. |

### 3.8 Authentication and Admin Validation Requirements

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| FR-AUTH-001 | The client shall support CATS and AD preflight as configured by server status and local config. | If auth status cannot be fetched, client uses strict local auth behavior. |
| FR-AUTH-002 | The server shall expose `GET /auth/status?login_id=<id>`. | Response includes required checks, bypass expiries, allowed-user status, server time, validation status, and reason. |
| FR-AUTH-003 | The server shall support temporary CATS and AD disable commands. | `/disablecatsauth`, `/disableadauth`, `/disableauth`, and matching enable/status commands operate at runtime only. |
| FR-AUTH-004 | Disabled auth shall place matching login attempts into admin validation state. | Admin can approve or deny with `/approveauth` and `/denyauth`; passwords are not stored in validation queues. |
| FR-AUTH-005 | Approved validation shall be temporary. | Approval expiry is bounded and visible to server-side auth status logic. |

### 3.9 Local IPC and GUI Requirements

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| FR-IPC-001 | App-owned local IPC shall support loopback WebSocket transport. | IPC binds to `127.0.0.1`, uses a per-process token, and rejects invalid tokens. |
| FR-IPC-002 | App-owned local IPC shall preserve stdio fallback. | Transport `auto` uses WebSocket when env vars are present and stdio otherwise. |
| FR-IPC-003 | Local IPC messages shall use a structured envelope. | Envelope includes type, role, channel, id, reply-to, sequence, data, and optional error. |
| FR-UI-001 | Tk and Qt dashboards shall provide equivalent core workflows. | Both expose clients, incidents, process database, incident rules, settings, folder info, and commands. |
| FR-UI-002 | Dashboard live refresh shall preserve scroll, selection, focus, and horizontal scroll where possible. | Timer ticks update values in place; table rebuilds are avoided unless row identity/order changes. |
| FR-UI-003 | Table and list rows shall highlight across the full row on hover. | Tk Treeview and Qt table/tree widgets visually highlight the entire hovered row. |
| FR-UI-004 | Client timer UIs shall show exam-folder information after material extraction. | Tk and Qt timer windows expose an Exam Folder button when available. |

### 3.10 Projector Requirements

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| FR-PROJ-001 | The server shall serve a read-only projector page at `/projector`. | Page is usable in a browser and contains no admin controls. |
| FR-PROJ-002 | The server shall serve a read-only SSE feed at `/projector/events`. | Browser receives projection-safe JSON updates and auto-reconnects. |
| FR-PROJ-003 | Projector state shall include exam phase, start state, counts, server time, connection status, and public notifications. | State is generated from server-side data without exposing private identifiers. |
| FR-PROJ-004 | Projector frontend assets shall be split into HTML, CSS, and JavaScript files. | Server serves separate static projector files. |
| FR-PROJ-005 | Projector UI shall be readable on low-resolution large projection. | Layout uses high contrast, large type, and minimal dense detail. |

### 3.11 Offline Installer Requirements

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| FR-INS-001 | The offline installer shall provide a one-click batch entry point. | `install_offline.bat` elevates and invokes PowerShell installer logic. |
| FR-INS-002 | The installer shall install or use all-users Python without installing packages into global site-packages. | Packages are installed into `C:\ProgramData\May_04_Deniz\python_env`. |
| FR-INS-003 | The installer shall configure Python launcher and `.py` file association for all users when bundled Python is installed. | Python installer flags include all-users launcher and file association. |
| FR-INS-004 | The installer shall copy runnable app code to a controlled shared install folder. | Launchers execute from `C:\ProgramData\May_04_Deniz\app`, not from a user's Desktop source path. |
| FR-INS-005 | The installer shall separate read-only code/dependency permissions from writable runtime data. | Normal users receive read/execute on code, venv, FFmpeg, and launchers; modify access is limited to app data. |
| FR-INS-006 | The offline bundle shall verify bundled file integrity when a manifest exists. | Installer validates `manifest.sha256` before installing. |
| FR-INS-007 | The bundle builder shall prevent mixed Python wheelhouses. | Existing wheels are cleared before downloading a new target wheelhouse. |

## 4. Non-Functional Requirements

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| NFR-SEC-001 | Loopback IPC shall reject non-loopback peers. | Non-loopback peer addresses are rejected before IPC message handling. |
| NFR-SEC-002 | Loopback IPC shall require a random token. | Missing or invalid tokens are rejected. |
| NFR-SEC-003 | Sensitive WebSocket events shall support signing and encryption. | Secured envelopes include timestamp, nonce, signature, and optional ciphertext. |
| NFR-SEC-004 | Projector payloads shall not expose sensitive data. | Payloads omit login ids, UUIDs, IPs, process names, window titles, artifact paths, submission paths, and evidence details. |
| NFR-REL-001 | Reconnect shall not interrupt local monitoring or logging. | Logs keep growing during transient server disconnects. |
| NFR-REL-002 | Persistent state files shall be normalized on load. | Missing defaults and version fields are repaired. |
| NFR-UX-001 | Dashboard refresh shall not disrupt operator scrolling or selection. | Scrollbars do not teleport during routine updates. |
| NFR-UX-002 | Projector UI shall remain readable from projection distance. | Text size, contrast, and layout are optimized for 720p and similar displays. |
| NFR-OPS-001 | The system shall be rebuildable from documented dependencies and source. | Requirements, offline installer notes, and operations docs define setup. |
| NFR-COMP-001 | Offline wheels shall match target Python ABI and platform. | Python 3.14 use requires a rebuilt `cp314` wheelhouse; `cp313` wheels are not accepted as 3.14 compatible. |

## 5. External Interface Requirements

### 5.1 HTTP Interfaces

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/health` | Server identity and availability check. |
| GET | `/auth/status?login_id=<id>` | Auth requirement and validation status lookup. |
| POST | `/login` | Student login and session UUID assignment. |
| GET | `/exam/config?id=<uuid>` | Exam configuration retrieval. |
| GET | `/exam/files?id=<uuid>` | Exam materials download. |
| POST | `/exam/submission?id=<uuid>` | Final submission upload. |
| POST | `/client/artifact?id=<uuid>` | Runtime artifact or evidence upload. |
| GET | `/ws?id=<uuid>` | LAN WebSocket runtime connection. |
| GET | `/projector` | Read-only projector page. |
| GET | `/projector/events` | Projection-safe SSE state feed. |

### 5.2 LAN WebSocket Event Families

Server-to-client events include welcome, time broadcast, error, exam policy,
policy update, replay request, sync time, session state, pause, resume, exam end,
process request, blacklist update, incident acknowledgement, kill-process, and
finish-exam prompts.

Client-to-server events include ping, client info, policy applied, start exam,
process catch, incident report, monitor event, and kill-process result.

### 5.3 Loopback IPC Channels

| Channel | Direction | Purpose |
| --- | --- | --- |
| `manager.console_command` | Manager UI to CLI process | Sends console commands. |
| `server.dashboard_state` | Server CLI to dashboard UI | Pushes dashboard state and output. |
| `dashboard.command` | Dashboard UI to server CLI | Sends structured dashboard actions. |
| `client.timer_state` | Client CLI to timer UI | Pushes timer, upload, and folder state. |
| `timer.command` | Timer UI to client CLI | Sends student UI actions. |
| `process.lifecycle` | Parent/child processes | Sends lifecycle notifications. |

### 5.4 Operator Commands

The server shall support commands for listing clients, saving replays, showing
exam status, adding time, pausing/resuming exams, killing PIDs, starting and
finishing exam globally, opening GUI, editing/applying policy databases,
exporting/importing settings, temporary auth disable/enable/status, auth request
approval/denial, kicking, banning, unbanning, forgiving violations, security
commands, and help.

## 6. Data Requirements

| Data Path | Owner | Requirement |
| --- | --- | --- |
| `data/server/server_users.json` | Server | Persist registered users and session state. |
| `data/server/incidents.jsonl` | Server | Append incident history. |
| `data/server/exam_policy.json` | Server/operator | Persist normalized exam policy. |
| `data/server/process_blacklist.txt` | Server/operator | Persist legacy process blacklist. |
| `data/server/process_definitions.json` | Server/operator | Persist process definition database. |
| `data/server/incident_rules.json` | Server/operator | Persist incident rule database. |
| `data/server/artifacts/*` | Server | Store uploaded runtime evidence. |
| `data/server/submissions/*` | Server | Store final submissions. |
| `data/client/{uuid}/buffer/*` | Client | Persist buffered incidents and evidence retry state. |
| `data/client/{uuid}/recordings/*` | Client | Store replay cache and saved replays. |
| `data/client/{uuid}/exam_files/*` | Client | Store downloaded exam ZIP copy and metadata. |
| `Desktop/Exam/DD-MM-YYYY` | Client/student | Store extracted exam materials. |

## 7. Acceptance and Validation

### 7.1 Automated Validation

The current expected validation commands are:

```powershell
cd May_04_Deniz
python -m compileall -q .
python -m unittest discover -s tests
python -m pip check
```

The latest local validation result recorded while preparing this package was:

- `python -m compileall -q .`: passed.
- `python -m unittest discover -s tests`: 168 tests passed.
- `python -m pip check`: no broken requirements found.

### 7.2 Manual Validation

Manual smoke validation should cover:

- server launcher Tk and Qt,
- client launcher Tk and Qt,
- login/auth validation flows,
- `/disablecatsauth`, `/disableadauth`, `/disableauth`, `/approveauth`,
  `/denyauth`, and `/authstatus`,
- `/startexam` and `/finishexam`,
- process blacklist and wildcard executable matching,
- titlebar incident rule saving with reusable contains patterns,
- dashboard hover/scroll behavior,
- reconnect logging and buffered incident flush,
- exam material extraction to Desktop Exam folder,
- final submission upload,
- projector page at `/projector`,
- offline installer dry-run or controlled VM install.

## 8. Traceability Summary

| Area | Requirement IDs | Primary Modules | Primary Tests |
| --- | --- | --- | --- |
| Server runtime | FR-SRV-* | `server.main`, `server.app`, `server.handlers`, `server.tasks`, `server.state` | `tests/unit/test_server_*` |
| Client runtime | FR-CLI-* | `client.main`, `client.ws_client`, `client.preflight`, `client.exam` | `tests/integration/test_client_main.py`, client unit tests |
| Monitoring | FR-MON-* | `client.custommodules`, `client.incidents`, `common.text_safety`, `common.process_definitions` | `test_client_incidents`, `test_focused_window_monitor`, `test_process_database` |
| Incident rules | FR-INC-* | `common.incident_rules`, `server.state`, `server.ui`, `client.incidents` | `test_incident_rules`, `test_process_database` |
| Reconnect/buffer | FR-REC-* | `client.runtime`, `client.incident_buffer`, `client.ws_client` | `test_incident_buffer`, reconnect tests |
| Submission/artifacts | FR-SUB-* | `client.submission`, `client.transfers`, `server.handlers` | `test_transfers`, `test_upload_multipart_order` |
| Auth validation | FR-AUTH-* | `server.auth_validation`, `server.tasks`, `server.handlers`, `client.preflight` | `test_auth_bypass` |
| IPC/UI | FR-IPC-*, FR-UI-* | `common.ipc_ws`, `launcher_ui`, `server.ui`, `client.ui` | `test_ipc_ws`, `test_row_refresh` |
| Projector | FR-PROJ-* | `server.projector`, `server.static.projector`, `server.app` | `test_projector` |
| Installer | FR-INS-* | `offline_installer` | PowerShell parse, pip dry-run, manifest verification |

