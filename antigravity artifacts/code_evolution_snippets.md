# Code Evolution: Old vs. New Sequences (May_04)

This document highlights the exact logical sequences that were remade from the old codebase, providing side-by-side comparisons of how the underlying architecture evolved.

---

## 1. The Launcher Sequence
In the old codebase, `client_launcher.py` and `server_launcher.py` were massive monolithic files (450+ lines each) that mixed business logic with raw Tkinter UI code.

**Old Sequence (`client_launcher.py`)**:
```python
# The entire UI and process management was hardcoded into one file
class ClientManager(tk.Tk):
    def __init__(self):
        super().__init__()
        # 300+ lines of ttk.Label, ttk.Entry, grid() layouts...
```

**New Sequence (`client_launcher.py`)**:
The launcher is now an abstract dispatcher. It parses the `--ui` argument and loads the appropriate decoupled manager module.
```python
import argparse
import sys

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui", choices=["tk", "qt"], default="tk")
    args = parser.parse_args()

    if args.ui == "qt":
        from launcher_ui.client_manager_qt import run
        return run()
    
    # Default to legacy Tk fallback
    from launcher_ui.client_manager_tk import ClientManager
    app = ClientManager()
    app.mainloop()
```
*What was remade:* The 450 lines of Tkinter UI were stripped out and moved to `launcher_ui/client_manager_tk.py`. A parallel Qt equivalent was built in `launcher_ui/client_manager_qt.py`. Both now inherit from `ManagerSupport`, ensuring the exact same process management sequence is executed regardless of the UI engine.

---

## 2. Replay Recording Sequence
Previously, when the client needed to save a screenshot (e.g. periodically or during an incident), it directly dumped it to disk using `run_in_executor` on the main thread. Under heavy load, this could starve the WebSocket connection.

**Old Sequence (`client/custommodules/replay_recorder/core.py`)**:
```python
# Executed inline inside the main event loop
async def save_screenshot(request_id: str):
    await self.loop.run_in_executor(None, self.recorder.save_replay, request_id)
```

**New Sequence (`client/custommodules/replay_recorder/core.py`)**:
A robust `ReplaySaveQueue` was introduced. It manages an `asyncio.PriorityQueue` to handle bursts of screenshots.
```python
def enqueue(self, source: str, priority: int = None):
    # Determine priority (e.g. Incident Evidence > Periodic Capture)
    request_priority = self._priority_for_source(source)
    optional = request_priority >= REPLAY_PRIORITY_OPTIONAL_REQUEST
    
    # Drop low-priority screenshots if the queue is overloaded
    if optional and self._queued_optional >= self.optional_queue_limit:
        print(f"[RECORDER] Dropping replay request... queue is full.")
        return None
        
    self._queue.put_nowait((save_request.priority, self._sequence, save_request))
    self._ensure_worker() # Spawns a background worker if not already running

async def _worker(self):
    while True:
        # Pulls the highest priority item and safely saves it in the background
        _priority, _sequence, save_request = await self._queue.get()
        await self.loop.run_in_executor(None, self.recorder.save_replay, save_request.request_id)
```
*What was remade:* The entire screenshot persistence layer was refactored. The `enqueue` sequence now guarantees that "Incident Evidence" is saved instantly, while generic "Periodic Captures" will be silently dropped if the disk is struggling to keep up, preventing crashes.

---

## 3. Applying Policy Settings Sequence
Previously, when an admin saved settings in the GUI, the JSON was blindly injected straight into the server's state dictionary.

**Old Sequence (`server/handlers.py`)**:
```python
async def _handle_settings_save_event(ws, config):
    # Raw JSON override
    state.exam_policy_config = config
    state.save_exam_policy()
```

**New Sequence (`server/settings_service.py` & `handlers.py`)**:
A dedicated `SettingsService` layer was created to act as a firewall between the GUI and the Server Engine.
```python
# Inside handlers.py
from .settings_service import apply_settings

async def _handle_settings_save_event(ws, config):
    # Delegates to the secure service layer
    success, message = apply_settings(state, config)
    if not success:
        return {"status": "error", "message": message}

# Inside settings_service.py
def apply_settings(state, payload: dict) -> tuple[bool, str]:
    try:
        # Validates schema
        if payload.get("schema_version") != 1:
            return False, "Invalid schema version"
            
        # Segregates process definitions to prevent bloating exam_policy.json
        if "process_definitions" in payload:
            update_process_definitions(state, payload.pop("process_definitions"))
            
        # Commits remaining safe configs to the state machine
        update_runtime_settings(state, payload)
        return True, "Settings applied successfully"
    except Exception as e:
        return False, str(e)
```
*What was remade:* All JSON manipulation, validation, and serialization were stripped out of the core network handlers and relocated into a dedicated, testable `settings_service.py` module.

---

## 4. Punitive Action Sequence
In the old codebase, detecting a forbidden process only logged a message. The new sequence introduces an automated punishment engine.

**New Sequence (`server/handlers.py`)**:
```python
async def _apply_configured_process_actions(ws, user, incident):
    actions = _configured_process_actions(incident)
    
    # New punitive sequence
    if actions.get("kill_pid"):
        # Actively commands the client OS to terminate the executable
        await ws.send_str(events.kill_process(pid=incident["pid"]))
        
    if actions.get("pause_exam"):
        # Freezes the student's exam timer
        session_state.set_state(user, session_state.ADMIN_PAUSED)
        await ws.send_str(events.pause_exam())
        
    if actions.get("ban"):
        # Flags the user as banned and forcibly terminates the WebSocket connection
        session_state.set_state(user, session_state.BANNED)
        await ws.close(message="Banned by process policy")
```
*What was remade:* The incident event handler was upgraded to proactively parse the `configured_actions` attached to blacklisted processes and execute automated remote interventions (Kill, Pause, Ban) instantly.
