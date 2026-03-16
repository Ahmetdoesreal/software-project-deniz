"""
Client -- connects to the server via WebSocket.

  - Receives a unique ID from the server on connect
  - Sends a "ping" and prints the echoed response
  - Listens for the server's time broadcasts
  - Type messages to send more pings, or Ctrl+C to quit
"""

import argparse
import asyncio
import sys
import uuid
import json
import os

import aiohttp

import shared
import events
from discovery import discover_server
from custommodules.replay_recorder import ReplayRecorder

async def perform_login(base_url: str, login_id: str, password: str) -> str:
    """Logs in and returns the session UUID. Raises on failure."""
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{base_url}/login", json={"login_id": login_id, "password": password}) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data["uuid"]
            else:
                body = await resp.text()
                raise ValueError(f"Login failed ({resp.status}): {body}")





async def check_health(base_url: str):
    """Quick HTTP health check."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base_url}/health") as resp:
            data = await resp.json()
            print(f"[HTTP] Health: {data}")


async def run_ws(ws_url: str, recorder: ReplayRecorder):
    """Connect via WebSocket, send pings, receive broadcasts."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            disconnected = asyncio.Event()

            # -- Listener task: prints everything the server sends --------
            async def listener():
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        event, data = shared.decode(msg.data)

                        if event == events.WELCOME:
                            print(f"[WS] Connected! Server assigned ID: {data['id']}")
                        elif event == events.ECHO:
                            print(f"[WS] Echo: {data}")
                        elif event == events.TIME:
                            print(f"[WS] [TIME] Server time: {data['server_time']}")
                        elif event == events.SAVESCREEN:
                            print("[WS] [SAVESCREEN] Server requested replay save.")
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(None, recorder.save_replay)
                        else:
                            print(f"[WS] {event}: {data}")

                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
                # WS loop ended -- server is gone
                disconnected.set()

            # -- Sender: reads stdin and sends pings ----------------------
            async def sender():
                print("\nType anything and press Enter to ping the server (Ctrl+C to quit):\n")
                loop = asyncio.get_event_loop()
                while not disconnected.is_set():
                    # Check for disconnect between each line read
                    read_future = loop.run_in_executor(None, sys.stdin.readline)
                    # Wait for either stdin input or disconnect
                    done, _ = await asyncio.wait(
                        [asyncio.ensure_future(read_future),
                         asyncio.ensure_future(disconnected.wait())],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if disconnected.is_set():
                        break
                    for task in done:
                        line = task.result()
                        if not line:
                            return
                        text = line.strip()
                        if text:
                            await ws.send_str(events.ping(text))

            listen_task = asyncio.create_task(listener())
            try:
                await sender()
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
            finally:
                listen_task.cancel()

            if disconnected.is_set():
                raise ConnectionError("Server disconnected")



async def discover_loop(server_id: str, timeout: float):
    """Keep searching until we find a server."""
    result = None
    while result is None:
        result = await discover_server(server_id=server_id, timeout=timeout)
        if result is None:
            print("No server found yet, retrying...")
    return result


async def main(args):
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
                host, port = await discover_loop(args.id, args.timeout)

            base_url = f"http://{host}:{port}"
            
            try:
                # 2. Login to get/verify UUID
                new_uuid = await perform_login(base_url, args.login_id, args.password)
                
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

                # 3. HTTP health check
                await check_health(base_url)

                # 4. WebSocket session
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

# -- Validation ------------------------------------------------------------
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Client")
    parser.add_argument("--login-id",  required=True, help="Client login ID")
    parser.add_argument("--password",  required=True, help="Client password")
    parser.add_argument("--id",        default="default", help="Server ID to connect to (default: default)")
    parser.add_argument("--host",      default=None,      help="Server host (skip discovery, connect directly)")
    parser.add_argument("--port",      default=8080, type=int, help="Server port (default: 8080)")
    parser.add_argument("--timeout",   default=15, type=float, help="Discovery timeout in seconds (default: 15)")
    parser.add_argument("--reconnect", default=3, type=float, help="Seconds to wait before reconnecting (default: 3)")
    parser.add_argument("--no-record", dest="record", action="store_false", help="Disable screen replay recorder")
    parser.set_defaults(record=True)
    args = parser.parse_args()

    validate_args(args)

    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print("\nBye!")


