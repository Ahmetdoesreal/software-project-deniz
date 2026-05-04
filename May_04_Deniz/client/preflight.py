"""
client/preflight.py

Local pre-login validation that runs before any network contact with the server.
Both checks run in parallel and must pass.

  1. CATS  — scrapes the school portal to confirm the student's credentials are live.
  2. AD    — validates via Windows LogonUserW and returns an HMAC token.

The HMAC token is what the client subprocess sends to the server.
The AD password never travels over the network.
"""

from __future__ import annotations

import concurrent.futures
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def load_auth_config(project_dir: Path | None = None) -> dict:
    """
    Read auth_config.json from the project root.
    Returns defaults if the file is missing or unreadable.
    """
    path = (project_dir or _ROOT) / "auth_config.json"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"ad_domain": ".", "auth_secret": ""}


# ── Individual checks ─────────────────────────────────────────────────────────

def _check_cats(login_id: str, password: str) -> tuple[bool, str]:
    """Returns (ok, display_name_or_error)."""
    try:
        import school_service
        return school_service.verify_user(login_id, password)
    except ImportError:
        return False, (
            "CATS module not available. "
            "Install requests and beautifulsoup4: pip install requests beautifulsoup4"
        )
    except Exception as exc:
        return False, f"CATS error: {exc}"


def _check_ad(login_id: str, password: str, ad_domain: str, auth_secret: str) -> tuple[bool, str]:
    """Returns (ok, token_or_error)."""
    try:
        from auth_util.ad_auth import generate_token
        token = generate_token(ad_domain, login_id, password, auth_secret)
        if token:
            return True, token
        return False, "Windows authentication failed. Check your username, password, and domain."
    except FileNotFoundError as exc:
        return False, f"AD auth unavailable: {exc}"
    except Exception as exc:
        return False, f"AD authentication error: {exc}"


# ── Public API ────────────────────────────────────────────────────────────────

def run_preflight(
    login_id: str,
    password: str,
    ad_domain: str,
    auth_secret: str,
) -> tuple[bool, str]:
    """
    Run CATS and AD checks in parallel. Both must pass.

    Returns:
        (True,  hmac_token)   — both checks passed; token is sent to the server
        (False, error_message) — one or both checks failed
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        cats_future = pool.submit(_check_cats, login_id, password)
        ad_future   = pool.submit(_check_ad, login_id, password, ad_domain, auth_secret)

        cats_ok, cats_result = cats_future.result()
        ad_ok,   ad_result   = ad_future.result()

    if not cats_ok:
        return False, f"School authentication failed: {cats_result}"
    if not ad_ok:
        return False, ad_result

    return True, ad_result  # ad_result is the HMAC token on success
