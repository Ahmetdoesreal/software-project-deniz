# Policy, Incident, And Monitoring Methods

## Policy Design

Policy has two representations:

1. Stored policy config in `data/server/exam_policy.json`.
2. Client-facing current policy emitted by `state.current_exam_policy()`.

The stored config is convenient for settings UI and operator edits. The client-facing policy is normalized, versioned, and includes rule IDs, sources, and runtime data such as process blacklist entries and process definitions.

The policy version is a SHA-256 hash of the client-facing policy payload serialized with stable key ordering. This means clients apply exactly the policy they receive, and the server can tie incidents to a specific policy version.

## Stored Policy Shape

Top-level:

```json
{
  "session": {
    "auto_resume_on_reconnect": true,
    "remember_settings": true
  },
  "rules": {
    "process_blacklist": {},
    "focused_window": {},
    "rapid_application_switching": {},
    "idle_policy": {},
    "unexpected_process": {},
    "process_definitions": {},
    "process_path_clarification": {}
  },
  "operator_defaults": {
    "confirm_kill_pid": true,
    "confirm_kick": true,
    "confirm_ban": true,
    "confirm_pause": true
  }
}
```

Stored policy should be tolerant of missing fields. Normalization must fill defaults and coerce invalid values to safe values.

## Rule Defaults

### `process_blacklist`

Purpose: direct process name blacklist.

Fields:

- `enabled`: default true.
- `severity`: default `violation`.
- `process_usernames`: optional process owner filters.
- `auto_violation_pause`: default true.
- `allow_remote_kill`: default true.

Client-facing additions:

- `entries`: current blacklist entries from `process_blacklist.txt`.
- `blacklist_version`: file version stamp.

### `focused_window`

Client-facing rule ID: `focused_window_policy`.

Purpose: detect foreground application/window title outside policy.

Fields:

- `enabled`: default false.
- `severity`: default `warning`.
- `allowed_process_names`
- `allowed_window_titles`
- `blocked_process_names`
- `blocked_window_titles`
- `window_title_match_mode`: `contains` or `exact`.
- `open_after_consecutive`: default 3.
- `resolve_after_consecutive`: default 2.
- `auto_violation_pause`: default false.

Algorithm:

1. Normalize active process name and window title.
2. If blocked process or blocked title matches, mark out of policy.
3. Else if allowed lists are non-empty, require process/title to match an allow entry.
4. Increment out-of-policy counter while violating.
5. Open incident only after `open_after_consecutive`.
6. Increment in-policy counter while clear.
7. Resolve only after `resolve_after_consecutive`.

### `rapid_application_switching`

Purpose: detect excessive foreground app/window changes.

Fields:

- `enabled`: default false.
- `severity`: default `warning`.
- `max_switches`: default 10.
- `window_seconds`: default 60.
- `window_observations`: default 10.
- `auto_violation_pause`: default false.

Algorithm:

1. Convert each focus snapshot into a subject key, typically process plus title.
2. When subject changes, append timestamp to a deque.
3. Drop timestamps older than `window_seconds`.
4. If change count exceeds `max_switches`, open incident.
5. Resolve when the change window falls below threshold or focus stabilizes.

### `idle_policy`

Purpose: detect student inactivity from OS idle time.

Fields:

- `enabled`: default false.
- `severity`: default `warning` for policy config.
- `warn_threshold_seconds`: default 80.
- `critical_threshold_seconds`: default 150.
- `auto_violation_pause`: default false.

Normalization rule: `critical_threshold_seconds` must be greater than or equal to `warn_threshold_seconds`. If an admin supplies a smaller critical threshold, normalize it up to the warning threshold.

Client algorithm:

1. If disabled, resolve any open idle incident.
2. Ignore snapshots with negative idle seconds.
3. If idle seconds is below warning threshold, resolve any open idle incident.
4. If idle seconds is at least warning threshold but below critical threshold, open a warning incident.
5. If idle seconds is at least critical threshold, open or escalate to a violation incident.
6. When escalating from warning to critical, resolve the warning incident first and open a fresh critical incident.

The server auto-pause check uses `state.rule_config("idle_policy").auto_violation_pause` and incident severity. Only critical idle incidents become `violation` severity, so auto-pause happens only on critical idle when enabled.

### `unexpected_process`

Purpose: detect processes that are not known, allowed, or suppressed by stronger definitions.

Fields:

- `enabled`: default false.
- `severity`: default `warning`.
- `known_process_names`
- `known_directory_paths`
- `allowed_process_names`
- `baseline_existing_processes`: default false.
- `auto_violation_pause`: default false.

Algorithm:

