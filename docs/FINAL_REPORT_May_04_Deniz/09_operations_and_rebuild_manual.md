# 09. Operations And Rebuild Manual

## 1. Environment Setup

Use Python 3. The implementation uses the dependencies listed in `May_04_Deniz/requirements.txt`:

- `aiohttp`
- `psutil`
- `cryptography`
- `requests`
- `beautifulsoup4`
- `PySide6` for optional Qt mode

Typical setup:

```powershell
cd May_04_Deniz
python -m pip install -r requirements.txt
python -m unittest discover -s tests
```

If Qt is not needed, Tk workflows can still operate without PySide6, but Qt launchers and dashboards require it.

## 2. Server Operation

Basic server:

```powershell
python -m server.main --id default --host 0.0.0.0 --port 8080
```

Server with GUI:

```powershell
python -m server.main --id default --host 0.0.0.0 --port 8080 --gui --ui tk
```

Qt UI:

```powershell
python -m server.main --id default --host 0.0.0.0 --port 8080 --gui --ui qt
```

Useful options:

- `--interval`: time broadcast interval.
- `--announce`: discovery beacon interval.
- `--exam-duration`: default exam duration in minutes.
- `--exam-files`: ZIP path for materials.
- `--max-submission-mb`: maximum final upload size.
- `--max-artifact-mb`: maximum artifact upload size.
- `--shutdown-grace-seconds`: graceful shutdown window.
- `--ipc-transport`: `auto`, `stdio`, or `ws`.
- `--auth-secret`: shared secret for HMAC token validation.
- `--reset`: clear persistent users on startup.

## 3. Client Operation

Basic direct connection:

```powershell
python -m client.main --login-id student1 --password password --host 127.0.0.1 --port 8080
```

Discovery connection:

```powershell
python -m client.main --login-id student1 --password password --id default
```

Check login:

```powershell
python -m client.main --login-id student1 --password password --host 127.0.0.1 --port 8080 --check-login
```

Qt UI:

```powershell
python -m client.main --login-id student1 --password password --host 127.0.0.1 --port 8080 --ui qt
```

Useful options:

- `--reconnect`: seconds between reconnect attempts.
- `--no-record`: disable replay recorder.
- `--ipc-transport`: `auto`, `stdio`, or `ws`.
- `--ad-domain`: enable AD preflight mode.
- `--auth-secret`: shared secret matching server.

## 4. Launcher Operation

Server launcher entry points:

- `server_launcher.py`
- `server_launcher_tk.py`
- `server_launcher_qt.py`

Client launcher entry points:

- `client_launcher.py`
- `client_launcher_tk.py`
- `client_launcher_qt.py`

Launchers build CLI commands, validate forms, start child processes, pass IPC environment, display logs, and expose console windows. The CLI remains the runtime authority.

## 5. Projector Operation

Open:

```text
http://<server-host>:<port>/projector
```

The projector page requires no login and exposes no controls. It should be used only as a public display. For privacy, it shows aggregate counts and generic notifications only.

## 6. Data Lifecycle

### Server Data

The server initializes missing files under `data/server`. Operators may edit policy, blacklist, process definitions, and incident rules through dashboard windows or file edit/apply commands. Submissions and artifacts are created during exam operation and should be archived or cleared according to local retention policy after the exam.

### Client Data

Each client session stores local runtime files under `data/client/{uuid}`. These include logs, buffers, exam files, replay cache, saved replays, and bundle staging. The desktop exam folder is a student-facing extraction target, while the client data folder is runtime evidence and cache.

### Logs

Runtime process logs are stored under `data/logs`. Monitor logs are JSONL files under each client UUID folder. These logs are useful for debugging and for inclusion in final submission bundles.

## 7. Troubleshooting

| Problem | Likely cause | Action |
| --- | --- | --- |
| Server cannot bind port | Port already in use or duplicate server. | Use another port, stop the other process, or check duplicate-server message. |
| Client cannot discover server | UDP discovery blocked or wrong server id. | Use explicit `--host` and `--port`; verify server id. |
| Qt UI does not start | PySide6 missing or environment issue. | Use `--ui tk` or install PySide6. |
| Projector does not update | SSE disconnected or server unreachable. | Refresh browser; check `/health`; confirm server is running. |
| Exam materials do not appear | No exam ZIP configured or unsafe ZIP rejected. | Check server `--exam-files`, client logs, and ZIP member paths. |
| Incident not sent during disconnect | It should be buffered. | Check `data/client/{uuid}/buffer`; reconnect and verify flush. |
| Dashboard scroll jumps | Row refresh helper regression. | Run `test_row_refresh` and inspect dashboard rebuild paths. |
| Browser titlebar matching fails | Unicode/title normalization or rule configuration issue. | Check `common.text_safety`, incident rules, and focused-window policy. |
| Submission rejected | Size, checksum, archive, or UUID issue. | Check server upload logs and max upload settings. |

## 8. Rebuild Order From Scratch

1. Create the package layout: `common`, `server`, `client`, `server/ui`, `client/ui`, `launcher_ui`, `tests`.
2. Implement shared `common.protocol` and `common.events`.
3. Implement `common.security` for secured sensitive events.
4. Implement discovery, runtime logging, text safety, process definitions, incident rules, and local IPC.
5. Implement server state files, defaults, normalization, version stamps, and settings import/export.
6. Implement server app factory, HTTP routes, WebSocket handler, upload handlers, and projector handlers.
7. Implement server task loop, command dispatch, dashboard state builder, and shutdown routine.
8. Implement client auth/preflight, discovery, login, exam prep, safe extraction, and reconnect loop.
9. Implement client WebSocket session handling and timer UI bridge.
10. Implement process, focused-window, idle, hardware, exam-state, replay, incident engine, incident buffer, and transfer modules.
11. Implement Tk and Qt timer/submission UIs.
12. Implement Tk and Qt server dashboards, settings windows, process database, incident rules, folder info, and smooth table refresh.
13. Implement manager launchers and local IPC integration.
14. Add tests subsystem by subsystem.
15. Run compile and test validation.
16. Perform manual smoke checks on Windows server/client machines.

## 9. Release Checklist

- Clean runtime data if starting a fresh exam.
- Confirm `allowed_users.json` and `auth_config.json`.
- Confirm server id, host, port, and firewall allowance.
- Confirm exam ZIP exists and extracts safely.
- Confirm Tk or Qt mode selected for the deployment machines.
- Run server and projector smoke.
- Run one client check-login.
- Run one full client start, incident, reconnect, and submission smoke.
- Export settings bundle for archive.
- Preserve submissions, artifacts, and logs after exam.
