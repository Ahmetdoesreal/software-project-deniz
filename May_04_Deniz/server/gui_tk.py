"""Compatibility wrapper for the Tk server dashboard.

The implementation lives in ``server.ui.dashboard_tk``.
"""

from server.ui.dashboard_tk import *  # noqa: F401,F403


if __name__ == "__main__":
    raise SystemExit(run())  # noqa: F405
