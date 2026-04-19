# Ahmet Delivery To Baris

This folder contains only Ahmet's files for Baris' integration request.

Included:

- `protocol.py`
- `events.py`
- `test_protocol_integrity_fields.py`

What changed:

- `protocol.py` now supports Engin's reliability metadata:
  - `seq`
  - `session_id`
  - `buffered`
  - `queued_at`

Checksum behavior is still strict for normal payload changes. Only the known reliability metadata is tolerated when it is added after checksum creation.

Verification from the project root:

```powershell
python -m unittest tests.unit.test_protocol_integrity_fields
```

No files from other teammates are included in this folder.
