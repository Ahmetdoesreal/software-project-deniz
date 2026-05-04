"""Entry point for the client manager.

Selects the GUI backend at runtime via ``--ui {tk,qt}``.

* ``--ui tk`` (default): the legacy Tkinter manager in ``client_launcher_tk``.
* ``--ui qt``: the PySide6 manager in ``client_launcher_qt``.
"""

import argparse
import os
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
os.chdir(PROJECT_DIR)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch the Exam Client manager.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--ui",
        choices=("tk", "qt"),
        default="tk",
        help="GUI backend: 'tk' opens the legacy Tkinter manager, 'qt' opens the new PySide6 manager.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.ui == "qt":
        try:
            from client_launcher_qt import run as run_qt
        except ImportError:
            return 1
        return run_qt()

    from client_launcher_tk import ClientManager
    from common.manager_support import apply_dpi_awareness

    apply_dpi_awareness()
    app = ClientManager()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
