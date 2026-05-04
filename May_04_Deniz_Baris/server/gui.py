"""Server monitor dashboard dispatcher.

Selects the GUI backend at runtime via ``--ui {tk,qt}``.

* ``--ui tk`` (default): the Tk dashboard in ``server.ui.dashboard_tk``.
* ``--ui qt``: the Qt dashboard in ``server.ui.dashboard_qt``.

Run directly via ``python -m server.gui [--ui tk|qt]``. ``server/tasks.py``
spawns this entry point with ``--ui`` already set by the launcher.
"""

from __future__ import annotations

import argparse
import sys

from server.ui.dashboard_table_helpers import PROCESS_DATABASE_FILTERS, process_row_matches_filter
from server.ui.process_database_helpers import (
    build_process_decision_payload,
    process_row_google_search_url,
)


def format_process_action_availability(row: dict) -> str:
    availability = row.get("action_availability", {})
    if not isinstance(availability, dict):
        return "-"
    parts = []
    for action in ("ban", "kick", "pause_exam", "kill_pid"):
        state = availability.get(action, {})
        possible = int(state.get("possible", 0) or 0) if isinstance(state, dict) else 0
        applied = int(state.get("applied", 0) or 0) if isinstance(state, dict) else 0
        blocked = int(state.get("not_possible", 0) or 0) if isinstance(state, dict) else 0
        if possible or applied or blocked:
            parts.append(f"{action.replace('_', ' ')} {possible}/{applied}/{blocked}")
    return "; ".join(parts) if parts else "-"


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
        from server.ui.dashboard_qt import run as run_qt
        return run_qt()

    from server.ui.dashboard_tk import run as run_tk
    return run_tk()


if __name__ == "__main__":
    raise SystemExit(main())
