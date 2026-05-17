"""Compatibility wrapper for bundled Qt widget factories."""

from __future__ import annotations

import sys
from pathlib import Path

BUNDLE_DIR = Path(__file__).resolve().parents[1]
if str(BUNDLE_DIR) not in sys.path:
    sys.path.insert(0, str(BUNDLE_DIR))

from common_ui.widgets import *  # noqa: F401,F403
