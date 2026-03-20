import json
import os
import uuid
from aiohttp import web, WSMsgType

from common import protocol, events
from .state import state


def _json_error(message: str, status: int) -> web.Response:
    return web.json_response({"error": message}, status=status)


def _validate_login_payload(data: dict) -> tuple[str | None, str | None]:
    login_id = data.get("login_id")
    password = data.get("password")
    return login_id, password


def _relay_client_message_to_gui(client_id: str, message: dict):
    gui_process = state.get_gui_process()
    if not gui_process:
        return

    try:
        payload = json.dumps(
            {"type": "client_message", "uuid": client_id, "text": message}
        )
        gui_process.stdin.write(payload + "\n")
        gui_process.stdin.flush()
    except Exception:
        pass


def _register_new_user(login_id: str, password: str) -> web.Response:
    new_uuid = str(uuid.uuid4())
    state.users_db[login_id] = {
        "password": password,
        "uuid": new_uuid,
        "time_spent_seconds": 0,
        "exam_started": False,
    }
    state.save_users()
    print(f"[+] New valid user registered: {login_id} -> {new_uuid}")
    return web.json_response({"status": "ok", "uuid": new_uuid})


async def _handle_ping_event(ws: web.WebSocketResponse, client_id: str, data: dict):
    await ws.send_str(events.echo(data, protocol.now_iso()))
    short_id = client_id[:8]
    print(f"[{short_id}] PING: {data}")
    _relay_client_message_to_gui(client_id, data)


async def _handle_start_exam(
    ws: web.WebSocketResponse,
    request: web.Request,
    client_id: str,
):
    _, user = state.find_user_by_uuid(client_id)
    if not user or user.get("exam_started", False):
        return

    user["exam_started"] = True
    state.save_users()
    print(f"[EXAM] Client {client_id} started their exam.")

    exam_duration_sec = request.app["exam_duration"] * 60
    remaining = max(0, exam_duration_sec - user.get("time_spent_seconds", 0))
    await ws.send_str(events.sync_time(remaining))


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
        return _json_error("Invalid JSON", 400)

    login_id, password = _validate_login_payload(data)
    if not login_id or not password:
        return _json_error("login_id and password required", 400)

    if login_id not in state.allowed_users:
        return _json_error("User is not allowed to take this exam.", 403)

    if state.allowed_users[login_id] != password:
        return _json_error("Invalid credentials provided.", 401)

    user = state.users_db.get(login_id)
    if not user:
        return _register_new_user(login_id, password)

    if user["password"] != password:
        return _json_error("Invalid stored credentials", 401)

    return web.json_response({"status": "ok", "uuid": user["uuid"]})


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

    if not client_id or not state.is_valid_session_uuid(client_id):
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
                    await _handle_ping_event(ws, client_id, data)
                elif event == events.START_EXAM:
                    await _handle_start_exam(ws, request, client_id)
                else:
                    await ws.send_str(events.error(f"unknown event: {event}"))

            elif msg.type == WSMsgType.ERROR:
                print(f"[!] Client {client_id} error: {ws.exception()}")
    finally:
        # Unregister on disconnect
        state.clients.pop(client_id, None)
        print(f"[-] Client {client_id} disconnected  ({len(state.clients)} total)")

    return ws
