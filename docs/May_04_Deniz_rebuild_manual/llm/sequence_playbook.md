# LLM Sequence Playbook

## Build The Shared Layer

1. Implement `protocol.encode/decode` with checksum.
2. Implement event constants and constructors.
3. Implement secured payload wrapper for selected events.
4. Implement process definition normalization and matching.
5. Implement loopback IPC server/client with token and peer checks.
6. Implement stdio compatibility helpers.
7. Implement JSONL runtime logging that survives missing stdio.

## Build The Server

1. Create `ServerState`.
2. Add file loaders that create defaults if files are missing.
3. Add `_default_exam_policy_config`.
4. Add `_normalize_exam_policy_config`.
5. Add `current_exam_policy` that emits a list of rules and policy hash.
6. Add session-state helper module.
7. Create aiohttp app and register routes.
8. Implement `/login`, `/exam/config`, `/exam/files`.
9. Implement `/exam/submission` and `/client/artifact`.
10. Implement `/ws` connect handshake and event dispatch.
11. Add time broadcaster.
12. Add command parser and command handlers.
13. Add settings service.
14. Add dashboard state snapshots.
15. Add shutdown routine.

## Build The Client

1. Implement server discovery or direct host selection.
2. Implement login and exam prep.
3. Implement replay recorder manager.
4. Implement GUI child launch and bridge.
5. Implement WebSocket connect/listener.
6. Implement handling for welcome, policy, blacklist, session state, sync time, pause/resume, finish, savescreen, kill process, and errors.
7. Implement monitors.
8. Implement incident engine.
9. Implement incident buffering and acknowledgement.
10. Implement incident evidence upload.
11. Implement submission bundle and upload.
12. Implement reconnect loop.

## Server WebSocket Algorithm

```text
validate uuid
reject banned/submitted/duplicate
prepare ws
state.clients[uuid] = ws metadata and security context
send welcome
send current exam_policy
send process_blacklist
send session_state
send sync/pause/finish depending on state
for each message:
    decode secure message
    dispatch by event
on disconnect:
    remove client
    if running: set disconnected_paused
    save users
```

## Client WebSocket Algorithm

```text
launch timer gui
start ipc/stdin bridge
connect ws
for each server event:
    decode secure message
    if policy: apply and ack
    if session/timer: update local state and gui
    if finish: open finish window
    if savescreen: enqueue replay save and upload
    if kill_process: terminate pid and report result
parallel:
    read gui commands
    run monitors
    report incidents
    upload evidence
    handle final submission
return True after accepted submission
```

## Incident Algorithm

```text
apply_policy(policy):
    require policy_version
    require rules list
    map rules by rule_id
    reset debounce/open incident state
    load process definitions

observe_processes(processes):
    process_definitions first
    blacklist second
    unexpected process last with suppressions
    return incident list

observe_focused_window(snapshot):
    evaluate focused_window_policy
    update rapid switching state
    return opened/resolved incidents

observe_idle(snapshot):
    if disabled: resolve open idle incident
    if idle < warn: resolve open idle incident
    if warn <= idle < critical: open warning
    if idle >= critical: escalate/open violation
```

## Submission Algorithm

```text
finish_exam(path):
    reject if upload already in progress
    gui upload_step
    export hardware snapshot
    export focused-window snapshot
    request final replay with timeout
    build package folder
    copy student file
    copy runtime files with retries
    write manifest with checksums
    zip package
    POST multipart archive with sha256
    if success:
        mark local submitted
        gui upload_ok
        close runtime
    else:
        gui upload_error
        allow retry
```

## Local IPC Algorithm

```text
parent:
    server = ThreadedIpcServer(role)
    env = server.start()
    env.update(server.child_env(child_role, transport))
    launch child with env and pipes

child:
    use_ws = should_use_ws_ipc()
    standalone = stdin_is_standalone() and not use_ws
    if use_ws:
        start ThreadedIpcClient
        if failed and no stdin: standalone = True
    if stdin_available: start stdin reader
    emit command by ipc first, stdout fallback second
```

## Idle Policy Implementation Notes

Server state must include stored rule `idle_policy`:

- `enabled`
- `severity`
- `warn_threshold_seconds`
- `critical_threshold_seconds`
- `auto_violation_pause`

Server current policy must emit rule:

- `rule_id`: `idle_policy`
- `source`: `idle_monitor`
- `type`: `idle_policy`

Tk and Qt policy windows must expose the same fields. Client incident engine consumes `warn_threshold_seconds` and `critical_threshold_seconds`. Critical idle incidents use severity `violation`; warning idle incidents use severity `warning`.

