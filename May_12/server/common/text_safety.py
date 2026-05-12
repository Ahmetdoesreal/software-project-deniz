"""Unicode text normalization helpers for window titles and logs."""

from __future__ import annotations

import locale
import re
import sys
import unicodedata


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_display_text(value) -> str:
    """Normalize text for UI display, matching, and diagnostic logs.

    Browser titlebars can include invisible directional marks, zero-width
    joiners, BOMs, and non-breaking spaces. Those characters make equivalent
    titles compare differently and can trigger Windows console charmap errors
    when they pass through direct stdout/stderr paths.
    """
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    cleaned: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if category == "Cf":
            continue
        if category.startswith("C"):
            if char in "\t\n\r":
                cleaned.append(" ")
            continue
        if category.startswith("Z") or char.isspace():
            cleaned.append(" ")
            continue
        cleaned.append(char)
    return _WHITESPACE_RE.sub(" ", "".join(cleaned)).strip()


def normalize_for_match(value) -> str:
    return normalize_display_text(value).casefold()


def sanitize_window_title(value) -> str:
    return normalize_display_text(value)


def sanitize_window_snapshot(snapshot: dict) -> dict:
    if not isinstance(snapshot, dict):
        return {}
    sanitized = dict(snapshot)
    original_title = sanitized.get("window_title")
    cleaned_title = sanitize_window_title(original_title)
    sanitized["window_title"] = cleaned_title or None
    if original_title is not None and str(original_title) != (cleaned_title or ""):
        sanitized["window_title_sanitized"] = True
    return sanitized


def safe_console_text(value, *, encoding: str | None = None) -> str:
    text = normalize_display_text(value)
    target_encoding = (
        encoding
        or getattr(sys.stdout, "encoding", None)
        or locale.getpreferredencoding(False)
        or "utf-8"
    )
    try:
        return text.encode(target_encoding, errors="backslashreplace").decode(
            target_encoding,
            errors="replace",
        )
    except LookupError:
        return text.encode("utf-8", errors="backslashreplace").decode("utf-8", errors="replace")
