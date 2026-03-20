import asyncio
import json
import sys
import time
from threading import Thread

from aiohttp import web

from common.discovery import ServerAnnouncer
from common import events, protocol
from .state import state


def _remove_dead_clients(client_ids: list[str]):
    for client_id in client_ids:
        state.clients.pop(client_id, None)


def _gui_process():
    return state.get_gui_process()


def _queue_stdin_line(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
    for line in sys.stdin:
        loop.call_soon_threadsafe(queue.put_nowait, line)


def _write_to_gui(payload: dict):
    gui_process = _gui_process()
    if not gui_process:
        return

    try:
        gui_process.stdin.write(json.dumps(payload) + "\n")
        gui_process.stdin.flush()
    except Exception as e:
        print(f"[GUI IPC] Warning: Failed to write to GUI: {e}")


def _uuid_to_login_map() -> dict[str, str]:
    return {
        user["uuid"]: login_id
        for login_id, user in state.users_db.items()
        if user.get("uuid")
    }


def _remaining_seconds(exam_duration_sec: int, user: dict) -> int:
    extra_time_sec = int(user.get("extra_time_seconds", 0))
    time_spent_seconds = user.get("time_spent_seconds", 0)
    return max(0, exam_duration_sec + extra_time_sec - int(time_spent_seconds))


def _exam_state(user: dict, remaining: int) -> str:
    if user.get("banned", False):
        return "Banned"
    if user.get("exam_started", False):
        if remaining <= 0:
            return "Finished"
        return "Running"
    return "Waiting"


def _status_label(is_connected: bool, exam_state: str) -> str:
    if exam_state == "Banned":
        return "Banned"
    if exam_state == "Finished":
        return "Finished"
    if is_connected:
        return exam_state
    return "Offline"


def _build_gui_clients(exam_duration_sec: int) -> list[dict]:
    clients = []
    for login_id, user in state.users_db.items():
        client_id = user["uuid"]
        client_connection = state.clients.get(client_id, {})
        is_connected = client_id in state.clients
        remaining = _remaining_seconds(exam_duration_sec, user)
        exam_state = _exam_state(user, remaining)
        clients.append(
            {
                "uuid": client_id,
                "login_id": login_id,
                "status_label": _status_label(is_connected, exam_state),
                "connection_status": "Connected" if is_connected else "Disconnected",
                "exam_state": exam_state,
                "exam_started": user.get("exam_started", False),
                "remaining": remaining,
                "time_spent_seconds": int(user.get("time_spent_seconds", 0)),
                "extra_time_seconds": int(user.get("extra_time_seconds", 0)),
                "banned": user.get("banned", False),
                "kick_count": int(user.get("kick_count", 0)),
                "last_action": user.get("last_action", ""),
                "ip": client_connection.get("ip"),
                "computer_name": client_connection.get("computer_name") or user.get("computer_name", ""),
                "short_id": client_connection.get("short_id"),
            }
        )
    return clients


def _build_server_info(app: web.Application) -> dict:
    advertised_host = app["host"]
    if advertised_host in {"0.0.0.0", "::", ""}:
        advertised_host = ServerAnnouncer._get_local_ip()
    return {
        "server_id": app["server_id"],
        "host": advertised_host,
        "port": app["port"],
        "broadcast_interval": app["broadcast_interval"],
        "announce_interval": app["announce_interval"],
        "exam_duration_minutes": app["exam_duration"],
        "exam_start_enabled": app["exam_start_enabled"],
        "has_exam_files": app["exam_files"] is not None,
        "exam_files_path": app["exam_files"],
    }


def _print_connected_clients():
    if not state.clients:
        print("[CMD] No clients connected.")
        return

    print(f"[CMD] {len(state.clients)} client(s) connected:")
    for client_id, data in state.clients.items():
        print(f"       - UUID:  {client_id}")
        print(f"         Short: {data['short_id']}")
        print(f"         IP:    {data['ip']}")
        print()


def _print_exam_status(app: web.Application):
    exam_duration_sec = app["exam_duration"] * 60
    print("\n[CMD] --- LIVE EXAM STATUS ---")

    if not state.clients:
        print("No clients connected.")
        print("------------------------------\n")
        return

    for client_id in state.clients:
        login_id, user = state.find_user_by_uuid(client_id)
        if not user:
            print(f"Unknown UUID: {client_id}")
            continue

        exam_state = _exam_state(user, _remaining_seconds(exam_duration_sec, user))
        remaining = _remaining_seconds(exam_duration_sec, user)
        minutes, seconds = divmod(remaining, 60)
        print(
            f"User: {login_id:12} | State: {exam_state:7} | "
            f"Remaining: {minutes:02d}m {seconds:02d}s"
        )

    print("------------------------------\n")


async def broadcast_to_all(payload: str) -> int:
    """Send a payload to every connected client. Returns count sent."""
    dead = []
    sent = 0

    for client_id, data in list(state.clients.items()):
        try:
            await data["ws"].send_str(payload)
            sent += 1
        except (ConnectionResetError, RuntimeError):
            dead.append(client_id)

    _remove_dead_clients(dead)
    return sent


async def send_to_client(target: str, payload: str) -> bool:
    """Send a payload to a specific client (by UUID, short ID, or IP)."""
    client_id, data = state.resolve_client(target)
    if not data:
        return False

    try:
        await data["ws"].send_str(payload)
        return True
    except (ConnectionResetError, RuntimeError):
        _remove_dead_clients([client_id])
        return False


async def _broadcast_time_payload(payload: str) -> list[str]:
    dead = []
    for client_id, data in list(state.clients.items()):
        try:
            await data["ws"].send_str(payload)
        except ConnectionResetError:
            dead.append(client_id)
    return dead


async def _sync_running_exams(
    app: web.Application,
    uuid_to_login: dict[str, str],
    elapsed: float,
) -> list[str]:
    dead = []
    exam_duration_sec = app["exam_duration"] * 60

    for client_id, data in list(state.clients.items()):
        login_id = uuid_to_login.get(client_id)
        if not login_id:
            continue

        user = state.users_db[login_id]
        if not user.get("exam_started", False):
            continue

        user["time_spent_seconds"] = user.get("time_spent_seconds", 0.0) + elapsed
        remaining = _remaining_seconds(exam_duration_sec, user)

        try:
            await data["ws"].send_str(events.sync_time(remaining))
            if remaining <= 0:
                print(f"[EXAM] Client {client_id} ran out of time!")
                await data["ws"].send_str(events.exam_end())
        except ConnectionResetError:
            dead.append(client_id)

    return dead


async def time_broadcaster(app: web.Application):
    """Background task that sends the current time to clients and updates exam timers."""
    tick_interval = app["broadcast_interval"]
    exam_duration_sec = app["exam_duration"] * 60
    last_tick_time = time.perf_counter()
    save_counter_sec = 0.0

    try:
        while True:
            await asyncio.sleep(tick_interval)

            now = time.perf_counter()
            elapsed = now - last_tick_time
            last_tick_time = now

            if state.clients:
                dead = await _broadcast_time_payload(events.time_broadcast(protocol.now_iso()))
                dead.extend(await _sync_running_exams(app, _uuid_to_login_map(), elapsed))
                _remove_dead_clients(dead)

            save_counter_sec += elapsed
            if save_counter_sec >= 10.0:
                state.save_users()
                save_counter_sec = 0.0

            _write_to_gui(
                {
                    "type": "state_update",
                    "server": _build_server_info(app),
                    "clients": _build_gui_clients(exam_duration_sec),
                }
            )
    except asyncio.CancelledError:
        pass


async def _sync_client_remaining_time(target: str, app: web.Application):
    client_id, data = state.resolve_client(target)
    if not data:
        return

    _, user = state.find_user_by_uuid(client_id)
    if not user:
        return

    remaining = _remaining_seconds(app["exam_duration"] * 60, user)
    await data["ws"].send_str(events.sync_time(remaining))


async def _handle_add_time(parts: list[str], app: web.Application):
    if len(parts) < 3:
        print("[CMD] Usage: /addtime <client_id|uuid|login_id> <minutes>")
        return

    target = parts[1]
    try:
        minutes = float(parts[2])
    except ValueError:
        print(f"[CMD] Invalid minutes value: {parts[2]}")
        return
    if minutes <= 0:
        print("[CMD] Minutes must be greater than 0.")
        return

    login_id, user = state.resolve_user(target)
    if not user:
        print(f"[CMD] User '{target}' not found.")
        return

    seconds_to_add = int(minutes * 60)
    user["extra_time_seconds"] = int(user.get("extra_time_seconds", 0)) + seconds_to_add
    state.save_users()

    client_id = user["uuid"]
    await _sync_client_remaining_time(client_id, app)
    print(
        f"[CMD] Added {minutes:g} minute(s) to {login_id} ({client_id}). "
        f"Extra time is now {int(user['extra_time_seconds'])} second(s)."
    )


async def _disconnect_client(target: str, reason: str) -> bool:
    client_id, data = state.resolve_client(target)
    if not data:
        return False

    try:
        await data["ws"].close(message=reason.encode("utf-8"))
    except Exception:
        pass
    finally:
        state.clients.pop(client_id, None)
    return True


async def _handle_start_exam_global(app: web.Application):
    if app["exam_start_enabled"]:
        print("[CMD] Exam start is already enabled.")
        return

    app["exam_start_enabled"] = True
    print("[CMD] Exam start is now enabled for all clients.")


async def _handle_kick(parts: list[str]):
    if len(parts) < 2:
        print("[CMD] Usage: /kick <client_id|uuid|login_id>")
        return

    target = parts[1]
    login_id, user = state.resolve_user(target)
    if not user:
        print(f"[CMD] User '{target}' not found.")
        return

    client_id = user["uuid"]
    if client_id not in state.clients:
        print(f"[CMD] User '{login_id}' is not currently connected.")
        return

    user["kick_count"] = int(user.get("kick_count", 0)) + 1
    user["last_action"] = "Kicked"
    state.save_users()
    await _disconnect_client(client_id, "kicked by server")
    print(f"[CMD] Kicked {login_id} ({client_id}).")


async def _handle_ban(parts: list[str]):
    if len(parts) < 2:
        print("[CMD] Usage: /ban <client_id|uuid|login_id>")
        return

    target = parts[1]
    login_id, user = state.resolve_user(target)
    if not user:
        print(f"[CMD] User '{target}' not found.")
        return

    user["banned"] = True
    user["kick_count"] = int(user.get("kick_count", 0)) + 1
    user["last_action"] = "Banned"
    state.save_users()
    await _disconnect_client(user["uuid"], "banned by server")
    print(f"[CMD] Banned {login_id} ({user['uuid']}).")


async def _handle_unban(parts: list[str]):
    if len(parts) < 2:
        print("[CMD] Usage: /unban <client_id|uuid|login_id>")
        return

    target = parts[1]
    login_id, user = state.resolve_user(target)
    if not user:
        print(f"[CMD] User '{target}' not found.")
        return

    user["banned"] = False
    user["last_action"] = "Unbanned"
    state.save_users()
    print(f"[CMD] Unbanned {login_id} ({user['uuid']}).")


async def handle_admin_command(line: str, app: web.Application):
    """Common handler for administrative commands from CLI or GUI."""
    command_line = line.strip()
    if not command_line:
        return

    print(f"[DEBUG] Received command: '{command_line}'")
    parts = command_line.split()
    if not parts:
        return

    command = parts[0].lower()
    if not command.startswith("/"):
        print(f"[CMD] Invalid command format: '{command_line}'. Commands must start with /")
        return

    if command == "/clients":
        _print_connected_clients()
        return

    if command == "/savescreen":
        if len(parts) < 2:
            print("[CMD] Usage: /savescreen <client_id>  or  /savescreen all")
            return

        target = parts[1]
        if target.lower() == "all":
            count = await broadcast_to_all(events.savescreen())
            print(f"[CMD] Sent SAVESCREEN to {count} client(s)")
            return

        if await send_to_client(target, events.savescreen()):
            print(f"[CMD] Sent SAVESCREEN to client {target}")
            return

        print(f"[CMD] Client '{target}' not found (tried UUID, short ID, IP).")
        print("      Type /clients to list available targets.")
        return

    if command == "/exam":
        _print_exam_status(app)
        return

    if command == "/addtime":
        await _handle_add_time(parts, app)
        return

    if command == "/startexam":
        await _handle_start_exam_global(app)
        return

    if command == "/kick":
        await _handle_kick(parts)
        return

    if command == "/ban":
        await _handle_ban(parts)
        return

    if command == "/unban":
        await _handle_unban(parts)
        return

    if command == "/help":
        print("  /clients              - List connected clients")
        print("  /savescreen <id>      - Save replay on a specific client")
        print("  /savescreen all       - Save replay on ALL clients")
        print("  /addtime <id> <min>   - Add time to a specific user/client")
        print("  /startexam            - Enable exam start for all clients")
        print("  /kick <id>            - Disconnect a specific client")
        print("  /ban <id>             - Ban and disconnect a specific user")
        print("  /unban <id>           - Remove a user's ban")
        print("  /exam                 - Show overall exam status")
        print("  /help                 - Show this help")
        return

    print(f"[CMD] Unknown command: {command}  (type /help)")


def _dispatch_gui_request(loop, app: web.Application, request: dict):
    message_type = request.get("type")
    command = request.get("cmd")
    client_id = request.get("uuid")

    if message_type == "console_command":
        command_line = request.get("command")
        if command_line:
            asyncio.run_coroutine_threadsafe(handle_admin_command(command_line, app), loop)
        return

    if command == "savescreen" and client_id in state.clients:
        ws = state.clients[client_id]["ws"]
        asyncio.run_coroutine_threadsafe(ws.send_str(events.savescreen()), loop)
        print(f"\n[GUI->WS] Sent savescreen to {client_id}")
        return

    if command == "get_processes" and client_id in state.clients:
        ws = state.clients[client_id]["ws"]
        asyncio.run_coroutine_threadsafe(ws.send_str(events.get_processes()), loop)
        print(f"\n[GUI->WS] Sent get_processes to {client_id}")
        return

    if command == "start_exam_global":
        asyncio.run_coroutine_threadsafe(
            handle_admin_command("/startexam", app),
            loop,
        )
        return

    if command == "kick":
        asyncio.run_coroutine_threadsafe(
            handle_admin_command(f"/kick {client_id}", app),
            loop,
        )
        return

    if command == "ban":
        asyncio.run_coroutine_threadsafe(
            handle_admin_command(f"/ban {client_id}", app),
            loop,
        )
        return

    if command == "unban":
        asyncio.run_coroutine_threadsafe(
            handle_admin_command(f"/unban {client_id}", app),
            loop,
        )


def _gui_reader_thread(loop, app):
    """Read stdout from the Tkinter GUI and forward actions into the event loop."""
    gui_process = _gui_process()
    if not gui_process:
        return

    for line in iter(gui_process.stdout.readline, ""):
        line = line.strip()
        if not line:
            continue
        try:
            _dispatch_gui_request(loop, app, json.loads(line))
        except Exception:
            pass


async def console_reader(app: web.Application):
    """Read stdin for operator commands."""
    loop = asyncio.get_event_loop()
    input_queue = asyncio.Queue()
    stdin_thread = Thread(
        target=_queue_stdin_line,
        args=(loop, input_queue),
        daemon=True,
    )
    stdin_thread.start()

    if _gui_process():
        thread = Thread(target=_gui_reader_thread, args=(loop, app), daemon=True)
        thread.start()

    try:
        while True:
            line = await input_queue.get()
            if not line:
                break
            await handle_admin_command(line, app)
    except asyncio.CancelledError:
        pass
