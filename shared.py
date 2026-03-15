"""
Shared protocol helpers for JSON message encoding/decoding.

Every message between server and client is a JSON object with:
  - "event": str   (e.g. "ping", "echo", "time", "welcome")
  - "data":  dict  (payload, varies per event)
"""

import json
from datetime import datetime, timezone


def encode(event: str, data: dict | None = None) -> str:
    """Encode an event + data dict into a JSON string."""
    return json.dumps({"event": event, "data": data or {}})


def decode(raw: str) -> tuple[str, dict]:
    """Decode a JSON string into (event, data). Returns ("error", {}) on failure."""
    try:
        msg = json.loads(raw)
        return msg["event"], msg.get("data", {})
    except (json.JSONDecodeError, KeyError):
        return "error", {"reason": "malformed message"}


def now_iso() -> str:
    """Current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()
