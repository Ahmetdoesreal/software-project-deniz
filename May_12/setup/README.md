# May_12 Setup Folder

This folder contains shared dependency setup assets for the split deployment.

## Files And Folders

| Path | Purpose |
| --- | --- |
| `install_client_deps.bat` | Creates/updates `..\client\.venv` and installs client dependencies. |
| `install_server_deps.bat` | Creates/updates `..\server\.venv` and installs server dependencies. |
| `install_bundle_deps.ps1` | Shared PowerShell installer used by both batch files. |
| `wheelhouse/` | Offline Python wheels used with `pip --no-index`. |
| `installers/` | Optional Python installer location. |
| `ffmpeg/` | FFmpeg binaries copied from the source offline installer bundle. |
| `manifest.sha256` | Integrity manifest copied from the source offline installer bundle. |

## Dependency Policy

The setup scripts create virtual environments inside the selected bundle folder.
They do not install packages into machine-wide Python `site-packages`.

The scripts prefer the local wheelhouse. If `wheelhouse/` is missing or empty,
they fall back to normal `pip install`, which requires internet access.

## Python Version

The currently copied wheelhouse contains Windows x64 wheels for the Python 3.13
bundle. Rebuild the wheelhouse before targeting Python 3.14 or another ABI.

