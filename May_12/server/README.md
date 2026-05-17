# May_12 Server Bundle

This folder is the deployable operator/server side of the project.

## Contents

| Path | Purpose |
| --- | --- |
| `server/` | Server runtime, HTTP/WebSocket routes, dashboard UI, projector files, state, policy, and command logic. |
| `common/` | Shared protocol, security, IPC, discovery, matching, and text-safety helpers required by the server. |
| `common_ui/` | Bundled visual theme/helpers used by the server UI. |
| `ui/` | Compatibility wrappers for bundled UI helpers. |
| `launcher_ui/` | Server manager UI only. |
| `data/server/` | Policy-style defaults copied from the source project. Runtime logs/artifacts are not preloaded. |
| `allowed_users.json` | Allowed login IDs for server-side admission. |
| `auth_config.json` | Shared auth secret/default auth config. |
| `server_launcher.py` | Main server manager launcher. |
| `server_cli.py` | Manual server CLI entry point. |
| `requirements.txt` | Server Python dependency list. |

## Setup

Online setup:

```bat
python setup.py
```

Offline setup, using the default local `offline-packages` folder:

```bat
python setup.py --offline
```

Use `python setup.py --offline --source X:\offline-packages` only when the
offline source lives outside this folder.

## Run

```bat
run_server_tk.bat
run_server_qt.bat
run_server_cli.bat --help
```

The run scripts use the user-wide Python 3.13 install. They prefer `py -3.13`
and fall back to `python` only when it resolves to Python 3.13.

## Deployment Notes

- Copy this whole `server` folder to the operator/server machine.
- Install Python 3.13 manually before running setup.
- `setup.py` installs dependencies with `pip install --user`; no local Python
  environment is created.
- Edit `allowed_users.json` before an exam.
- Server runtime data is written under this folder's `data/` tree.
- The client bundle is not required inside this folder.
