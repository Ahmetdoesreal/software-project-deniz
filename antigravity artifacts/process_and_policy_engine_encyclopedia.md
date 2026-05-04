# The Process & Policy Engine Encyclopedia (May_04)

This document is the definitive, encyclopedic reference for the Process and Policy subsystem introduced in the May_04 iteration. It provides exhaustive explanations of the data models, state machines, client enforcement loops, and server punitive mechanics that replaced the legacy Tkinter implementation.

---

## Part 1: The Flaws of the Legacy Architecture
In previous iterations, the "Process Blacklist" was a simple flat file or JSON array containing literal string names (e.g., `["cheatengine.exe", "discord.exe"]`). This created massive operational overhead:
1. **Lack of Granularity**: You could not blacklist `cmd.exe` running from a user directory without also blocking `C:\Windows\System32\cmd.exe` (which might be required for the OS).
2. **Schema Bloat**: As hundreds of processes were added, `exam_policy.json` grew exponentially, slowing down every WebSocket transmission that synced the policy.
3. **Passive Enforcement**: The server merely logged the violations. Administrators had to manually stare at the dashboard to notice a cheating attempt and manually click "Kick" or "Ban".

---

## Part 2: The Core Identity Model (`common/process_definitions.py`)
To solve the lack of granularity, processes are now identified by a sophisticated "Identity Model". 

### 2.1 Match Scopes
When an administrator creates a rule, they must specify a `match_scope` (`PROCESS_DEFINITION_SCOPES = {"path", "directory", "name"}`).

1. **`NAME` Scope**: The legacy mode. It runs `os.path.basename()` on the running process and compares it to the defined name. (e.g., `discord.exe`).
2. **`DIRECTORY` Scope**: Validates the parent directory of the running process. If a student launches *any* executable from `C:\Program Files\Cheats\`, it will trigger the rule, even if they rename the executable to `chrome.exe`.
3. **`PATH` Scope**: Absolute strict equality. The rule only triggers if the exact binary at the exact path is launched.

### 2.2 Deterministic Hashing (`stable_process_key`)
To store these advanced rules in a database and synchronize them across the network without generating duplicate UUIDs, a deterministic hash is used:
```python
def stable_process_key(process_name, process_path, match_scope):
    # Generates a deterministic SHA-256 hash slice.
    # Example: Hashing "path" + "discord.exe" + "C:\Mods\discord.exe" 
    digest = hashlib.sha256(f"{scope}|{normalized_name}|{target}".encode("utf-8")).hexdigest()
    return digest[:24]
