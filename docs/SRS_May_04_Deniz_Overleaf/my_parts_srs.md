# Contributor Software Requirements Specification Copy

Project: `May_04_Deniz` Exam Monitoring and Management Platform

Document type: Contributor-focused SRS copy

Prepared for: individual contribution report / assigned parts

Date: 2026-05-12

## Editable Cover Information

| Field | Value |
| --- | --- |
| Contributor name | Replace with your name |
| Student number | Replace with your student number |
| Course | Replace with course name |
| Supervisor / instructor | Replace if required |
| Project repository | `May_04_Deniz` |

## 1. Purpose

This document is a copy of the project SRS focused on the parts that can be
presented as an individual contribution. It does not replace the full-project
SRS. Instead, it extracts the requirements, interfaces, constraints, and
validation points most relevant to the recent implementation areas.

If the actual assigned parts differ, update Section 2 and keep the requirement
IDs stable where possible.

## 2. Contributor Scope

The contributor scope covered by this copy is:

| Area | Description |
| --- | --- |
| Incident rules and titlebar matching | Definition-based rules for focused-window/titlebar incidents, whitelist/warning/blacklist behavior, Save as Rule logic, reusable contains patterns, and browser-title handling. |
| Process/executable matching | Wildcard-style executable matching for process definitions and blacklist-style behavior, including desktop app variants. |
| Dashboard UX stability | Full-row hover behavior and non-disruptive refresh for client, incident, process database, and incident rule lists. |
| Auth validation and temporary disable | Temporary CATS/AD disable with admin-managed validation and approval/denial flow. |
| Reconnect and buffering | Keeping local logging active during disconnects and preserving incident/evidence buffers. |
| Exam materials and folder info | Safe extraction of exam materials to the student Desktop Exam folder and UI folder information. |
| Projector frontend | Read-only projection-safe notification page with separated HTML, CSS, and JavaScript. |
| Offline installer hardening | Shared all-users install layout, shared venv, integrity manifest, package compatibility checks, and safe permissions. |

## 3. Functional Requirements for Contributor Scope

### 3.1 Incident Rules and Titlebar Matching

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| MY-FR-INC-001 | The system shall represent titlebar and incident behavior as reusable incident rules. | Rules include status, match mode, event type, source, title patterns, process restrictions, priority, and actions. |
| MY-FR-INC-002 | Whitelist incident rules shall suppress matching incident candidates before warning or blacklist rules. | Approved browser titles such as New Tab can suppress focused-window incidents. |
| MY-FR-INC-003 | Saved titlebar rules shall prefer reusable `contains` patterns. | Saving a WhatsApp titlebar incident can produce a pattern such as `whatsapp` instead of the full observed title. |
| MY-FR-INC-004 | Title normalization shall handle Unicode and invisible/control characters. | Edge/Yandex/browser titles with unusual spacing do not break matching or stop the incident system. |
| MY-FR-INC-005 | Incident History shall provide Save as Rule behavior. | The selected incident can prefill a rule decision dialog, and the admin can save it to policy. |
| MY-FR-INC-006 | Incident-rule actions shall be saved and applied where context allows. | Ban, kick, pause exam, and kill-pid actions remain configurable and context-checked. |

### 3.2 Process and Executable Matching

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| MY-FR-PROC-001 | Process matching shall support wildcard-style executable patterns. | One entry can match related executables such as WhatsApp desktop variants. |
| MY-FR-PROC-002 | Process definition behavior shall remain backward compatible with exact and contains matching. | Existing process definitions and blacklist entries continue to work. |
| MY-FR-PROC-003 | Process rules shall integrate with incidents and configured actions. | Matched processes can open incidents and trigger configured actions. |

### 3.3 Dashboard UX Stability

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| MY-FR-UI-001 | Tk and Qt lists shall highlight the full row on hover. | Hover feedback covers all visible cells, not only the current cell. |
| MY-FR-UI-002 | Live dashboard updates shall avoid full table rebuilds when row identity and order have not changed. | Timers and state updates update row values in place. |
| MY-FR-UI-003 | Scroll position, horizontal scroll, focus, and selection shall be preserved during unavoidable rebuilds. | User scrolling does not reset every second during normal updates. |
| MY-FR-UI-004 | Sorting and filtering shall remain available. | Explicit user sorting/filtering continues to work while automatic countdown ticks avoid disruptive resorting. |

