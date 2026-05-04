# Source Code Evolution: Method-Level Deep Dive

While the UI overhaul to Qt is the most visually striking change, the core backend logic (`client/` and `server/`) received significant architectural refactoring to improve stability, decoupled state management, and testability.

Below is an in-depth analysis of how methods and core loops have changed between the `near final delivery` and `May_04` milestones.

---

## 1. Client Engine (`client/ws_client.py` & `client/custommodules/`)

### Replay Save Queue Implementation
Previously, screen capture requests were executed inline or spawned as unmanaged asyncio tasks, risking memory leaks or freezing the WebSocket event loop under heavy load.

- **`ReplaySaveQueue` (New Class)**: We introduced a managed `asyncio.PriorityQueue` to handle all disk-write operations for replays.
  - **`enqueue()`**: Computes dynamic deadlines and priorities (`REPLAY_PRIORITY_FINAL_SUBMISSION`, `REPLAY_PRIORITY_INCIDENT_EVIDENCE`, `REPLAY_PRIORITY_OPTIONAL_REQUEST`). Drops low-priority periodic captures if the queue is overloaded, prioritizing incident evidence.
  - **`_worker()`**: A continuous background task that safely consumes the queue, executing the blocking disk I/O via `loop.run_in_executor()`.
  - **`WebSocketSession.__init__()`**: Now instantiates the `ReplaySaveQueue` and dynamically passes a `gui_ui` (`tk` or `qt`) parameter into the `ClientGUIBridge` initialization.

### Incident Reporting (`client/incidents.py`)
- **`ClientIncidentEngine`**: Methods handling process violations were refactored to consume the new `process_definitions.json` schema, matching running executables against specific scopes (`NAME`, `PATH`, `DIRECTORY`) rather than relying on a flat string blacklist.

---

## 2. Server State Management (`server/state.py`)

The server previously merged all configurations (including large JSON arrays of process definitions) into a single `exam_policy.json` file. This caused the policy file to become bloated and difficult to version control.

- **`load_process_definitions()` & `save_process_definitions()` (New)**: The server state now explicitly segregates process definitions into a dedicated `data/server/process_definitions.json` file.
- **`rule_config(rule_id)` (Modified)**: Dynamically injects the `process_definitions` array back into the policy payload *only* when requested by the GUI or client over IPC, preventing disk serialization collisions.
- **`_policy_without_process_definitions()` (New)**: Ensures that when the main `exam_policy.json` is dumped, it remains clean and lightweight.

---

## 3. Settings Service Orchestration (`server/settings_service.py`)

Previously, methods parsing policy updates were scattered across `server/handlers.py` and deeply embedded inside the UI mixins. A dedicated service layer (+1,022 lines) was created to centralize this.

- **`apply_settings(payload)`**: Intercepts the raw JSON from the Qt/Tk UI, validates the schema structure, and safely commits changes to the `ServerState`.
- **`export_settings()` & `import_settings()`**: Introduces standardized mechanisms for administrators to backup and restore policy states.
- **`generate_default_policy()`**: Provides a reliable factory pattern to rebuild missing policy rules dynamically if `exam_policy.json` is corrupted.

---

## 4. Launchers & Pre-Exam Setup (`launcher_ui/`)

The massive `client_launcher.py` and `server_launcher.py` scripts (each nearly 500 lines) were gutted.
- They have been converted to lightweight dispatchers.
- All actual pre-exam sequence methods (e.g., `prompt_auth()`, `wait_for_server()`) were moved into `launcher_ui/client_manager_qt.py` and `launcher_ui/client_manager_tk.py`. They now uniformly inherit from standard abstract interfaces (`ManagerSupport`), guaranteeing the exact same logical steps execute regardless of whether `--ui qt` or `--ui tk` is provided.
