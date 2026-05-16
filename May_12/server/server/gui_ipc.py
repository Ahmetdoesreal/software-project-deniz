"""Helpers for parent-process IPC with the server dashboard GUI."""

from __future__ import annotations

import errno
import json
import subprocess

from .state import state


DASHBOARD_STATE_CHANNEL = "server.dashboard_state"

_CLOSED_PIPE_ERRNOS = {
    errno.EBADF,
    errno.EINVAL,
    errno.EPIPE,
}
if hasattr(errno, "ECONNRESET"):
    _CLOSED_PIPE_ERRNOS.add(errno.ECONNRESET)


def _is_closed_pipe_error(exc: BaseException) -> bool:
    if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
        return True
    return isinstance(exc, OSError) and getattr(exc, "errno", None) in _CLOSED_PIPE_ERRNOS


def _close_stdin(process) -> None:
    stream = getattr(process, "stdin", None)
    if stream is None:
        return
    try:
        stream.close()
    except Exception:
        pass


def mark_gui_process_closed(process=None) -> None:
    """Forget a dashboard process and stop its local IPC server."""
    current = getattr(state, "gui_process", None)
    target = process if process is not None else current
    if target is not None:
        _close_stdin(target)

    is_current_process = process is None or current is process
    if is_current_process:
        state.gui_process = None

        gui_ipc = getattr(state, "gui_ipc_server", None)
        if gui_ipc:
            try:
                gui_ipc.stop()
            except Exception:
                pass
            state.gui_ipc_server = None


def request_gui_shutdown(process=None, *, timeout: float = 2.0) -> None:
    """Ask the dashboard GUI to exit before falling back to termination."""
    target = process if process is not None else getattr(state, "gui_process", None)
    if target is None:
        mark_gui_process_closed(process)
        return

    if target.poll() is None:
        _close_stdin(target)
        try:
            target.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                target.terminate()
                target.wait(timeout=1.0)
            except Exception:
                try:
                    target.kill()
                except Exception:
                    pass

    mark_gui_process_closed(target)


def send_gui_payload(payload: dict, *, log_failures: bool = False) -> bool:
    """Send a dashboard payload over WebSocket IPC, falling back to stdio."""
    gui_ipc = getattr(state, "gui_ipc_server", None)
    if gui_ipc and gui_ipc.send(DASHBOARD_STATE_CHANNEL, payload):
        return True

    gui_process = state.get_gui_process()
    if not gui_process:
        return False

    stdin = getattr(gui_process, "stdin", None)
    if stdin is None:
        mark_gui_process_closed(gui_process)
        return False

    try:
        stdin.write(json.dumps(payload, ensure_ascii=True) + "\n")
        stdin.flush()
    except Exception as exc:
        if _is_closed_pipe_error(exc):
            mark_gui_process_closed(gui_process)
            if log_failures:
                print("[GUI IPC] Dashboard pipe closed; marked GUI as closed.")
        elif log_failures:
            print(f"[GUI IPC] Warning: Failed to write to GUI: {exc}")
        return False
    return True
