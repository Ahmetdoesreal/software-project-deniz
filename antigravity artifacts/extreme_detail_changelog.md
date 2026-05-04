# Extreme Detail Changelog: Method & Logic Deep-Dive (May_04)

You requested absolute granular detail. This document breaks down the specific classes, methods, and logic branches that were altered or added in the 16,606-line diff between `near final delivery` and `May_04_Deniz`. 

---

## 1. Automated Punitive Actions (`server/handlers.py`)
Previously, process violations were purely passive (logged as incidents). The server now actively enforces rules based on policy configurations.

* **`_configured_process_actions(incident: dict) -> dict` [NEW]**: Extracts the `actions` block from the matched process definition payload (defaulting to empty if none exist).
* **`_apply_configured_process_actions(...)` [NEW]**: Intercepts `_handle_incident_report_event` when `status == "opened"`.
  * **Kill PID**: If `actions.get("kill_pid")`, issues `events.kill_process(pid)` directly to the client's WebSocket. Returns `{"action": "kill_pid", "state": "applied"}`.
  * **Pause Exam**: If `actions.get("pause_exam")` and the user is running, calls `session_state.set_state(user, ADMIN_PAUSED)`, sends a `pause_exam` event, and freezes their remaining time.
  * **Ban**: If `actions.get("ban")`, immediately transitions the user state to `BANNED`, increments `kick_count`, sets `last_action = "Process policy ban"`, and force-closes the WebSocket (`ws.close()`).
  * **Kick**: Disconnects the socket without a permanent ban.

## 2. Asynchronous Replay Save Queues (`client/custommodules/replay_recorder/core.py`)
The entire screenshot management engine was gutted (-253 lines) and rebuilt (+381 lines) to prevent disk I/O blocking.

* **`class ReplaySaveQueue` [NEW]**:
  * Initializes an `asyncio.PriorityQueue[tuple[int, int, ReplaySaveRequest]]`.
  * **Priorities**: Hardcoded priority integers. `REPLAY_PRIORITY_FINAL_SUBMISSION` (10), `REPLAY_PRIORITY_INCIDENT_EVIDENCE` (20), `REPLAY_PRIORITY_OPTIONAL_REQUEST` (50).
  * **`enqueue()`**: Computes a timeout deadline for optional requests. If the queue size exceeds `REPLAY_OPTIONAL_SAVE_QUEUE_LIMIT`, it intentionally drops the screenshot to prevent memory leaks.
  * **`_worker()`**: An infinite background coroutine. It safely awaits `self.loop.run_in_executor(None, self.recorder.save_replay, request_id)` so the main WebSocket client loop never stutters during disk writes.

## 3. Policy Settings Decoupling (`server/settings_service.py`)
A massive new 1,022-line file created to rip out policy parsing from the UI.

* **`apply_settings(state, payload)`**: Parses the giant JSON tree from the dashboard.
* **`update_process_definitions(state, payload)`**: Intercepts updates to `rules.process_definitions`. It validates the `process_key` schema (generating UUIDs if missing) and securely triggers `state.save_process_definitions()`.
* **`export_settings(state)` / `import_settings(state, raw_json)`**: Adds deep schema validation, asserting that `config["schema_version"] == 1` before allowing an admin to restore a backup.

## 4. Advanced Client Violations (`client/incidents.py`)
The client no longer just looks at executable names; it has a sophisticated scoping engine.

* **`ClientIncidentEngine._check_process_violations()` [MODIFIED]**:
  * Now receives `process_definitions.json`.
  * For each running process, iterates through definitions and checks the `match_scope`.
  * **Scope `PATH`**: Performs an exact `lower()` string match against the executable's absolute path.
  * **Scope `DIRECTORY`**: Checks if the running executable's parent directory starts with the blacklisted directory path.
  * **Scope `NAME`**: Falls back to the legacy `endswith(".exe")` filename check.
  * If matched, it attaches the `configured_actions` directly into the incident payload sent to the server.

## 5. UI Dispatchers & Interfaces (`launcher_ui/`)
The sprawling 500-line monolithic Tkinter launchers were replaced by abstract factories.

* **`class ClientManagerUI(ABC)` & `class ServerManagerUI(ABC)`**: Define required abstract methods like `show_error()`, `prompt_auth()`, `wait_for_server()`.
* **`launcher_ui/client_manager_qt.py`**:
  * Implements the Qt overrides. Uses `QWizard` or stacked `QWidget` layouts to handle the progression from "Select Exam" -> "Authenticating" -> "Ready".
* **`launcher_ui/client_manager_tk.py`**:
  * The exact same logical steps, but executed using `tk.Toplevel`, `ttk.Progressbar`, and `messagebox`.
  * The `client_launcher.py` script simply checks `sys.argv` for `--ui qt` and instantiates the correct class, firing `.run()`.

## 6. Server State Persistence (`server/state.py`)
* **`load_process_definitions()`**: A new boot method. If it detects embedded definitions inside `exam_policy.json` (from an old version), it extracts them, saves them to `process_definitions.json`, and scrubs `exam_policy.json` clean (`_remove_embedded_process_definitions()`), seamlessly upgrading the user's data schema on boot.

## 7. Deep Unit Testing Engine (`tests/unit/`)
* **`test_process_database.py`**: Mocks complex overlapping scopes. Tests what happens if an admin blacklists "Discord.exe" by name but allows "C:\Program Files\Discord\Discord.exe" by exact path.
* **`test_replay_save_queue.py`**: Uses `asyncio.sleep` mocks to fill the priority queue intentionally, asserting that `.enqueue()` returns `None` (drops) for optional requests when the limit is reached, while proving that `INCIDENT_EVIDENCE` still successfully bypasses the limit lock.