### 3.4 Auth Validation and Temporary Disable

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| MY-FR-AUTH-001 | The server shall expose current auth requirements to clients before login. | `/auth/status?login_id=<id>` reports CATS/AD required flags, bypass expiry, allowed-user status, validation status, and reason. |
| MY-FR-AUTH-002 | Temporarily disabled auth shall not automatically admit a user. | Matching login attempts enter admin validation state. |
| MY-FR-AUTH-003 | Admins shall approve or deny pending auth validation requests. | `/authrequests`, `/approveauth`, and `/denyauth` control the queue. |
| MY-FR-AUTH-004 | Client-side UI/preflight shall reflect server auth status. | If the server says validation is pending or required, the client shows/waits instead of reporting that normal AD/CATS auth is still required. |

### 3.5 Reconnect, Offline Buffering, and Evidence

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| MY-FR-REC-001 | A WebSocket disconnect shall not stop local monitoring or local logs. | Process, focus, idle, hardware, exam-state, GUI, replay, and incident components remain active. |
| MY-FR-REC-002 | Incidents generated while disconnected shall be queued persistently. | Buffered incidents include sequence, queued time, and buffered flag. |
| MY-FR-REC-003 | Evidence upload state shall survive reconnect attempts. | Pending evidence is retried after reconnect. |
| MY-FR-REC-004 | Repeated reconnects shall not duplicate buffered incident entries. | Restore logic deduplicates entries. |

### 3.6 Exam Folder and Folder Info

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| MY-FR-FILE-001 | Downloaded exam materials shall be copied under client data and safely extracted to Desktop Exam folder. | ZIP traversal, absolute paths, drive-letter paths, and unsafe names are rejected. |
| MY-FR-FILE-002 | Existing unmarked user folders shall not be deleted. | The extractor creates a safe suffixed folder when needed. |
| MY-FR-FILE-003 | Client UI shall show an Exam Folder button after extraction. | The button displays or opens the extracted folder path. |
| MY-FR-FILE-004 | Server dashboard shall show folder information for selected users. | Operator can inspect server-side submission/artifact paths and expected client-side exam folder. |

### 3.7 Projector Frontend

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| MY-FR-PROJ-001 | The server shall provide a read-only projector page. | `/projector` serves a browser page with no mutating controls. |
| MY-FR-PROJ-002 | Projector frontend files shall be separated. | HTML, CSS, and JavaScript are served as separate files. |
| MY-FR-PROJ-003 | Projector state shall be projection-safe. | It contains aggregate counts and generic notifications, not private data. |
| MY-FR-PROJ-004 | Projector layout shall be suitable for low-resolution projection. | Large text, high contrast, and minimal dense detail are used. |

### 3.8 Offline Installer Hardening

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| MY-FR-INS-001 | The installer shall use a shared virtual environment instead of global machine site-packages. | Packages install into `C:\ProgramData\May_04_Deniz\python_env`. |
| MY-FR-INS-002 | Launchers shall run from the installed shared app folder. | Launchers use `C:\ProgramData\May_04_Deniz\app` instead of a Desktop source path. |
| MY-FR-INS-003 | Installer permissions shall separate code from runtime data. | Normal users get read/execute for code and dependencies; modify access is limited to `app\data`. |
| MY-FR-INS-004 | The installer shall verify bundled file integrity when a manifest is present. | `manifest.sha256` is checked before installation. |
| MY-FR-INS-005 | Wheelhouse content shall match target Python version and platform. | Python 3.14 requires a rebuilt `cp314` wheelhouse; `cp313` wheels are not treated as compatible. |

## 4. Non-Functional Requirements for Contributor Scope

| ID | Requirement | Acceptance Criteria |
| --- | --- | --- |
| MY-NFR-SEC-001 | Projector payloads shall avoid private and evidentiary information. | No login id, UUID, IP, process name, window title, path, or evidence field appears in projector state. |
| MY-NFR-SEC-002 | Temporary auth disable shall be bounded and admin controlled. | Disable windows expire and do not persist to configuration files. |
| MY-NFR-REL-001 | Reconnect behavior shall preserve local evidence. | Buffered incidents and pending evidence survive transient network failures. |
| MY-NFR-UX-001 | Dashboard lists shall remain usable during live updates. | Scrollbars and selections do not reset during normal updates. |
| MY-NFR-COMP-001 | Offline installer dependencies shall avoid machine-wide pip conflicts. | Dependencies are installed into the project venv only. |

