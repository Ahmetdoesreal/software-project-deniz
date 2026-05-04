import asyncio
import json
import os
import shlex
import subprocess
import sys
import time
from threading import Thread

from aiohttp import web

from common.discovery import ServerAnnouncer
from common import events, protocol, security
from .state import EXAM_POLICY_FILE, PROCESS_BLACKLIST_FILE, PROCESS_DEFINITIONS_FILE, state
from . import session_state
from .settings_service import (
    apply_process_decision,
    build_process_database,
    get_settings_snapshot,
    update_exam_policy,
    update_process_blacklist,
    update_process_definitions,
    update_runtime_settings,
)


def _user_has_submission(user: dict) -> bool:
    return bool(user.get("submitted_at"))


def _user_needs_submission(user: dict) -> bool:
    return session_state.derive_state(user) == session_state.AWAITING_SUBMISSION


def _user_is_running(user: dict) -> bool:
    return session_state.running_timer(user)


def _remove_dead_clients(client_ids: list[str]):
    for client_id in client_ids:
        state.clients.pop(client_id, None)


def _gui_process():
    return state.get_gui_process()


def _protect_payload(client_data: dict, payload: str) -> str:
    return security.protect_wire_message(payload, client_data.get("security"))


def _queue_input(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue, value):
    try:
        loop.call_soon_threadsafe(queue.put_nowait, value)
    except RuntimeError:
        # The event loop is already shutting down.
        pass


