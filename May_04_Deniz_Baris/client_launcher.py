"""Exam Client Manager launcher — dispatches between Tk and Qt backends.

Usage:
    python client_launcher.py            # default: Tk
    python client_launcher.py --ui tk    # explicit Tk
    python client_launcher.py --ui qt    # PySide6 Qt
"""

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Client Manager Launcher")
    parser.add_argument(
        "--ui",
        choices=["tk", "qt"],
        default="tk",
        help="UI backend: tk (default) or qt (requires PySide6)",
    )
    args = parser.parse_args()

    if args.ui == "qt":
        try:
            from launcher_ui.client_manager_qt import run
        except ImportError as exc:
            print(f"PySide6 is required for Qt mode: {exc}", file=sys.stderr)
            print("Falling back to Tk.", file=sys.stderr)
            from launcher_ui.client_manager_tk import ClientManager
            from common.manager_support import apply_dpi_awareness

            apply_dpi_awareness()
            app = ClientManager()
            app.mainloop()
            return 0
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
