# Baris Files Analysis

## Chosen Source

I chose `extras_new/baris` as the source folder for this workspace.

Reasons:

- It contains `baris_report.txt`, which is the task source requested.
- It has the most complete Baris-specific set: server core, database manager, school service, and notebooks.
- The plain files without `(1)` are zero-byte placeholders, so the usable versions are the `(1)` files.
- Within Baris' files, `server_core_baris_2 (1).py` and `server_baris_2.ipynb` are the most up-to-date-ish server pair because they are newer than the first Baris versions and include CATS verification / waiting-room behavior referenced by the report.

## Files Copied Here

- `server_core.py`: from `extras_new/baris/server_core_baris_2 (1).py`
- `db_manager.py`: from `extras_new/baris/db_manager_baris (1).py`
- `school_service.py`: from `extras_new/baris/school_service_baris (1).py`
- `server_baris_2.ipynb`: latest Baris notebook reference
- `baris_report.txt`: original report
- `network_sender_engin.py`: from `extras_new/engin/network_sender (1).py`
- `monitor_loop_engin.py`: from `extras_new/engin/monitor_loop (1).py`
- `mytask.txt`: from `extras_new/me/mytask.txt`
- `protocol.py`: copied from active `common/protocol.py`, then patched for Ahmet's task
- `events.py`: copied from active `common/events.py`
- `test_protocol_compat.py`: local unittest coverage for the protocol compatibility patch

## Deep Notes

The Baris server code is an experimental integration layer, not a drop-in replacement for the current aiohttp server. It uses `websockets`, direct module imports such as `security_layer`, `instructor_auth`, `discovery`, and `runtime_logging`, and a SQLite manager named `db_manager.py`.

The newer Baris core adds:

- Live CATS/Orion verification through `school_service.verify_user`.
- Waiting-room flow: authenticated students enter `waiting_for_start` and wait for `start_all_students`.
- `exam_started_ack` broadcast when the instructor starts the exam.
- Crash-recovery state via SQLite.
- Monitoring integrity fields from Engin: `seq`, `session_id`, `buffered`, `queued_at`.
- Risk scoring for violations.

Important integration risk:

`server_core.py` still assumes Ahmet protocol messages can be decoded and then remapped into legacy actions. If reliability metadata arrives outside the `data` object, the server needs `protocol.decode` to preserve it. The patched local `protocol.py` does that for the known fields only.

The active root project already has a different, more mature aiohttp structure under `client`, `server`, and `common`. This `baris_files` folder should stay isolated until individual ideas are intentionally ported into the active architecture.

## Second Extras Scan

The second scan found files that were not present or not noticed in the first pass:

- `extras_new/engin/network_sender (1).py`
- `extras_new/engin/monitor_loop (1).py`
- `extras_new/me/mytask.txt`

These are relevant because Baris' report directly assigns work to Engin, and `mytask.txt` describes the client-monitoring event/violation detection goal.

### Engin Against Baris Report

Baris asked Engin for two things:

1. Add `password` to the `request_start_exam` payload because the server now verifies CATS/Orion live.
2. Update `monitor_loop.py` so the client waits for `exam_started_ack` instead of starting time immediately.

`network_sender_engin.py` does include reliability fields:

- `seq`
- `session_id`
- `buffered`
- `queued_at`

But its registration payload still builds:

- `action`
- `student_id`
- `exam_id`
- `session_id`

Then it merges whatever `AuthClient.build_credential_fields(...)` returns. I did not find a literal raw `password` field being added in this file. That means it may still be incomplete for Baris' CATS verification requirement unless `AuthClient` returns plain `password`.

`monitor_loop_engin.py` still only checks `exam_state.is_active()` in the loop. The actual waiting-room handshake is not obvious there. The sender treats any `status == "success"` response as a started/registered state, but Baris' newer server sends `auth_success` first and later `exam_started_ack` when the instructor starts all students. So this also looks incomplete against the report.

### `mytask.txt` Against Active App

`mytask.txt` asks for client-side event and violation detection instead of raw collection only.

The active app already has a meaningful version of this in `client/incidents.py`:

- prohibited process detection through `process_blacklist`
- focused-window policy violation detection
- structured incident payloads with `incident_id`, `rule_id`, `severity`, `status`, `summary`, and `event_at`
- server-side incident handling and optional violation pause

Missing or not obvious in the active app:

- rapid application switching detection
- unexpected-new-process detection beyond configured blacklist

So the active app partially satisfies `mytask.txt`, but there is room to extend it.
