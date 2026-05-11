# 07. Security, Privacy, And Safety

## 1. Security Model

`May_04_Deniz` is a LAN exam system. It does not assume a hostile internet deployment, but it does assume that clients may disconnect, send malformed messages, or attempt to bypass policy. The server remains authoritative for session state, policy distribution, incidents, submissions, artifacts, and administrative actions. The client remains responsible for local observation because the server cannot directly inspect student machines.

The implementation uses several layered controls:

- Server-side login and allowed-user checks.
- Optional HMAC token validation through shared auth secret.
- Optional CATS and AD preflight on the client.
- Temporary server-authorized auth bypass with short TTL.
- Checksum-protected LAN event messages.
- Secured sensitive events with signing, timestamp, nonce, and optional encryption.
- Loopback-only token-protected local IPC.
- Safe ZIP extraction for exam materials.
- Upload size limits and checksum validation.
- Public-safe projector payload construction.

## 2. Authentication And Authorization

### Login

The client sends login id, password, and optional token to `POST /login`. The server checks allowed users and user state. Banned, kicked, or completed states can block login depending on stored session fields. New users may be registered according to server logic and configuration.

### CATS And AD Preflight

Client preflight can perform local CATS and AD checks before full runtime. The client first asks the server for `/auth/status?login_id=<id>`. If the server is unreachable or the status request fails, the client falls back to strict local behavior. This is important: bypass is never decided solely by the client.

### Temporary Bypass

Operators can temporarily bypass CATS or AD checks:

- `/disablecatsauth [seconds]`
- `/disableadauth [seconds]`
- `/enablecatsauth`
- `/enableadauth`
- `/authstatus`

Default disable duration is 60 seconds and durations are clamped by server logic. Bypass state is runtime-only. It is not persisted into policy files. AD bypass only changes token behavior for allowed users and still requires a nonempty password.

## 3. LAN Message Integrity And Security

Every LAN WebSocket message includes a checksum over canonical event and data. This catches malformed or modified messages before handlers process them.

Sensitive event bodies can be wrapped by `common.security.SessionSecurityContext`. The secured envelope includes:

- timestamp
- nonce
- encrypted flag
- signature
- payload or ciphertext

The signature uses HMAC over canonical envelope fields. Replay protection checks timestamp windows and remembered nonces. When `cryptography` is available and the event is configured for encryption, Fernet encryption protects event content. If encrypted content is malformed, decoding fails closed into a protocol error.

## 4. Local IPC Security

Local process IPC is not a LAN API. It is for same-machine process control between launchers, CLIs, dashboards, and timer UIs.

Controls:

- The IPC server binds only to `127.0.0.1`.
- The server rejects non-loopback peers.
- A random per-process token is required.
- The token is passed through process environment, not stored as a shared file.
- Transport `auto` only uses WebSocket IPC when the URL and token env vars exist.
- Stdio fallback remains available for manual terminal operation.

The local IPC protocol must not be used for student/server LAN communication. It has different trust assumptions and command semantics.

## 5. Privacy Boundaries

### Dashboard

The server dashboard is operator-only and may display sensitive information such as login ids, UUIDs, incident details, process names, window titles, artifact paths, submission paths, and folder information. Dashboard traffic is local process IPC, not public HTTP.

### Projector

The projector page is public-safe by construction. It exposes only:

- exam phase
- start enabled state
- aggregate counts
- server time
- connection status
- generic notifications

It must not expose:

- login ids
- student names
- UUIDs
- IP addresses
- process names
- window titles
- artifact paths
- submission paths
- evidence details
- rule evidence

This is enforced by the projection state builder and unit tests.

## 6. Exam Material Safety

Downloaded exam ZIP files are copied to client data and extracted to `Desktop/Exam/DD-MM-YYYY`. Extraction rejects:

- absolute paths
- drive-letter paths
- path traversal
- unsafe names

The client writes a manifest marker. If the target dated folder was created by the app, managed files can be refreshed safely. If the folder contains unmarked user files, a safe suffixed folder is selected instead of deleting user content.

## 7. Upload Safety

Submission and artifact upload handlers enforce configured maximum sizes. Checksums are verified when provided. Runtime file collection on the client is best-effort so locked or missing logs do not break the whole submission. Server-side storage paths are controlled by server handlers rather than client-supplied raw paths.

## 8. Incident Action Safety

Configured actions are context-sensitive:

- `ban` and `kick` affect server session state and connection.
- `pause_exam` affects timer state.
- `kill_pid` is only valid when a live process id exists and the client is connected.

For browser/titlebar incidents, killing a pid terminates the browser process, not a tab. This is a deliberate safety and capability limitation because the system does not extract or control browser tabs.

## 9. Text Safety

Focused-window title matching passes through text normalization. This prevents invisible Unicode and unusual whitespace characters from breaking matching or console output. The same approach reduces failures for browser titlebars involving Chrome, Edge, Yandex, and localized New Tab titles.

## 10. Failure Containment

| Failure | Containment behavior |
| --- | --- |
| WebSocket disconnect | Client marks reconnecting, keeps monitors/logs running, buffers incidents, and reconnects. |
| Malformed WebSocket message | Protocol decode error; handler sends protected error when required. |
| Long close reason | UTF-8-safe close message trimming avoids WebSocket close-frame limit failure. |
| Artifact upload failure | Pending evidence remains retryable. |
| Duplicate server id | Startup precheck and runtime duplicate guard stop duplicate operation. |
| Qt unavailable | Tk remains available; Qt missing message can be shown. |
| Projector feed disconnect | Browser EventSource reconnects and displays reconnecting state. |

## 11. Residual Risks

- The LAN server is not designed as an internet-hardened service.
- Student machines can always attempt local tampering; the system records and reacts, but cannot provide kernel-level enforcement.
- CATS and AD integrations depend on local environment assumptions.
- FFmpeg availability and desktop capture support vary by machine.
- Browser titlebar approval is less precise than URL extraction by design.

## 12. Security Acceptance Criteria

The security posture is acceptable when:

- Local IPC rejects invalid tokens and non-loopback peers.
- Sensitive WebSocket events can be protected and decoded by both sides.
- Projector payloads never contain private identifiers or evidence.
- Auth bypass is short-lived, server-authorized, visible in status, and not persisted.
- Safe ZIP extraction rejects unsafe archive members.
- Upload size/checksum validation is active.
- Tests covering these areas pass.
