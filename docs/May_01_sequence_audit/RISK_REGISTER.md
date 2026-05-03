# Risk Register

This page describes the main ways the system can fail under pressure. Each item is written as a practical story: what you would see, why it happens, and what protects the system now.

## R01: Final Submission Waits Behind Savescreens

**Severity:** High

**What you would see:** A student clicks finish, but the client appears slow while saving the final replay.

**Why it happens:** Replay saving uses FFmpeg. FFmpeg should not be called in parallel for the same recorder, so saves are queued. Before the fix, optional admin savescreens and final submission replay saves used the same queue priority.

**Overload trigger:** Repeated `/savescreen all`, repeated GUI savescreen clicks, or shutdown savescreen requests while FFmpeg is slow.

**Protection now:** Replay saves are prioritized. Final submission goes before incident evidence, and both go before optional requested saves.

## R02: Too Many Optional Savescreens Build A Backlog

**Severity:** High

**What you would see:** Many savescreen requests are accepted, but the client spends a long time catching up.

**Why it happens:** Optional saves used to have no queue limit.

**Overload trigger:** Large class plus repeated admin savescreen requests.

**Protection now:** Optional saves are bounded. If the optional queue is full, the client drops the extra optional save and returns `None`.

## R03: Incident Response Waits For Evidence Upload

**Severity:** High

**What you would see:** A violation happens, but server-side pause or process action arrives late.

**Why it happens:** The client used to wait for evidence creation and upload before sending the incident report.

**Overload trigger:** FFmpeg timeout, replay queue backlog, slow LAN upload, or large evidence bundle.

**Protection now:** The client reports the incident immediately with `evidence_status="pending"`. Evidence uploads in the background and sends a later update.

## R04: Evidence Update Replaces Active Incident

**Severity:** Medium

**What you would see:** The server has evidence for an incident, but the active incident status may no longer look like the original opened violation.

**Why it happens:** The server treated every non-resolved incident status as the active incident state.

**Protection now:** Evidence-only updates merge artifact fields into the active opened incident instead of replacing it.

## R05: Shutdown Does Not Wait Long Enough

**Severity:** High

**What you would see:** Shutdown asks clients for process reports and screen saves, but replay artifacts are missing.

**Why it happens:** The server only waited 2 seconds, while FFmpeg merge can take much longer.

**Protection now:** Shutdown waits 60 seconds by default and can be configured with `--shutdown-grace-seconds`.

## R06: Bundle Names Collide

**Severity:** Medium

**What you would see:** A repeated submission or incident bundle overwrites or reuses a filename.

**Why it happens:** Bundle names used second-level timestamps.

**Overload trigger:** Double click, retry, incident burst, or fast automated test.

**Protection now:** Bundle names include a `time_ns()` uniqueness token.

## R07: Incident ID Creates Awkward Filename

**Severity:** Medium

**What you would see:** An incident bundle path contains strange separators or unsafe filename characters.

**Why it happens:** Incident IDs were used directly in filenames.

**Protection now:** Incident IDs are sanitized before entering bundle filenames.

## R08: Large Uploads Still Depend On Network Quality

**Severity:** Medium

**What you would see:** Upload retries happen, then final failure on very slow or unstable Wi-Fi.

**Why it happens:** Uploads have a timeout and retry limit, even though the timeout scales with file size.

**Protection now:** Uploads retry 3 times and use an adaptive timeout up to 3600 seconds. This is still an operational risk for very large packages.

## R09: Some WebSocket Events Are Not Session-Secured

**Severity:** Low

**What you would see:** No normal user-visible symptom. This is a hardening concern.

**Why it happens:** The security envelope covers policy, session state, incident, pause/resume, and kill events, but not every event.

**Recommended follow-up:** Consider securing `savescreen`, `get_processes`, `finish_exam`, and `process_blacklist`.

## R10: Monitor Logs Can Grow During Long Sessions

**Severity:** Low

**What you would see:** Client data folders get large after long sessions.

**Why it happens:** Process, focus, hardware, and exam-state logs append JSONL records without rotation.

**Current guardrails:** Full snapshots are periodic, and focus status sent to the server is throttled.

**Recommended follow-up:** Add max-size cleanup if practice sessions or long exams become common.

## Test Anchors

- Replay queue behavior: `May_01/tests/unit/test_replay_save_queue.py`
- Replay recorder and FFmpeg fallback: `May_01/tests/unit/test_replay_recorder.py`
- Immediate incident report and background evidence: `May_01/tests/unit/test_client_incident_reporting.py`
- Server evidence update behavior: `May_01/tests/unit/test_server_handlers.py`
- Unique bundle names: `May_01/tests/unit/test_transfers.py`
- Shutdown grace: `May_01/tests/unit/test_server_app.py`, `May_01/tests/unit/test_server_shutdown.py`
