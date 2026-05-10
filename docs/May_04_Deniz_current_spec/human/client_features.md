# Client-Side Feature Spec

Source root: `May_04_Deniz/`

## Runtime Entry Points

- `python -m client.main`: starts the student runtime.
- `client_launcher.py`: starts the manager UI, which validates login and launches `client.main`.
- `python -m client.gui`: starts the timer/submission UI directly.

## Client Features

- Authentication and startup:
  - Manager preflight checks CATS school authentication and Windows AD authentication in parallel.
  - Runtime can authenticate with raw password or local AD HMAC token.
  - Client discovers the server by server ID or connects to an explicit host/port.
  - Client fetches exam config and exam ZIP before WebSocket runtime begins.
- WebSocket session:
  - Connects to `ws://<server>/ws?id=<session_uuid>`.
  - Uses `common.protocol` checksums for all event envelopes.
  - Uses `common.security` signing/encryption for protected events.
  - Reconnects after connection loss until final submission completes.
- Timer and submission UI:
  - Supports Tk and Qt backends.
  - Shows ready/running/paused/submission states.
  - Opens a protected finish window for final upload.
  - Receives timer/UI commands through local WebSocket IPC when available, with stdin fallback preserved.
- Monitoring:
  - Process monitor records process snapshots and detects blacklist, unexpected process, and process definition incidents.
  - Focused-window monitor records foreground application/window state and supports focused-window policy plus rapid switching incidents.
  - Hardware monitor records hardware snapshots and changes.
  - Idle monitor feeds local incident rules.
  - Replay recorder saves screen evidence through FFmpeg; FFmpeg stdin control remains out of app IPC migration scope.
- Incident flow:
  - Client reports incidents immediately.
  - Evidence upload is asynchronous and later reports `evidence_uploaded` or `evidence_failed`.
  - Incident buffer stores unacknowledged incidents across reconnects.
  - Server acknowledgements clear buffered incident entries.
- Transfers:
  - Runtime artifacts upload to `/client/artifact`.
  - Final submission builds a local package folder, copies the selected file and runtime evidence, writes `manifest.json`, zips the package, and uploads it to `/exam/submission`.
  - Uploads include SHA-256 checksums and retry with adaptive timeouts.

## Local Data

- `data/client/<session_uuid>/`: per-session runtime evidence and package output.
- `process_report.json`, `processes.jsonl`: process monitor output.
- `focused_window_snapshot.json`, `focused_window.jsonl`: focused-window output.
- `hardware_snapshot.json`, `hardware_changes.jsonl`: hardware monitor output.
- `exam_state.jsonl`: timer/session transition log.
- `submission_bundle/`: staged final submission packages and ZIPs.
- `incident_bundles/`: staged incident evidence ZIPs.
