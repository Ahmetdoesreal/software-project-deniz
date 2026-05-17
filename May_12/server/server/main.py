import argparse
import asyncio
import errno
import sys
import os
from pathlib import Path
from aiohttp import web

from common.discovery import check_duplicate_server
from common.runtime_logging import setup_runtime_logging
from common.server_ports import describe_port_conflict, probe_local_server_id
from .state import state
from .app import create_app


def validate_args(args):
    errors = []
    if not 1 <= args.port <= 65535:
        errors.append(f"--port must be 1-65535, got {args.port}")
    if args.interval <= 0:
        errors.append(f"--interval must be > 0, got {args.interval}")
    if args.announce <= 0:
        errors.append(f"--announce must be > 0, got {args.announce}")
    if not args.id.strip():
        errors.append("--id cannot be empty")
    if args.max_submission_mb <= 0:
        errors.append(f"--max-submission-mb must be > 0, got {args.max_submission_mb}")
    if args.max_artifact_mb <= 0:
        errors.append(f"--max-artifact-mb must be > 0, got {args.max_artifact_mb}")
    if args.shutdown_grace_seconds <= 0:
        errors.append(f"--shutdown-grace-seconds must be > 0, got {args.shutdown_grace_seconds}")
    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        sys.exit(1)


def _duplicate_check_timeout(announce_interval: float) -> float:
    # Wait for at least two announce windows plus a small buffer so a second
    # server has a realistic chance to hear an existing beacon before booting.
    return max(5.0, announce_interval * 2.0 + 1.0)


def main():
    setup_runtime_logging(
        "server_cli",
        Path(__file__).resolve().parent.parent / "data" / "logs" / "server",
    )

    parser = argparse.ArgumentParser(description="Server")
    parser.add_argument("--id",       default="default", help="Server identifier (clients must match)")
    parser.add_argument("--host",     default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--port",     default=8080, type=int, help="Port to listen on (default: 8080)")
    parser.add_argument("--interval", default=1, type=float, help="Time broadcast/sync interval in seconds (default: 1)")
    parser.add_argument("--announce", default=3, type=float, help="Discovery beacon interval in seconds (default: 3)")
    parser.add_argument("--exam-duration", default=45, type=int, help="Exam duration in minutes (default: 45)")
    parser.add_argument("--exam-files", default=None, type=str, help="Path to a .zip file containing exam materials")
    parser.add_argument(
        "--max-submission-mb",
        default=2048,
        type=int,
        help="Maximum submission upload size in MB (default: 2048)",
    )
    parser.add_argument(
        "--max-artifact-mb",
        default=2048,
        type=int,
        help="Maximum runtime artifact upload size in MB (default: 2048)",
    )
    parser.add_argument(
        "--shutdown-grace-seconds",
        default=60.0,
        type=float,
        help="Seconds to keep the server alive for client shutdown reports/replays (default: 60)",
    )
    parser.add_argument("--ui", choices=["auto", "tk", "qt"], default="auto", help="UI backend for GUI windows: auto (Qt first), qt, or tk")
    parser.add_argument("--ipc-transport", choices=["auto", "stdio", "ws"], default="auto", help="Local manager IPC transport: auto, stdio, or ws")
    parser.add_argument("--gui", action="store_true", help="Launch the server companion GUI monitor")
    parser.add_argument("--reset", action="store_true", help="Reset the server state (clear used IDs/timers) on startup")
    parser.add_argument("--auth-secret", default=None, help="Shared secret for HMAC token verification (matches auth_config.json on clients)")
    args = parser.parse_args()

    if args.reset:
        from .state import USERS_FILE
        if os.path.exists(USERS_FILE):
            print(f"[RESET] Clearing persistent state: {USERS_FILE}")
            try:
                os.remove(USERS_FILE)
            except Exception as e:
                print(f"[RESET] Error: {e}")

    validate_args(args)
    args.project_dir = str(Path(__file__).resolve().parent.parent)
    args.gui_module = "server.gui"
    args.python_executable = sys.executable

    # Check for duplicate server with same ID
    duplicate_timeout = _duplicate_check_timeout(args.announce)
    print(
        f"[CHECK] Waiting up to {duplicate_timeout:.1f}s for an existing server "
        f"with id '{args.id}' to announce itself..."
    )
    dup = asyncio.run(
        check_duplicate_server(
            args.id,
            timeout=duplicate_timeout,
            local_port=args.port,
        )
    )
    if dup:
        host, port = dup
        print(f"[ERROR] A server with id '{args.id}' is already running at {host}:{port}")
        print("[ERROR] Use a different --id or stop the other server first.")
        sys.exit(1)
    print(f"[CHECK] No duplicate found, safe to start.\n")

    print(f"Starting server '{args.id}' on http://{args.host}:{args.port}")

    try:
        web.run_app(create_app(args), host=args.host, port=args.port)
    except OSError as e:
        if e.errno == errno.EADDRINUSE or "address already in use" in str(e).lower():
            observed_server_id = probe_local_server_id(args.port)
            print(f"\n[ERROR] {describe_port_conflict(args.id, args.port, observed_server_id)}")
        else:
            print(f"\n[ERROR] {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
