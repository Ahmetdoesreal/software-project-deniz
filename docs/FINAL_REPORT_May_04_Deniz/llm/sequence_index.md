# LLM Sequence Index

## Rebuild Order

1. Shared contracts: protocol, events, security, text safety, IPC, process definitions, incident rules.
2. Server state: users, policy, incidents, process definitions, incident rules, settings bundles.
3. Server app and routes: health, auth status, projector, login, config, files, submission, artifact, WebSocket.
4. Server tasks: broadcaster, admin commands, GUI state, actions, shutdown.
5. Client setup: discovery, health, auth status, login, config/files, safe extraction.
6. Client WebSocket: session connect, policy sync, timer UI, monitor ownership, event handlers.
7. Monitoring: process, focused window, idle, hardware, replay, exam-state logging.
8. Incident engine: candidates, incident rules, buffering, evidence retry.
9. Transfers: submission bundle, artifact bundle, checksum upload.
10. GUI: launchers, dashboards, settings, timer/submission, local IPC.
11. Projector: safe payload, HTML, SSE tests.
12. Tests and smoke.

## Key Sequences

### Server Startup

`server.main` validates args, checks duplicate server id, calls `create_app`, loads state, registers routes, starts broadcaster, console reader, discovery announcer, duplicate guard, and optional GUI.

### Client Startup

`client.main` resolves server by host/port or discovery, checks health, fetches auth status, logs in, fetches config/files, extracts desktop materials, then starts reconnecting WebSocket attempts.

### Policy Sync

Server sends `exam_policy`, `process_blacklist`, and `session_state`. Client applies policy to incident engine and monitors, then sends `policy_applied`.

### Reconnect

WebSocket disconnect sets timer state to reconnecting but leaves monitors, recorder, GUI bridge, incident engine, and buffers alive. New WebSocket attempt receives state and flushes unacked incident packets in sequence order.

### Incident

Observation becomes incident candidate. Incident rules may suppress or change severity/actions. Candidate is queued, sent if connected, stored by server, acknowledged by `incident_received`, displayed in dashboard, and reduced to generic notification for projector.

### Submission

Server sends `finish_exam`. Client opens submission UI. Student selects file. Client builds bundle with runtime files and manifest. Server receives multipart upload and marks submission state.

### Projector

Browser loads `/projector`, opens `/projector/events`, receives safe aggregate payload, and reconnects automatically if SSE disconnects.

## Hard Constraints

- Do not expose sensitive fields on projector.
- Do not stop local logging on reconnect.
- Do not copy local IPC into LAN protocol.
- Do not delete unmarked desktop exam folders.
- Do not split UTF-8 when trimming close messages.
- Do not hardcode CATS title whitelist; make it an incident rule.
