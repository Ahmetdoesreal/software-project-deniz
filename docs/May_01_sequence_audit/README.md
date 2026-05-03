# May_01 Sequence Audit

This folder explains how the `May_01` version of the project behaves while an exam is running.

The goal is simple: if something breaks during a live exam, you should be able to open these docs and quickly answer:

- What was supposed to happen?
- Which client/server files are involved?
- What files or uploads should have been produced?
- What overload or edge case might explain the failure?
- Which tests cover the behavior?

## Start Here

- [Coverage Matrix](COVERAGE_MATRIX.md): a lookup table for routes, events, commands, and their sequence docs.
- [Risk Register](RISK_REGISTER.md): the bugs and overload risks found during the audit, written as practical failure stories.
- [Fix Plan](FIX_PLAN.md): what was fixed, what was tested, and what remains worth improving later.

## Sequence Guides

Read these like short walkthroughs of the system:

- [Server startup and shutdown](sequences/01_server_startup_shutdown.md)
  Explains server boot, duplicate-server checks, GUI launch, and the shutdown flush that asks clients for final evidence.
- [Client startup, WebSocket, and policy sync](sequences/02_client_startup_ws_policy.md)
  Explains discovery, login, exam-file download, recorder startup, WebSocket connection, and first policy sync.
- [Exam timer and session state](sequences/03_exam_timer_session.md)
  Explains start, pause, resume, add-time, finish, disconnect, and reconnect.
- [Replay, savescreen, and artifacts](sequences/04_replay_savescreen_artifacts.md)
  Explains `/savescreen`, FFmpeg replay saving, fallback files, process reports, and artifact upload.
- [Monitoring, incidents, and process actions](sequences/05_monitoring_incidents_process_actions.md)
  Explains process/focus/hardware monitoring, incident evidence, auto-pause, kill PID, kick, ban, and policy decisions.
- [Final submission and uploads](sequences/06_submission_uploads.md)
  Explains final packaging, checksums, multipart upload, server validation, and client exit.

## What Changed During This Audit

Four overload-sensitive areas were hardened:

- Replay saves now have priorities. Final submission gets first chance, then incident evidence, then optional admin-requested saves.
- Repeated `/savescreen` requests no longer create an unlimited backlog.
- Incidents are reported immediately. Evidence uploads happen in the background and send a follow-up status.
- Server shutdown now waits long enough for realistic replay saves and uploads by default.
- Submission and incident bundles now use unique names even when created in the same second.

## Verification

After the changes:

- Focused compile check: passed.
- Focused touched-path tests: `30 tests OK`.
- Full `May_01` test discovery: `101 tests OK`.

Before these changes, the baseline full suite was also passing with `93 tests OK`; the extra tests are regression coverage for the new hardening.
