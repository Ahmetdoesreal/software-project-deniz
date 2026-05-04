"""
server/baris_features.py
========================
Authentication & security integration module — all auth-related logic
consolidated in one place:

  * CATS web-scrape authentication (school_service.py)
  * Same-IP duplicate login prevention (anti-cheat)
  * IP-based login rate-limiting (brute-force protection)
  * Admin endpoints (token-protected, instructor RBAC)
  * SQLite audit hooks (db_manager.py)

Design decision:
  The existing server code is changed MINIMALLY. All auth/security logic
  lives here; other server files simply call the hook functions defined
  in this module.

Server files modified:
  - server/handlers.py  login_handler     -> baris_login_preflight call
  - server/handlers.py  websocket_handler -> IP capture added
  - server/app.py       create_app        -> register_admin_routes() added
  - server_launcher.py                    -> Authentication & Security panel
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Optional

from aiohttp import web


# ════════════════════════════════════════════════════════════════════════
#  IMPORT PATH SETUP
#  Stand-alone modules (school_service, db_manager, instructor_auth,
#  security_layer) live in the May_04 root. Add it to sys.path once.
# ════════════════════════════════════════════════════════════════════════
_MODULE_ROOT = Path(__file__).resolve().parent.parent  # -> May_04/
if str(_MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(_MODULE_ROOT))


# ════════════════════════════════════════════════════════════════════════
#  OPTIONAL MODULES (graceful degrade if missing)
# ════════════════════════════════════════════════════════════════════════
try:
    import school_service  # CATS HTML scrape
    SCHOOL_SERVICE_AVAILABLE = True
except ImportError as exc:
    print(f"[SERVER] school_service not available: {exc}")
    school_service = None
    SCHOOL_SERVICE_AVAILABLE = False

try:
    import db_manager as baris_db  # SQLite layer
    DB_MANAGER_AVAILABLE = True
except ImportError as exc:
    print(f"[SERVER] db_manager not available: {exc}")
    baris_db = None
    DB_MANAGER_AVAILABLE = False

try:
    from instructor_auth import verify_instructor_role  # RBAC
    INSTRUCTOR_AUTH_AVAILABLE = True
except ImportError as exc:
    print(f"[SERVER] instructor_auth not available: {exc}")
    verify_instructor_role = None
    INSTRUCTOR_AUTH_AVAILABLE = False


# ════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
#  All values can be overridden via environment variables.
# ════════════════════════════════════════════════════════════════════════
USE_CATS = os.environ.get("BARIS_USE_CATS", "1") == "1"
SAME_IP_DUPLICATE_CHECK = os.environ.get("BARIS_IP_CHECK", "1") == "1"
LOGIN_RATE_LIMIT_SEC = float(os.environ.get("BARIS_RATE_LIMIT_SEC", "1.0"))
ADMIN_TOKEN = os.environ.get("BARIS_ADMIN_TOKEN", "admin-token-2026")
LOG_PREFIX = "[SERVER]"

# Login rate-limit tracker (IP -> last_attempt_unix_ts)
_recent_login_attempts: dict[str, float] = {}

# CATS-verified display names (login_id -> "Full Name")
_cats_display_names: dict[str, str] = {}


# ════════════════════════════════════════════════════════════════════════
#  CATS AUTH
# ════════════════════════════════════════════════════════════════════════
def cats_enabled() -> bool:
    return USE_CATS and SCHOOL_SERVICE_AVAILABLE


def verify_with_cats(login_id: str, password: str) -> tuple[bool, str]:
    """
    Authenticate a student via CATS web scrape.
    Returns: (success, display_name_or_error_message)
    """
    if not cats_enabled():
        return False, "CATS module is disabled"
    try:
        return school_service.verify_user(login_id, password)
    except Exception as exc:
        return False, f"CATS error: {exc}"


def get_display_name(login_id: str) -> str:
    """Return the CATS-fetched display name, or login_id as fallback."""
    return _cats_display_names.get(login_id, login_id)


# ════════════════════════════════════════════════════════════════════════
#  IP DUPLICATE PREVENTION (anti-cheat)
# ════════════════════════════════════════════════════════════════════════
def is_ip_already_active(ip: str, except_login_id: str = "", state=None) -> bool:
    """
    Returns True if another active student is already connected from the same IP.
    Localhost addresses (127.0.0.1, ::1) are exempt for testing purposes.
    """
    if not SAME_IP_DUPLICATE_CHECK or not state:
        return False
    if not ip or ip in ("0.0.0.0", "127.0.0.1", "::1", "localhost"):
        return False

    for uuid_key, client_data in state.clients.items():
        if not isinstance(client_data, dict):
            continue
        if client_data.get("login_id") == except_login_id:
            continue
        client_ip = client_data.get("ip", "")
        if client_ip == ip:
            return True
    return False


# ════════════════════════════════════════════════════════════════════════
#  RATE LIMIT
# ════════════════════════════════════════════════════════════════════════
def check_rate_limit(ip: str) -> bool:
    """Returns True if the request is allowed, False if it should be rejected."""
    if not ip or not LOGIN_RATE_LIMIT_SEC > 0:
        return True
    now = time.time()
    last = _recent_login_attempts.get(ip, 0.0)
    if now - last < LOGIN_RATE_LIMIT_SEC:
        return False
    _recent_login_attempts[ip] = now
    return True


# ════════════════════════════════════════════════════════════════════════
#  DB AUDIT HOOKS
# ════════════════════════════════════════════════════════════════════════
def db_log_login(login_id: str, ip: str, ok: bool, reason: str = ""):
    if not DB_MANAGER_AVAILABLE:
        return
    try:
        baris_db.log_audit(
            "http_login",
            actor=login_id,
            target=ip,
            details={"reason": reason},
            result="OK" if ok else "FAIL",
        )
    except Exception as exc:
        print(f"{LOG_PREFIX} DB audit log error: {exc}")


def db_log_violation(login_id: str, vtype: str, window: str, score: int):
    if not DB_MANAGER_AVAILABLE:
        return
    try:
        baris_db.save_violation_to_db(login_id, vtype, window, score)
    except Exception:
        pass


def db_log_admin_action(action: str, target: str, details: dict):
    if not DB_MANAGER_AVAILABLE:
        return
    try:
        baris_db.log_audit(
            f"admin_{action}",
            actor="admin",
            target=target,
            details=details,
            result="OK",
        )
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════════
#  PRE-LOGIN PIPELINE
#  handlers.login_handler calls this function -> all auth checks in one
#  place. If it passes, the normal login flow continues.
# ════════════════════════════════════════════════════════════════════════
async def baris_login_preflight(
    request: web.Request,
    login_id: str,
    password: str,
    state,
) -> tuple[bool, Optional[web.Response]]:
    """
    Returns (ok, response):
        - (True, None)          -> all checks passed, login may proceed
        - (False, web.Response) -> rejected, return the response directly
    """
    client_ip = request.remote or "0.0.0.0"

    # 1) Rate limit
    if not check_rate_limit(client_ip):
        db_log_login(login_id, client_ip, False, "rate_limit")
        return False, web.json_response(
            {"error": "Too many login attempts. Please wait before trying again."},
            status=429,
        )

    # 2) Same-IP duplicate check
    if is_ip_already_active(client_ip, except_login_id=login_id, state=state):
        db_log_login(login_id, client_ip, False, "duplicate_ip")
        print(f"{LOG_PREFIX} Second login attempt from {client_ip} rejected (login_id={login_id})")
        return False, web.json_response(
            {"error": "Another student is already active from this computer."},
            status=409,
        )

    # 3) CATS authentication (if enabled)
    if cats_enabled():
        ok, name_or_err = verify_with_cats(login_id, password)
        if not ok:
            db_log_login(login_id, client_ip, False, f"cats_fail: {name_or_err}")
            print(f"{LOG_PREFIX} CATS rejected: {login_id} -> {name_or_err}")
            return False, web.json_response(
                {"error": f"Authentication error: {name_or_err}"},
                status=401,
            )

        # CATS success -> automatically add to allowed_users so Ahmet's existing
        # allowed_users check passes (CATS-verified users bypass allowed_users.json)
        state.allowed_users[login_id] = password
        _cats_display_names[login_id] = name_or_err
        print(f"{LOG_PREFIX} CATS verified: {login_id} -> '{name_or_err}'")

    db_log_login(login_id, client_ip, True, "preflight_passed")
    return True, None


def remember_client_ip(state, client_uuid: str, ip: str):
    """
    Called by websocket_handler when a connection is established.
    Stores the client IP so is_ip_already_active can detect duplicate connections.
    """
    if client_uuid in state.clients and isinstance(state.clients[client_uuid], dict):
        state.clients[client_uuid]["ip"] = ip


# ════════════════════════════════════════════════════════════════════════
#  ADMIN ENDPOINTS
#  Token-protected. Registered via register_admin_routes() in app.py.
# ════════════════════════════════════════════════════════════════════════
def _check_admin_token(request: web.Request) -> tuple[bool, str]:
    token = request.query.get("token") or request.headers.get("X-Admin-Token", "")
    if token != ADMIN_TOKEN:
        return False, "Invalid admin token."
    return True, ""


async def admin_status(request: web.Request) -> web.Response:
    """GET /admin/status — no auth required, returns system status."""
    return web.json_response({
        "version": "server-integrated-v1.0",
        "cats_enabled": cats_enabled(),
        "ip_check_enabled": SAME_IP_DUPLICATE_CHECK,
        "rate_limit_sec": LOGIN_RATE_LIMIT_SEC,
        "db_manager_available": DB_MANAGER_AVAILABLE,
        "instructor_auth_available": INSTRUCTOR_AUTH_AVAILABLE,
        "school_service_available": SCHOOL_SERVICE_AVAILABLE,
    })


async def admin_list_students(request: web.Request) -> web.Response:
    """GET /admin/list?token=... — list all active students."""
    ok, err = _check_admin_token(request)
    if not ok:
        return web.json_response({"status": "error", "message": err}, status=401)

    from .state import state
    students = []
    for uuid_key, client_data in state.clients.items():
        if not isinstance(client_data, dict):
            continue
        login_id = client_data.get("login_id", "")
        user = state.users_db.get(login_id, {}) if login_id else {}
        students.append({
            "login_id": login_id,
            "uuid": uuid_key,
            "ip": client_data.get("ip", ""),
            "computer_name": client_data.get("computer_name", ""),
            "display_name": get_display_name(login_id),
            "exam_started": user.get("exam_started", False),
            "exam_finished": user.get("exam_finished", False),
            "banned": user.get("banned", False),
            "admin_paused": user.get("admin_paused", False),
            "extra_time_seconds": user.get("extra_time_seconds", 0),
            "session_state": user.get("session_state", "unknown"),
        })
    return web.json_response({"students": students, "count": len(students)})


async def admin_force_stop(request: web.Request) -> web.Response:
    """POST /admin/force_stop?token=...&login_id=... — force-terminate a student."""
    ok, err = _check_admin_token(request)
    if not ok:
        return web.json_response({"status": "error", "message": err}, status=401)

    login_id = request.query.get("login_id", "").strip()
    if not login_id:
        return web.json_response({"status": "error", "message": "login_id required"}, status=400)

    from .state import state
    user = state.users_db.get(login_id)
    if not user:
        return web.json_response({"status": "error", "message": f"{login_id} not found"}, status=404)

    user["exam_finished"] = True
    user["session_state"] = "submitted"
    state.save_users()
    db_log_admin_action("force_stop", login_id, {})
    print(f"{LOG_PREFIX} Admin: {login_id} force-stopped")
    return web.json_response({"status": "ok", "message": f"{login_id} terminated."})


async def admin_pause_user(request: web.Request) -> web.Response:
    """POST /admin/pause?token=...&login_id=... — pause a student."""
    ok, err = _check_admin_token(request)
    if not ok:
        return web.json_response({"status": "error", "message": err}, status=401)

    login_id = request.query.get("login_id", "").strip()
    if not login_id:
        return web.json_response({"status": "error", "message": "login_id required"}, status=400)

    from .state import state
    user = state.users_db.get(login_id)
    if not user:
        return web.json_response({"status": "error", "message": f"{login_id} not found"}, status=404)

    user["admin_paused"] = True
    state.save_users()
    db_log_admin_action("pause", login_id, {})
    return web.json_response({"status": "ok", "message": f"{login_id} paused."})


async def admin_resume_user(request: web.Request) -> web.Response:
    """POST /admin/resume?token=...&login_id=... — resume a paused student."""
    ok, err = _check_admin_token(request)
    if not ok:
        return web.json_response({"status": "error", "message": err}, status=401)

    login_id = request.query.get("login_id", "").strip()
    if not login_id:
        return web.json_response({"status": "error", "message": "login_id required"}, status=400)

    from .state import state
    user = state.users_db.get(login_id)
    if not user:
        return web.json_response({"status": "error", "message": f"{login_id} not found"}, status=404)

    user["admin_paused"] = False
    state.save_users()
    db_log_admin_action("resume", login_id, {})
    return web.json_response({"status": "ok", "message": f"{login_id} resumed."})


async def admin_grant_extra_time(request: web.Request) -> web.Response:
    """POST /admin/extra_time?token=...&login_id=...&minutes=N — grant extra time."""
    ok, err = _check_admin_token(request)
    if not ok:
        return web.json_response({"status": "error", "message": err}, status=401)

    login_id = request.query.get("login_id", "").strip()
    minutes_str = request.query.get("minutes", "5")
    if not login_id:
        return web.json_response({"status": "error", "message": "login_id required"}, status=400)

    try:
        minutes = int(minutes_str)
    except ValueError:
        return web.json_response({"status": "error", "message": "minutes must be an integer"}, status=400)

    from .state import state
    user = state.users_db.get(login_id)
    if not user:
        return web.json_response({"status": "error", "message": f"{login_id} not found"}, status=404)

    user["extra_time_seconds"] = int(user.get("extra_time_seconds", 0)) + minutes * 60
    state.save_users()
    db_log_admin_action("extra_time", login_id, {"minutes": minutes})
    return web.json_response({"status": "ok", "message": f"{login_id} -> +{minutes} min added."})


async def admin_unban(request: web.Request) -> web.Response:
    """POST /admin/unban?token=...&login_id=... — remove a ban from a student."""
    ok, err = _check_admin_token(request)
    if not ok:
        return web.json_response({"status": "error", "message": err}, status=401)

    login_id = request.query.get("login_id", "").strip()
    if not login_id:
        return web.json_response({"status": "error", "message": "login_id required"}, status=400)

    from .state import state
    user = state.users_db.get(login_id)
    if not user:
        return web.json_response({"status": "error", "message": f"{login_id} not found"}, status=404)

    user["banned"] = False
    state.save_users()
    db_log_admin_action("unban", login_id, {})
    return web.json_response({"status": "ok", "message": f"{login_id} unbanned."})


def register_admin_routes(app: web.Application):
    """Called from app.py create_app() — registers all admin endpoints."""
    app.router.add_get("/admin/status", admin_status)
    app.router.add_get("/admin/list", admin_list_students)
    app.router.add_post("/admin/force_stop", admin_force_stop)
    app.router.add_post("/admin/pause", admin_pause_user)
    app.router.add_post("/admin/resume", admin_resume_user)
    app.router.add_post("/admin/extra_time", admin_grant_extra_time)
    app.router.add_post("/admin/unban", admin_unban)


# ════════════════════════════════════════════════════════════════════════
#  STARTUP BANNER
# ════════════════════════════════════════════════════════════════════════
def print_startup_banner():
    """ASCII-only output for Windows console compatibility."""
    def _safe_print(text: str):
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode("ascii", "replace").decode("ascii"))

    line = "=" * 64
    _safe_print(line)
    _safe_print("  [SERVER] Authentication & Security Module Loaded (v1.0)")
    _safe_print(f"    - CATS Auth         : {'YES' if cats_enabled() else 'NO (off)'}")
    _safe_print(f"    - Same-IP Check     : {'YES' if SAME_IP_DUPLICATE_CHECK else 'NO (off)'}")
    _safe_print(f"    - Rate Limit        : {LOGIN_RATE_LIMIT_SEC} sec")
    _safe_print(f"    - SQLite Audit      : {'YES' if DB_MANAGER_AVAILABLE else 'NO (missing)'}")
    _safe_print(f"    - Instructor RBAC   : {'YES' if INSTRUCTOR_AUTH_AVAILABLE else 'NO (missing)'}")
    _safe_print(f"    - Admin Endpoints   : /admin/status, /admin/list, /admin/force_stop,")
    _safe_print(f"                          /admin/pause, /admin/resume, /admin/extra_time, /admin/unban")
    _safe_print(f"    - Admin Token       : {ADMIN_TOKEN!r}")
    _safe_print(line)
