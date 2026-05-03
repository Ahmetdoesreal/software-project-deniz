# Fix Plan

This page describes what changed in plain language. It is useful when you want to understand the safety fixes without reading the code first.

## What Was Fixed

**Replay saves now know what is urgent.**

Before, every replay save waited in the same first-in-first-out line. That was safe for FFmpeg, but bad under load: a final submission could wait behind a pile of optional `/savescreen` requests. Now the queue still runs one FFmpeg save at a time, but it chooses work in this order:

1. Final submission replay.
2. Incident evidence replay.
3. Optional requested replay, such as admin savescreen or shutdown savescreen.

**Optional replay requests are bounded.**

If an operator repeatedly asks for savescreens while FFmpeg is slow, the client no longer keeps accepting unlimited work. Extra optional requests return `None` and are logged as dropped. This protects memory and keeps urgent work from getting buried.

**Queued replay requests can expire.**

If a queued replay is already too old before FFmpeg starts, the client skips it. This is better than saving stale evidence that no longer represents the requested moment.

**Incidents are reported before evidence finishes.**

Before, the client waited for process reports, replay save, bundle creation, and upload before sending the incident. That meant an FFmpeg or upload delay could delay server-side auto-pause or process actions. Now the client sends the incident immediately with:

```text
evidence_status = "pending"
```

Then it uploads evidence in the background and sends a second incident update:

```text
status = "evidence_uploaded"
evidence_status = "uploaded"
artifact_path = "..."
```

If evidence fails, it sends:

```text
status = "evidence_failed"
evidence_status = "failed"
```

**Evidence updates no longer overwrite the active incident.**

The server keeps the original opened incident active and only merges evidence fields into it. This avoids accidentally changing an active violation into an evidence-only status.

**Server shutdown waits long enough to matter.**

The shutdown routine used to wait only 2 seconds after requesting process reports and screen saves. FFmpeg alone can take up to 30 seconds. The default is now 60 seconds, with a CLI option:

```text
--shutdown-grace-seconds
```

**Bundle names no longer collide within the same second.**

Submission and incident bundle names now include a `time_ns()` token. Repeated retries, double clicks, or incident bursts will not reuse the same filename.

## Tests Added

- Replay queue keeps FIFO order inside the same priority.
- Replay queue never calls the recorder in parallel.
- Final submission jumps ahead of queued optional saves.
- Optional replay requests are dropped when the queue is full.
- Expired queued saves do not call FFmpeg.
- Closing the replay queue does not leave pending futures stuck.
- Initial incident report is sent before evidence upload completes.
- Evidence-upload updates do not rerun server auto actions.
- Server app honors configured shutdown grace.
- Shutdown routine waits for configured shutdown grace.
- Bundle names are unique even when created in the same second.

## Still Worth Doing Later

- Consider securing `savescreen`, `get_processes`, `finish_exam`, and `process_blacklist` with the same session security envelope used by policy, incidents, pause/resume, and kill-process events.
- Add operator-visible replay queue telemetry so admins can see when optional saves are dropped.
- Add cleanup rules for old replay files and incident bundles.
- Add a live multi-client smoke test for `/savescreen all` while one client submits under artificial FFmpeg delay.
