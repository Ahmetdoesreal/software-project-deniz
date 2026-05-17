# May_12 Client Bundle

This folder is the deployable student/client side of the project.

## Contents

| Path | Purpose |
| --- | --- |
| `client/` | Client runtime, monitoring, buffering, submission, and timer UI code. |
| `common/` | Shared protocol, security, IPC, discovery, matching, and text-safety helpers required by the client. |
| `common_ui/` | Bundled visual theme/helpers used by the client UI. |
| `ui/` | Compatibility wrappers for bundled UI helpers. |
| `launcher_ui/` | Client manager UI only. |
| `auth_util/` | AD/local auth helper code and executable. |
| `school_service.py` | CATS authentication helper. |
| `client_launcher.py` | Main client manager launcher. |
| `client_cli.py` | Manual client CLI entry point. |
| `requirements.txt` | Client Python dependency list. |

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
run_client_tk.bat
run_client_qt.bat
run_client_cli.bat --help
```

The run scripts use the user-wide Python 3.13 install. They prefer `py -3.13`
and fall back to `python` only when it resolves to Python 3.13.

## Deployment Notes

- Copy this whole `client` folder to a student machine.
- Install Python 3.13 manually before running setup.
- `setup.py` installs dependencies with `pip install --user`; no local Python
  environment is created.
- Keep `auth_config.json` with the client if AD/auth secret settings are needed.
- The client stores runtime files under its local `data/` folder after first run.
- The server bundle is not required inside this folder.
