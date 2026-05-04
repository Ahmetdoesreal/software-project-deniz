import ctypes
from ctypes import wintypes

import psutil


def get_focused_window_for_windows() -> dict:
    try:
        user32 = ctypes.windll.user32
    except Exception as exc:
        return _unavailable_snapshot("user32_unavailable", str(exc))

    hwnd = int(user32.GetForegroundWindow() or 0)
    if not hwnd:
        return _unavailable_snapshot("no_foreground_window")

    process_id = _window_process_id(user32, hwnd)
    process_info = _process_info(process_id)

    return {
        "platform": "windows",
        "available": True,
        "window_handle": hwnd,
        "window_title": _window_text(user32, hwnd),
        "window_class": _window_class_name(user32, hwnd),
        "process_id": process_id,
        "process_name": process_info.get("process_name"),
        "process_path": process_info.get("process_path"),
        "source": "user32",
    }


def _window_process_id(user32, hwnd: int) -> int | None:
    pid = wintypes.DWORD()
    try:
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    except Exception:
        return None
    return int(pid.value or 0) or None


def _window_text(user32, hwnd: int) -> str | None:
    try:
        length = int(user32.GetWindowTextLengthW(wintypes.HWND(hwnd)))
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(wintypes.HWND(hwnd), buffer, len(buffer))
    except Exception:
        return None
    return buffer.value or None


def _window_class_name(user32, hwnd: int) -> str | None:
    buffer = ctypes.create_unicode_buffer(256)
    try:
        length = int(user32.GetClassNameW(wintypes.HWND(hwnd), buffer, len(buffer)))
    except Exception:
        return None
    if length <= 0:
        return None
    return buffer.value or None


def _process_info(process_id: int | None) -> dict:
    if not process_id:
        return {"process_name": None, "process_path": None}

    try:
        process = psutil.Process(process_id)
        return {
            "process_name": process.name() or None,
            "process_path": process.exe() or None,
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, psutil.Error, OSError):
        return {
            "process_name": None,
            "process_path": None,
        }


def _unavailable_snapshot(reason: str, detail: str | None = None) -> dict:
    snapshot = {
        "platform": "windows",
        "available": False,
        "reason": reason,
        "source": "user32",
    }
    if detail:
        snapshot["detail"] = detail
    return snapshot
