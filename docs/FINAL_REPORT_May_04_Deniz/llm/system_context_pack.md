# LLM System Context Pack

Snapshot date: 2026-05-11

Authoritative source: `May_04_Deniz/`

## One-Paragraph System Definition

`May_04_Deniz` is a Python LAN exam runtime with an authoritative `aiohttp` server, student clients, Tk/Qt GUI surfaces, local loopback IPC, process/focus/idle/hardware/replay monitoring, policy-driven incident detection, final submission upload, temporary server-authorized CATS/AD auth bypass, reconnect-safe incident buffering, safe desktop exam-file extraction, and a read-only projection notification page.

## Critical Architecture Rules

- LAN student/server protocol is `common.events` over `/ws?id=<uuid>`.
- Local GUI/manager process control is `common.ipc_ws` over loopback or stdio fallback.
- Do not merge LAN WebSocket semantics with local IPC semantics.
- Server owns users, policy, incident history, session state, submissions, artifacts, auth bypass, and dashboard/projector state.
- Client owns local observation: process list, focused window, idle, hardware, replay, local logs, desktop exam files, incident buffering, and submission bundle assembly.
- Reconnect is network state only; monitors and local logging must continue.
- Projector payloads must be public-safe by construction.

## Primary Modules

- `server.main`: CLI args, duplicate server precheck, runtime logging, app run.
- `server.app`: app factory, route registration, background tasks, cleanup.
- `server.handlers`: HTTP/WebSocket handlers, login, auth status, uploads, incidents.
- `server.tasks`: admin commands, broadcaster, GUI state, policy apply, actions.
- `server.state`: persistent state, policy normalization, settings bundles.
- `server.projector`: `/projector`, `/projector/events`, safe projection state.
- `client.main`: discovery/login/prep/reconnect loop and persistent runtime owners.
- `client.ws_client`: WebSocket attempt, event handling, monitor coordination, UI bridge.
- `client.incidents`: incident engine and policy/rule application.
- `client.incident_buffer`: durable incident/evidence retry.
- `client.exam`: config/material download and safe desktop extraction.
- `client.transfers`: submission/artifact bundle and upload logic.
- `common.protocol`: JSON envelope and checksum.
- `common.events`: event names and constructors.
- `common.security`: secured event signing/encryption.
- `common.ipc_ws`: local loopback IPC.
- `common.incident_rules`: incident-rule normalization and matching.
- `common.text_safety`: title/display normalization.

## Interfaces

HTTP routes:

- `GET /health`
- `GET /auth/status?login_id=<id>`
- `GET /projector`
- `GET /projector/events`
- `POST /login`
- `GET /exam/config?id=<uuid>`
- `GET /exam/files?id=<uuid>`
- `POST /exam/submission?id=<uuid>`
- `POST /client/artifact?id=<uuid>`
- `GET /ws?id=<uuid>`

Local IPC channels:

- `manager.console_command`
- `server.dashboard_state`
- `dashboard.command`
- `client.timer_state`
- `timer.command`
- `process.lifecycle`

Admin commands:

- `/clients`
- `/savescreen <id>|all`
- `/exam`
- `/addtime <id> <minutes>`
- `/pauseexam <id>`
- `/resumeexam <id>`
- `/killpid <id> <pid>`
- `/startexam`
- `/finishexam`
- `/gui`
- `/editblacklist`
- `/applyblacklist`
- `/editpolicy`
- `/applypolicy`
- `/editdefinitions`
- `/applydefinitions`
- `/editincidentrules`
- `/applyincidentrules`
- `/exportsettings <path>`
- `/importsettings <path>`
- `/remembersettings on|off`
- `/disablecatsauth [seconds]`
- `/disableadauth [seconds]`
- `/enablecatsauth`
- `/enableadauth`
- `/authstatus`
- `/kick <id>`
- `/ban <id>`
- `/unban <id>`
- `/forgiveviolation <id>`
- `/security ...`
- `/help`

## Current Feature Notes

- Incident rules support statuses `unknown`, `whitelist`, `warning`, `blacklist`.
- Browser New Tab whitelist is shipped by default for common browser process names and New Tab title patterns.
- CATS is not hardcoded as an approval; it can be configured as a whitelist title rule.
- Focused-window text is sanitized for Unicode/invisible titlebar problems.
- `/finishexam` skips banned users.
- WebSocket close messages are trimmed to 120 bytes without splitting UTF-8.
- Projector page is read-only and uses SSE.
- Dashboard table refresh uses stable row snapshots to preserve scroll and selection.

## Validation Commands

Run from `May_04_Deniz/`:

```powershell
python -m compileall -q .
python -m unittest discover -s tests
```
