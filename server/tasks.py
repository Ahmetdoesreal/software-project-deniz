import asyncio
import sys
import json
from threading import Thread
from aiohttp import web

from common import protocol, events
from .state import state

async def broadcast_to_all(payload: str) -> int:
    """Send a payload to every connected client. Returns count sent."""
    dead = []
    sent = 0
    for cid, data in state.clients.items():
        ws = data["ws"]
        try:
            await ws.send_str(payload)
            sent += 1
        except (ConnectionResetError, RuntimeError):
            dead.append(cid)
    for cid in dead:
        state.clients.pop(cid, None)
    return sent

async def send_to_client(target: str, payload: str) -> bool:
    """Send a payload to a specific client (by UUID, short ID, or IP)."""
    cid, data = state.resolve_client(target)
    if not data:
        return False

    ws = data["ws"]
    try:
        await ws.send_str(payload)
        return True
    except (ConnectionResetError, RuntimeError):
        state.clients.pop(cid, None)
        return False

async def time_broadcaster(app: web.Application):
    """Background task that sends the current time to every connected client, and manages exam timers."""
    tick_interval = app["broadcast_interval"]
    exam_duration_sec = app["exam_duration"] * 60
    
    try:
        while True:
            await asyncio.sleep(tick_interval)
            
            uuid_to_login = {u["uuid"]: login_id for login_id, u in state.users_db.items()}
            
            if state.clients:
                payload = events.time_broadcast(protocol.now_iso())
                dead = []
                for cid, data in state.clients.items():
                    ws = data["ws"]
                    try:
                        await ws.send_str(payload)
                        
                        login_id = uuid_to_login.get(cid)
                        if login_id:
                            user = state.users_db[login_id]
                            num_spent = user.get("time_spent_seconds", 0)
                            has_started = user.get("exam_started", False)
                            
                            if has_started:
                                num_spent += tick_interval
                                user["time_spent_seconds"] = num_spent
                                
                                remaining = max(0, exam_duration_sec - num_spent)
                                await ws.send_str(events.sync_time(remaining))
                                
                                if remaining <= 0:
                                    print(f"[EXAM] Client {cid} ran out of time!")
                                    await ws.send_str(events.exam_end())
                                    
                    except ConnectionResetError:
                        dead.append(cid)
                for cid in dead:
                    state.clients.pop(cid, None)
                    
                state.save_users()
                
                # --- UI PIPELINE ---
                if state.gui_process and state.gui_process.poll() is None:
                    try:
                        ui_clients = []
                        for login_id, u in state.users_db.items():
                            cid = u["uuid"]
                            
                            status = "Disconnected"
                            if cid in state.clients:
                                status = "Connected"
                                
                            rem = max(0, exam_duration_sec - u.get("time_spent_seconds", 0))
                            ui_clients.append({
                                "uuid": cid,
                                "login_id": login_id,
                                "status": status,
                                "remaining": rem
                            })
                        
                        payload = json.dumps({"type": "state_update", "clients": ui_clients})
                        state.gui_process.stdin.write(payload + "\n")
                        state.gui_process.stdin.flush()
                    except Exception as e:
                        print(f"[GUI IPC] Warning: Failed to write to GUI: {e}")
    except asyncio.CancelledError:
        pass


def _gui_reader_thread(loop):
    """Reads stdout from the Tkinter GUI to pick up Options actions like sending savescreen."""
    if not state.gui_process:
        return
        
    for line in iter(state.gui_process.stdout.readline, ''):
        line = line.strip()
        if not line: continue
        try:
            req = json.loads(line)
            cmd = req.get("cmd")
            uuid_val = req.get("uuid")
            
            if cmd == "savescreen" and uuid_val in state.clients:
                ws = state.clients[uuid_val]["ws"]
                asyncio.run_coroutine_threadsafe(ws.send_str(events.savescreen()), loop)
                print(f"\n[GUI->WS] Sent savescreen to {uuid_val}")
            
            elif cmd == "get_processes" and uuid_val in state.clients:
                ws = state.clients[uuid_val]["ws"]
                asyncio.run_coroutine_threadsafe(ws.send_str(events.get_processes()), loop)
                print(f"\n[GUI->WS] Sent get_processes to {uuid_val}")
                
        except Exception:
            pass

async def console_reader(app: web.Application):
    """Reads stdin for operator commands."""
    loop = asyncio.get_event_loop()
    
    if state.gui_process:
        t = Thread(target=_gui_reader_thread, args=(loop,), daemon=True)
        t.start()
        
    try:
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            parts = line.strip().split()
            if not parts:
                continue
            cmd = parts[0].lower()

            if cmd == "/clients":
                if state.clients:
                    print(f"[CMD] {len(state.clients)} client(s) connected:")
                    for cid, data in state.clients.items():
                        print(f"       - UUID:  {cid}")
                        print(f"         Short: {data['short_id']}")
                        print(f"         IP:    {data['ip']}")
                        print()
                else:
                    print("[CMD] No clients connected.")

            elif cmd == "/savescreen":
                if len(parts) < 2:
                    print("[CMD] Usage: /savescreen <client_id>  or  /savescreen all")
                elif parts[1].lower() == "all":
                    count = await broadcast_to_all(events.savescreen())
                    print(f"[CMD] Sent SAVESCREEN to {count} client(s)")
                else:
                    target = parts[1]
                    if await send_to_client(target, events.savescreen()):
                        print(f"[CMD] Sent SAVESCREEN to client {target}")
                    else:
                        print(f"[CMD] Client '{target}' not found (tried UUID, short ID, IP).")
                        print("      Type /clients to list available targets.")

            elif cmd == "/exam":
                exam_duration_sec = app["exam_duration"] * 60
                
                print("\n[CMD] --- LIVE EXAM STATUS ---")
                active_users = []
                for cid, data in state.clients.items():
                    # Find user record in DB by UUID
                    user_record = None
                    for login_id, db in state.users_db.items():
                        if db["uuid"] == cid:
                            user_record = db
                            break
                    active_users.append((cid, data, user_record))
                
                if not active_users:
                    print("No clients connected.")
                else:
                    for cid, _, user_data in active_users:
                        if user_data:
                            # Find login_id for this user
                            login_id = "unknown"
                            for lid, data in state.users_db.items():
                                if data["uuid"] == cid:
                                    login_id = lid
                                    break
                                    
                            state_val = "Waiting"
                            if user_data.get("exam_started"):
                                state_val = "Running"
                                
                            rem = max(0, exam_duration_sec - user_data.get("time_spent_seconds", 0))
                            m, s = divmod(rem, 60)
                            print(f"User: {login_id:12} | State: {state_val:7} | Remaining: {m:02d}m {s:02d}s")
                        else:
                            print(f"Unknown UUID: {cid}")
                print("------------------------------\n")
                
            elif cmd == "/help":
                print("  /clients              - List connected clients")
                print("  /savescreen <id>      - Save replay on a specific client")
                print("  /savescreen all       - Save replay on ALL clients")
                print("  /help                 - Show this help")
            else:
                print(f"[CMD] Unknown command: {cmd}  (type /help)")
    except asyncio.CancelledError:
        pass