```
If two different administrators manually attempt to blacklist the exact same path independently, they will generate the exact same `stable_process_key`, cleanly merging the rule rather than duplicating it.

### 2.3 Statuses and Actions
A process definition contains a `status` (`whitelist`, `blacklist`, `warning`, `unknown`) and an `actions` dictionary. The `actions` dictionary defines exactly what the server should do automatically if this process is detected:
* `ban`: Irrevocably permanently bans the user.
* `kick`: Forcefully disconnects the user, but allows reconnects.
* `pause_exam`: Freezes the student's exam timer.
* `kill_pid`: Attempts to forcefully terminate the remote executable.

---

## Part 3: State Decoupling (`server/state.py`)
The server's memory management was entirely refactored to stop `exam_policy.json` from ballooning.

### 3.1 Seamless Data Migration
Upon boot, `ServerState.load_process_definitions()` performs a live schema migration. 
1. It checks if the old `exam_policy.json` contains the legacy embedded `process_definitions` array. 
2. If it does, it extracts the array, writes it to a brand new `data/server/process_definitions.json` file.
3. It then executes `_remove_embedded_process_definitions()` and overwrites `exam_policy.json`, permanently scrubbing the legacy data from the main policy file.

---

## Part 4: Autonomous Client Enforcement (`client/incidents.py`)
The client no longer blindly streams every single running process to the server. It has been upgraded into an autonomous "Edge Enforcer".

### 4.1 The Observation Loop (`observe_processes`)
Every few seconds, the `ClientIncidentEngine` scans the OS process tree. 
For every running process, it executes `find_matching_definitions()`.

```python
matches = find_matching_definitions(self._process_definitions, name, process_path)
```
If a process matches a rule with the `whitelist` status, the client *suppresses the incident entirely*, generating zero network traffic.

### 4.2 Action Payload Injection
If the process matches a `blacklist` or `warning` rule, the client generates an incident. Crucially, the client pre-computes the server's response:
```python
incident.update({
    "event_type": "process_definition_match",
    "matched_definition_id": definition.get("definition_id"),
    "configured_actions": normalize_actions(definition.get("actions", {})),
})
```
By embedding the `configured_actions` into the incident payload *before* sending it over the WebSocket, the server doesn't have to look up the rule in its own database. It can execute the punishment instantly.

### 4.3 The Unexpected Process Baseline
If the policy has "Detect Unknown Processes" enabled, the client will flag any process that isn't explicitly whitelisted. However, to prevent banning a student the second the exam starts because of background Windows services, the client respects `baseline_existing_processes`. 
On the very first scan, it silently records every running process into `_unexpected_seen_identities`. Only processes launched *after* the exam starts will trigger "Unexpected Process" incidents.

---

## Part 5: Automated Server Execution (`server/handlers.py`)
When the WebSocket server receives an `opened` incident, it intercepts the payload.

### 5.1 `_apply_configured_process_actions()`
This function reads the `configured_actions` block injected by the client. It executes a rigorous enforcement tree:

1. **Kill PID**: 
   `await ws.send_str(events.kill_process(pid=incident["pid"]))`
   Instantly sends a command back to the client OS to terminate the executable.
2. **Pause Exam**: 
   `session_state.set_state(user, session_state.ADMIN_PAUSED)`
   Freezes the server-side exam timer and broadcasts a pause event to the student's GUI.
3. **Ban User**: 
   `session_state.set_state(user, session_state.BANNED)`
   Permanently flags the user as banned in the `users_db.json`. It increments their `kick_count`, tags the `last_action` with the specific process name, and force-closes the WebSocket connection (`ws.close()`).

---

## Part 6: Intelligent UI Aggregation (`server/settings_service.py`)
To power the modern PySide6 Qt interface, the server must calculate highly complex derived states. Administrators need to see exactly how many students are violating a rule, and whether they can take action.

### 6.1 `build_process_database(state)`
This algorithm constructs the master view for the "Process Database" Qt tab.
1. It iterates over the static disk rules (`state.process_definitions`).
2. It iterates over the volatile RAM (`state.incidents`).
3. It merges them. For every definition, it calculates:
   * `match_count`: How many times this process has been seen.
   * `affected_student_count`: How many unique `login_ids` have spawned it.
   * `active`: Whether the process is *currently* running on at least one student's machine.

### 6.2 Action Guardrails (`build_action_states`)
The UI buttons (Kill, Kick, Ban) must be mathematically verified before they are enabled in Qt. `build_action_states` iterates through every student violating a process rule and calculates `action_availability`:
* If `session_state == SUBMITTED`, `kill_pid` is physically impossible (the exam is over).
* If a client's WebSocket dropped, `kick` and `pause` are marked `not_possible` (reason: `disconnected`).
This allows the PySide6 UI to render disabled, greyed-out buttons with hover tooltips explaining *why* the administrator cannot take action.

---

## Part 7: Retroactive Application (`apply_process_decision`)
When an administrator clicks "Apply" on a new rule in the UI (e.g., changing an "Unknown" process to "Blacklist" with a "Ban" action), the `apply_process_decision` sequence fires:

1. **Schema Update**: Saves the new rule to `process_definitions.json`.
2. **Historical Retroactive Tagging**: Scans `state.incidents` for every historical occurrence of that process. It retroactively updates old incidents with the new `definition_id`, allowing the system to track that an "Unknown" process seen 2 hours ago is actually the malware that was just blacklisted.
3. **Immediate Live Fire**: If the new rule dictates a `Ban`, it instantly iterates over every `login_id` currently running the process, flags them as `BANNED`, and severs their WebSockets.