def _queue_stdin_line(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
    try:
        for line in sys.stdin:
            _queue_input(loop, queue, line)
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        print(f"[CMD] Console input unavailable; continuing without stdin commands: {exc}")
    finally:
        _queue_input(loop, queue, None)


def _write_to_gui(payload: dict):
    gui_process = _gui_process()
    if not gui_process:
        return

    try:
        gui_process.stdin.write(json.dumps(payload) + "\n")
        gui_process.stdin.flush()
    except Exception as e:
        print(f"[GUI IPC] Warning: Failed to write to GUI: {e}")


def _push_gui_state(app: web.Application):
    exam_duration_sec = app["exam_duration"] * 60
    _write_to_gui(
        {
            "type": "state_update",
            "server": _build_server_info(app),
            "settings": get_settings_snapshot(state, app),
            "clients": _build_gui_clients(exam_duration_sec),
            "incidents": _build_gui_incidents(),
            "process_database": build_process_database(state),
        }
    )


def _launch_server_gui(loop: asyncio.AbstractEventLoop, app: web.Application) -> str:
    if _gui_process():
        print("[GUI] Server monitor UI is already open.")
        return "already_open"

    gui_module = app.get("gui_module", "server.gui")
    project_dir = app.get("project_dir")
    python_executable = app.get("python_executable", sys.executable)
    if not gui_module or not project_dir:
        print("[GUI] GUI module is not configured.")
        return "failed"
    gui_env = os.environ.copy()
    gui_env["PYTHONPATH"] = str(project_dir) + os.pathsep + gui_env.get("PYTHONPATH", "")
    gui_env["PYTHONUNBUFFERED"] = "1"

    gui_ui = str(app.get("gui_ui", "tk") or "tk")
    if gui_ui not in {"tk", "qt"}:
        gui_ui = "tk"

    try:
        gui_process = subprocess.Popen(
            [python_executable, "-m", str(gui_module), "--ui", gui_ui],
            cwd=str(project_dir),
            env=gui_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except Exception as exc:
        print(f"[GUI] Failed to launch gui: {exc}")
        return "failed"

    state.gui_process = gui_process
    Thread(target=_gui_reader_thread, args=(loop, app, gui_process), daemon=True).start()
    print("[GUI] Server monitor UI launched. Use /gui to reopen it if you close the window.")
    _push_gui_state(app)
    return "opened"


def _uuid_to_login_map() -> dict[str, str]:
    return {
        user["uuid"]: login_id
        for login_id, user in state.users_db.items()
        if user.get("uuid")
    }


def _remaining_seconds(exam_duration_sec: int, user: dict) -> int:
    extra_time_sec = int(user.get("extra_time_seconds", 0))
    time_spent_seconds = user.get("time_spent_seconds", 0)
    return max(0, exam_duration_sec + extra_time_sec - int(time_spent_seconds))


def _session_remaining_seconds(exam_duration_sec: int, user: dict) -> int:
    state_name = session_state.derive_state(user)
    if state_name in session_state.PAUSED_STATES or state_name == session_state.AWAITING_SUBMISSION:
        paused_remaining = int(user.get("paused_remaining_seconds", 0) or 0)
        return paused_remaining or _remaining_seconds(exam_duration_sec, user)
    return _remaining_seconds(exam_duration_sec, user)


def _session_reason(user: dict) -> str:
    return str(user.get("session_state_reason") or user.get("admin_pause_reason") or "")


def _exam_state(user: dict, remaining: int) -> str:
    if remaining <= 0 and session_state.derive_state(user) == session_state.RUNNING:
        return "Finished"
    return session_state.display_name(user)


def _status_label(is_connected: bool, exam_state: str) -> str:
    if exam_state in {
        "Banned",
        "Finished",
        "Submitted",
        "Awaiting Submission",
        "Admin Paused",
        "Disconnected Paused",
        "Violation Paused",
    }:
        return exam_state
    if is_connected:
        return exam_state
    return "Offline"


def _build_gui_clients(exam_duration_sec: int) -> list[dict]:
    clients = []
    for login_id, user in state.users_db.items():
        client_id = user["uuid"]
        client_connection = state.clients.get(client_id, {})
        is_connected = client_id in state.clients
        remaining = _session_remaining_seconds(exam_duration_sec, user)
        exam_state = _exam_state(user, remaining)
        session_name = session_state.derive_state(user)
        clients.append(
            {
                "uuid": client_id,
                "login_id": login_id,
                "status_label": _status_label(is_connected, exam_state),
                "connection_status": "Connected" if is_connected else "Disconnected",
                "exam_state": exam_state,
                "session_state": session_name,
                "session_state_reason": _session_reason(user),
                "resume_allowed": session_state.reconnect_resume_allowed(user, state.session_policy()),
                "blocking_incident_id": user.get("blocking_incident_id", ""),
                "blocking_rule_id": user.get("blocking_rule_id", ""),
                "exam_started": user.get("exam_started", False),
                "remaining": remaining,
                "time_spent_seconds": int(user.get("time_spent_seconds", 0)),
                "extra_time_seconds": int(user.get("extra_time_seconds", 0)),
                "banned": user.get("banned", False),
                "kick_count": int(user.get("kick_count", 0)),
                "blacklist_catch_count": int(user.get("blacklist_catch_count", 0)),
                "last_blacklist_match": list(user.get("last_blacklist_match", [])),
                "last_action": user.get("last_action", ""),
                "admin_paused": user.get("admin_paused", False),
                "admin_pause_reason": user.get("admin_pause_reason", ""),
                "paused_remaining_seconds": int(user.get("paused_remaining_seconds", 0)),
                "applied_policy_version": user.get("applied_policy_version", ""),
                "latest_incident_id": user.get("latest_incident_id", ""),
                "latest_incident_rule_id": user.get("latest_incident_rule_id", ""),
                "latest_incident_severity": user.get("latest_incident_severity", ""),
                "latest_incident_status": user.get("latest_incident_status", ""),
                "latest_incident_summary": user.get("latest_incident_summary", ""),
                "latest_incident_artifact_path": user.get("latest_incident_artifact_path", ""),
                "ip": client_connection.get("ip"),
                "computer_name": client_connection.get("computer_name") or user.get("computer_name", ""),
                "short_id": client_connection.get("short_id"),
                "exam_finished": user.get("exam_finished", False),
                "submitted_at": user.get("submitted_at", ""),
                "submission_name": user.get("submission_name", ""),
                "submission_path": user.get("submission_path", ""),
                "submission_size_bytes": int(user.get("submission_size_bytes", 0)),
            }
        )
    return clients


def _build_server_info(app: web.Application) -> dict:
    advertised_host = app["host"]
    if advertised_host in {"0.0.0.0", "::", ""}:
        advertised_host = ServerAnnouncer._get_local_ip()
    known_hosts = [str(host) for host in sorted(app.get("server_identity_hosts") or []) if str(host).strip()]
    if advertised_host and advertised_host not in known_hosts:
        known_hosts.insert(0, advertised_host)
    return {
        "server_id": app["server_id"],
        "host": advertised_host,
        "all_host_ips": known_hosts,
        "bind_host": app["host"],
        "port": app["port"],
        "broadcast_interval": app["broadcast_interval"],
        "announce_interval": app["announce_interval"],
        "exam_duration_minutes": app["exam_duration"],
        "exam_phase": app.get("exam_phase", "waiting"),
        "exam_start_enabled": app["exam_start_enabled"],
        "has_exam_files": app["exam_files"] is not None,
        "exam_files_path": app["exam_files"],
        "process_blacklist_count": len(state.process_blacklist),
        "process_definition_count": len(state.rule_config("process_definitions").get("definitions", [])),
        "process_blacklist_file": PROCESS_BLACKLIST_FILE,
        "process_blacklist_version": state.process_blacklist_version,
        "process_definitions_file": PROCESS_DEFINITIONS_FILE,
        "process_definitions_version": state.process_definitions_version,
        "policy_file": EXAM_POLICY_FILE,
        "policy_version": state.current_exam_policy().get("policy_version", ""),
        "operator_defaults": state.operator_defaults(),
        "remember_settings": state.session_policy().get("remember_settings", True),
        "incident_count": len(state.incidents),
        "active_incident_count": len(state.active_incidents),
    }


def _build_gui_incidents() -> list[dict]:
    incidents = []
    for incident in reversed(state.incidents):
        incident_id = str(incident.get("incident_id", "")).strip()
        active = bool(incident_id and incident_id in state.active_incidents)
        login_id = str(incident.get("login_id", "") or "")
        user = state.users_db.get(login_id, {})
        rule_id = str(incident.get("rule_id", "") or "")
        status = str(incident.get("status", "") or "")
        severity = str(incident.get("severity", "") or "")
        rule_config = state.rule_config(rule_id)
        blocking = incident_id and incident_id == str(user.get("blocking_incident_id", "") or "")
        auto_action_name = ""
        auto_action_state = "manual"
        if bool(rule_config.get("auto_violation_pause", False)) and severity.strip().lower() == "violation":
            auto_action_name = "auto_violation_pause"
            if blocking:
                auto_action_state = "applied"
            elif incident.get("blocking"):
                auto_action_state = "released"
            else:
                auto_action_state = "configured"
        incidents.append(
            {
                "incident_id": incident_id,
                "client_id": str(incident.get("client_id", "") or ""),
                "login_id": login_id,
                "status": status,
                "severity": severity,
                "rule_id": rule_id,
                "rule_name": str(incident.get("rule_name", "") or incident.get("rule_id", "")),
                "source": str(incident.get("source", "") or ""),
                "summary": str(incident.get("summary", "") or ""),
                "process_name": str(incident.get("process_name", "") or ""),
                "pid": int(incident.get("pid", 0) or 0),
                "artifact_path": str(incident.get("artifact_path", "") or ""),
                "policy_version": str(incident.get("policy_version", "") or ""),
                "event_at": str(
                    incident.get("server_received_at")
                    or incident.get("reported_at")
                    or incident.get("event_at")
                    or ""
                ),
                "active": active,
                "kill_available": (
                    int(incident.get("pid", 0) or 0) > 0
                    and bool(rule_config.get("allow_remote_kill", True))
                ),
                "session_state": session_state.derive_state(user) if user else "",
                "resume_allowed": session_state.reconnect_resume_allowed(user, state.session_policy()) if user else False,
                "blocking": blocking,
                "auto_action_name": auto_action_name,
                "auto_action_state": auto_action_state,
                "auto_action_state_label": auto_action_state.replace("_", " ").title(),
                "details": incident,
            }
        )
    return incidents


def _open_text_file(path: str) -> bool:
    target_path = os.path.abspath(path)

    try:
        subprocess.Popen(["notepad.exe", target_path])
        return True
    except Exception as exc:
        print(f"[CMD] Failed to open text file: {exc}")
        return False


async def _broadcast_process_blacklist() -> int:
    process_blacklist_config = state.rule_config("process_blacklist")
    payload = events.process_blacklist(
        state.process_blacklist,
        state.process_blacklist_version,
        list(process_blacklist_config.get("process_usernames", [])),
    )
    return await broadcast_to_all(payload)


async def _broadcast_exam_policy(update: bool = False) -> int:
    payload = state.current_exam_policy()
    message = events.policy_update(payload) if update else events.exam_policy(payload)
    return await broadcast_to_all(message)


def _session_state_message(user: dict, exam_duration_sec: int, *, reason: str = "") -> str:
    return events.session_state(
        session_state.derive_state(user),
        _session_remaining_seconds(exam_duration_sec, user),
        reason=reason or _session_reason(user),
        resume_allowed=session_state.reconnect_resume_allowed(user, state.session_policy()),
        policy_version=state.current_exam_policy().get("policy_version", ""),
        pause_source=session_state.pause_source(user),
    )


async def _sync_client_timer_state(client_id: str, app: web.Application, *, reason: str = ""):
    data = state.clients.get(client_id)
    if not data:
        return

    _, user = state.find_user_by_uuid(client_id)
    if not user:
        return

    exam_duration_sec = app["exam_duration"] * 60
    state_name = session_state.derive_state(user)
    remaining = _session_remaining_seconds(exam_duration_sec, user)
    await data["ws"].send_str(_protect_payload(data, _session_state_message(user, exam_duration_sec, reason=reason)))
    if state_name in session_state.PAUSED_STATES:
        await data["ws"].send_str(
            _protect_payload(data, events.pause_exam(
                remaining,
                source=session_state.pause_source(user),
                reason=reason or _session_reason(user),
            ))
        )
    else:
        await data["ws"].send_str(
            _protect_payload(data, events.resume_exam(
                remaining,
                source="admin",
                reason=reason or _session_reason(user),
            ))
        )
    await data["ws"].send_str(
        _protect_payload(data, events.sync_time(
            remaining,
            timer_state="paused" if state_name in session_state.PAUSED_STATES else "running",
            pause_source=session_state.pause_source(user),
            reason=reason or _session_reason(user),
        ))
    )


async def _handle_apply_blacklist():
    previous_version = state.process_blacklist_version
    previous_count = len(state.process_blacklist)
    state.load_process_blacklist()
    sent_count = await _broadcast_process_blacklist()
    await _broadcast_exam_policy(update=True)
    print(
        f"[CMD] Applied process blacklist from {PROCESS_BLACKLIST_FILE}. "
        f"{previous_count} -> {len(state.process_blacklist)} entrie(s), "
        f"version {previous_version} -> {state.process_blacklist_version}. "
        f"Updated {sent_count} connected client(s)."
    )


async def _handle_edit_blacklist():
    state.ensure_process_blacklist_file()
    if _open_text_file(PROCESS_BLACKLIST_FILE):
        print(f"[CMD] Opened process blacklist file: {os.path.abspath(PROCESS_BLACKLIST_FILE)}")


async def _handle_apply_policy():
    previous_version = state.current_exam_policy().get("policy_version", "")
    state.load_exam_policy()
    sent_count = await _broadcast_exam_policy(update=True)
    print(
        f"[CMD] Applied exam policy from {EXAM_POLICY_FILE}. "
        f"Version {previous_version} -> {state.current_exam_policy().get('policy_version', '')}. "
        f"Updated {sent_count} connected client(s)."
    )


async def _handle_edit_policy():
    state.ensure_exam_policy_file()
    if _open_text_file(EXAM_POLICY_FILE):
        print(f"[CMD] Opened exam policy file: {os.path.abspath(EXAM_POLICY_FILE)}")


async def _handle_apply_process_definitions():
    previous_version = state.current_exam_policy().get("policy_version", "")
    previous_definition_version = state.process_definitions_version
    previous_count = len(state.rule_config("process_definitions").get("definitions", []))
    state.load_process_definitions()
    sent_count = await _broadcast_exam_policy(update=True)
    print(
        f"[CMD] Applied process definitions from {PROCESS_DEFINITIONS_FILE}. "
        f"{previous_count} -> {len(state.rule_config('process_definitions').get('definitions', []))} definition(s), "
        f"definitions version {previous_definition_version} -> {state.process_definitions_version}, "
        f"policy {previous_version} -> {state.current_exam_policy().get('policy_version', '')}. "
        f"Updated {sent_count} connected client(s)."
    )


async def _handle_edit_process_definitions():
    state.ensure_process_definitions_file()
    if _open_text_file(PROCESS_DEFINITIONS_FILE):
        print(f"[CMD] Opened process definitions file: {os.path.abspath(PROCESS_DEFINITIONS_FILE)}")


async def _handle_export_settings(parts: list[str]):
    if len(parts) < 2:
        print("[CMD] Usage: /exportsettings <path>")
        return

    export_path = os.path.abspath(parts[1])
    os.makedirs(os.path.dirname(export_path) or ".", exist_ok=True)
    state.export_settings_bundle(export_path)
    print(f"[CMD] Exported settings bundle to {export_path}")


async def _handle_import_settings(parts: list[str]):
    if len(parts) < 2:
        print("[CMD] Usage: /importsettings <path>")
        return

    import_path = os.path.abspath(parts[1])
    if not os.path.exists(import_path):
        print(f"[CMD] Settings file does not exist: {import_path}")
        return

    previous_version = state.current_exam_policy().get("policy_version", "")
    state.import_settings_bundle(import_path)
    blacklist_sent = await _broadcast_process_blacklist()
    policy_sent = await _broadcast_exam_policy(update=True)
    print(
        f"[CMD] Imported settings from {import_path}. "
        f"Policy {previous_version} -> {state.current_exam_policy().get('policy_version', '')}. "
        f"Updated {max(blacklist_sent, policy_sent)} connected client(s)."
    )


async def _handle_save_settings_from_gui(request: dict, app: web.Application):
    errors: list[str] = []
    messages: list[str] = []
    changed_paths: list[str] = []
    policy_changed = False
    blacklist_changed = False
    definitions_changed = False

    try:
        if "runtime" in request:
            runtime_result = update_runtime_settings(app, request.get("runtime", {}), actor="gui")
            messages.append(runtime_result.message)
            changed_paths.extend(runtime_result.changed_paths)
            errors.extend(runtime_result.errors)
            if errors:
                _write_to_gui(
                    {
                        "type": "settings_result",
                        "ok": False,
                        "message": "Settings were not saved.",
                        "errors": errors,
                        "changed_paths": changed_paths,
                    }
                )
                _push_gui_state(app)
                return

        if "exam_policy" in request:
            policy_result = update_exam_policy(state, request.get("exam_policy", {}), actor="gui")
            messages.append(policy_result.message)
            changed_paths.extend(policy_result.changed_paths)
            errors.extend(policy_result.errors)
            policy_changed = bool(policy_result.changed)

        if "process_blacklist" in request:
            blacklist_payload = request.get("process_blacklist", {})
            if isinstance(blacklist_payload, dict):
                entries = blacklist_payload.get("entries", [])
            else:
                entries = blacklist_payload
            blacklist_result = update_process_blacklist(state, "replace", entries, actor="gui")
            messages.append(blacklist_result.message)
            changed_paths.extend(blacklist_result.changed_paths)
            errors.extend(blacklist_result.errors)
            blacklist_changed = bool(blacklist_result.changed)

        if "process_definitions" in request:
            definitions_payload = request.get("process_definitions", {})
            if isinstance(definitions_payload, dict):
                definitions = definitions_payload.get("entries", [])
            else:
                definitions = definitions_payload
            definitions_result = update_process_definitions(state, definitions, actor="gui")
            messages.append(definitions_result.message)
            changed_paths.extend(definitions_result.changed_paths)
            errors.extend(definitions_result.errors)
            definitions_changed = bool(definitions_result.changed)

        if errors:
            _write_to_gui(
                {
                    "type": "settings_result",
                    "ok": False,
                    "message": "Settings were not saved.",
                    "errors": errors,
                    "changed_paths": changed_paths,
                }
            )
            _push_gui_state(app)
            return

        policy_sent = 0
        blacklist_sent = 0
        if policy_changed or blacklist_changed or definitions_changed:
            blacklist_sent = await _broadcast_process_blacklist()
            policy_sent = await _broadcast_exam_policy(update=True)

        changed_count = len(set(changed_paths))
        if changed_count:
            message = (
                f"Saved {changed_count} setting path(s). "
                f"Updated {max(blacklist_sent, policy_sent)} connected client(s)."
            )
        else:
            message = "No settings changes."

        _write_to_gui(
            {
                "type": "settings_result",
                "ok": True,
                "message": message,
                "errors": [],
                "changed_paths": sorted(set(changed_paths)),
                "policy_version": state.current_exam_policy().get("policy_version", ""),
                "process_blacklist_version": state.process_blacklist_version,
                "process_definitions_version": state.process_definitions_version,
                "details": [msg for msg in messages if msg],
            }
        )
        print(f"[CMD] GUI settings saved. {message}")
        _push_gui_state(app)
    except Exception as exc:
        error = f"Failed to save GUI settings: {exc}"
        print(f"[CMD] {error}")
        _write_to_gui(
            {
                "type": "settings_result",
                "ok": False,
                "message": error,
                "errors": [error],
                "changed_paths": changed_paths,
            }
        )
        _push_gui_state(app)


async def _handle_set_remember_settings(parts: list[str]):
    if len(parts) < 2:
        print("[CMD] Usage: /remembersettings <on|off>")
        return

    value = parts[1].strip().lower()
    if value not in {"on", "off", "true", "false", "1", "0"}:
        print(f"[CMD] Invalid remember-settings value: {parts[1]}")
        return

    enabled = value in {"on", "true", "1"}
    state.exam_policy_config["session"]["remember_settings"] = enabled
    state.save_exam_policy()
    print(f"[CMD] Remember settings set to {'on' if enabled else 'off'}.")


def _print_connected_clients():
    if not state.clients:
        print("[CMD] No clients connected.")
        return

    print(f"[CMD] {len(state.clients)} client(s) connected:")
    for client_id, data in state.clients.items():
        print(f"       - UUID:  {client_id}")
        print(f"         Short: {data['short_id']}")
        print(f"         IP:    {data['ip']}")
        print()


def _print_exam_status(app: web.Application):
    exam_duration_sec = app["exam_duration"] * 60
    print("\n[CMD] --- LIVE EXAM STATUS ---")

    if not state.users_db:
        print("No registered users.")
        print("------------------------------\n")
        return

    for login_id, user in state.users_db.items():
        client_id = user.get("uuid", "-")
        exam_state = _exam_state(user, _session_remaining_seconds(exam_duration_sec, user))
        remaining = _session_remaining_seconds(exam_duration_sec, user)
        minutes, seconds = divmod(remaining, 60)
        print(
            f"User: {login_id:12} | State: {exam_state:7} | "
            f"Remaining: {minutes:02d}m {seconds:02d}s"
        )

    print("------------------------------\n")


async def broadcast_to_all(payload: str) -> int:
    """Send a payload to every connected client. Returns count sent."""
    dead = []
    sent = 0

    for client_id, data in list(state.clients.items()):
        try:
            await data["ws"].send_str(_protect_payload(data, payload))
            sent += 1
        except (ConnectionResetError, RuntimeError):
            dead.append(client_id)

    _remove_dead_clients(dead)
    return sent


async def send_to_client(target: str, payload: str) -> bool:
    """Send a payload to a specific client (by UUID, short ID, or IP)."""
    client_id, data = state.resolve_client(target)
    if not data:
        return False

    try:
        await data["ws"].send_str(_protect_payload(data, payload))
        return True
    except (ConnectionResetError, RuntimeError):
        _remove_dead_clients([client_id])
        return False


async def _broadcast_time_payload(payload: str) -> list[str]:
    dead = []
    for client_id, data in list(state.clients.items()):
        try:
            await data["ws"].send_str(_protect_payload(data, payload))
        except ConnectionResetError:
            dead.append(client_id)
    return dead


async def _sync_running_exams(
    app: web.Application,
    uuid_to_login: dict[str, str],
    elapsed: float,
) -> list[str]:
    dead = []
    exam_duration_sec = app["exam_duration"] * 60

    for client_id, data in list(state.clients.items()):
        login_id = uuid_to_login.get(client_id)
        if not login_id:
            continue

        user = state.users_db[login_id]
        current_state = session_state.derive_state(user)
        if current_state not in {session_state.RUNNING, *session_state.PAUSED_STATES}:
            continue

        if current_state in session_state.PAUSED_STATES:
            remaining = _session_remaining_seconds(exam_duration_sec, user)
        else:
            user["time_spent_seconds"] = user.get("time_spent_seconds", 0.0) + elapsed
            remaining = _remaining_seconds(exam_duration_sec, user)

        try:
            await data["ws"].send_str(
                _protect_payload(data, events.sync_time(
                    remaining,
                    timer_state="paused" if current_state in session_state.PAUSED_STATES else "running",
                    pause_source=session_state.pause_source(user),
                    reason=_session_reason(user),
                ))
            )
            if current_state == session_state.RUNNING and remaining <= 0:
                session_state.set_state(
                    user,
                    session_state.AWAITING_SUBMISSION,
                    reason="Time is up. Please upload your archive.",
                    remaining_seconds=0,
                    clear_blocking=True,
                )
                user["last_action"] = "Awaiting submission"
                print(f"[EXAM] Client {client_id} ran out of time!")
                await data["ws"].send_str(_protect_payload(data, _session_state_message(user, exam_duration_sec)))
                await data["ws"].send_str(
                    _protect_payload(data, events.finish_exam("Time is up. Please upload your archive."))
                )
        except ConnectionResetError:
            dead.append(client_id)

    return dead


async def time_broadcaster(app: web.Application):
    """Background task that sends the current time to clients and updates exam timers."""
    tick_interval = app["broadcast_interval"]
    exam_duration_sec = app["exam_duration"] * 60
    last_tick_time = time.perf_counter()
    save_counter_sec = 0.0

    try:
        while True:
            await asyncio.sleep(tick_interval)

            now = time.perf_counter()
            elapsed = now - last_tick_time
            last_tick_time = now

            if state.clients:
                dead = await _broadcast_time_payload(events.time_broadcast(protocol.now_iso()))
                dead.extend(await _sync_running_exams(app, _uuid_to_login_map(), elapsed))
                _remove_dead_clients(dead)

            save_counter_sec += elapsed
            if save_counter_sec >= 10.0:
                state.save_users()
                save_counter_sec = 0.0

            _push_gui_state(app)
    except asyncio.CancelledError:
        pass


async def _sync_client_remaining_time(target: str, app: web.Application):
    client_id, data = state.resolve_client(target)
    if not data:
        return

    await _sync_client_timer_state(client_id, app)


async def _handle_add_time(parts: list[str], app: web.Application):
    if len(parts) < 3:
        print("[CMD] Usage: /addtime <client_id|uuid|login_id> <minutes>")
        return

    target = parts[1]
    try:
        minutes = float(parts[2])
    except ValueError:
        print(f"[CMD] Invalid minutes value: {parts[2]}")
        return
    if minutes <= 0:
        print("[CMD] Minutes must be greater than 0.")
        return

    login_id, user = state.resolve_user(target)
    if not user:
        print(f"[CMD] User '{target}' not found.")
        return

    seconds_to_add = int(minutes * 60)
    user["extra_time_seconds"] = int(user.get("extra_time_seconds", 0)) + seconds_to_add
    state.save_users()

    client_id = user["uuid"]
    await _sync_client_remaining_time(client_id, app)
    print(
        f"[CMD] Added {minutes:g} minute(s) to {login_id} ({client_id}). "
        f"Extra time is now {int(user['extra_time_seconds'])} second(s)."
    )


async def _handle_pause_exam(parts: list[str], app: web.Application):
    if len(parts) < 2:
        print("[CMD] Usage: /pauseexam <client_id|uuid|login_id> [reason]")
        return

    target = parts[1]
    reason = " ".join(parts[2:]).strip() or "Paused by administrator."
    login_id, user = state.resolve_user(target)
    if not user:
        print(f"[CMD] User '{target}' not found.")
        return
    current_state = session_state.derive_state(user)
    if current_state != session_state.RUNNING:
        print(f"[CMD] User '{login_id}' is not running an exam.")
        return

    exam_duration_sec = app["exam_duration"] * 60
    remaining = _remaining_seconds(exam_duration_sec, user)
    session_state.set_state(
        user,
        session_state.ADMIN_PAUSED,
        reason=reason,
        remaining_seconds=remaining,
    )
    user["last_action"] = "Admin paused"
    state.save_users()
    await _sync_client_timer_state(user["uuid"], app, reason=reason)
    print(f"[CMD] Paused {login_id} ({user['uuid']}) at {remaining} second(s) remaining.")


async def _handle_resume_exam(parts: list[str], app: web.Application):
    if len(parts) < 2:
        print("[CMD] Usage: /resumeexam <client_id|uuid|login_id> [reason]")
        return

    target = parts[1]
    reason = " ".join(parts[2:]).strip() or "Resumed by administrator."
    login_id, user = state.resolve_user(target)
    if not user:
        print(f"[CMD] User '{target}' not found.")
        return
    current_state = session_state.derive_state(user)
    if current_state not in {session_state.ADMIN_PAUSED, session_state.DISCONNECTED_PAUSED}:
        print(f"[CMD] User '{login_id}' is not in a resumable paused state.")
        return

    session_state.set_state(
        user,
        session_state.RUNNING,
        reason=reason,
        remaining_seconds=_session_remaining_seconds(app["exam_duration"] * 60, user),
        clear_blocking=True,
    )
    user["last_action"] = "Admin resumed"
    state.save_users()
    await _sync_client_timer_state(user["uuid"], app, reason=reason)
    print(f"[CMD] Resumed {login_id} ({user['uuid']}).")


async def _handle_forgive_violation(parts: list[str], app: web.Application):
    if len(parts) < 2:
        print("[CMD] Usage: /forgiveviolation <client_id|uuid|login_id> [incident_id] [reason]")
        return

    target = parts[1]
    requested_incident_id = parts[2].strip() if len(parts) >= 3 else ""
    reason = " ".join(parts[3:]).strip() if len(parts) >= 4 else "Violation forgiven by administrator."
    login_id, user = state.resolve_user(target)
    if not user:
        print(f"[CMD] User '{target}' not found.")
        return

    current_state = session_state.derive_state(user)
    if current_state != session_state.VIOLATION_PAUSED:
        print(f"[CMD] User '{login_id}' is not violation-paused.")
        return

    blocking_incident_id = str(user.get("blocking_incident_id", "") or "")
    if requested_incident_id and blocking_incident_id and requested_incident_id != blocking_incident_id:
        print(
            f"[CMD] User '{login_id}' is blocked by incident {blocking_incident_id}, "
            f"not {requested_incident_id}."
        )
        return

    remaining = _session_remaining_seconds(app["exam_duration"] * 60, user)
    next_state = session_state.RUNNING if user["uuid"] in state.clients else session_state.DISCONNECTED_PAUSED
    session_state.set_state(
        user,
        next_state,
        reason=reason,
        remaining_seconds=remaining,
        clear_blocking=True,
    )
    user["violation_forgiven_at"] = protocol.now_iso()
    user["violation_forgiven_by"] = "admin"
    user["violation_forgiven_incident_id"] = blocking_incident_id or requested_incident_id
    user["last_action"] = "Violation forgiven"
    state.append_audit(
        {
            "at": protocol.now_iso(),
            "action": "forgive_violation",
            "login_id": login_id,
            "client_id": user["uuid"],
            "incident_id": blocking_incident_id or requested_incident_id,
            "reason": reason,
            "next_state": next_state,
        }
    )
    state.save_users()

    if user["uuid"] in state.clients:
        await _sync_client_timer_state(user["uuid"], app, reason=reason)

    print(
        f"[CMD] Forgave violation for {login_id} ({user['uuid']}). "
        f"State is now {session_state.display_name(user)}."
    )


async def _handle_kill_pid(parts: list[str], app: web.Application):
    if len(parts) < 3:
        print("[CMD] Usage: /killpid <client_id|uuid|login_id> <pid> [incident_id] [process_name]")
        return

    target = parts[1]
    login_id, user = state.resolve_user(target)
    if not user:
        print(f"[CMD] User '{target}' not found.")
        return

    try:
        pid = int(parts[2])
    except ValueError:
        print(f"[CMD] Invalid pid value: {parts[2]}")
        return

    incident_id = parts[3] if len(parts) >= 4 else ""
    process_name = " ".join(parts[4:]).strip() if len(parts) >= 5 else ""
    if incident_id:
        incident = state.active_incidents.get(incident_id)
        rule_id = str(incident.get("rule_id", "") or "") if incident else ""
        if rule_id and not state.rule_config(rule_id).get("allow_remote_kill", True):
            print(f"[CMD] Remote kill is disabled by policy for rule '{rule_id}'.")
            return
    if not await send_to_client(
        user["uuid"],
        events.kill_process(
            pid,
            incident_id=incident_id,
            process_name=process_name,
            reason="Requested by administrator.",
        ),
    ):
        print(f"[CMD] Could not reach client {login_id} ({user['uuid']}) to kill pid {pid}.")
        return

    user["last_action"] = f"Kill PID requested ({pid})"
    state.save_users()
    print(f"[CMD] Requested kill of pid {pid} on {login_id} ({user['uuid']}).")


async def _disconnect_client(target: str, reason: str) -> bool:
    client_id, data = state.resolve_client(target)
    if not data:
        return False

    try:
        await data["ws"].close(message=reason.encode("utf-8"))
    except Exception:
        pass
    finally:
        state.clients.pop(client_id, None)
    return True


async def _handle_start_exam_global(app: web.Application):
    if app.get("exam_phase") == "running":
        print("[CMD] Exam start is already enabled.")
        return
    if app.get("exam_phase") == "finished":
        print("[CMD] Exam has already been finished.")
        return

    app["exam_phase"] = "running"
    app["exam_start_enabled"] = True
    print("[CMD] Exam start is now enabled for all clients.")


async def _handle_finish_exam_global(app: web.Application):
    if app.get("exam_phase") == "finished":
        print("[CMD] Exam is already finished.")
        return
    if app.get("exam_phase") != "running":
        print("[CMD] Start the exam before finishing it.")
        return

    app["exam_phase"] = "finished"
    app["exam_start_enabled"] = False

    finished_count = 0
    connected_count = 0
    for login_id, user in state.users_db.items():
        client_id = user["uuid"]
        if _user_has_submission(user):
            continue

        session_state.set_state(
            user,
            session_state.AWAITING_SUBMISSION,
            reason="The server ended the exam. Please upload your archive.",
            remaining_seconds=_session_remaining_seconds(app["exam_duration"] * 60, user),
            clear_blocking=True,
        )
        user["last_action"] = "Awaiting submission"
        finished_count += 1
        data = state.clients.get(client_id)
        if not data:
            continue
        try:
            await data["ws"].send_str(_protect_payload(data, _session_state_message(user, app["exam_duration"] * 60)))
            await data["ws"].send_str(
                _protect_payload(data, events.finish_exam("The server ended the exam. Please upload your archive."))
            )
            connected_count += 1
        except (ConnectionResetError, RuntimeError):
            _remove_dead_clients([client_id])

        print(f"[EXAM] Finish requested for {login_id} ({client_id}).")

    state.save_users()
    print(
        f"[CMD] Finished the exam for {finished_count} user(s); "
        f"notified {connected_count} connected client(s)."
    )


async def _handle_kick(parts: list[str]):
    if len(parts) < 2:
        print("[CMD] Usage: /kick <client_id|uuid|login_id>")
        return

    target = parts[1]
    login_id, user = state.resolve_user(target)
    if not user:
        print(f"[CMD] User '{target}' not found.")
        return

    client_id = user["uuid"]
    if client_id not in state.clients:
        print(f"[CMD] User '{login_id}' is not currently connected.")
        return

    user["kick_count"] = int(user.get("kick_count", 0)) + 1
    user["last_action"] = "Kicked"
    state.save_users()
    await _disconnect_client(client_id, "kicked by server")
    print(f"[CMD] Kicked {login_id} ({client_id}).")


async def _handle_ban(parts: list[str]):
    if len(parts) < 2:
        print("[CMD] Usage: /ban <client_id|uuid|login_id>")
        return

    target = parts[1]
    login_id, user = state.resolve_user(target)
    if not user:
        print(f"[CMD] User '{target}' not found.")
        return

    session_state.set_state(user, session_state.BANNED, reason="Banned by administrator.")
    user["kick_count"] = int(user.get("kick_count", 0)) + 1
    user["last_action"] = "Banned"
    state.save_users()
    await _disconnect_client(user["uuid"], "banned by server")
    print(f"[CMD] Banned {login_id} ({user['uuid']}).")


async def _handle_unban(parts: list[str]):
    if len(parts) < 2:
        print("[CMD] Usage: /unban <client_id|uuid|login_id>")
        return

    target = parts[1]
    login_id, user = state.resolve_user(target)
    if not user:
        print(f"[CMD] User '{target}' not found.")
        return

    next_state = session_state.WAITING
    if _user_has_submission(user):
        next_state = session_state.SUBMITTED
    elif _user_needs_submission(user):
        next_state = session_state.AWAITING_SUBMISSION
    elif user.get("exam_started", False):
        next_state = session_state.DISCONNECTED_PAUSED if user["uuid"] not in state.clients else session_state.RUNNING
    session_state.set_state(user, next_state, reason="User unbanned.", clear_blocking=False)
    user["last_action"] = "Unbanned"
    state.save_users()
    print(f"[CMD] Unbanned {login_id} ({user['uuid']}).")


async def _handle_apply_process_decision(request: dict, app: web.Application):
    result = apply_process_decision(state, request, actor="admin_gui")
    if not result.get("ok"):
        print(f"[PROCESS] Decision failed: {result.get('message')}")
        _push_gui_state(app)
        return

    definition = result.get("definition", {})
    actions = definition.get("actions", {})
    history_by_login = {
        str(entry.get("login_id", "") or ""): entry
        for entry in result.get("matching_history", [])
        if str(entry.get("login_id", "") or "")
    }
    live_results = []

    if actions.get("kill_pid"):
        for student_state in result.get("action_states", []):
            kill_state = student_state.get("actions", {}).get("kill_pid", {})
            if kill_state.get("state") != "possible":
                continue
            client_id = str(student_state.get("client_id", "") or "")
            pid = int(student_state.get("pid", 0) or 0)
            if not client_id or pid <= 0:
                continue
            sent = await send_to_client(
                client_id,
                events.kill_process(
                    pid,
                    incident_id=str(student_state.get("incident_id", "") or ""),
                    process_name=str(student_state.get("process_name", "") or definition.get("process_name", "")),
                    reason="Requested by process policy decision.",
                ),
            )
            live_results.append(
                {
                    "login_id": student_state.get("login_id", ""),
                    "action": "kill_pid",
                    "state": "applied" if sent else "not_possible",
                    "reason": "requested" if sent else "disconnected",
                }
            )

    if actions.get("pause_exam"):
        for student_state in result.get("action_states", []):
            pause_state = student_state.get("actions", {}).get("pause_exam", {})
            if pause_state.get("state") != "possible":
                continue
            login_id = str(student_state.get("login_id", "") or "")
            user = state.users_db.get(login_id)
            if not user:
                continue
            remaining = _session_remaining_seconds(app["exam_duration"] * 60, user)
            session_state.set_state(
                user,
                session_state.ADMIN_PAUSED,
                reason="Paused by process policy decision.",
                remaining_seconds=remaining,
            )
            user["last_action"] = "Process decision pause"
            state.save_users()
            await _sync_client_timer_state(user["uuid"], app, reason="Paused by process policy decision.")
            live_results.append({"login_id": login_id, "action": "pause_exam", "state": "applied", "reason": "paused"})

    for login_id in result.get("banned_login_ids", []):
        user = state.users_db.get(login_id)
        if not user:
            continue
        await _disconnect_client(user["uuid"], "banned by process decision")
        live_results.append({"login_id": login_id, "action": "ban", "state": "applied", "reason": "disconnected"})

    if actions.get("kick") and not actions.get("ban"):
        for student_state in result.get("action_states", []):
            kick_state = student_state.get("actions", {}).get("kick", {})
            if kick_state.get("state") != "possible":
                continue
            login_id = str(student_state.get("login_id", "") or "")
            user = state.users_db.get(login_id)
            if not user:
                continue
            user["kick_count"] = int(user.get("kick_count", 0)) + 1
            user["last_action"] = "Process decision kick"
            state.save_users()
            await _disconnect_client(user["uuid"], "kicked by process decision")
            live_results.append({"login_id": login_id, "action": "kick", "state": "applied", "reason": "disconnected"})

    if result.get("saved_to_policy"):
        sent_count = await _broadcast_exam_policy(update=True)
        print(f"[PROCESS] Saved process decision policy and updated {sent_count} client(s).")

    print(
        f"[PROCESS] Applied decision for {definition.get('process_name') or definition.get('normalized_process_name')} "
        f"to {len(history_by_login)} historical user(s). Live actions: {live_results}"
    )
    _push_gui_state(app)


async def handle_admin_command(line: str, app: web.Application):
    """Common handler for administrative commands from CLI or GUI."""
    command_line = line.strip()
    if not command_line:
        return

    print(f"[DEBUG] Received command: '{command_line}'")
    try:
        parts = shlex.split(command_line)
    except ValueError as exc:
        print(f"[CMD] Failed to parse command: {exc}")
        return
    if not parts:
        return

    command = parts[0].lower()
    if not command.startswith("/"):
        print(f"[CMD] Invalid command format: '{command_line}'. Commands must start with /")
        return

    if command == "/clients":
        _print_connected_clients()
        return

    if command == "/savescreen":
        if len(parts) < 2:
            print("[CMD] Usage: /savescreen <client_id>  or  /savescreen all")
            return

        target = parts[1]
        if target.lower() == "all":
            count = await broadcast_to_all(events.savescreen(source="admin_cli"))
            print(f"[CMD] Sent SAVESCREEN to {count} client(s)")
            return

        if await send_to_client(target, events.savescreen(source="admin_cli")):
            print(f"[CMD] Sent SAVESCREEN to client {target}")
            return

        print(f"[CMD] Client '{target}' not found (tried UUID, short ID, IP).")
        print("      Type /clients to list available targets.")
        return

    if command == "/exam":
        _print_exam_status(app)
        return

    if command == "/addtime":
        await _handle_add_time(parts, app)
        return

    if command == "/pauseexam":
        await _handle_pause_exam(parts, app)
        return

    if command == "/resumeexam":
        await _handle_resume_exam(parts, app)
        return

    if command == "/killpid":
        await _handle_kill_pid(parts, app)
        return

    if command == "/startexam":
        await _handle_start_exam_global(app)
        return

    if command == "/finishexam":
        await _handle_finish_exam_global(app)
        return

    if command == "/gui":
        launch_result = _launch_server_gui(asyncio.get_running_loop(), app)
        if launch_result in {"opened", "already_open"}:
            return
        print("[GUI] Server monitor UI could not be opened.")
        return

    if command == "/editblacklist":
        await _handle_edit_blacklist()
        return

    if command == "/applyblacklist":
        await _handle_apply_blacklist()
        return

    if command == "/editpolicy":
        await _handle_edit_policy()
        return

    if command == "/applypolicy":
        await _handle_apply_policy()
        return

    if command == "/editdefinitions":
        await _handle_edit_process_definitions()
        return

    if command == "/applydefinitions":
        await _handle_apply_process_definitions()
        return

    if command == "/exportsettings":
        await _handle_export_settings(parts)
        return

    if command == "/importsettings":
        await _handle_import_settings(parts)
        return

    if command == "/remembersettings":
        await _handle_set_remember_settings(parts)
        return

    if command == "/kick":
        await _handle_kick(parts)
        return

    if command == "/ban":
        await _handle_ban(parts)
        return

    if command == "/unban":
        await _handle_unban(parts)
        return

    if command == "/forgiveviolation":
        await _handle_forgive_violation(parts, app)
        return

    if command == "/help":
        print("  /clients              - List connected clients")
        print("  /savescreen <id>      - Save replay on a specific client")
        print("  /savescreen all       - Save replay on ALL clients")
        print("  /addtime <id> <min>   - Add time to a specific user/client")
        print("  /pauseexam <id>       - Pause a specific user's timer")
        print("  /resumeexam <id>      - Resume a specific user's timer")
        print("  /killpid <id> <pid>   - Ask a client to kill a specific process id")
        print("  /startexam            - Enable exam start for all clients")
        print("  /finishexam           - Finish the exam for all started clients")
        print("  /gui                  - Open or reopen the server monitor UI")
        print("  /editblacklist        - Open the server process blacklist file for editing")
        print("  /applyblacklist       - Reload and broadcast the process blacklist")
        print("  /editpolicy           - Open the exam policy file for editing")
        print("  /applypolicy          - Reload and broadcast the exam policy")
        print("  /editdefinitions      - Open the process definitions file for editing")
        print("  /applydefinitions     - Reload and broadcast process definitions")
        print("  /exportsettings <p>   - Export blacklist + policy settings bundle")
        print("  /importsettings <p>   - Import blacklist + policy settings bundle")
        print("  /remembersettings on|off - Toggle remembered policy settings")
        print("  /kick <id>            - Disconnect a specific client")
        print("  /ban <id>             - Ban and disconnect a specific user")
        print("  /unban <id>           - Remove a user's ban")
        print("  /forgiveviolation <id> [incident] - Clear a violation hold")
        print("  /exam                 - Show overall exam status")
        print("  /help                 - Show this help")
        return

    print(f"[CMD] Unknown command: {command}  (type /help)")


def _dispatch_gui_request(loop, app: web.Application, request: dict):
    message_type = request.get("type")
    command = request.get("cmd")
    client_id = request.get("uuid")

    if message_type == "console_command":
        command_line = request.get("command")
        if command_line:
            asyncio.run_coroutine_threadsafe(handle_admin_command(command_line, app), loop)
        return

    if command == "savescreen" and client_id in state.clients:
        data = state.clients[client_id]
        asyncio.run_coroutine_threadsafe(
            data["ws"].send_str(_protect_payload(data, events.savescreen(source="admin_gui"))),
            loop,
        )
        print(f"\n[GUI->WS] Sent savescreen to {client_id}")
        return

    if command == "get_processes" and client_id in state.clients:
        data = state.clients[client_id]
        asyncio.run_coroutine_threadsafe(
            data["ws"].send_str(_protect_payload(data, events.get_processes())),
            loop,
        )
        print(f"\n[GUI->WS] Sent get_processes to {client_id}")
        return

    if command == "start_exam_global":
        asyncio.run_coroutine_threadsafe(
            handle_admin_command("/startexam", app),
            loop,
        )
        return

    if command == "edit_blacklist":
        asyncio.run_coroutine_threadsafe(
            handle_admin_command("/editblacklist", app),
            loop,
        )
        return

    if command == "apply_blacklist":
        asyncio.run_coroutine_threadsafe(
            handle_admin_command("/applyblacklist", app),
            loop,
        )
        return

    if command == "edit_policy":
        asyncio.run_coroutine_threadsafe(
            handle_admin_command("/editpolicy", app),
            loop,
        )
        return

    if command == "apply_policy":
        asyncio.run_coroutine_threadsafe(
            handle_admin_command("/applypolicy", app),
            loop,
        )
        return

    if command == "edit_process_definitions":
        asyncio.run_coroutine_threadsafe(
            handle_admin_command("/editdefinitions", app),
            loop,
        )
        return

    if command == "apply_process_definitions":
        asyncio.run_coroutine_threadsafe(
            handle_admin_command("/applydefinitions", app),
            loop,
        )
        return

    if command == "save_settings":
        asyncio.run_coroutine_threadsafe(
            _handle_save_settings_from_gui(request, app),
            loop,
        )
        return

    if command == "apply_process_decision":
        asyncio.run_coroutine_threadsafe(
            _handle_apply_process_decision(request, app),
            loop,
        )
        return

    if command == "export_settings":
        export_path = str(request.get("path", "") or "").strip()
        if export_path:
            asyncio.run_coroutine_threadsafe(
                handle_admin_command(f"/exportsettings {shlex.quote(export_path)}", app),
                loop,
            )
        return

    if command == "import_settings":
        import_path = str(request.get("path", "") or "").strip()
        if import_path:
            asyncio.run_coroutine_threadsafe(
                handle_admin_command(f"/importsettings {shlex.quote(import_path)}", app),
                loop,
            )
        return

    if command == "set_remember_settings":
        remember = "on" if bool(request.get("remember", False)) else "off"
        asyncio.run_coroutine_threadsafe(
            handle_admin_command(f"/remembersettings {remember}", app),
            loop,
        )
        return

    if command == "finish_exam_global":
        asyncio.run_coroutine_threadsafe(
            handle_admin_command("/finishexam", app),
            loop,
        )
        return

    if command == "kick":
        asyncio.run_coroutine_threadsafe(
            handle_admin_command(f"/kick {client_id}", app),
            loop,
        )
        return

    if command == "ban":
        asyncio.run_coroutine_threadsafe(
            handle_admin_command(f"/ban {client_id}", app),
            loop,
        )
        return

    if command == "unban":
        asyncio.run_coroutine_threadsafe(
            handle_admin_command(f"/unban {client_id}", app),
            loop,
        )
        return

    if command == "pause_exam":
        asyncio.run_coroutine_threadsafe(
            handle_admin_command(
                f"/pauseexam {client_id} {request.get('reason', 'Paused by administrator.')}",
                app,
            ),
            loop,
        )
        return

    if command == "resume_exam":
        asyncio.run_coroutine_threadsafe(
            handle_admin_command(
                f"/resumeexam {client_id} {request.get('reason', 'Resumed by administrator.')}",
                app,
            ),
            loop,
        )
        return

    if command == "forgive_violation":
        incident_id = str(request.get("incident_id", "") or "").strip()
        command_line = f"/forgiveviolation {client_id}"
        if incident_id:
            command_line += f" {incident_id}"
        command_line += " 'Violation forgiven by administrator.'"
        asyncio.run_coroutine_threadsafe(
            handle_admin_command(command_line, app),
            loop,
        )
        return

    if command == "kill_pid":
        pid = int(request.get("pid", 0) or 0)
        if pid <= 0:
            return
        incident_id = str(request.get("incident_id", "") or "")
        process_name = str(request.get("process_name", "") or "")
        command_line = f"/killpid {client_id} {pid}"
        if incident_id:
            command_line += f" {incident_id}"
        if process_name:
            command_line += f" {process_name}"
        asyncio.run_coroutine_threadsafe(
            handle_admin_command(command_line, app),
            loop,
        )
        return


def _gui_reader_thread(loop, app, gui_process):
    """Read stdout from the Tkinter GUI and forward actions into the event loop."""
    try:
        for line in iter(gui_process.stdout.readline, ""):
            line = line.strip()
            if not line:
                continue
            try:
                _dispatch_gui_request(loop, app, json.loads(line))
            except Exception:
                pass
    finally:
        try:
            gui_process.stdout.close()
        except Exception:
            pass
        if state.gui_process is gui_process:
            state.gui_process = None
            print("[GUI] Server monitor UI closed. Type /gui to reopen it.")


async def console_reader(app: web.Application):
    """Read stdin for operator commands."""
    loop = asyncio.get_event_loop()
    input_queue = asyncio.Queue()
    stdin_thread = Thread(
        target=_queue_stdin_line,
        args=(loop, input_queue),
        daemon=True,
    )
    stdin_thread.start()

    gui_process = _gui_process()
    if gui_process:
        thread = Thread(target=_gui_reader_thread, args=(loop, app, gui_process), daemon=True)
        thread.start()

    try:
        while True:
            line = await input_queue.get()
            if line is None:
                break
            await handle_admin_command(line, app)
    except asyncio.CancelledError:
        pass
