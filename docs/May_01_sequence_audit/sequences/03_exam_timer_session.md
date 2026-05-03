# Exam Timer And Session State

This page explains how students move through waiting, running, paused, awaiting submission, and submitted states.

## In One Sentence

The server owns the timer and session state; the client follows server updates and records state changes in its local evidence logs.

## Who Is Involved

- Operator CLI or server GUI.
- Student CLI or client GUI.
- `server.tasks`, which handles start, finish, pause, resume, add-time, and timer broadcasts.
- `server.session_state`, which normalizes state names.
- `client.ws_client`, which updates client state and GUI.

## Starting The Exam

1. The operator enables the exam with `/startexam` or the GUI.
2. A student clicks start or types `start`.
3. The client sends `start_exam`.
4. The server checks that global exam start is enabled.
5. The server marks that user as running.
6. The server sends `session_state` and `sync_time`.
7. The client starts showing the countdown and records a timer-state marker in monitor logs.

## Timer Updates

The server broadcasts time on a regular interval. For every running student, it increments time spent and sends `sync_time` with the remaining seconds.

If a student is paused, time does not advance for that student.

When time reaches zero:

1. The server moves the student to `awaiting_submission`.
2. The server sends `session_state`.
3. The server sends `finish_exam`.
4. The client opens the final submission window.

## Pause And Resume

An operator can pause or resume a student from the CLI or GUI.

When this happens:

1. The server updates the persisted user state.
2. The server sends `session_state`.
3. The server sends either `pause_exam` or `resume_exam`.
4. The client updates its GUI and writes monitor state markers.

Pauses can come from administrators, disconnect handling, or violation policy.

## Global Finish

When the operator finishes the exam globally, the server moves every non-submitted user to `awaiting_submission`.

This includes users who never started, which matters because they still need a way to submit if the exam was ended by the server.

Connected clients receive `session_state` and `finish_exam`. Disconnected clients get the awaiting-submission state on reconnect.

## Disconnect And Reconnect

If a running client disconnects, the server saves remaining time and moves the user to `disconnected_paused`.

On reconnect, the server sends the current state. If policy allows automatic resume, the server moves the user back to running.

## Common Failure Clues

- Student cannot start: global start may not be enabled.
- Time keeps moving while paused: check `_sync_running_exams()` and paused session state.
- Finish window does not open: check whether `finish_exam` was sent after `session_state`.
- Reconnect does not resume: check session policy and whether state is `disconnected_paused`.

## Tests

- `tests/unit/test_server_tasks.py`
- `tests/unit/test_server_handlers.py`
- `tests/unit/test_server_state.py`
- `tests/unit/test_settings_service.py`
