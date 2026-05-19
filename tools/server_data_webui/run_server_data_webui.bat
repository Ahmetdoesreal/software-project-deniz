@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%..\.."
set "DATA_ROOT=%~1"
set "PORT=%~2"

if "%DATA_ROOT%"=="" set "DATA_ROOT=data\server"
if "%PORT%"=="" set "PORT=8765"

cd /d "%REPO_ROOT%"

echo Server Data Web UI
echo Data root: %DATA_ROOT%
echo URL: http://127.0.0.1:%PORT%/
echo.
echo Pass a different data root as the first argument, and a different port as the second.
echo Example:
echo   tools\server_data_webui\run_server_data_webui.bat Software\server_data\data\server 8765
echo.

start "" "http://127.0.0.1:%PORT%/"
python "%SCRIPT_DIR%server.py" --data-root "%DATA_ROOT%" --host 127.0.0.1 --port "%PORT%"

echo.
echo Server stopped.
pause
