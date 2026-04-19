# Client-Side Monitoring Report

## Objective

This module set was developed to monitor the exam client during an active session by collecting:

- the currently focused window,
- the list of running processes,
- and structured evidence files that can be sent to the server.

The implementation uses JSON as the common data structure so the output stays compatible with the existing client streaming and artifact-transfer pipeline.

## Implemented Client Modules

### 1. Active Window Monitor

The active-window detector is implemented in:

- `custommodules/focused_window_monitor/core.py`
- `custommodules/focused_window_monitor/windows.py`

Its job is to detect which window is currently in focus during the exam and record the related process details.

Main behavior:

- starts automatically with the websocket session in `client/ws_client.py`,
- polls every `1.0` second,
- writes an initial snapshot,
- logs only when the focused window changes,
- exports a standalone JSON snapshot when evidence is needed.

On Windows, the monitor collects:

- `window_handle`
- `window_title`
- `window_class`
- `process_id`
- `process_name`
- `process_path`
- `platform`
- `available`
- `source`

If the platform is unsupported or the foreground window cannot be read, the module still produces a valid JSON object with:

- `available: false`
- a `reason`
- and a `source`

### 2. Running Process Monitor

The running-process detector is implemented in:

- `custommodules/process_monitor/core.py`
- `custommodules/process_monitor/psutil_collector.py`

Its job is to track the processes that are running during the exam and keep a structured audit trail.

Main behavior:

- starts automatically with the websocket session in `client/ws_client.py`,
- polls process state every `15` seconds,
- writes a full process snapshot every `120` seconds,
- writes incremental `diff` entries between snapshots,
- exports a standalone JSON process report when the server requests evidence or when an incident is reported.

Each process entry is stored as:

- `[pid, process_name]`

This compact list format keeps the payload lightweight and JSON-serializable.

## Output Files

The monitoring modules produce two main continuous runtime files:

- `data/client/<session_uuid>/focused_window.jsonl`
- `data/client/<session_uuid>/processes.jsonl`

They also produce on-demand snapshot files:

- `data/client/<session_uuid>/focused_window_snapshot_<timestamp>.json`
- `data/client/<session_uuid>/process_report_requested_<timestamp>.json`

`JSONL` is used for continuous logging so each line is a complete JSON object and can be streamed, appended, or parsed incrementally.

## JSON Structure

### Active Window Log Format

Example focused-window snapshot:

```json
{
  "timestamp": "2026-04-07T12:00:00+00:00",
  "type": "focused_window_snapshot",
  "window": {
    "platform": "windows",
    "available": true,
    "window_handle": 531240,
    "window_title": "Exam App",
    "window_class": "Chrome_WidgetWin_1",
    "process_id": 10452,
    "process_name": "exam.exe",
    "process_path": "C:\\Program Files\\ExamApp\\exam.exe",
    "source": "user32"
  }
}
```

Continuous log entries use the same JSON-compatible structure, with event types such as:

- `focused_window_initial`
- `focused_window_change`
- `exam_state_marker`

Example change record:

```json
{
  "timestamp": "2026-04-07T12:00:05+00:00",
  "type": "focused_window_change",
  "previous": {
    "platform": "windows",
    "available": true,
    "window_title": "Exam App",
    "process_id": 10452,
    "process_name": "exam.exe",
    "source": "user32"
  },
  "current": {
    "platform": "windows",
    "available": true,
    "window_title": "Google Chrome",
    "process_id": 21480,
    "process_name": "chrome.exe",
    "source": "user32"
  }
}
```

### Running Process Log Format

Example full process report:

```json
{
  "timestamp": "2026-04-07T12:00:00+00:00",
  "remaining_time": 3570,
  "type": "requested",
  "platform": "windows",
  "processes": [
    [10452, "exam.exe"],
    [21480, "chrome.exe"],
    [24500, "explorer.exe"]
  ]
}
```

Example incremental process change entry:

```json
{
  "timestamp": "2026-04-07T12:00:15+00:00",
  "remaining_time": 3555,
  "type": "diff",
  "platform": "windows",
  "added": [
    [30010, "discord.exe"]
  ],
  "removed": [
    [21480, "chrome.exe"]
  ]
}
```

Continuous process logs may contain:

- `diff`
- `full_list`
- `requested`
- `exam_state_marker`

## Compatibility With the Streaming Module

The output is compatible with the existing streaming module because:

- all monitor payloads are plain JSON objects, arrays, numbers, strings, and booleans,
- timestamps use the shared `protocol.now_iso()` helper,
- no binary transformation is needed before transfer,
- the client already uses the common websocket protocol envelope defined in `common/protocol.py`.

The shared transport format is:

```json
{
  "event": "incident_report",
  "data": {
    "incident_id": "example-id",
    "rule_id": "focused_window_policy",
    "status": "opened"
  },
  "checksum": "..."
}
```

This means the monitor output can be:

- consumed locally for policy checks,
- wrapped into websocket events,
- or uploaded as JSON/ZIP evidence artifacts without changing the data model.

## Integration Flow

The runtime flow in the client is:

1. `client/ws_client.py` starts `FocusedWindowMonitor` and `ProcessMonitor`.
2. The monitors collect focused-window and process data during the exam.
3. The data is written to `focused_window.jsonl` and `processes.jsonl`.
4. Callback hooks feed the snapshots into `ClientIncidentEngine`.
5. If a rule violation is detected, the client sends a structured `incident_report`.
6. If the server requests evidence, the client exports JSON snapshots and uploads them through `upload_runtime_artifact()`.
7. The same files are also included in submission and incident bundles by `client/transfers.py`.

## Result

The client-side monitoring requirement is satisfied with a JSON-based design that is:

- structured,
- lightweight,
- stream-friendly,
- easy to store as evidence,
- and already aligned with the websocket/event transport used by the project.

In summary, the project uses JSON for both the active-window and running-process files, and those files are ready for server transmission through the existing streaming and artifact-upload pipeline.
