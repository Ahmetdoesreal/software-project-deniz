"""
IP-based login restrictions for the exam server.

Rules (all configurable at runtime via /security CLI commands):
  one_user_per_ip  — only one user account may be connected from a given IP at a time
  one_ip_per_user  — a user account is locked to the first IP it connected from
  rate_limit       — cap login attempts per IP within a rolling time window

Integration (minimal changes needed in other files):
  handlers.py  — call check_login() before returning UUID; call register_ip() on WS connect
  tasks.py     — forward "/security ..." commands to handle_security_command()

None of the public functions import from server.state to avoid circular imports;
they accept clients / users_db as plain dicts.
"""

import time
from typing import Callable

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_rules: dict = {
    "one_user_per_ip": True,
    "one_ip_per_user": True,
    "rate_limit_enabled": True,
    "rate_limit_max_attempts": 5,
    "rate_limit_window_seconds": 60,
}

_login_attempts: dict[str, list[float]] = {}  # ip -> [monotonic timestamps]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _record_attempt(ip: str) -> None:
    _login_attempts.setdefault(ip, []).append(time.monotonic())


def _is_rate_limited(ip: str) -> bool:
    now = time.monotonic()
    window = _rules["rate_limit_window_seconds"]
    attempts = _login_attempts.get(ip, [])
    recent = [t for t in attempts if now - t < window]
    _login_attempts[ip] = recent
    return len(recent) > _rules["rate_limit_max_attempts"]


def _ip_has_other_user(ip: str, login_id: str, clients: dict) -> bool:
    for client_id, info in clients.items():
        if info.get("ip") == ip:
            # resolve the login_id for this client by checking the UUID
            # clients dict doesn't directly store login_id, so we rely on the
            # caller having already resolved it — we compare via computer_name
            # fallback: mark as conflict only when computer_name is set and ip matches
            # The real login_id resolution happens via users_db in check_login().
            return True
    return False


def _user_has_other_ip(login_id: str, ip: str, users_db: dict) -> bool:
    user = users_db.get(login_id)
    if not user:
        return False
    stored = user.get("login_ip")
    return stored is not None and stored != ip

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_login(
    ip: str,
    login_id: str,
    clients: dict,
    users_db: dict,
) -> str | None:
    """
    Run all enabled checks for an incoming login attempt.

    Returns a human-readable reason string (for server-side logging only) if
    the attempt should be blocked, or None if it should be allowed.

    The HTTP response to the client must ALWAYS use the generic message
    "Authentication failed." — never expose the real reason.
    """
    if _rules["rate_limit_enabled"]:
        _record_attempt(ip)
        if _is_rate_limited(ip):
            return f"rate limit exceeded for ip={ip}"

    if _rules["one_user_per_ip"]:
        # Build a reverse map: ip -> set of login_ids currently in clients
        ip_to_users: dict[str, set] = {}
        for _cid, info in clients.items():
            cip = info.get("ip")
            clogin = info.get("login_id")  # populated by register_ip companion
            if cip and clogin:
                ip_to_users.setdefault(cip, set()).add(clogin)
        current_users_on_ip = ip_to_users.get(ip, set())
        others = current_users_on_ip - {login_id}
        if others:
            return f"ip={ip} already used by user(s): {', '.join(others)}"

    if _rules["one_ip_per_user"]:
        if _user_has_other_ip(login_id, ip, users_db):
            stored_ip = users_db[login_id].get("login_ip")
            return f"user={login_id} locked to ip={stored_ip}, attempted from ip={ip}"

    return None


def register_ip(
    login_id: str,
    ip: str,
    clients: dict,
    client_id: str,
    users_db: dict,
    save_fn: Callable,
) -> None:
    """
    Called when a WebSocket connection is fully established.
    - Stores login_ip in users_db (persisted via save_fn).
    - Annotates the clients entry with login_id for one_user_per_ip checks.
    """
    if login_id in users_db:
        if not users_db[login_id].get("login_ip"):
            users_db[login_id]["login_ip"] = ip
            save_fn()
    if client_id in clients:
        clients[client_id]["login_id"] = login_id


# ---------------------------------------------------------------------------
# CLI command handler
# ---------------------------------------------------------------------------

