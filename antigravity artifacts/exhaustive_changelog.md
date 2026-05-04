# Sovereign Sentinel: Exhaustive Changelog (May_04)

Per your request for absolute granularity, below is the exhaustive, file-by-file analysis of every single change between the `near final delivery` codebase and the newly finalized `May_04` codebase. A total of ~12,600 lines were added and ~2,000 removed across 95 core files.

---

## 🎨 1. The Core UI Ecosystem (`ui/`)
This is an entirely new directory replacing hardcoded Tkinter styles with a centralized design system.
* **`ui/theme.py` (+103 lines):** Introduces `MaterialTheme` holding core visual tokens (Surface, Primary, Outline, Error, Success colors) and font sizing constants.
* **`ui/styles.py` (+561 lines):** Contains the massive Qt Style Sheets (`GLOBAL_QSS` and `GLASS_QSS`) that apply consistent glassmorphism to every button, table, tree, and dialog in the app.
* **`ui/background.py` (+173 lines):** Implements the animated "Starfield" background class (`StarfieldBackground`) mapped via `QPainter`.
* **`ui/widgets.py` (+152 lines):** Factory functions (`make_button`, `make_combo`, `apply_card_style`) ensuring all standard UI elements are built uniformly.

---

## 🖥️ 2. The Server Engine (`server/`)
### State & Services
* **`server/settings_service.py` [NEW, +1,022 lines]:** 
  * Extracts all exam policy JSON parsing, validation, merging, default ruleset generation, import/export logic, and process decision application away from the GUI threads.
* **`server/state.py` (+239 lines):** 
  * Introduced `PROCESS_DEFINITIONS_FILE` (`data/server/process_definitions.json`) to keep `exam_policy.json` clean.
  * Added `load_process_definitions()` and `save_process_definitions()`.
* **`server/handlers.py` (+114 lines):**
  * Added `_apply_configured_process_actions()`. The server will now automatically *Kill PID*, *Pause Exam*, or *Ban/Kick User* when a client reports a blacklisted process violation, whereas before it only logged it.
* **`server/tasks.py` (+324 lines):**
  * Refactored `_launch_server_gui()` to use `subprocess.Popen` with dynamic `--ui qt` or `--ui tk` flags.
  * Now pushes the massive `settings_snapshot` over IPC to update the new Qt dialogs in real-time.

### Server Dispatchers & UI Routing
* **`server_launcher.py` (Refactored):** Completely gutted (-485 lines) and turned into a simple CLI interface relying on `launcher_ui/`.
* **`server/gui.py`, `gui_qt.py`, `gui_tk.py`:** Replaces the old `server_gui.py` monolithic script. These files now act as IPC/Subprocess bridges between the backend engine and the graphical UI loops.
* **`server/ui/dashboard_qt.py` [NEW, +1,458 lines] & `dashboard_tk.py` [MOVED, +608 lines]:** 
  * Complete PySide6 implementation of the main monitoring dashboard. Features `QTableWidget` for clients and `QTreeWidget` for process tracking.
* **`server/ui/policy_settings_qt.py` [NEW, +757 lines] & `policy_settings_tk.py` [NEW, +657 lines]:** 
  * The massive 9-tab policy editor (Runtime, Exceptions, Processes, etc.) rewritten natively for Qt.
* **`server/ui/process_database_helpers.py` [NEW, +50 lines]:** Centralizes logic to match process attributes (Paths vs Directories vs Names) and calculate admin action availability.

---

## 💻 3. The Client Engine (`client/`)
### Replay & Recorders
* **`client/custommodules/replay_recorder/core.py` [REWRITTEN, +381 lines]:**
  * Old inline saving was scrapped. Replaced with `ReplaySaveQueue`.
  * Implements `asyncio.PriorityQueue` to manage screenshot writing. Prevents system freezes by dropping low-priority interval screenshots if the queue is overloaded, prioritizing actual "Incident Evidence" screenshots instead.
* **`client/ws_client.py` (+358 lines):**
  * Instantiates the new `ReplaySaveQueue`. 
  * Spawns `ClientGUIBridge` with dynamic `ui="qt"` or `ui="tk"` configurations.

### Client UI & Incidents
* **`client/incidents.py` (+405 lines):**
  * `ClientIncidentEngine` now understands deep `process_definitions`. It checks against exact paths or folder wildcards instead of just flat string names.
* **`client/ui/exam_qt.py` [NEW, +641 lines] & `exam_tk.py` [MOVED]:**
  * The actual client locking UI (fullscreen, top-most, anti-alt-tab) written natively in PySide6 to replace Tkinter's `overrideredirect`.

---

## 🚀 4. Launchers Manager (`launcher_ui/`)
This entirely new package manages the sequence of events *before* the exam/server starts (Auth, File Validation, Connection Checks).
* **`launcher_ui/client_manager_qt.py` (+491 lines) & `client_manager_tk.py` (+506 lines)**: Handles student login flow visually.
* **`launcher_ui/server_manager_qt.py` (+527 lines) & `server_manager_tk.py` (+541 lines)**: Handles admin setup visually.
* **Shared Logic (`common/manager_support.py` & `manager_support_qt.py`):** Ensures abstract logical parity so both graphical toolkits execute the exact same state machine.

---

## 🛡️ 5. Testing Engine (`tests/`)
Almost 2,000 lines of rigorous automated testing were added, transforming the repository from a prototype into enterprise-grade.
* **Unit Tests (`tests/unit/`)**:
  * `test_process_database.py` (+268 lines): Verifies accurate fingerprinting of active processes against defined blacklists.
  * `test_replay_recorder.py` (+236 lines) & `test_replay_save_queue.py` (+153 lines): Simulates high-load screenshot dumping to ensure the priority queue manages memory effectively.
  * `test_client_incidents.py` (+188 lines): Validates detection triggers for unauthorized applications.
  * `test_settings_service.py` (+148 lines): Mocks serialization of the JSON policy config.
  * `test_server_handlers.py`, `test_server_app.py`, `test_server_shutdown.py`: Validate server lifecycle.
* **Integration Tests (`tests/integration/`)**:
  * `test_discovery.py` (+77 lines): Simulates UDP packets verifying the client successfully auto-discovers the Server's IP address.

---

## 📁 6. General Housekeeping
* **`common/process_definitions.py` (+329 lines):** Added a standardized data model for how processes are identified across the app.
* **`docs/`**: Cleaned up the root directory by moving `FEATURE_MATRIX.md`, `FILE_CLASSIFICATION.md`, `OWNER_CONFIRMATION.md`, and `VALIDATION.md` here.
* **`run_demo.*`**: Fully deleted all legacy shell/batch startup scripts to enforce usage of the modern `python server_launcher.py --ui qt` CLI flows.
