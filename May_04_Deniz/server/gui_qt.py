"""Compatibility wrapper for the Qt server dashboard.

The implementation lives in ``server.ui.dashboard_qt``.
"""

from server.ui.dashboard_qt import *  # noqa: F401,F403


if __name__ == "__main__":
    raise SystemExit(run())  # noqa: F405
