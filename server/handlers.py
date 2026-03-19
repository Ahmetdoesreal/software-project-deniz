import json
import os
import uuid
import asyncio
from aiohttp import web, WSMsgType

from common import protocol, events
from .state import state

# -- HTTP Routes -----------------------------------------------------------
async def health(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "ok",
        "server_id": request.app["server_id"],
        "clients_connected": len(state.clients),
    })

async def login_handler(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    
    login_id = data.get("login_id")
    password = data.get("password")
    
    if not login_id or not password:
        return web.json_response({"error": "login_id and password required"}, status=400)
        
    # Check if user is in the allowed list
    if login_id not in state.allowed_users:
        return web.json_response({"error": "User is not allowed to take this exam."}, status=403)
        
    if state.allowed_users[login_id] != password:
        return web.json_response({"error": "Invalid credentials provided."}, status=401)
        
    user = state.users_db.get(login_id)
    if user:
        if user["password"] != password:
            return web.json_response({"error": "Invalid stored credentials"}, status=401)
        # Valid login existing
        return web.json_response({"status": "ok", "uuid": user["uuid"]})
    else:
        # Create new user
        new_uuid = str(uuid.uuid4())
        state.users_db[login_id] = {
            "password": password,
            "uuid": new_uuid,
            "time_spent_seconds": 0,
            "exam_started": False
        }
        state.save_users()
        print(f"[+] New valid user registered: {login_id} -> {new_uuid}")
        return web.json_response({"status": "ok", "uuid": new_uuid})


async def exam_config(request: web.Request) -> web.Response:
    app = request.app
    return web.json_response({
        "exam_duration_seconds": app["exam_duration"] * 60,
        "has_files": app["exam_files"] is not None
    })

async def exam_files(request: web.Request) -> web.Response:
    app = request.app
    path = app["exam_files"]
    if not path or not os.path.exists(path):
        return web.Response(status=404, text="No exam files available")
    
    if os.path.isdir(path):
        return web.Response(status=400, text="Directory serving not implemented, please provide a .zip file")
        
    return web.FileResponse(path)

# -- WebSocket Handler -----------------------------------------------------
async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    client_id = request.query.get("id")
    
    # Verify the UUID was issued by us
    valid_uuids = {u["uuid"] for u in state.users_db.values()}
    if not client_id or client_id not in valid_uuids:
        return web.Response(status=401, text="Unauthorized: invalid or missing session ID")

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    short_id = client_id[:8]
    ip = request.remote

    state.clients[client_id] = {
        "ws": ws,
        "short_id": short_id,
        "ip": ip
    }
    print(f"[+] Client connected: {client_id} (short: {short_id}, ip: {ip})")

    # Send welcome with their ID
    await ws.send_str(events.welcome(client_id, request.app["server_id"]))

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                event, data = protocol.decode(msg.data)

                if event == events.PING:
                    # Echo back with the same data
                    await ws.send_str(events.echo(data, protocol.now_iso()))
                    
                    short_id = client_id[:8]
                    print(f"[{short_id}] PING: {data}")
                    
                    # Relay to GUI if active
                    if state.gui_process and state.gui_process.poll() is None:
                        try:
                            msg = json.dumps({"type": "client_message", "uuid": client_id, "text": data})
                            state.gui_process.stdin.write(msg + "\n")
                            state.gui_process.stdin.flush()
                        except Exception:
                            pass
                elif event == events.START_EXAM:
                    # Find user in DB
                    for login_id, u in state.users_db.items():
                        if u["uuid"] == client_id:
                            if not u.get("exam_started", False):
                                u["exam_started"] = True
                                state.save_users()
                                print(f"[EXAM] Client {client_id} started their exam.")
                                
                                # Instantly sync the precise starting time so the client doesn't start at -10s
                                exam_duration_sec = request.app["exam_duration"] * 60
                                rem = max(0, exam_duration_sec - u.get("time_spent_seconds", 0))
                                await ws.send_str(events.sync_time(rem))
                            break
                else:
                    await ws.send_str(events.error(f"unknown event: {event}"))

            elif msg.type == WSMsgType.ERROR:
                print(f"[!] Client {client_id} error: {ws.exception()}")
    finally:
        # Unregister on disconnect
        state.clients.pop(client_id, None)
        print(f"[-] Client {client_id} disconnected  ({len(state.clients)} total)")

    return ws
