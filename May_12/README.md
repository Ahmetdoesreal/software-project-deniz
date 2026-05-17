# May_12 Deployment Split

This folder keeps the student/client and operator/server bundles separate.

## Layout

| Folder | Purpose |
| --- | --- |
| `client/` | Student/client deployment bundle with its own `setup.py`, requirements, UI, launcher, and runtime code. |
| `server/` | Operator/server deployment bundle with its own `setup.py`, requirements, UI, launcher, and runtime code. |

The bundles are intentionally independent. Copy `client/` to student machines
and `server/` to the operator machine.

## Offline Packages

On the dev PC, generate offline package folders:

```bat
python tools\offline_package_generator.py --target all
```

This writes:

```text
May_12\client\offline-packages
May_12\server\offline-packages
```

If you already have a prepared wheelhouse/FFmpeg source, seed from it:

```bat
python tools\offline_package_generator.py --target all --source X:\prepared-offline-packages
```

## Client Setup

```bat
cd May_12\client
python setup.py --offline
run_client_qt.bat
```

`--offline` defaults to `client\offline-packages`. Use `--source` only when
the offline source is elsewhere.

## Server Setup

```bat
cd May_12\server
python setup.py --offline
run_server_qt.bat
```

`--offline` defaults to `server\offline-packages`. Use `--source` only when
the offline source is elsewhere.

## Notes

- Python 3.13 must be installed manually before setup runs.
- Setup never launches or installs Python.
- Setup installs Python packages into the current user's site-packages with
  `pip install --user`; no local Python environment is created.
- Offline dependency installs use `offline-packages\wheelhouse` with
  `pip --no-index`.
- FFmpeg is loaded from `EXAM_FFMPEG_PATH` first, then
  `client\offline-packages\ffmpeg\bin`, then normal `PATH`.
- LAN deployment assumes local copies on each machine, with server discovery and
  manual host fallback kept as-is.
