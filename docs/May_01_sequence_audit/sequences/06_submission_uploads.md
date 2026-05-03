# Final Submission And Uploads

This page explains how the student's final file becomes a checked, archived, uploaded submission bundle.

## In One Sentence

When the exam ends, the client packages the student's file with runtime evidence, uploads the bundle, waits for server confirmation, and then exits.

## Who Is Involved

- Student CLI or client GUI.
- `client.ws_client`, which runs the final submission sequence.
- `client.submission`, which validates the chosen file.
- `client.transfers`, which builds bundles and uploads files.
- `server.handlers.exam_submission`, which validates and stores the upload.

## Final Submission: What Happens

1. The server sends `finish_exam`, or the client reconnects in `awaiting_submission`.
2. The student chooses a file in the GUI or types `finish <path>`.
3. The client validates that file.
4. The client marks submission as in progress.
5. Live monitors stop.
6. The client exports final process, hardware, and focused-window snapshots.
7. The client requests a final replay save with highest replay priority.
8. The client creates a local package folder.
9. The student's file is copied into `student_submission/`.
10. Runtime evidence is copied into `runtime/`.
11. A `manifest.json` is written with checksums.
12. The package is zipped.
13. The zip is uploaded to `POST /exam/submission`.
14. The server validates the upload and stores it.
15. The client shows success, closes the WebSocket, and exits intentionally.

## Upload Validation

The server checks:

- Session id is valid.
- User exists and is not banned.
- User has not already submitted.
- Exam state allows submission.
- Multipart field includes an archive.
- Archive is not empty.
- Archive is a supported zip/tar type.
- SHA-256 checksum matches.

## Files You May See

- `data/client/<session_uuid>/submission_bundle/submission_package_<token>/...`
- `data/client/<session_uuid>/submission_bundle/submission_bundle_<token>.zip`
- `data/client/<session_uuid>/incident_bundles/incident_bundle_<id>_<token>.zip`
- `data/server/submissions/<client_id>/...`
- `data/server/artifacts/<client_id>/<kind>/...`

## Common Failure Clues

- Final replay missing: replay save timed out or recorder was not running; submission still continues.
- Optional runtime log missing from zip: copy failed and the optional file was skipped.
- Upload rejected as duplicate: server already has a submission for that user.
- Upload checksum mismatch: file changed during upload or request body was corrupted.
- Student cannot submit before exam starts: expected, unless global exam phase is finished.

## Tests

- `tests/unit/test_transfers.py`
- `tests/unit/test_upload_multipart_order.py`
- `tests/unit/test_server_handlers.py`
- `tests/unit/test_server_tasks.py`
