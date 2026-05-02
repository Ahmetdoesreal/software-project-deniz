# Repository Comparison Report

Date: 2026-05-02

Compared repositories:

- Mine/current runtime: top-level `client/`, `server/`, `common/`, `custommodules/`, `tests/`, and launchers in this repository.
- EnginErkurt: `.codex_compare_repos/EnginErkurt-Software-Engineering`
- Akiren7: `.codex_compare_repos/Akiren7-software-enginnering-project`

Historic folders in this repository (`third_iteration/`, `to-be-implemented/`, `extras_new/`, `baris_files/`, `deliver_to_baris/`, `clean_iteration/`, `near final delivery/`, `May_01/`) were checked separately from the active runtime.

## Executive Summary

Your active top-level project already includes most of the important runtime features from the two comparison repositories, but not all of them. The current app is also more production-shaped than either comparison repo: it has a modular `client/server/common` layout, session-state handling, policy-driven incidents, runtime evidence uploads, process kill commands, GUI integration, and tests.

The strongest evidence of shared/copied active code is:

- `Akiren7/protocol.py` is an exact code match with `common/protocol.py`.
- `Akiren7/runtime_logging.py` and `EnginErkurt/runtime_logging.py` are exact code matches with `common/runtime_logging.py`.
- `Akiren7/events.py` is a near-exact match with `common/events.py` at about `0.99` similarity.
- Both repos' `discovery.py` are strongly related to `common/discovery_v2.py` at about `0.908` similarity, but the active file is modified.

Most other exact matches are not in your active runtime. They live in archive/integration folders such as `third_iteration/`, `to-be-implemented/`, `baris_files/`, `deliver_to_baris/`, and `extras_new/`.

The most useful missing features to add from their implementations are:

1. Reliable outbound event buffering with `seq`, `session_id`, `buffered`, and `queued_at`.
2. A durable SQLite audit/review database layer.
3. Instructor role-based authorization for admin actions.
4. Idle-time monitoring and idle violation rules.
5. Optional CATS/Orion school authentication, if the project must validate against the real school system.
6. Same-IP/multiple-student login prevention.
7. Post-exam review notes/report screens.

## Method

I compared files using:

- Exact normalized text hashes.
- Exact normalized Python-code hashes, ignoring blank/comment-only lines and whitespace differences.
- Near-duplicate similarity over normalized Python code.
- Manual feature tracing through active modules and comparison modules.

File counts used in the scan:

- Active current source files: `72`
- Current plus relevant archive/snapshot files: `393`
- EnginErkurt comparison source files: `18`
- Akiren7 comparison source files: `37`
- Exact text matches found in current/archive scope: `21`
- Exact normalized code matches found in current/archive scope: `21`

## Code Reuse Evidence

### Active Runtime Matches

These files are used by your active top-level runtime.

| External file | Active file | Evidence | Interpretation |
|---|---|---:|---|
| `Akiren7/protocol.py` | `common/protocol.py` | exact, `1.0` | Active code is copied/shared from Akiren7 lineage. |
| `Akiren7/runtime_logging.py` | `common/runtime_logging.py` | exact, `1.0` | Active code is copied/shared. |
| `EnginErkurt/runtime_logging.py` | `common/runtime_logging.py` | exact, `1.0` | Same shared runtime logging code exists in both repos. |
| `Akiren7/events.py` | `common/events.py` | near match, `0.99` | Active code is clearly derived/shared, with small changes. |
| `Akiren7/discovery.py` | `common/discovery_v2.py` | near match, `0.908` | Active discovery is derived from the same implementation but modified. |
| `EnginErkurt/discovery.py` | `common/discovery_v2.py` | near match, `0.908` | Same discovery lineage. |
| `EnginErkurt/protocol.py` | `common/protocol.py` | near match, `0.829` | Shared base, but Akiren7 version is the exact active match. |

### Archive/Snapshot Matches

These files exist in your repository but are not part of the active top-level runtime unless manually imported.

| External file | Matching local archive files | Evidence |
|---|---|---:|
| `activity_monitor.py` | `third_iteration/baris/activity_monitor.py` | exact |
| `auth_client.py` | `to-be-implemented/naz/auth_client (1).py`, `third_iteration/naz/auth_client.py` | exact |
| `security_layer.py` | `to-be-implemented/naz/security_layer (1).py`, `third_iteration/naz/security_layer.py` | exact |
| `test_naz_modules.py` | `to-be-implemented/naz/test_naz_modules(1) (1).py`, `third_iteration/naz/test_naz_modules.py` | exact |
| `db_manager.py` | `baris_files/db_manager.py`, `deliver_to_baris/db_manager.py`, `third_iteration/mert/db_manager.py`, `extras_new/baris/db_manager_baris (1).py` | exact |
| `school_service.py` | `baris_files/school_service.py`, `deliver_to_baris/school_service.py`, `third_iteration/baris/school_service.py`, `extras_new/baris/school_service_baris (1).py` | exact or near-exact |
| `payload_builder.py` | `third_iteration/baris/payload_builder.py` | exact or near-exact |
| `instructor_auth.py` | `third_iteration/naz/instructor_auth.py` | near match, about `0.994` |
| `server_core.py` | `baris_files/server_core.py`, `deliver_to_baris/server_core.py`, `third_iteration/baris/server_core.py`, `extras_new/baris/server_core_baris_2 (1).py` | near match, `0.923-0.994` |
| `Deneme-dosyalari/monitor_loop_eski.py` | `to-be-implemented/engin/monitor_loop (1).py` | exact |
| `Deneme-dosyalari/network_sender_eski.py` | `to-be-implemented/naz/network_sender (2).py` | near exact, `0.999` |

