"""Small stdio helpers for console and windowed GUI processes."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator


def stdin_available() -> bool:
    stream = sys.stdin
    return stream is not None and not bool(getattr(stream, "closed", False))


def stdin_is_standalone() -> bool:
    stream = sys.stdin
    if stream is None or bool(getattr(stream, "closed", False)):
        return True
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError, ValueError):
        return True


def iter_stdin_lines() -> Iterator[str]:
    stream = sys.stdin
    if stream is None or bool(getattr(stream, "closed", False)):
        return
    try:
        for line in stream:
            yield line
    except (AttributeError, OSError, ValueError):
        return


def write_json_stdout(payload: dict) -> bool:
    stream = sys.stdout
    if stream is None or bool(getattr(stream, "closed", False)):
        return False
    try:
        stream.write(json.dumps(payload, ensure_ascii=True) + "\n")
        stream.flush()
    except (AttributeError, OSError, TypeError, ValueError):
        return False
    return True


def write_text_stderr(message: str) -> bool:
    stream = sys.stderr
    if stream is None or bool(getattr(stream, "closed", False)):
        return False
    try:
        stream.write(str(message))
        if not str(message).endswith("\n"):
            stream.write("\n")
        stream.flush()
    except (AttributeError, OSError, TypeError, ValueError):
        return False
    return True