## 5. Interfaces in Contributor Scope

### 5.1 HTTP

| Route | Use |
| --- | --- |
| `/auth/status?login_id=<id>` | Client checks auth requirements and validation status before login. |
| `/projector` | Browser opens read-only projection page. |
| `/projector/events` | Browser receives SSE state updates. |
| `/exam/files?id=<uuid>` | Client downloads exam material ZIP for safe extraction. |
| `/client/artifact?id=<uuid>` | Client uploads incident or replay evidence. |

### 5.2 CLI Commands

| Command | Use |
| --- | --- |
| `/disablecatsauth [seconds]` | Temporarily disable CATS preflight and require admin validation. |
| `/disableadauth [seconds]` | Temporarily disable AD auth and require admin validation. |
| `/disableauth [seconds]` | Temporarily disable both CATS and AD auth paths. |
| `/enablecatsauth` | Re-enable CATS preflight. |
| `/enableadauth` | Re-enable AD auth. |
| `/enableauth` | Re-enable both auth paths. |
| `/authstatus` | Show auth bypass/validation status. |
| `/authrequests` | List pending or recent validation requests. |
| `/approveauth <id> [seconds]` | Temporarily approve a pending auth validation. |
| `/denyauth <id> [reason]` | Deny a pending auth validation. |
| `/editincidentrules` | Open incident rule database. |
| `/applyincidentrules` | Reload and broadcast incident rules. |

### 5.3 Files

| File or Folder | Use |
| --- | --- |
| `data/server/incident_rules.json` | Incident rule database. |
| `data/server/exam_policy.json` | Policy source for focused-window, idle, and process behavior. |
| `data/server/process_definitions.json` | Process definition database. |
| `data/client/{uuid}/buffer/*` | Offline incident and evidence retry buffer. |
| `Desktop/Exam/DD-MM-YYYY` | Extracted exam materials. |
| `server/static/projector/index.html` | Projector page. |
| `server/static/projector/projector.css` | Projector styles. |
| `server/static/projector/projector.js` | Projector update logic. |
| `offline_installer/manifest.sha256` | Offline bundle integrity manifest. |

## 6. Validation Plan for Contributor Scope

### 6.1 Automated Tests

Expected validation commands:

```powershell
cd May_04_Deniz
python -m compileall -q .
python -m unittest discover -s tests
python -m pip check
```

Relevant test groups include:

- incident rule normalization and matching,
- focused-window Unicode/titlebar normalization,
- client incident generation and buffering,
- auth bypass/admin validation,
- projector payload safety and HTTP routes,
- process wildcard matching,
- dashboard row refresh helper behavior,
- server task command behavior,
- offline package dry-run and manifest verification.

### 6.2 Manual Tests

Manual checks for this contributor scope:

- Add `whatsapp` as a contains title pattern and verify browser title variants match.
- Add a wildcard executable entry for WhatsApp desktop variants and verify it catches matching processes.
- Scroll client and incident lists while timer updates arrive and verify the scrollbar does not reset.
- Hover rows in Tk and Qt tables and verify the entire row highlights.
- Run `/disableauth`, attempt client login, approve through admin validation, and verify admission.
- Disconnect the server during an exam and verify client-side logs continue growing.
- Generate an incident while disconnected and verify it flushes after reconnect.
- Download exam materials and verify safe Desktop Exam extraction.
- Open `/projector` at 1280x720 and 1024x768 and verify readability and privacy.
- Run offline installer checks in a VM or controlled admin environment.

## 7. Traceability to Full SRS

| Contributor Area | Full SRS IDs |
| --- | --- |
| Incident rules/titlebar | FR-MON-003 to FR-MON-005, FR-INC-001 to FR-INC-007 |
| Process executable matching | FR-MON-001 to FR-MON-002 |
| Dashboard UX stability | FR-UI-001 to FR-UI-003, NFR-UX-001 |
| Auth validation | FR-AUTH-001 to FR-AUTH-005 |
| Reconnect and buffering | FR-REC-001 to FR-REC-005 |
| Exam folder info | FR-CLI-005, FR-UI-004 |
| Projector frontend | FR-PROJ-001 to FR-PROJ-005 |
| Offline installer | FR-INS-001 to FR-INS-007, NFR-COMP-001 |

