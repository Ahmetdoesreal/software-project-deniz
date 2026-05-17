@echo off
setlocal
cd /d "%~dp0"
set "PY_CMD="
py -3.13 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY_CMD=py -3.13"
if not defined PY_CMD (
    python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
)
if not defined PY_CMD (
    echo Python 3.13 was not found. Install Python manually, then rerun this script.
    exit /b 1
)
%PY_CMD% server_cli.py %*
