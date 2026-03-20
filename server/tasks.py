import asyncio
import json
import sys
import time
from threading import Thread

from aiohttp import web

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


def _remaining_seconds(exam_duration_sec: int, time_spent_seconds: float) -> int:
    return max(0, exam_duration_sec - int(time_spent_seconds))


def _build_gui_clients(exam_duration_sec: int) -> list[dict]:
    clients = []
    for login_id, user in state.users_db.items():
        client_id = user["uuid"]
        clients.append(
            {
                "uuid": client_id,
                "login_id": login_id,
                "status": "Connected" if client_id in state.clients else "Disconnected",
                "remaining": _remaining_seconds(
                    exam_duration_sec,
                    user.get("time_spent_seconds", 0),
                ),
            }
        )
    return clients


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

        exam_state = "Running" if user.get("exam_started") else "Waiting"
        remaining = _remaining_seconds(
            exam_duration_sec,
            user.get("time_spent_seconds", 0),
        )
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
        remaining = _remaining_seconds(
            exam_duration_sec,
            user["time_spent_seconds"],
        )

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
                {"type": "state_update", "clients": _build_gui_clients(exam_duration_sec)}
            )
    except asyncio.CancelledError:
        pass


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

    if command == "/help":
        print("  /clients              - List connected clients")
        print("  /savescreen <id>      - Save replay on a specific client")
        print("  /savescreen all       - Save replay on ALL clients")
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