Note: `Akiren7/components/main.py` is empty, so its exact match with several empty local files is not meaningful evidence of code reuse.

## Feature Matrix

| Feature | External repos | Your active runtime | Status |
|---|---|---|---|
| JSON event protocol with checksum | `protocol.py` | `common/protocol.py` | Included. Exact/derived code. Current version also preserves `seq`, `session_id`, `buffered`, `queued_at`. |
| Event constructors | `events.py` | `common/events.py` | Included and expanded. Current has incidents, pause/resume, kill-process, finish-exam. |
| Runtime JSONL logging | `runtime_logging.py` | `common/runtime_logging.py` | Included. Exact code. |
| UDP discovery / duplicate server guard | `discovery.py` | `common/discovery_v2.py`, `common/discovery.py` | Included and modified. Current version is active through a compatibility import. |
| HMAC/encrypted transport | `security_layer.py` | `common/security.py` | Included differently. Current implementation is session-derived, supports nonces/replay protection, and wraps protocol events. |
| Student authentication | `auth_client.py`, `school_service.py` | `client/auth.py`, `server/handlers.py` | Partial. Current uses static `allowed_users.json`; external has CATS/Orion scraping and credential-signing modules. |
| Instructor RBAC | `instructor_auth.py` | CLI/GUI admin commands in `server/tasks.py` | Missing as RBAC. Current has admin controls, but no instructor token/role enforcement. |
| Waiting room / global start | `server_core.py`, `network_sender.py` | `server/tasks.py`, `server/handlers.py`, `client/ws_client.py` | Included. Current uses `exam_phase` and client start requests. |
| Duration changes | `change_duration` in `server_core.py` | `/addtime` in `server/tasks.py` | Partial. Current supports per-user added time, not exam-id-wide duration changes. |
| Resume/forgive violation | `resume_student` | `/resumeexam`, `/forgiveviolation` | Included and stronger. Current syncs session state back to the client. |
| Disconnect handling | `disconnected_paused` in `server_core.py` | `server/session_state.py`, `server/handlers.py` | Included. Current supports reconnect state and optional auto-resume. |
| Real-time monitoring payload builder | `activity_monitor.py`, `payload_builder.py`, `monitor_loop.py` | `custommodules/process_monitor`, `focused_window_monitor`, `hardware_monitor`, `client/incidents.py` | Included differently. Current is more structured, but lacks idle-time rules and an exam-process-closed rule. |
| Process blacklist detection | `payload_builder.py` banned apps | `ProcessMonitor`, `ClientIncidentEngine`, server policy | Included and stronger. Current supports runtime policy updates and process owner filtering. |
| Focus-lost detection | `payload_builder.py` | `ClientIncidentEngine.observe_focused_window()` | Included, but current focus capture is Windows-only. External had Linux/macOS fallbacks. |
| Rapid app switching detection | Not present in external implementation | `ClientIncidentEngine` | Current-only feature. |
| Unexpected process detection | Not present in external implementation | `ClientIncidentEngine` | Current-only feature. |
| Idle detection | `ActivityMonitor.get_idle_seconds()` and `IDLE_WARN/IDLE_CRITICAL` | No active idle monitor/rule | Missing. |
| Reliable transfer buffering | `NetworkSender`, `OutboundBuffer`, `seq`, `buffered`, `queued_at` | Protocol tolerates fields, but `client/ws_client.py` does not implement a queue/flush layer | Missing/partial. This is the biggest Engin-feature gap. |
| SQLite persistence and audit review | `db_manager.py` | JSON files in `server/state.py`: users, incidents JSONL, audit JSONL | Partial. Current persists data, but lacks normalized SQLite queries and post-exam reconstruction helpers. |
| Same-IP anti-cheat | `server_core.py` blocks another student from same IP | Current blocks duplicate login/session UUID, not same IP across different users | Missing. |
| Dashboard | PyQt component files in Akiren repo | `server_gui.py`, `client_gui.py` | Included differently. Current GUI is integrated and more complete for live operations. |
| Post-exam report components | Akiren component names imply report/timeline/status cards | Current GUI has incident history/details, but no explicit post-exam review workflow or notes | Partial/missing. |
| Hardware monitoring | Not in comparison repos | `custommodules/hardware_monitor` | Current-only feature. |
| Replay recording/evidence bundles | Not in comparison repos | `custommodules/replay_recorder`, `client/transfers.py`, artifact upload routes | Current-only feature. |
| Submission upload with checksum | Not central in comparison repos | `client/submission.py`, `client/transfers.py`, `server/submissions.py`, `server/handlers.py` | Current-only/stronger. |

