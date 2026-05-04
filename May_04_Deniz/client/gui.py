"""Client exam GUI dispatcher.

Selects the GUI backend at runtime via ``--ui {tk,qt}``.

* ``--ui tk`` (default): the legacy Tkinter timer + submission GUI in
  ``client/gui_tk.py``.
* ``--ui qt``: the PySide6 reimplementation in ``client/gui_qt.py``.

Run directly via ``python -m client.gui [--ui tk|qt]``. ``client/ws_client.py``
spawns this entry point with ``--ui`` already set by the launcher.
"""

from __future__ import annotations

import argparse
import sys


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch the client exam timer / submission GUI.",
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
        from client.gui_qt import run as run_qt
        return run_qt()

    from client.gui_tk import run as run_tk
    return run_tk()


if __name__ == "__main__":
    raise SystemExit(main())