1. Build known set from policy and existing blacklist/definition context.
2. Ignore whitelisted definitions.
3. Ignore allowed process names.
4. Ignore paths under known directories.
5. Optionally baseline currently running unknown processes without incident.
6. Open an incident for new unknown identities.
7. Resolve incidents when process disappears.

### `process_definitions`

Purpose: classify processes by stable admin decisions.

Fields:

- `enabled`: default true.
- `severity`: default `violation`.
- `detect_unknown_processes`: default true.
- `unknown_severity`: default `warning`.
- `baseline_existing_processes`: default true.
- `auto_violation_pause`: default false.
- `allow_remote_kill`: default true.

Definitions are stored separately in `process_definitions.json`, not embedded in `exam_policy.json`, so process database changes can be managed independently.

Definition fields:

- `definition_id`
- `process_key`
- `process_name`
- `normalized_process_name`
- `process_path`
- `normalized_process_path`
- `process_dir`
- `normalized_process_dir`
- `match_scope`: `name`, `path`, or `directory`
- `status`: `unknown`, `whitelist`, `blacklist`, or `warning`
- `actions`: `ban`, `kick`, `pause_exam`, `kill_pid`
- history and decision metadata.

Matching algorithm:

1. Normalize process name and path.
2. For name scope, require normalized process name.
3. For path scope, require exact normalized path.
4. For directory scope, require normalized process directory.
5. Prefer the first normalized matching definition.
6. Whitelist suppresses further incidents for that process identity.
7. Blacklist and warning statuses open incidents with configured actions.

### `process_path_clarification`

Purpose: detect process-name matches where the path differs from saved evidence and needs admin clarification.

Fields:

- `enabled`: default true.
- `severity`: default `warning`.
- `auto_violation_pause`: default false.
- `allow_remote_kill`: default true.

Use this to prevent a single process name from hiding different executables or directories.

## Incident Lifecycle

Incident statuses:

- `opened`: new issue detected.
- `resolved`: condition cleared.
- `evidence_uploaded`: artifact upload succeeded.
- `evidence_failed`: artifact upload failed or exhausted retry.
- `escalated`: optional status for future escalation paths.

Required fields:

```json
{
  "incident_id": "uuid",
  "policy_version": "sha256",
  "rule_id": "process_blacklist",
  "rule_name": "process_blacklist",
  "source": "process_monitor",
  "severity": "violation",
  "status": "opened",
  "summary": "Blacklisted process detected",
  "event_type": "process_blacklist",
  "event_at": "2026-05-10T...",
  "timestamp": "2026-05-10T...",
  "needs_evidence": true
}
```

Rule-specific fields may include:

- `pid`
- `process_name`
- `process_username`
- `process_path`
- `process_dir`
- `normalized_process_name`
- `window_title`
- `idle_seconds`
- `raw_processes`
- `definition`
- `action_availability`

## Server Incident Handling

When server receives `incident_report`:

1. Validate payload is an object.
2. Persist it to `incidents.jsonl`.
3. Update `active_incidents`.
4. Acknowledge with `incident_received`.
5. If status is `opened` and rule config has `auto_violation_pause` and severity is `violation`, move user to `violation_paused`.
6. Apply configured process actions where allowed.
7. Refresh dashboard state.

Configured process actions:

- `pause_exam`: server-side session transition.
- `kill_pid`: send `kill_process` event to client.
- `kick`: close WebSocket.
- `ban`: set user banned and persist.

Remote kill should only be offered when the rule and incident mark it available.

## Evidence Upload Method

For incidents that need evidence:

1. Client sends the incident immediately so server and dashboard are not delayed.
2. Client exports focused-window and hardware snapshots.
3. Client requests or saves replay evidence if recorder is active.
4. Client builds an incident ZIP through `build_incident_bundle`.
5. Client uploads the ZIP as `/client/artifact` with `kind=incident_evidence`.
6. On success, client sends incident update with `status=evidence_uploaded` and `artifact_path`.
7. On failure, client sends or schedules `evidence_failed` update.

This two-stage design prevents slow replay or upload work from delaying the first incident notification.

## Policy Settings Method

All settings UIs should build the same payload:

```json
{
  "cmd": "save_settings",
  "runtime": {
    "exam_duration": 45,
    "exam_files": "C:/path/exam.zip"
  },
  "exam_policy": {
    "session": {},
    "rules": {},
    "operator_defaults": {}
  },
  "process_blacklist": {
    "entries": ["discord.exe"]
  }
}
```

The server command handler should route this to settings service methods:

1. Update runtime settings.
2. Update exam policy.
3. Replace blacklist entries.
4. Broadcast policy and blacklist changes if needed.
5. Return `settings_result` to dashboard GUI.

Tk and Qt must expose the same rule fields. If a rule exists in `state.current_exam_policy()`, it should also be visible and editable in both policy windows.

