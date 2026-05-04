# Validation

Executed from: `near final delivery/`  
Execution date: `2026-04-21` (local machine time)

## Command Results

1. `python -m server.main --help`  
Result: `PASS`

2. `python -m client.main --help`  
Result: `PASS`

3. `python -m unittest tests.unit.test_client_incidents`  
Result: `PASS` (`Ran 7 tests`)

4. `python -m unittest tests.unit.test_security`  
Result: `PASS` (`Ran 4 tests`, `skipped=1`)

5. `python -m unittest tests.integration.test_client_main`  
Result: `PASS` (`Ran 2 tests`)

6. `python -m py_compile` over all copied `.py` files  
Result: `PASS` (`PY_COMPILE_OK`)

## Notes
- Runtime help/tests briefly created `data/logs/*`; generated `data/` was removed after validation to keep the delivery folder clean.

## Glitch Patch Follow-Up

Issue found:
- `python -m unittest discover -s tests` initially failed because `tests/unit/test_setup.py` imports `setup`, but `setup.py` was not present in `near final delivery`.

Patches applied:
- Added `setup.py` to `near final delivery`.
- Removed undefined variable usage (`privacy_ok`) in the new `setup.py` summary path.
- Updated `FILE_CLASSIFICATION.md` to classify `setup.py` as `required`.

Re-validation after patch:
- `python -m unittest discover -s tests`: `PASS` (`Ran 50 tests`)
- `python -m unittest tests.unit.test_setup`: `PASS`
- `python -m py_compile` over all `.py`: `PASS`

## Launcher / Manual Entry Checks

Patches applied:
- `server/gui.py`: allow normal window close when launched standalone from terminal (`stdin` is TTY), keep protected close behavior under managed mode.
- `client/gui.py`: same standalone/manual close behavior improvement.
- Added manual CLI wrappers: `server_cli.py`, `client_cli.py`.

Smoke checks:
- `python server_launcher.py`: starts and stays alive (manual termination after startup check).
- `python -m server.gui`: starts and stays alive (manual termination after startup check).
- `python client_launcher.py`: starts and stays alive (manual termination after startup check).
- `python -m client.gui`: starts and stays alive (manual termination after startup check).
- `python server_cli.py --help`: `PASS`
- `python client_cli.py --help`: `PASS`
- `python -m unittest tests.unit.test_server_main tests.integration.test_client_main`: `PASS`

## Transfer Reliability Patch

Issue reported:
- File transfers were failing in practice except requested process report.

Patches applied:
- `server/handlers.py`:
  - Multipart parsing is now order-independent for upload routes.
  - Upload endpoints no longer assume file part is first or that text fields arrive in fixed order.
- `server/main.py` + `server/app.py`:
  - Added configurable upload limits:
    - `--max-submission-mb` (default `2048`)
    - `--max-artifact-mb` (default `2048`)
- `client/transfers.py`:
  - Increased upload retries (`3` attempts).
  - Added adaptive upload timeout based on file size (up to `3600s`).
- Added regression test:
  - `tests/unit/test_upload_multipart_order.py`

Validation:
- `python -m unittest tests.unit.test_upload_multipart_order tests.unit.test_transfers`: `PASS`
- `python -m unittest discover -s tests`: `PASS` (`Ran 52 tests`)
- Live smoke check:
  - runtime artifact upload to `/client/artifact`: `PASS`
  - submission upload route reached and returned expected state gate (`409 Exam has not started for this client`) in the smoke scenario.

## Final Submission Sequence Patch

Issue reported:
- Client could appear stuck at `Uploading file...` during final submission.

Patches applied:
- `server/tasks.py`:
  - Global finish now moves all non-submitted users to `awaiting_submission` (not only users already marked `exam_started`).
- `server/handlers.py`:
  - Submission endpoint allows upload after global exam finish even if the user state still resolves to `waiting`.
- `client/ws_client.py`:
  - Added explicit step logs in final submission flow.
  - Added bounded replay save timeout (`45s`) with fallback to continue without replay.
  - Added bounded submission upload timeout (`900s`) with clear timeout error.
- `client/custommodules/replay_recorder/core.py`:
  - Added FFmpeg merge timeout handling in `save_replay()` to prevent indefinite blocking.

Validation:
- `python -m unittest discover -s tests`: `PASS` (`Ran 53 tests`)

## Finish Pipeline UX + Packaging Steps

Implemented finish pipeline behavior:
- Client now emits explicit step-by-step progress during final submission in both CLI logs and submission UI status.
- Submission file is first copied into a local package folder under:
  - `data/client/<session_uuid>/submission_bundle/submission_package_<timestamp>/student_submission/`
- Runtime logs/evidence files are copied into the same local package folder under `runtime/...` paths.
- Current replay snapshot is saved before packaging (best-effort with timeout fallback).
- The copied package content is archived into `submission_bundle_<timestamp>.zip`.
- Archive checksum is sent (`sha256`, `archive_sha256`) and per-file checksums remain in `manifest.json`.
- Client waits for server response before success; only then it shows upload-success and closes the submission window.

Validation:
- `python -m py_compile client/transfers.py client/ws_client.py client/gui.py`: `PASS`
- `python -m unittest tests.unit.test_transfers tests.unit.test_upload_multipart_order tests.unit.test_server_tasks`: `PASS`
- `python -m unittest discover -s tests`: `PASS` (`Ran 53 tests`)
