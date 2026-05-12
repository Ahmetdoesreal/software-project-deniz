import time

from common import protocol


APP_KEY = "auth_validation"
APPROVAL_SECONDS_DEFAULT = 300
APPROVAL_SECONDS_MAX = 300


def _store(app) -> dict:
    if APP_KEY not in app or not isinstance(app.get(APP_KEY), dict):
        app[APP_KEY] = {"requests": {}, "approvals": {}}
    store = app[APP_KEY]
    store.setdefault("requests", {})
    store.setdefault("approvals", {})
    return store


def _now() -> float:
    return time.time()


def _bypass_until(app, name: str) -> float:
    bypass = app.get("auth_bypass") or {}
    try:
        return float(bypass.get(f"{name}_until", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def active_bypass_modes(app, *, allowed_user: bool) -> list[str]:
    now = _now()
    modes = []
    if _bypass_until(app, "cats") > now:
        modes.append("cats")
    if _bypass_until(app, "ad") > now:
        modes.append("ad")
    return modes


def validation_required(app, *, allowed_user: bool) -> bool:
    return bool(active_bypass_modes(app, allowed_user=allowed_user))


def approval_until(app, login_id: str) -> float:
    approval = _store(app)["approvals"].get(login_id) or {}
    try:
        until = float(approval.get("until", 0.0) or 0.0)
    except (TypeError, ValueError):
        until = 0.0
    if until <= _now():
        _store(app)["approvals"].pop(login_id, None)
        return 0.0
    return until


def is_approved(app, login_id: str) -> bool:
    return approval_until(app, login_id) > _now()


def validation_status(app, login_id: str) -> str:
    if not login_id:
        return "none"
    if is_approved(app, login_id):
        return "approved"
    request = _store(app)["requests"].get(login_id)
    if not isinstance(request, dict):
        return "none"
    return str(request.get("status") or "pending")


def record_request(
    app,
    *,
    login_id: str,
    ip: str,
    modes: list[str],
    password_present: bool,
) -> dict:
    requests = _store(app)["requests"]
    now_iso = protocol.now_iso()
    previous = requests.get(login_id) if isinstance(requests.get(login_id), dict) else {}
    request = {
        "login_id": login_id,
        "status": "pending",
        "requested_at": previous.get("requested_at") or now_iso,
        "updated_at": now_iso,
        "ip": ip,
        "auth_modes": list(modes),
        "password_present": bool(password_present),
        "attempts": int(previous.get("attempts", 0) or 0) + 1,
        "reason": "Waiting for admin credential validation.",
    }
    requests[login_id] = request
    return request


def approve(app, login_id: str, seconds: int = APPROVAL_SECONDS_DEFAULT) -> dict:
    seconds = max(1, min(APPROVAL_SECONDS_MAX, int(seconds or APPROVAL_SECONDS_DEFAULT)))
    until = _now() + seconds
    now_iso = protocol.now_iso()
    store = _store(app)
    request = store["requests"].get(login_id) if isinstance(store["requests"].get(login_id), dict) else {}
    if request:
        request["status"] = "approved"
        request["updated_at"] = now_iso
        request["reason"] = f"Approved for {seconds} second(s)."
        store["requests"][login_id] = request
    store["approvals"][login_id] = {
        "login_id": login_id,
        "until": until,
        "approved_at": now_iso,
        "seconds": seconds,
    }
    return store["approvals"][login_id]


def deny(app, login_id: str, reason: str = "") -> dict:
    now_iso = protocol.now_iso()
    store = _store(app)
    request = store["requests"].get(login_id) if isinstance(store["requests"].get(login_id), dict) else {}
    request = dict(request)
    request.update(
        {
            "login_id": login_id,
            "status": "denied",
            "updated_at": now_iso,
            "reason": reason or "Denied by admin.",
        }
    )
    request.setdefault("requested_at", now_iso)
    request.setdefault("ip", "")
    request.setdefault("auth_modes", [])
    request.setdefault("password_present", False)
    request.setdefault("attempts", 0)
    store["requests"][login_id] = request
    store["approvals"].pop(login_id, None)
    return request


def clear(app, login_id: str) -> None:
    store = _store(app)
    store["requests"].pop(login_id, None)
    store["approvals"].pop(login_id, None)


def rows(app) -> list[dict]:
    store = _store(app)
    now = _now()
    result = []
    for login_id, request in sorted(store["requests"].items()):
        if not isinstance(request, dict):
            continue
        approval = store["approvals"].get(login_id) or {}
        try:
            until = float(approval.get("until", 0.0) or 0.0)
        except (TypeError, ValueError):
            until = 0.0
        status = "approved" if until > now else str(request.get("status") or "pending")
        row = dict(request)
        row["status"] = status
        row["approval_remaining_seconds"] = int(max(0, until - now))
        result.append(row)
    return result


def summary(app) -> dict:
    all_rows = rows(app)
    return {
        "pending_count": sum(1 for row in all_rows if row.get("status") == "pending"),
        "approved_count": sum(1 for row in all_rows if row.get("status") == "approved"),
        "denied_count": sum(1 for row in all_rows if row.get("status") == "denied"),
        "requests": all_rows,
    }
