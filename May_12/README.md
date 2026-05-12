# May_12 Deployment Split

This folder is a clean deployment split of the current `May_04_Deniz` implementation.

## Layout

| Folder | Purpose |
| --- | --- |
| `client/` | Student/client deployment bundle. Contains client code, shared common code, client UI, client launchers, auth helpers, and client requirements. |
| `server/` | Operator/server deployment bundle. Contains server code, shared common code, server UI, server launchers, projector files, server policy defaults, and server requirements. |
| `setup/` | Shared dependency setup assets and scripts. Contains the offline wheelhouse, Python installer location, FFmpeg binaries, and venv install helpers. |

## Deployment Rule

The `client` and `server` folders are intentionally independent. Shared modules
such as `common/` and `ui/` are duplicated so that either folder can be copied to
another machine without depending on `May_04_Deniz/` or the other side.

Server code is not placed inside the client bundle. Client runtime code is not
placed inside the server bundle.

## Quick Start

From this folder:

```bat
setup\install_server_deps.bat
setup\install_client_deps.bat
```

Then start:

```bat
server\run_server_tk.bat
client\run_client_tk.bat
```

Qt variants are also available:

```bat
server\run_server_qt.bat
client\run_client_qt.bat
```

## Notes

- Dependency setup creates `.venv` inside the selected `client` or `server`
  folder. It does not install packages into global Python `site-packages`.
- The offline wheelhouse currently matches the bundled Python 3.13.x assets.
  Rebuild the wheelhouse before targeting another Python version.
- Runtime logs, submissions, artifacts, and client buffers are not preloaded
  from the source project.

