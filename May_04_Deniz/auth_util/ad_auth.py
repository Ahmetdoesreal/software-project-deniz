"""
ad_auth.py

Client-side AD authentication via check_user.exe.

Flow:
  1. User enters their Windows username + AD password on the client.
  2. generate_token() calls check_user.exe --gen-token which:
       a. validates the credentials locally via LogonUserW (never sends password)
       b. on success: computes HMAC-SHA256(shared_secret, username|time_window)
          and prints the hex token to stdout
       c. on failure: exits 1 with no output
  3. The Python client sends {login_id, token} to the server — no password travels
     over the network.
  4. The server independently verifies the HMAC with the same shared secret.

Build command (Developer Command Prompt):
    cl /EHsc /W4 check_user.cpp /link Secur32.lib Advapi32.lib Bcrypt.lib
"""

import subprocess
from pathlib import Path

_EXE = Path(__file__).parent / "check_user.exe"


def _exe_path() -> Path:
    if not _EXE.exists():
        raise FileNotFoundError(
            f"check_user.exe not found at {_EXE}. "
            "Recompile from auth_util/check_user.cpp."
        )
    return _EXE


def generate_token(domain: str, username: str, password: str, secret: str) -> str | None:
    """
    Validate Windows/AD credentials locally and return an HMAC auth token.

    The AD password is validated by check_user.exe and never sent anywhere.
    The returned token is what the client presents to the server.

    Args:
        domain:   AD domain name or "." for local accounts.
        username: Windows username (no domain prefix).
        password: The user's Windows / AD password.
        secret:   Shared secret configured on both client and server.

    Returns:
        64-character hex HMAC token on success, None if credentials are wrong
        or the exe is unavailable.
    """
    exe = _exe_path()
    result = subprocess.run(
        [str(exe), "--gen-token", domain, username, password, secret],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return None
    token = result.stdout.strip()
    return token if token else None


def current_domain_user() -> str | None:
    """
    Return the domain username of the currently logged-in Windows user
    in DOMAIN\\username format, or None if unavailable.
    """
    try:
        exe = _exe_path()
    except FileNotFoundError:
        return None
    try:
        result = subprocess.run(
            [str(exe), "--whoami"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            value = result.stdout.strip()
            return value if value and value != "UNKNOWN" else None
    except Exception:
        pass
    return None
