import argparse
import asyncio
import sys
import os
import aiohttp

from common.protocol import extract_client_uuid
from common.discovery import discover_server
from custommodules.replay_recorder import ReplayRecorder
from .auth import perform_login, check_health
from .exam import fetch_exam_prep
from .ws_client import run_ws

async def discover_loop(server_id: str, timeout: float):
    """Keep searching until we find a server."""
    result = None
    while result is None:
        result = await discover_server(server_id=server_id, timeout=timeout)
        if result is None:
            print("No server found yet, retrying...")
    return result


async def main_loop(args):
    session_uuid = None
    recorder = None
    
    print(f"=== Client [{args.login_id}] (awaiting session assignment) ===\n")

    try:
        while True:
            # 1. Discover or use explicit host/port
            if args.host:
                host, port = args.host, args.port
                print(f"[DIRECT] Connecting to {host}:{port}")
            else:
                if getattr(args, 'check_login', False):
                    # Don't loop forever during a quick check
                    server_info = await discover_server(args.id, args.timeout)
                    if not server_info:
                        print(f"\n[FATAL] Could not discover server '{args.id}' on the local network.")
                        sys.exit(1)
                    host, port = server_info
                else:
                    host, port = await discover_loop(args.id, args.timeout)

            base_url = f"http://{host}:{port}"
            
            try:
                # 2. Login to get/verify UUID
                new_uuid = await perform_login(base_url, args.login_id, args.password)
                
                if getattr(args, 'check_login', False):
                    print("[+] Credentials verified successfully.")
                    sys.exit(0)
                
                if not session_uuid:
                    session_uuid = new_uuid
                    print(f"[LOGIN] Assigned session UUID: {session_uuid}")
                    
                    recorder = ReplayRecorder(session_uuid=session_uuid)
                    if args.record:
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(None, recorder.start)
                elif session_uuid != new_uuid:
                    print(f"[!] Server returned a different UUID ({new_uuid}) than active ({session_uuid}). Resyncing.")
                    session_uuid = new_uuid
                    
                    if recorder:
                        if args.record:
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(None, recorder.stop)
                            
                        recorder = ReplayRecorder(session_uuid=session_uuid)
                        if args.record:
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(None, recorder.start)

                ws_url = f"ws://{host}:{port}/ws?id={session_uuid}"

                # 3. Fetch Exam Configuration and Files
                await fetch_exam_prep(base_url, session_uuid)

                # 4. HTTP health check
                await check_health(base_url)

                # 5. WebSocket session
                print()
                await run_ws(ws_url, recorder)
            except ValueError as e:
                # Fatal login error (e.g., wrong password), we should probably exit
                print(f"\n[FATAL] {e}")
                sys.exit(1)
            except (aiohttp.ClientError, ConnectionError, OSError) as e:
                print(f"\n[!] Connection lost: {e}")

            # If we get here, server died or connection dropped
            print(f"[!] Reconnecting in {args.reconnect} seconds...\n")
            await asyncio.sleep(args.reconnect)
    finally:
        if args.record and recorder:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, recorder.stop)

def validate_args(args):
    errors = []
    if not 1 <= args.port <= 65535:
        errors.append(f"--port must be 1-65535, got {args.port}")
    if args.timeout <= 0:
        errors.append(f"--timeout must be > 0, got {args.timeout}")
    if args.reconnect < 0:
        errors.append(f"--reconnect must be >= 0, got {args.reconnect}")
    if not args.id.strip():
        errors.append("--id cannot be empty")
    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Client")
    parser.add_argument("--login-id",  required=True, help="Client login ID")
    parser.add_argument("--password",  required=True, help="Client password")
    parser.add_argument("--id",        default="default", help="Server ID to connect to (default: default)")
    parser.add_argument("--host",      default=None,      help="Server host (skip discovery, connect directly)")
    parser.add_argument("--port",      default=8080, type=int, help="Server port (default: 8080)")
    parser.add_argument("--timeout",   default=15, type=float, help="Discovery timeout in seconds (default: 15)")
    parser.add_argument("--reconnect", default=3, type=float, help="Seconds to wait before reconnecting (default: 3)")
    parser.add_argument("--no-record", dest="record", action="store_false", help="Disable screen replay recorder")
    parser.add_argument("--check-login", action="store_true", help="Only validate server connection and login credentials, then exit.")
    parser.set_defaults(record=True)
    args = parser.parse_args()

    validate_args(args)

    try:
        asyncio.run(main_loop(args))
    except KeyboardInterrupt:
        print("\nBye!")

if __name__ == "__main__":
    main()
