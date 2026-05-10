"""
ad_detect.py

Detect the currently logged-in Windows domain user so the launcher
can pre-fill the --login-id field.

Usage:
    from client.ad_detect import detect_login_id, detect_domain

    login_id = detect_login_id()   # e.g. "Deniz"  (bare username, no domain prefix)
    domain   = detect_domain()     # e.g. "CAN"
"""

from __future__ import annotations


def detect_login_id() -> str | None:
    """Return the bare Windows username of the currently logged-in user, or None."""
    try:
        from auth_util.ad_auth import current_domain_user
        domain_user = current_domain_user()
        if not domain_user:
            return None
        return domain_user.split("\\", 1)[1] if "\\" in domain_user else domain_user
    except Exception:
        return None


def detect_domain() -> str | None:
    """Return the domain portion of the currently logged-in user, or None."""
    try:
        from auth_util.ad_auth import current_domain_user
        domain_user = current_domain_user()
        if not domain_user or "\\" not in domain_user:
            return None
        return domain_user.split("\\", 1)[0]
    except Exception:
        return None
