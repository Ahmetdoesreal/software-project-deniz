# Offline Installer Bundle

This folder is a local, one-click offline setup bundle for the `May_04_Deniz` application.

## One-Click Install

Run:

```bat
install_offline.bat
```

The installer:

- Requests administrator rights.
- Finds or installs all-users Python when a Python installer is present under `installers\`.
- Installs the Python launcher and `.py` file association for all users when bundled Python is installed.
- Installs Python packages from `wheelhouse\` into `C:\ProgramData\May_04_Deniz\python_env` without internet access.
- Installs the bundled FFmpeg files from `ffmpeg\bin\` into `C:\ProgramData\May_04_Deniz\ffmpeg\bin`.
- Adds the bundled FFmpeg path to the machine `PATH` when needed.
- Copies the runnable application into `C:\ProgramData\May_04_Deniz\app`.
- Seeds policy-style server config files into `C:\ProgramData\May_04_Deniz\app\data\server` without copying live logs, artifacts, incidents, or session state.
- Creates shared launch wrappers under `C:\ProgramData\May_04_Deniz\launchers`.
- Verifies `manifest.sha256` before installing when the manifest is present.
- Writes a setup log to `install_logs\`.

## Bundle Contents

- `install_offline.bat` - double-click entry point.
- `install_offline.ps1` - offline installation logic.
- `requirements-offline.txt` - package requirements installed from the local wheelhouse.
- `wheelhouse\` - Python wheels used by pip with `--no-index`.
- `ffmpeg\bin\` - FFmpeg binaries copied into the shared install area.
- `installers\` - optional Python installer location.
- `manifest.sha256` - optional SHA-256 manifest for the bundled wheels, Python installer, and FFmpeg files.
- `build_bundle.bat` and `build_bundle.ps1` - online builder for refreshing this bundle.

## Refreshing The Bundle

On a machine with internet access, run:

```bat
build_bundle.bat
```

That downloads the package wheelhouse for the current Python and copies the local FFmpeg binaries.

## Notes

The currently populated bundle targets Windows x64 and Python 3.13.5. Python 3.14.5 support is prepared in `build_bundle.ps1`; run `build_bundle.bat` on an internet-connected machine to refresh this folder with the Python 3.14.5 installer and Python 3.14 compatible wheels.

The wheelhouse is Python-version and platform specific. Rebuild it with `build_bundle.bat` before targeting another Python version.

The installer does not place packages into the machine Python `site-packages`. It creates a shared virtual environment under `C:\ProgramData\May_04_Deniz\python_env`, grants normal users read/execute access to code and dependencies, and grants write access only to `C:\ProgramData\May_04_Deniz\app\data` for runtime files.
