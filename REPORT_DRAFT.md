# Software Engineering Task 2 Report Draft

Student Name: `[Your Name]`  
Student ID: `[Your Student ID]`  
Course: `[Course Name]`  
Task: `Design the architecture of the student-side client application, including exam launch control, time tracking, and activity monitoring structure`

## Abstract

This report presents the architecture of the student-side client application for a network-based exam system. The client is responsible for discovering the server, authenticating the student, preparing the exam environment, launching the exam session, tracking remaining time, and collecting monitoring data during the exam. The implementation is organized around a central client controller supported by separate modules for protocol handling, GUI interaction, activity monitoring, and replay recording. This report explains how the student-side architecture is structured, how its main modules collaborate, and how well the current implementation satisfies the task requirements.

## 1. Introduction

The goal of this task is to design the architecture of the student-side client application rather than the whole exam platform. For that reason, the main focus of this report is the internal organization of the client program and the way it supports three key responsibilities:

- exam launch control,
- time tracking,
- activity monitoring.

In the current project, the student client is implemented primarily in `client.py`, with support from `client_gui.py`, `shared.py`, `events.py`, `discovery.py`, `custommodules/process_monitor.py`, and `custommodules/replay_recorder.py`. Together, these modules form a client architecture that is event-driven, network-aware, and extensible enough to support a supervised exam workflow.

## 2. Task Completion Assessment

Based on the current repository state, I would estimate that the task is **about 78% complete**.

This estimate is based on the following breakdown:

- **Student-side client architecture:** about **85% complete**.  
  The client already has a clear modular structure with a main controller, protocol helpers, GUI support, monitoring modules, and network discovery.

- **Exam launch control:** about **80% complete**.  
  The student can start the exam through terminal input or the GUI start button, and the client sends the correct event to the server.

- **Time tracking:** about **80% complete**.  
  Remaining exam time is synchronized from the server and displayed locally in the GUI, while also being forwarded to the monitoring module.

- **Activity monitoring structure:** about **70% complete**.  
  A process-monitoring module and replay-recording module both exist, but the monitoring architecture still feels prototype-level and could use stronger integration, clearer interfaces, and fuller validation.

The task is not yet fully complete for three main reasons:

1. The architecture exists mostly in code, but it is not yet fully documented as a formal design.
2. There is at least one important runtime issue in the client path: `client.py` uses `Thread(...)` but does not import it.
3. The testing setup is incomplete and partly out of sync with the active credential configuration.

## 3. Design Goals of the Student Client

The student-side client should achieve the following design goals:

- connect to the correct server with minimal manual configuration,
- authenticate the student and preserve a unique session identity,
- allow the student to explicitly begin the exam,
- track and present the remaining exam time,
- collect monitoring information during the exam,
- remain responsive while network and monitoring tasks run in the background,
- support future extension without major redesign.

The current architecture addresses these goals by dividing the client into a small number of focused modules instead of placing all logic in one large monolithic flow.

## 4. High-Level Client Architecture

### 4.1 Main Structure

At a high level, the student-side architecture is centered on `client.py`. This file acts as the application coordinator. It does not implement everything directly; instead, it orchestrates other modules that each handle a narrower responsibility.

The main layers of the client architecture are:

1. **Connection and session layer**  
   Responsible for discovery, login, configuration retrieval, file download, and WebSocket communication.

2. **Exam control layer**  
   Responsible for the pre-exam phase, start action, session lifecycle, and disconnection handling.

3. **Time tracking layer**  
   Responsible for receiving synchronized countdown updates from the server and reflecting them in both the GUI and monitoring state.

4. **Monitoring layer**  
   Responsible for process logging and optional replay capture.

5. **Presentation layer**  
   Responsible for the student-facing timer window and start button.

This layered structure is appropriate for the task because it directly matches the functional requirements of the student application.

### 4.2 Architectural View

The architecture can be summarized as follows:

