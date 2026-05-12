# May_12 Client Bundle

This folder is the deployable student/client side of the project.

## Contents

| Path | Purpose |
| --- | --- |
| `client/` | Client runtime, monitoring, buffering, submission, and timer UI code. |
| `common/` | Shared protocol, security, IPC, discovery, matching, and text-safety helpers required by the client. |
| `ui/` | Shared Qt visual helpers used by the Qt client UI. |
| `launcher_ui/` | Client manager UI only. |
| `auth_util/` | AD/local auth helper code and executable. |
| `school_service.py` | CATS authentication helper. |
| `client_launcher.py` | Main client manager launcher. |
| `client_cli.py` | Manual client CLI entry point. |
| `requirements.txt` | Client Python dependency list. |

## Setup

From the parent `May_12` folder, run:

```bat
setup\install_client_deps.bat
```

This creates `client\.venv` and installs packages from `setup\wheelhouse` when
available.

## Run

```bat
run_client_tk.bat
run_client_qt.bat
run_client_cli.bat --help
```

The run scripts prefer `client\.venv\Scripts\python.exe` and fall back to
`python` if no local venv exists.

## Deployment Notes

- Copy this whole `client` folder to a student machine.
- Keep `auth_config.json` with the client if AD/auth secret settings are needed.
- The client stores runtime files under its local `data/` folder after first run.
- The server bundle is not required inside this folder.

