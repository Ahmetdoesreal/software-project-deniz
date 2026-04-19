# Delivery For Baris

This folder is a clean delivery copy. It does not modify the original files from other teammates.

## Included

- `server_core.py`
  - Baris' newest usable server core from `extras_new/baris/server_core_baris_2 (1).py`
- `db_manager.py`
  - DB support file Baris' server core expects
- `school_service.py`
  - CATS/Orion verification helper Baris' server core expects
- `protocol.py`
  - Ahmet's protocol module with compatibility handling for Engin's fields
- `events.py`
  - Ahmet's events module from the active project
- `test_protocol_compat.py`
  - Unittest coverage for the protocol compatibility behavior
- `test_protocol_integrity_fields.py`
  - Same compatibility coverage in the active project's unit-test style
- `baris_report.txt`
  - Original integration task report

## What Changed

Only Ahmet's `protocol.py` behavior was changed.

It now tolerates these known reliability fields without weakening unrelated checksum validation:

- `seq`
- `session_id`
- `buffered`
- `queued_at`

No files owned by other teammates were edited.

## Verification

From the source workspace, these passed:

```powershell
cd ..
python -m unittest tests.unit.test_protocol_integrity_fields

cd deliver_to_baris
python -m unittest test_protocol_integrity_fields.py
python -m py_compile protocol.py events.py db_manager.py school_service.py server_core.py test_protocol_integrity_fields.py
```

## Still Missing Before Standalone Run

`server_core.py` still imports teammate modules that are not included here:

- `security_layer.py`
- `instructor_auth.py`

I found a Naz draft for `security_layer.py` elsewhere in the repo, but no `instructor_auth.py` in the current scan.

So this delivery is ready as Baris' implementation/integration package, but not yet a fully standalone runnable server until those missing teammate modules are provided or stubbed.

## Important

`protocol.py` and `events.py` are Ahmet's files. Other teammates' originals are not modified in this delivery.