`client.py`  
-> discovers the server using `discovery.py`  
-> authenticates and retrieves exam information over HTTP  
-> opens a WebSocket session  
-> launches `client_gui.py` for student interaction  
-> starts `ProcessMonitor` for activity monitoring  
-> optionally starts `ReplayRecorder` for rolling screen capture  
-> reacts to server events through `shared.py` and `events.py`

This means the client is designed as an orchestration-based application rather than a single-purpose script.

## 5. Exam Launch Control Architecture

Exam launch control is one of the strongest implemented parts of the task.

The client includes a dedicated pre-exam stage before the exam officially begins. In this stage, the student is connected and authenticated, but the exam has not yet started. This allows the system to separate “session joined” from “exam started,” which is an important design decision for real exam workflows.

The exam can currently be launched in two ways:

- by typing `start` in the terminal,
- by clicking the start button in `client_gui.py`.

This control flow is coordinated in `client.py` through an `asyncio.Event` called `start_event`. The event acts as a synchronization point between terminal input, GUI actions, and the WebSocket session. Once the event is set, the client sends the `start_exam` protocol message to the server and transitions into the active exam phase.

This is a good architectural choice because:

- it decouples UI action from network transmission,
- it avoids immediate exam start on connection,
- it makes future additions such as confirmation dialogs or biometric checks easier to add.

One weakness remains: the GUI path in `client.py` starts a background thread with `Thread(...)`, but `Thread` is not imported there. As a result, the launch-control architecture is conceptually sound, but the current implementation has a runtime risk that should be fixed before final submission.

## 6. Time Tracking Architecture

Time tracking is implemented as a synchronized client-server responsibility.

The client does not calculate the official exam time independently. Instead, the server remains authoritative and periodically sends `sync_time` events to the client. This is a strong architectural decision because it prevents the student client from becoming the source of truth for exam duration.

On the client side, time tracking has three destinations:

1. **User interface**  
   `client_gui.py` receives `SYNC:<seconds>` messages through standard input and updates the countdown shown to the student.

2. **Monitoring state**  
   `ProcessMonitor.update_time()` receives the same remaining-time information so that activity logs can be correlated with the exact exam phase.

3. **Console feedback**  
   `client.py` occasionally prints remaining time to the terminal as a secondary visibility channel.

This design is effective because it keeps the client synchronized with the server while still allowing local display and local metadata generation.

The time-tracking structure is therefore mostly complete, but it still has some limitations:

- the client GUI decrements time locally between server updates, so long delays or lost sync events could create temporary display drift,
- the client depends entirely on server availability for authoritative timing,
- no dedicated recovery logic exists for time resynchronization after prolonged interruption beyond reconnect behavior.

## 7. Activity Monitoring Architecture

The task explicitly requires an activity monitoring structure, and the current project provides one through two complementary components.

### 7.1 Process Monitoring

`custommodules/process_monitor.py` is responsible for collecting process-level activity during the exam. It periodically inspects running processes using `psutil` and stores structured JSON lines in a per-session log file. The design combines:

- differential snapshots every 15 seconds,
- periodic full snapshots,
- manual full reports triggered by the server.

This is a sensible architecture because it avoids unnecessarily large logs while still preserving meaningful change history. The monitor also stores the remaining exam time alongside each payload, which makes later review easier.

### 7.2 Replay Recording

`custommodules/replay_recorder.py` provides a second monitoring mechanism through rolling replay capture. It uses FFmpeg to maintain short recording segments and can later merge the most recent period into a saved replay file.

Although replay recording is optional, architecturally it strengthens the client because it gives the monitoring system two layers:

- process-based activity evidence,
- screen-based retrospective evidence.

### 7.3 Architectural Evaluation

The monitoring structure is clearly present and reasonably modular, but it is not fully mature yet. Some weaknesses are:

- replay recording depends on FFmpeg and OS-specific permissions,
- there is no single abstraction layer that unifies all monitoring outputs under one interface,
- the current architecture is stronger at data collection than at policy evaluation.

Even with these limitations, the student-side client already demonstrates a valid activity-monitoring architecture rather than only a placeholder idea.

## 8. Module-by-Module Analysis

