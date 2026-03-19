import asyncio
import sys
import os
import subprocess
from threading import Thread
import aiohttp

from common import protocol, events
from custommodules.process_monitor import ProcessMonitor
from custommodules.replay_recorder import ReplayRecorder

async def prompt_start_exam(ws: aiohttp.ClientWebSocketResponse, start_event: asyncio.Event):
    """Wait for the user to type 'start' or a GUI signal to begin the exam."""
    print("\n--- PRE-EXAM PREPARATION ---")
    print("When you are ready, type 'start' or click the button in the GUI to begin the exam.")
    loop = asyncio.get_event_loop()
    
    while not start_event.is_set():
        def wait_for_start():
            while not start_event.is_set():
                line = sys.stdin.readline()
                if not line: break
                if line.strip().lower() == "start":
                    return True
            return False

        cli_task = loop.run_in_executor(None, wait_for_start)
        done, _ = await asyncio.wait(
            [asyncio.ensure_future(cli_task), asyncio.ensure_future(start_event.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        if start_event.is_set() or (cli_task.done() and cli_task.result()):
            await ws.send_str(events.start_exam())
            print("[EXAM] Started. Good luck!\n")
            start_event.set()
            return
            
        if not start_event.is_set():
            print("Type 'start' or use the GUI to begin.")


async def run_ws(ws_url: str, recorder: ReplayRecorder):
    """Connect via WebSocket, handle exam flow and pings."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            disconnected = asyncio.Event()
            exam_active = [True] # Use list for closure
            gui_process_ref = {"proc": None}
            
            client_uuid = protocol.extract_client_uuid(ws_url)
            out_dir = os.path.join("data", "client", client_uuid)
            pm = ProcessMonitor(out_dir)
            pm.start()
            
            start_event = asyncio.Event()

            def start_gui():
                if gui_process_ref["proc"] is None:
                    # client_gui.py is in the root directory relative to client/
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    gui_path = os.path.join(os.path.dirname(script_dir), "client_gui.py")
                    
                    gui_process_ref["proc"] = subprocess.Popen(
                        [sys.executable, gui_path], 
                        stdin=subprocess.PIPE, 
                        stdout=subprocess.PIPE, 
                        text=True,
                        bufsize=1
                    )
                    
                    def gui_stdout_reader():
                        for line in iter(gui_process_ref["proc"].stdout.readline, ''):
                            if "ACTION:START" in line:
                                print("[GUI] Start button pressed.")
                                loop = asyncio.get_event_loop()
                                loop.call_soon_threadsafe(start_event.set)
                        gui_process_ref["proc"].stdout.close()

                    Thread(target=gui_stdout_reader, daemon=True).start()

            async def listener():
                try:
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            event, data = protocol.decode(msg.data)
                            
                            if event == events.WELCOME:
                                print(f"[WS] Connected! Server assigned ID: {data['id']}")
                                start_gui()
                            elif event == events.ECHO:
                                print(f"[WS] Echo: {data}")
                            elif event == events.TIME:
                                pass
                            elif event == events.SYNC_TIME:
                                rem = data.get("remaining_seconds", 0)
                                if pm:
                                    pm.update_time(rem)
                                
                                start_gui()
                                
                                if gui_process_ref["proc"] and gui_process_ref["proc"].poll() is None:
                                    try:
                                        gui_process_ref["proc"].stdin.write(f"SYNC:{rem}\n")
                                        gui_process_ref["proc"].stdin.flush()
                                    except Exception:
                                        pass

                                if rem % 10 == 0:
                                    m, s = divmod(rem, 60)
                                    print(f"[EXAM] Time remaining: {m}m {s}s")
                                    
                            elif event == events.EXAM_END:
                                print("\n===============================")
                                print("       EXAM TIME IS UP!        ")
                                print("===============================")
                                exam_active[0] = False
                                
                                if gui_process_ref["proc"] and gui_process_ref["proc"].poll() is None:
                                    try:
                                        gui_process_ref["proc"].stdin.write("END:-1\n")
                                        gui_process_ref["proc"].stdin.flush()
                                    except Exception:
                                        pass
                                
                                disconnected.set()
                            elif event == events.SAVESCREEN:
                                print("[WS] [SAVESCREEN] Server requested replay save.")
                                loop = asyncio.get_event_loop()
                                await loop.run_in_executor(None, recorder.save_replay)
                            elif event == events.GET_PROCESSES:
                                print("[WS] [GET_PROCESSES] Server requested a manual process report.")
                                if pm:
                                    pm.trigger_full_report()
                            else:
                                print(f"[WS] {event}: {data}")

                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
                except Exception as e:
                    print(f"[WS] Listener error: {e}")
                finally:
                    disconnected.set()

            async def sender():
                await prompt_start_exam(ws, start_event)
                
                print("Type anything and press Enter to ping the server (Ctrl+C to quit):\n")
                loop = asyncio.get_event_loop()
                while not disconnected.is_set() and exam_active[0]:
                    read_future = loop.run_in_executor(None, sys.stdin.readline)
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
                if gui_process_ref["proc"] and gui_process_ref["proc"].poll() is None:
                    gui_process_ref["proc"].kill()
                if pm:
                    pm.stop()

            if disconnected.is_set():
                raise ConnectionError("Server disconnected")
