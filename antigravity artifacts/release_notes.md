# Sovereign Sentinel — Release Notes (May_04 Iteration)

Welcome to the largest architectural and UI modernization in Sovereign Sentinel's history. This release dramatically improves codebase maintainability, introduces a stunning new Qt-based UI, fully decouples our backend services, and adds comprehensive test coverage.

Below are the detailed patch notes covering the ~12,600 lines of new code.

---

## 🎨 1. The Sovereign Sentinel Design System & Qt Migration
We have completely overhauled the user interface layer. Moving away from monolithic Tkinter logic, we’ve built a robust dual-dispatch UI system that natively supports PySide6 (Qt) while retaining Tkinter as a lightweight fallback.

* **New `ui/` Module**: Introduced a centralized design system.
  * **`theme.py` & `styles.py`**: Defines a consistent, modern "Sovereign Sentinel" visual identity featuring dark modes, curated color palettes, and unified typography.
  * **`background.py` & `widgets.py`**: Added support for premium aesthetics like the dynamic glassmorphic "Starfield" background, elevated translucent cards, and smooth hover state transitions.
* **Dual-Dispatch Launchers**: `server_launcher.py` and `client_launcher.py` have been refactored into clean dispatchers. You can now launch the application with either `--ui qt` or `--ui tk`.
* **Dedicated UI Sub-Modules**:
  * **Server UI**: Extracted and modernized the dashboard into `server/ui/dashboard_qt.py` (+1,458 lines) and `server/ui/policy_settings_qt.py` (+757 lines). Legacy Tkinter variants have been preserved in `server/ui/dashboard_tk.py` and `policy_settings_tk.py`.
  * **Client UI**: The client exam window has been ported to Qt in `client/ui/exam_qt.py` (+641 lines).
  * **Launcher Managers**: Created a dedicated `launcher_ui/` directory managing both Qt and Tk flows for the pre-exam configuration stages.

## ⚙️ 2. Backend Decoupling & Services
The server architecture has been massively refactored to decouple business logic from the presentation layer.

* **`SettingsService` Introduction**: A massive new service (`server/settings_service.py`, +1,022 lines) now entirely manages the exam policy lifecycle. This removes all scattered dictionary state from the GUI, intelligently handling rule merging, serialization, validation, and default generation off the main thread.
* **Process Database Normalization**: Created `server/ui/process_database_helpers.py` to standardize how processes are fingerprinted, mapped against blacklists, and evaluated for admin action availability.
* **Replay Recorder Overhaul**: The core engine responsible for screen recording (`client/custommodules/replay_recorder/core.py`) has been rewritten (+381 lines) to utilize a robust queue system, ensuring that bursts of screenshots or incident recordings never freeze the main client event loop.
* **WebSocket Communications**: `ws_client.py` and server `tasks.py`/`state.py` saw significant updates to reliably route state snapshots between the backend services and the newly decoupled UI dispatchers.

## 🛡️ 3. Massive Testing Expansion
We've introduced rigorous unit and integration testing to ensure absolute stability during exams.

* **Replay & Queue Reliability**: Added `test_replay_recorder.py` and `test_replay_save_queue.py` to strictly verify file writing concurrency and buffer management.
* **Client Incident Reporting**: Added `test_client_incidents.py` and `test_client_incident_reporting.py` to guarantee that local violations (forbidden windows, unauthorized processes) are accurately captured and emitted to the server.
* **Process Integrity**: Added `test_process_database.py` (+268 lines) to validate correct matching scopes (Path, Directory, Name) and process key generation.
* **Server Lifecycle Tests**: Expanded coverage for core server mechanics including `test_server_app.py`, `test_server_handlers.py`, `test_server_shutdown.py`, and `test_server_state.py`.
* **Network Discovery**: Added `test_discovery.py` (Integration) to verify UDP broadcast/listening handshakes between clients and the server.
* **Policy Serialization**: Added `test_settings_service.py` to ensure rule modifications are accurately saved to and loaded from `exam_policy.json`.

## 📁 4. Project Structure & Cleanup
* **Documentation Consolidation**: Moved root-level documentation (`FEATURE_MATRIX.md`, `FILE_CLASSIFICATION.md`, `OWNER_CONFIRMATION.md`, `VALIDATION.md`) into a clean `docs/` folder.
* **Root De-cluttering**: Removed legacy developer demo scripts (`run_demo.bat`, `run_demo.py`, `run_demo.sh`) that are no longer necessary for the modern launcher flows.
* **File Separation**: The monolithic `client.py` and `server.py` scripts have been officially fully absorbed into their respective `client/` and `server/` module directories.
