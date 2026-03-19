import argparse
import asyncio
import errno
import sys
import os
import subprocess
from aiohttp import web

from common.discovery import check_duplicate_server
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
    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Server")
    parser.add_argument("--id",       default="default", help="Server identifier (clients must match)")
    parser.add_argument("--host",     default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--port",     default=8080, type=int, help="Port to listen on (default: 8080)")
    parser.add_argument("--interval", default=1, type=float, help="Time broadcast/sync interval in seconds (default: 1)")
    parser.add_argument("--announce", default=3, type=float, help="Discovery beacon interval in seconds (default: 3)")
    parser.add_argument("--exam-duration", default=45, type=int, help="Exam duration in minutes (default: 45)")
    parser.add_argument("--exam-files", default=None, type=str, help="Path to a .zip file containing exam materials")
    parser.add_argument("--gui", action="store_true", help="Launch the server companion GUI monitor")
    parser.add_argument("--reset", action="store_true", help="Reset the server state (clear used IDs/timers) on startup")
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
    
    if args.gui:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # server_gui.py is in the root directory relative to server/
        gui_path = os.path.join(os.path.dirname(script_dir), "server_gui.py")
        print(f"[GUI] Launching Server Monitor UI...")
        try:
            state.gui_process = subprocess.Popen(
                [sys.executable, gui_path], 
                stdin=subprocess.PIPE, 
                stdout=subprocess.PIPE,
                text=True,
                bufsize=1  # Line buffered
            )
        except Exception as e:
            print(f"[GUI] Failed to launch gui: {e}")

    # Check for duplicate server with same ID
    dup = asyncio.run(check_duplicate_server(args.id, timeout=5.0))
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
            print(f"\n[ERROR] Port {args.port} is already in use.")
            print(f"[ERROR] Use --port to pick a different port.")
        else:
            print(f"\n[ERROR] {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
