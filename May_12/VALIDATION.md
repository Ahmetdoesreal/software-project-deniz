# May_12 Deployment Split Validation

Date: 2026-05-12

## Structure

| Folder | Status |
| --- | --- |
| `setup/` | Created with offline wheelhouse, installer assets, FFmpeg assets, manifest, and dependency setup scripts. |
| `client/` | Created as standalone client bundle with no server package folder. |
| `server/` | Created as standalone server bundle with no client package folder. |

## Boundary Checks

| Check | Result |
| --- | --- |
| `May_12/server` has no `client/` package folder | Passed |
| `May_12/client` has no `server/` package folder | Passed |
| Server bundle source scan for top-level `from client` or `import client` | Passed |
| Client bundle source scan for top-level `from server` or `import server` | Passed |

## Dependency Checks

| Check | Result |
| --- | --- |
| Client requirements resolved with `pip --dry-run --ignore-installed --no-index --find-links ..\setup\wheelhouse` | Passed |
| Server requirements resolved with `pip --dry-run --ignore-installed --no-index --find-links ..\setup\wheelhouse` | Passed |
| Setup PowerShell script parse | Passed |
| Setup `manifest.sha256` verification | Passed, 31 files |

## Import And Syntax Checks

| Check | Result |
| --- | --- |
| `python -m compileall -q .` in `May_12/client` | Passed |
| `python -m compileall -q .` in `May_12/server` | Passed |
| `python client_cli.py --help` in `May_12/client` | Passed |
| `python server_cli.py --help` in `May_12/server` | Passed |

## Cleanup

Validation-generated `__pycache__` folders and runtime log folders were removed
from `May_12` after checks completed.

## Notes

The copied offline wheelhouse is currently Python 3.13 / Windows x64 oriented.
Rebuild it before using Python 3.14 or a different platform.