## Implementation Quality Notes

Your active runtime is not just a direct copy of the comparison repos. It appears to be an integrated later version:

- The active code is modular instead of monolithic (`server_core.py` was split into server handlers, tasks, state, submissions, session state, and common modules).
- Security is more careful than the older `security_layer.py`: it derives per-session keys and rejects replayed nonces.
- Incident detection is policy-driven and emits lifecycle events (`opened`, `resolved`) instead of one-shot flag strings.
- Evidence handling is stronger: incident bundles, requested process reports, hardware snapshots, replay clips, and submission bundles.
- Tests exist for protocol integrity, session state, process monitor behavior, transfer packaging, and server handlers.

The main thing your active project does not yet have is Engin-style reliable queued delivery. The protocol has fields for it, but the client does not yet use them as an ordered offline buffer.

## Missing Features To Add

### 1. Reliable outbound event buffering

Source inspiration: `Akiren7/network_sender.py`, `EnginErkurt/network_sender.py`, `Tasks/Engin.txt`.

Add to current runtime:

- A client-side outbound queue for important events.
- Monotonic `seq`.
- Stable `session_id` per client websocket session.
- `queued_at` timestamp.
- `buffered: true` when an event is sent after reconnect/delay.
- Ordered flush after reconnection.
- Server-side audit of these fields.

Do not copy the old `NetworkSender` directly. It targets the old monolithic client/server shape. Adapt the behavior into `client/ws_client.py` or a new small helper module.

### 2. SQLite audit/review database

Source inspiration: `Akiren7/db_manager.py`, `Tasks/Mert.txt`.

Add to current runtime:

- Tables for exam sessions, student sessions, raw monitoring events, interpreted incidents, instructor actions, submissions, and audit log.
- Query helpers to reconstruct a student's timeline.
- Integration points from `server/handlers.py` and `server/tasks.py`.

This should complement the current JSON/JSONL files or replace them through a migration plan. A direct drop-in of old `db_manager.py` would not match the current data model.

### 3. Instructor RBAC and auditable admin auth

Source inspiration: `instructor_auth.py`, `Tasks/Naz.txt`.

Add to current runtime:

- Instructor/admin identity model.
- Signed or token-based admin actions.
- Role checks for start exam, finish exam, add time, pause/resume, kill process, ban/kick, edit policies, and read incident history.
- Security audit events for denied actions and token/session expiry.

Current admin operations are local CLI/GUI commands, so this becomes important if the instructor panel can be remote or multi-user.

### 4. Idle-time monitoring and idle incidents

Source inspiration: `activity_monitor.py`, `payload_builder.py`, `Tasks/Deniz.txt`.

Add to current runtime:

- `custommodules/idle_monitor`.
- Windows implementation using `GetLastInputInfo`.
- Linux/macOS best-effort support if those platforms are in scope.
- Policy rules for `idle_warning` and `idle_critical`.
- Incident lifecycle events and evidence bundles.

### 5. Exam-process-closed / client-integrity rule

Source inspiration: `payload_builder.py`.

Add a rule that confirms required exam processes/windows are still present. This can be integrated with current `ProcessMonitor` and `FocusedWindowMonitor`.

### 6. Same-IP duplicate login defense

Source inspiration: `server_core.py`.

Current code rejects the same login being active twice, but it does not reject two different students from the same IP. Add a configurable policy such as:

- `allow_multiple_students_per_ip: false`
- exceptions for lab NAT/proxy environments
- audit logging for rejected attempts

### 7. Post-exam review workflow

Source inspiration: `Tasks/Irem.txt`, `Tasks/Rana.txt`, and Akiren UI component intent.

Current GUI already lists incidents, details, auto-actions, and artifacts. Missing review features:

- Filter by student, severity, active/resolved, rule.
- Per-student chronological timeline.
- Instructor notes/final decision fields.
- Exportable review report.

## Features Not Worth Copying Directly

- The monolithic `server_core.py`: your current server is cleaner and should stay modular.
- The old `network_sender.py` as-is: useful behavior, but wrong integration shape for current `client/ws_client.py`.
- The old `payload_builder.py` as-is: the current policy engine is better; only port the missing rule concepts.
- Direct CATS scraping without a clear requirement: it handles real credentials and depends on external HTML structure.
- The old timer freeze behavior: the comparison report itself flags disconnected/violation timer freezing as a cheat risk. Your current app also intentionally freezes paused states, so this is a policy decision, not something to copy blindly.

## Recommended Implementation Order

1. Add reliable outbound event buffering.
2. Add SQLite audit/review storage.
3. Add idle monitoring and idle incident rules.
4. Add instructor RBAC around admin commands.
5. Add same-IP duplicate-student policy.
6. Add post-exam review/report UI.
7. Consider CATS/Orion only if required by the course/demo.

This order gives the biggest functional improvement while preserving your current architecture.
