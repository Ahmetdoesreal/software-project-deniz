# May_12 Server Bundle

This folder is the deployable operator/server side of the project.

## Contents

| Path | Purpose |
| --- | --- |
| `server/` | Server runtime, HTTP/WebSocket routes, dashboard UI, projector files, state, policy, and command logic. |
| `common/` | Shared protocol, security, IPC, discovery, matching, and text-safety helpers required by the server. |
| `ui/` | Shared Qt visual helpers used by the Qt dashboard. |
| `launcher_ui/` | Server manager UI only. |
| `data/server/` | Policy-style defaults copied from the source project. Runtime logs/artifacts are not preloaded. |
| `allowed_users.json` | Allowed login IDs for server-side admission. |
| `auth_config.json` | Shared auth secret/default auth config. |
| `server_launcher.py` | Main server manager launcher. |
| `server_cli.py` | Manual server CLI entry point. |
| `requirements.txt` | Server Python dependency list. |

## Setup

From the parent `May_12` folder, run:

```bat
setup\install_server_deps.bat
```

This creates `server\.venv` and installs packages from `setup\wheelhouse` when
available.

## Run

```bat
run_server_tk.bat
run_server_qt.bat
run_server_cli.bat --help
```

The run scripts prefer `server\.venv\Scripts\python.exe` and fall back to
`python` if no local venv exists.

## Deployment Notes

- Copy this whole `server` folder to the operator/server machine.
- Edit `allowed_users.json` before an exam.
- Server runtime data is written under this folder's `data/` tree.
- The client bundle is not required inside this folder.

