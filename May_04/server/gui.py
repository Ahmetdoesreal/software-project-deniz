"""Server monitor dashboard dispatcher.

Selects the GUI backend at runtime via ``--ui {tk,qt}``.

* ``--ui tk`` (default): the legacy Tkinter dashboard in ``server/gui_tk.py``.
* ``--ui qt``: the PySide6 reimplementation in ``server/gui_qt.py``.

Run directly via ``python -m server.gui [--ui tk|qt]``. ``server/tasks.py``
spawns this entry point with ``--ui`` already set by the launcher.
"""

from __future__ import annotations

import argparse
import sys


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch the server monitor dashboard GUI.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--ui",
        choices=("tk", "qt"),
        default="tk",
        help="GUI backend: 'tk' (legacy Tkinter), 'qt' (PySide6).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.ui == "qt":
        from server.gui_qt import run as run_qt
        return run_qt()

    from server.gui_tk import run as run_tk
    return run_tk()


if __name__ == "__main__":
    raise SystemExit(main())
