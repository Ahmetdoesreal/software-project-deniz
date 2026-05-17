"""Exam Client Manager launcher — dispatches between Tk and Qt backends.

Usage:
    python client_launcher.py            # default: auto, Qt first
    python client_launcher.py --ui auto  # Qt first, Tk fallback
    python client_launcher.py --ui tk    # explicit Tk
    python client_launcher.py --ui qt    # PySide6 Qt
"""

import argparse
import os
import sys
from pathlib import Path


BUNDLE_DIR = Path(__file__).resolve().parent
if str(BUNDLE_DIR) not in sys.path:
    sys.path.insert(0, str(BUNDLE_DIR))
os.chdir(BUNDLE_DIR)


def _is_pyside6_import_error(exc: ImportError) -> bool:
    missing = getattr(exc, "name", "") or ""
    return missing == "PySide6" or missing.startswith("PySide6.")


def _handle_qt_import_error(exc: ImportError, *, explicit_qt: bool) -> int:
    if _is_pyside6_import_error(exc):
        print(f"PySide6 is required for Qt mode: {exc}", file=sys.stderr)
    else:
        print(f"Qt mode failed while importing application modules: {exc}", file=sys.stderr)
    if explicit_qt:
        return 1
    print("Falling back to Tk.", file=sys.stderr)
    from launcher_ui.client_manager_tk import ClientManager
    from common.manager_support import apply_dpi_awareness

    apply_dpi_awareness()
    app = ClientManager()
    app.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Client Manager Launcher")
    parser.add_argument(
        "--ui",
        choices=["auto", "tk", "qt"],
        default="auto",
        help="UI backend: auto (default, Qt first), qt, or tk",
    )
    args = parser.parse_args()

    if args.ui in {"auto", "qt"}:
        try:
            from launcher_ui.client_manager_qt import run
        except ImportError as exc:
            return _handle_qt_import_error(exc, explicit_qt=args.ui == "qt")
        return run()

    # Default: Tk
    from common.manager_support import apply_dpi_awareness
    from launcher_ui.client_manager_tk import ClientManager

    apply_dpi_awareness()
    app = ClientManager()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