_VALID_BOOL_RULES = {"one_user_per_ip", "one_ip_per_user", "rate_limit_enabled"}


def handle_security_command(parts: list[str], users_db: dict) -> str:
    """
    Handle /security sub-commands. Returns a string to print in the admin console.

    Usage:
      /security status
      /security setrule <one_user_per_ip|one_ip_per_user|rate_limit> <on|off>
      /security setrate <max_attempts> <window_seconds>
      /security clearip <ip>
      /security clearuser <login_id>
    """
    if not parts:
        return security_help()

    sub = parts[0].lower()

    if sub == "status":
        lines = ["[ip_guard] Current settings:"]
        lines.append(f"  one_user_per_ip  : {'ON' if _rules['one_user_per_ip'] else 'OFF'}")
        lines.append(f"  one_ip_per_user  : {'ON' if _rules['one_ip_per_user'] else 'OFF'}")
        lines.append(f"  rate_limit       : {'ON' if _rules['rate_limit_enabled'] else 'OFF'}")
        lines.append(f"  rate_limit_max   : {_rules['rate_limit_max_attempts']} attempts")
        lines.append(f"  rate_limit_window: {_rules['rate_limit_window_seconds']}s")
        tracked = len(_login_attempts)
        lines.append(f"  tracked ips      : {tracked}")
        return "\n".join(lines)

    if sub == "setrule":
        if len(parts) < 3:
            return "[ip_guard] Usage: /security setrule <rule> <on|off>"
        rule_name = parts[1].lower()
        value_str = parts[2].lower()
        if value_str not in {"on", "off"}:
            return "[ip_guard] Value must be 'on' or 'off'."
        value = value_str == "on"
        # allow shorthand "rate_limit" to map to "rate_limit_enabled"
        if rule_name == "rate_limit":
            rule_name = "rate_limit_enabled"
        if rule_name not in _VALID_BOOL_RULES:
            return (
                f"[ip_guard] Unknown rule '{rule_name}'. "
                f"Valid: one_user_per_ip, one_ip_per_user, rate_limit"
            )
        _rules[rule_name] = value
        display = rule_name.replace("_enabled", "")
        return f"[ip_guard] Rule '{display}' set to {'ON' if value else 'OFF'}."

    if sub == "setrate":
        if len(parts) < 3:
            return "[ip_guard] Usage: /security setrate <max_attempts> <window_seconds>"
        try:
            max_att = int(parts[1])
            window = int(parts[2])
        except ValueError:
            return "[ip_guard] Both arguments must be integers."
        if max_att < 1 or window < 1:
            return "[ip_guard] Values must be positive integers."
        _rules["rate_limit_max_attempts"] = max_att
        _rules["rate_limit_window_seconds"] = window
        return f"[ip_guard] Rate limit set to {max_att} attempts per {window}s."

    if sub == "clearip":
        if len(parts) < 2:
            return "[ip_guard] Usage: /security clearip <ip>"
        ip = parts[1]
        removed = _login_attempts.pop(ip, None)
        if removed is None:
            return f"[ip_guard] No rate-limit record for ip={ip}."
        return f"[ip_guard] Cleared {len(removed)} attempt(s) for ip={ip}."

    if sub == "clearuser":
        if len(parts) < 2:
            return "[ip_guard] Usage: /security clearuser <login_id>"
        login_id = parts[1]
        user = users_db.get(login_id)
        if not user:
            return f"[ip_guard] Unknown user '{login_id}'."
        old_ip = user.pop("login_ip", None)
        if old_ip is None:
            return f"[ip_guard] User '{login_id}' has no stored IP lock."
        return f"[ip_guard] Cleared IP lock for '{login_id}' (was {old_ip})."

    return f"[ip_guard] Unknown sub-command '{sub}'. Type /security for help."


def security_help() -> str:
    return (
        "  /security status                          Show IP restriction rule states\n"
        "  /security setrule <rule> <on|off>         Toggle a rule (one_user_per_ip | one_ip_per_user | rate_limit)\n"
        "  /security setrate <max> <window_secs>     Set rate limit thresholds\n"
        "  /security clearip <ip>                    Clear rate-limit history for an IP\n"
        "  /security clearuser <login_id>            Remove IP lock for a user"
    )