### 8.1 `client.py`

This is the main controller of the student-side architecture. It performs:

- server discovery,
- login,
- exam file retrieval,
- health checking,
- WebSocket session management,
- exam launch coordination,
- GUI process management,
- monitoring startup and shutdown,
- reconnection handling.

From an architectural perspective, `client.py` successfully acts as the composition root of the student client. Its main weakness is that it now carries many responsibilities, so future refactoring could extract dedicated controller classes.

### 8.2 `client_gui.py`

This module implements the student-side GUI. It provides:

- a waiting screen,
- a start button,
- a local countdown display,
- a simple inter-process communication path with the parent client process.

This file fits the task very well because it directly supports exam launch control and time tracking.

### 8.3 `discovery.py`

This module is not part of monitoring or timing directly, but it supports the student experience by making server connection more automatic. In architectural terms, it improves usability and reduces setup complexity.

### 8.4 `shared.py` and `events.py`

These modules define the communication contract used by the client. They reduce duplication and make event usage more explicit, which is important in an event-driven client application.

### 8.5 `custommodules/process_monitor.py`

This module is the clearest implementation of the “activity monitoring structure” required by the task. It has a well-defined role and outputs structured logs, which is exactly the kind of modular support component expected in a good architecture.

### 8.6 `custommodules/replay_recorder.py`

This module extends the monitoring architecture with evidence capture. Even though it is less central than process logging, it makes the client design stronger and more realistic.

## 9. Testing and Current Validation Status

The current codebase provides some evidence that the architecture is already implemented in a meaningful way.

First, the core client-related modules compile successfully with `python3 -m py_compile`, which confirms that the source files are structurally valid.

Second, the repository includes integration-style scripts such as `test_auth.py` and `test_comm.py`, showing that the project attempts automated validation of client-server behavior.

However, the current validation story is not fully complete.

- The test scripts use `testuser / secret`, while the current `allowed_users.json` contains `student1 / secret1`, `student2 / secret2`, and similar entries.
- In the analysis environment, UDP binding and local server binding were blocked by sandbox restrictions, so a full runtime verification could not be completed here.
- Because of the missing `Thread` import in `client.py`, the GUI-assisted start flow still has a real runtime risk.

For these reasons, the architecture should be described as **implemented and partially validated**, not fully production-ready.

## 10. Strengths of the Current Design

The current student-side client architecture has several clear strengths:

- it is modular rather than monolithic,
- it separates networking, GUI, timing, and monitoring concerns,
- it uses server-authoritative time synchronization,
- it supports both terminal and GUI launch control,
- it records monitoring data in structured formats,
- it is extensible enough for future features.

These strengths show that the task has been addressed with a real architectural solution rather than only a minimal functional script.

## 11. Remaining Work

To consider the task fully complete, the following improvements should still be made:

1. Fix the missing `Thread` import in `client.py`.
2. Align the test scripts with the active credential set.
3. Add a small architecture diagram for the report.
4. Refactor `client.py` into smaller controllers if a cleaner design is desired.
5. Strengthen the monitoring abstraction so process logs and replay capture feel like one coherent subsystem.
6. Add stronger runtime validation for GUI-triggered exam start and reconnect scenarios.

## 12. Conclusion

The student-side client architecture in the current project is already substantial and mostly aligned with the stated task. The implementation includes a central client controller, a GUI-based launch mechanism, synchronized time tracking, and a modular monitoring structure based on process logging and replay recording. These are the exact core areas requested by the task.

For that reason, the work should be considered mostly complete rather than incomplete. The main missing part is not the absence of architecture, but the need to stabilize, document, and validate the architecture more thoroughly. With a few targeted corrections and clearer presentation, this client design would satisfy the task very well.

## 13. Submission Notes

Before final submission, you should:

- replace the placeholder identity fields,
- add screenshots if your instructor expects visual evidence,
- optionally include a simple component diagram,
- update the completion wording if you improve the implementation before submitting,
- correct any code issues you want to mention as “resolved” instead of “known limitation.”
