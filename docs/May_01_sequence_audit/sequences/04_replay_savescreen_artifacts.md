# Replay, Savescreen, And Artifacts

This page explains what happens when the server asks a client to save recent screen evidence or upload a process report.

## In One Sentence

Savescreen asks the client to turn its rolling FFmpeg cache into a replay artifact and upload it to the server.

## Who Is Involved

- Operator CLI, server GUI, or shutdown routine.
- `common.events.savescreen`.
- `client.ws_client.ReplaySaveQueue`.
- `client.custommodules.replay_recorder.ReplayRecorder`.
- `client.transfers.upload_runtime_artifact`.
- `server.handlers.client_artifact_upload`.

## Savescreen: What Happens

1. The operator runs `/savescreen`, clicks savescreen in the GUI, or the server starts shutdown.
2. The server sends `savescreen` with a request id, request time, and source.
3. The client puts the request into the replay save queue.
4. The queue decides when the request should run.
5. The recorder copies the current FFmpeg segment files into a request-specific folder.
6. FFmpeg merges those copied segments into an MP4.
7. If MP4 merge fails, times out, or produces an incomplete file, the recorder writes a TS fallback.
8. The client uploads the replay as a `requested_replay` artifact.
9. The server stores the artifact and a metadata sidecar.

## Why The Queue Exists

FFmpeg replay saves should not run in parallel for the same recorder. The queue preserves that safety.

The queue is now priority-aware:

1. Final submission replay.
2. Incident evidence replay.
3. Optional requested replay, such as admin savescreen.

That means an optional savescreen burst cannot bury final submission evidence.

## Requested Process Report

The server can also send `get_processes`.

When that happens:

1. The client exports a full process snapshot.
2. The client uploads it as `requested_process_report`.
3. The server stores it under client artifacts.

## Files You May See

- `data/client/<session_uuid>/recordings/cache/replay.m3u8`
- `data/client/<session_uuid>/recordings/cache/cache_*.ts`
- `data/client/<session_uuid>/recordings/replays/replay_<request_id>.mp4`
- `data/client/<session_uuid>/recordings/replays/replay_<request_id>.ts`
- `data/server/artifacts/<client_id>/requested_replay/...`
- `data/server/artifacts/<client_id>/requested_process_report/...`

## Common Failure Clues

- No replay yet: FFmpeg may not have produced enough segments.
- Replay returns `None`: recorder may not be running, playlist may be empty, or optional queue may be full.
- MP4 missing but TS exists: FFmpeg merge failed, and fallback protected the evidence.
- Shutdown replay missing: the client may not have finished before shutdown grace expired.

## Tests

- `tests/unit/test_replay_save_queue.py`
- `tests/unit/test_replay_recorder.py`
- `tests/unit/test_savescreen_event.py`
- `tests/unit/test_process_monitor.py`
- `tests/unit/test_upload_multipart_order.py`
