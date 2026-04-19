# Tasks Extracted From Baris Report

Source: `baris_report.txt`

## Ahmet

Baris says Ahmet's `protocol.py` and `events.py` modules have been integrated into the server. Engin added transport reliability fields:

- `seq`
- `session_id`
- `buffered`

Those fields must not break Ahmet's `decode` logic or checksum calculation. If they cause checksum errors, handle the compatibility in `protocol.py`.

Work done in this folder:

- Added compatibility handling to `protocol.py`.
- Top-level integrity fields are merged into the returned payload so server handlers can still use them.
- Payload-level integrity fields added after checksum creation are tolerated.
- Non-integrity payload changes still fail checksum validation.
- Added `test_protocol_compat.py` to verify the behavior without needing `pytest`.

## Deniz

No Deniz-specific task appears in `baris_report.txt`.

## Extra Task Found Later

The second scan found `extras_new/me/mytask.txt`. It does not name Deniz directly, but because it is in `extras_new/me`, it appears to be the local/user task:

Extend client monitoring from raw collection into event/violation detection. It specifically mentions:

- prohibited applications
- focus loss
- rapid application switching
- unexpected processes
- structured output with raw logs, event type, timestamp, and severity

The active project already covers prohibited applications and focus policy via `client/incidents.py`, but rapid switching and unexpected process detection are not obvious yet.
