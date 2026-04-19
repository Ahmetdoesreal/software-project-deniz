# Missed Extras Rescan

Second scan date: 2026-04-19

## Newly Noticed Files

`extras_new` now contains three top-level contributor folders:

- `baris`
- `engin`
- `me`

The missed or newly added files were:

- `extras_new/engin/network_sender (1).py`
- `extras_new/engin/monitor_loop (1).py`
- `extras_new/me/mytask.txt`

The zero-byte partner files without `(1)` are placeholders:

- `extras_new/engin/network_sender.py`
- `extras_new/engin/monitor_loop.py`

## Why They Matter

`network_sender (1).py` is the origin of the reliability metadata mentioned in Baris' report:

- `seq`
- `session_id`
- `buffered`
- `queued_at`

`monitor_loop (1).py` is the file Baris explicitly says must wait for `exam_started_ack`.

`mytask.txt` describes a client-monitoring extension task: turn process/window collection into structured violation events.

## Current Assessment

Engin's `network_sender` has reliability metadata, buffering, reconnect, sequence IDs, and session IDs.

It does not obviously satisfy Baris' `password` requirement. The registration message does not directly include a raw `password` field; it delegates credentials to `AuthClient.build_credential_fields(...)`.

Engin's `monitor_loop` does not obviously satisfy the waiting-room requirement. It checks `exam_state.is_active()`, but the file itself does not consume or wait for `exam_started_ack`.

The active root code already has a better incident/event path than the Engin draft:

- `client/incidents.py`
- `client/ws_client.py`
- `server/handlers.py`

But it does not obviously include rapid application switching or unexpected-process detection yet.

## Files Copied Into This Workspace

- `network_sender_engin.py`
- `monitor_loop_engin.py`
- `mytask.txt`
