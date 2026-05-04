# Process & Policy Engine Evolution (May_04)

This document exclusively details the architectural changes made to how the Sovereign Sentinel engine identifies unauthorized processes, how policy definitions are scoped, and how punitive actions are calculated and applied. 

---

## 1. Process Definition Scopes (`common/process_definitions.py`)
In the old codebase, process blacklists were essentially a flat list of names (e.g., `["discord.exe", "cheatengine.exe"]`). This was prone to false positives. 

The engine now utilizes three distinct **Scopes**:
1. **`NAME` Scope**: The legacy approach. Matches purely on the executable filename (e.g. `discord.exe`).
2. **`DIRECTORY` Scope**: Matches any executable launched from a specific folder (e.g., blacklisting `C:\Program Files\Cheats\`).
3. **`PATH` Scope**: The strictest match. Checks absolute equality against the exact executable path.

**Identification Hashing**:
A new `stable_process_key()` hashing algorithm was introduced. It generates a deterministic UUID (SHA-256 slice) derived from a combination of the `match_scope`, the `normalized_process_name`, and the target path. This guarantees that processes are uniquely identified and updated correctly across both the UI and Server databases without collision.

---

## 2. Decoupled Policy Storage (`server/state.py`)
Previously, the `exam_policy.json` grew enormous because it held massive arrays of process definitions inline alongside the standard exam rules.

* **`process_definitions.json` Migration**: Process definitions have been formally split out of the `exam_policy.json`. 
* **Backwards Compatibility**: A seamless `load_process_definitions()` sequence was written into the boot lifecycle. If it detects legacy inline definitions, it extracts them, saves them to the new file, and permanently scrubs the legacy policy clean.

---

## 3. Intelligent Action Availability (`server/settings_service.py`)
The new GUI must know exactly *which* punishments can be legally applied to an offending student based on their current connection status.

The new `build_process_database()` and `build_action_states()` methods act as an intelligent intermediary logic layer:
* **Contextual State Awareness**: Before exposing an action like `kill_pid` or `pause_exam`, the service evaluates the student's state. 
* **Guardrails**:
  * If `session_state == SUBMITTED`, the student cannot be kicked, paused, or have PIDs killed (their exam is finished).
  * If a client disconnected mid-exam, `kill_pid`, `kick`, and `pause_exam` report `not_possible` with the reason `"disconnected"`.
  * If `banned == True`, all actions report `"already banned"`.
* This dynamic calculation is transmitted to the Qt UI, ensuring admins are never given a button that will silently fail.

---

## 4. Applying Process Decisions (`server/settings_service.py` -> `apply_process_decision()`)
When an administrator clicks "Apply" on a process definition in the new UI, a massive coordination sequence fires:

1. **Schema Generation**: Reconstructs the policy schema, setting `updated_at`, `decided_at`, and `decided_by` based on the actor applying the rule.
2. **Policy Commit**: Commits the rule to `process_definitions.json` permanently.
3. **Retroactive Incident Tagging**: It scans the live memory bank (`state.incidents`) for *every* past incident matching the new definition and retroactively applies the new `definition_id` and `decided_at` tags to them, allowing historical correlation.
4. **Immediate Punitive Fire**: If the new decision includes `actions: {"ban": true}`, it iterates through all live `login_ids` currently violating this process rule, injects the `BANNED` state into their session data, kicks them off the WebSocket, and forcibly saves the users database.

---

## 5. Client Enforcement (`client/incidents.py`)
The client no longer blindly streams raw processes over the wire.
* The `ClientIncidentEngine` now securely consumes `process_definitions.json`.
* Before reporting an incident, it executes `definition_matches_process()` utilizing the advanced `DIRECTORY`, `PATH`, and `NAME` logic. 
* If a process violates a definition, the client pre-attaches the `configured_actions` (like `kill_pid`) directly into the WebSocket payload, drastically reducing the server's compute overhead when making immediate kill decisions.
