"""Compatibility wrapper for the Tk client exam UI.

The implementation lives in ``client.ui.exam_tk``.
"""

from client.ui.exam_tk import *  # noqa: F401,F403


if __name__ == "__main__":
    raise SystemExit(run())  # noqa: F405
