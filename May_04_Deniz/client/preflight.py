"""
client/preflight.py

Local pre-login validation. When possible, the launcher first asks the server
whether a short-lived CATS/AD bypass is currently allowed for this login.
Otherwise both checks run in parallel and must pass.

  1. CATS  — scrapes the school portal to confirm the student's credentials are live.
  2. AD    — validates via Windows LogonUserW and returns an HMAC token.

The HMAC token is what the client subprocess sends to the server.
The AD password never travels over the network.
"""

from __future__ import annotations

import concurrent.futures
import asyncio
import json
import sys
from pathlib import Path

import aiohttp

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from common.discovery import discover_server_with_local_fallback


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


async def fetch_auth_status(base_url: str, login_id: str) -> dict | None:
    try:
        timeout = aiohttp.ClientTimeout(total=3.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{base_url}/auth/status", params={"login_id": login_id}) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data if isinstance(data, dict) else None
    except Exception:
        return None


async def resolve_auth_status(
    login_id: str,
    *,
    server_id: str,
    host: str | None,
    port: int,
    timeout: float = 3.0,
) -> dict | None:
    if host:
        return await fetch_auth_status(f"http://{host}:{port}", login_id)
    target = await discover_server_with_local_fallback(
        server_id=server_id,
        timeout=timeout,
        local_port=port,
    )
    if not target:
        return None
    resolved_host, resolved_port = target
    return await fetch_auth_status(f"http://{resolved_host}:{resolved_port}", login_id)


def resolve_auth_status_sync(
    login_id: str,
    *,
    server_id: str,
    host: str | None,
    port: int,
    timeout: float = 3.0,
) -> dict | None:
    try:
        return asyncio.run(
            resolve_auth_status(
                login_id,
                server_id=server_id,
                host=host,
                port=port,
                timeout=timeout,
            )
        )
    except Exception:
        return None


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
    auth_status: dict | None = None,
) -> tuple[bool, str]:
    """
    Run CATS and AD checks in parallel. Both must pass.

    Returns:
        (True,  hmac_token)   — both checks passed; token is sent to the server
        (False, error_message) — one or both checks failed
    """
    cats_required = True
    ad_required = bool(ad_domain and auth_secret)
    if isinstance(auth_status, dict):
        cats_required = bool(auth_status.get("cats_required", True))
        ad_required = bool(auth_status.get("ad_required", ad_required))

    if not cats_required and not ad_required:
        return True, "Temporary server auth bypass active."

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        cats_future = pool.submit(_check_cats, login_id, password) if cats_required else None
        ad_future = pool.submit(_check_ad, login_id, password, ad_domain, auth_secret) if ad_required else None

        cats_ok, cats_result = (cats_future.result() if cats_future else (True, "CATS bypassed by server."))
        ad_ok, ad_result = (ad_future.result() if ad_future else (True, "AD bypassed by server."))

    if not cats_ok:
        return False, f"School authentication failed: {cats_result}"
    if not ad_ok:
        return False, ad_result

    return True, ad_result  # ad_result is the HMAC token on success
