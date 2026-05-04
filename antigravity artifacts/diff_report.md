# Sovereign Sentinel: Codebase Evolution Report

This report highlights the major structural, architectural, and feature-level differences between the `near final delivery` folder and the modernised `May_04` (currently located in `May_04_Deniz`) folder.

> [!NOTE]
> The transition to the `May_04` codebase represents a significant leap forward in maintainability, user experience, and testing coverage. A total of **326 files were modified**, with over **23,000 lines added** and **1,997 lines removed**.

---

## 1. Modern Qt Interface & Dual-Dispatcher
The most significant change is the deprecation of the monolithic, hardcoded Tkinter GUI in favor of a modern, PySide6-powered **Sovereign Sentinel Design System**, while keeping Tkinter as a fallback.

- **Design System (`ui/`)**: A completely new native UI library was added (`ui/theme.py`, `ui/styles.py`, `ui/widgets.py`, and `ui/background.py`). It implements a beautiful, glassmorphic dark theme (Starfield background, translucent cards, responsive hover states) that is globally applied via Qt stylesheets.
- **Dual-Dispatch Architecture**: Launchers (`client_launcher.py`, `server_launcher.py`) were rewritten to accept a `--ui {qt,tk}` CLI argument.
- **File Separation**: The old `server_gui.py` has been split and relocated:
  - `server/ui/dashboard_tk.py` (legacy Tkinter dashboard)
  - `server/ui/dashboard_qt.py` (new Qt dashboard)
  - `server/ui/dashboard_dialogs_tk.py` (legacy popups)
  - `server/policy_settings_qt.py` & `server/ui/policy_settings_tk.py` (policy settings UI)

## 2. Server Architecture Refactoring
The backend server architecture was heavily decoupled to improve testability and maintainability.

- **Settings Service (`server/settings_service.py`)**: A massive new module (+1,020 lines) was introduced to isolate all exam policy management, JSON serialization, ruleset enforcement, and default policy generation. This replaces the scattered dictionary management that used to exist within the GUI and main threads.
- **Process Database Helpers (`server/ui/process_database_helpers.py`)**: Dedicated logic was extracted to handle process normalization, mapping, and admin decision application independently of the UI framework.

## 3. Replay Recorder & Queue System
Extensive testing and structural improvements were made to how student screenshots and incidents are buffered and recorded.
- Introduced `test_replay_recorder.py` and `test_replay_save_queue.py`. This solidifies the "Replay" functionality, ensuring that bursts of screen captures are reliably queued and written to disk without freezing the main event loop.

## 4. Enhanced Test Coverage
The `tests/` directory saw massive expansion, particularly in `unit` testing. Key additions include:
- **Client Incident Reporting**: `test_client_incident_reporting.py` and `test_client_incidents.py` were added to guarantee that the client accurately detects and forwards violations (like forbidden windows and blacklisted processes).
- **Process Database Integrity**: `test_process_database.py` was added to verify process fingerprinting.
- **Server State & Handlers**: New tests (`test_server_app.py`, `test_server_handlers.py`, `test_server_shutdown.py`, `test_server_state.py`) ensure the server state machine cleanly handles connections, disconnects, and graceful termination.
- **Integration**: Added `tests/integration/test_discovery.py` to ensure UDP discovery packets properly link clients to the server.

## 5. Structural Cleanup & Documentation
- **Docs Consolidation**: `FEATURE_MATRIX.md`, `FILE_CLASSIFICATION.md`, `OWNER_CONFIRMATION.md`, and `VALIDATION.md` were moved from the root folder into a dedicated `docs/` folder, cleaning up the root directory.
- **Demo Scripts Removed**: Legacy, cluttering scripts (`run_demo.bat`, `run_demo.py`, `run_demo.sh`) were completely wiped from the root.

---

### Summary
The `near final delivery` was a functional but monolithic prototype heavily tied to Tkinter. The `May_04` iteration has transformed it into a professional, decoupled, and highly-tested application with a premium Qt-based user interface.
