# Technical Specification: Advanced Process & Policy Engine (May_04)

This document provides a professional-grade technical teardown of the Process and Policy Engine modifications introduced in the May_04 iteration. It contains the exact structural logic, algorithmic sequences, and code references required to understand or recreate the architecture.

## 1. Architectural Motivation
The legacy architecture relied on a flat array of string names (e.g., `["cheatengine.exe"]`) merged directly into the `exam_policy.json` file. This caused several critical issues:
1. **False Positives**: An admin could not differentiate between `C:\System32\cmd.exe` and a malicious `cmd.exe` located on a USB drive.
2. **Monolithic Bloat**: The policy file became massive, dragging down parsing times during WebSocket handshakes.
3. **Passive Monitoring**: Violations were only logged; administrators had to manually intervene.

The May_04 architecture solves this through deterministic hashing, decentralized policy storage, and proactive, client-driven punitive actions.

---

## 2. Core Identity Engine (`common/process_definitions.py`)

The engine now understands processes through three distinct **Match Scopes** (`PROCESS_DEFINITION_SCOPES`):
* `PATH`: Exact absolute path match (e.g., `C:\Games\Steam\steam.exe`).
* `DIRECTORY`: Prefix match. Flags any executable launched from the target folder (e.g., `C:\Program Files\Cheats\`).
* `NAME`: Fallback filename match (e.g., `discord.exe`).

### Algorithmic Hashing (`stable_process_key`)
To manage these definitions without UUID collision across different administrative sessions, the system generates deterministic identities:
```python
def stable_process_key(process_name, process_path, match_scope):
    # Generates a deterministic SHA-256 hash slice based on the defined scope
    if scope == "path":
        target = normalized_process_path
    elif scope == "directory":
        target = normalized_process_dir
    else:
        target = normalized_process_name
        
    digest = hashlib.sha256(f"{scope}|{normalized_name}|{target}".encode("utf-8")).hexdigest()
    return digest[:24]
```
*Why this matters:* If an admin blacklists "Discord" via Name, and another admin blacklists "Discord" via Path, they generate distinct deterministic hashes, preventing database collisions while allowing the UI to display them as separate rules.

---

## 3. The Client Enforcement Loop (`client/incidents.py`)

The `ClientIncidentEngine` no longer just streams running processes to the server. It securely downloads the `process_definitions.json` payload on boot and acts as an autonomous enforcer.

### `_observe_process_definitions(processes)`
During the periodic process scan, the client checks every active PID against the defined scopes:
```python
matches = find_matching_definitions(self._process_definitions, name, process_path)
if matches:
    definition = matches[0]
    # If the process is globally whitelisted by the admin, suppress it entirely.
    if definition.get("status") == "whitelist":
        suppressed_identities.add(identity)
        continue
        
    # Inject punitive actions directly into the incident payload!
    incident.update({
        "event_type": "process_definition_match",
        "matched_definition_id": definition.get("definition_id"),
        "configured_actions": normalize_actions(definition.get("actions", {})),
    })
```
*Why this matters:* By pre-attaching the `configured_actions` block to the outgoing network payload, the server does not have to waste CPU cycles scanning the policy dictionary during a burst of WebSocket incidents.

---

## 4. Automated Server Execution (`server/handlers.py`)

When the server receives an `opened` incident report from the client, it intercepts it before standard logging to execute any automated actions requested by the policy.

### `_apply_configured_process_actions(...)`
The server reads the `configured_actions` dictionary injected by the client and executes a ruthless if/else tree:
```python
actions = _configured_process_actions(incident)

if actions.get("kill_pid"):
    # Immediately fire a reverse-command telling the client OS to terminate the executable
    await ws.send_str(events.kill_process(pid=incident["pid"]))

if actions.get("pause_exam"):
    # Freeze the exam timer on the server side and notify the client GUI
    session_state.set_state(user, session_state.ADMIN_PAUSED)
    await ws.send_str(events.pause_exam(remaining))

if actions.get("ban"):
    # Irrevocably alter the user's state, increment kick_count, and sever the socket
    session_state.set_state(user, session_state.BANNED)
    user["kick_count"] += 1
    await ws.close(message="Banned by process policy")
```

---

## 5. Intelligent UI Data Aggregation (`server/settings_service.py`)

The new PySide6 Dashboard features a "Process Database" tab that displays every definition alongside historical matching data. To power this, the backend merges static policies with live volatile memory.

### `build_process_database(state)`
This algorithm iterates over `state.incidents` (live memory) and merges them against the `state.process_definitions` (saved disk rules).
1. **Aggregation**: Calculates `affected_student_count`, `opened_students`, and `match_count`.
2. **Action Availability Guardrails (`build_action_states`)**: Evaluates the network state of every violating student. 
   - If a user disconnected, it flags `kill_pid` as `not_possible`.
   - If a user's exam is `SUBMITTED`, it flags `pause_exam` as `not_possible`. 
   - This metadata is shipped to the UI, allowing the frontend to intelligently disable the "Kill Process" button if the server knows it will fail.

### Retroactive Rule Application (`apply_process_decision`)
When an administrator clicks "Apply Rule" on an unknown process from the UI, the engine updates history dynamically:
```python
# Save the rule permanently to the decoupled JSON file
upsert_process_definition(state, definition)

# Scan historical memory and update past incidents with the new rule ID
matches = matching_process_incidents(state, definition)
for incident in matches:
    incident["process_decision"] = {
        "definition_id": definition.get("definition_id"),
        "status": definition.get("status"),
        "actions": definition.get("actions")
    }

# Execute immediate punitive bans if the new rule dictates it
if definition.get("actions", {}).get("ban"):
    for login_id in violator_login_ids:
        session_state.set_state(user, session_state.BANNED)
```
*Why this matters:* Admins can see an unexpected process, realize it's a cheating tool 10 minutes into the exam, apply a `Ban` rule to it, and the server will instantly kick and ban every student who has *ever* spawned that process during the session.
