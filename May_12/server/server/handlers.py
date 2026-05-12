import json
import hashlib
import os
import tarfile
import time
import uuid
import zipfile
from pathlib import Path
from aiohttp import web, WSMsgType

from common import protocol, events, security
from common.text_safety import normalize_display_text, safe_console_text, sanitize_window_title
from common.process_definitions import PROCESS_DEFINITIONS_RULE_ID, normalize_actions, process_name_matches_any
from .state import state
from .submissions import build_artifact_path, build_submission_path, safe_relative_path
from . import session_state
from . import ip_guard
from . import auth_validation


def _json_error(message: str, status: int, code: str = "ERROR") -> web.Response:
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps({"error": message, "code": code}),
    )


def _auth_bypass_until(request: web.Request, name: str) -> float:
    bypass = request.app.get("auth_bypass") or {}
    try:
        return float(bypass.get(f"{name}_until", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _auth_bypass_active(request: web.Request, name: str) -> bool:
    return _auth_bypass_until(request, name) > time.time()


def _iso_from_epoch(epoch_seconds: float) -> str:
    if epoch_seconds <= time.time():
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch_seconds))


def _safe_close_message(reason: str, max_bytes: int = 120) -> bytes:
    # WebSocket close frame allows roughly 123 bytes of reason payload.
    # Trim by character so the trailing UTF-8 sequence stays valid.
    text = reason or ""
    encoded = text.encode("utf-8", errors="replace")
    while len(encoded) > max_bytes and text:
        text = text[:-1]
        encoded = text.encode("utf-8", errors="replace")
    return encoded


def _validate_login_payload(data: dict) -> tuple[str | None, str | None]:
    login_id = data.get("login_id")
    password = data.get("password")
    return login_id, password


def _relay_client_message_to_gui(client_id: str, message: dict):
    gui_process = state.get_gui_process()
    if not gui_process:
        return

    try:
        payload = json.dumps(
            {"type": "client_message", "uuid": client_id, "text": message}
        )
        gui_process.stdin.write(payload + "\n")
        gui_process.stdin.flush()
    except Exception:
        pass


def _relay_text_to_gui(client_id: str, text: str):
    _relay_client_message_to_gui(client_id, text)


def _protect_payload(client_id: str, payload: str) -> str:
    client_data = state.clients.get(client_id, {})
    return security.protect_wire_message(payload, client_data.get("security"))


def _register_new_user(login_id: str) -> web.Response:
    new_uuid = str(uuid.uuid4())
    state.users_db[login_id] = {
        "uuid": new_uuid,
        "time_spent_seconds": 0,
        "exam_started": False,
        "exam_finished": False,
        "extra_time_seconds": 0,
        "banned": False,
        "kick_count": 0,
        "last_action": "",
    }
    state.ensure_user_defaults(state.users_db[login_id])
    state.save_users()
    print(f"[+] New valid user registered: {login_id} -> {new_uuid}")
    return web.json_response({"status": "ok", "uuid": new_uuid})


def _remaining_seconds(request: web.Request, user: dict) -> int:
    exam_duration_sec = request.app["exam_duration"] * 60
    extra_time_sec = int(user.get("extra_time_seconds", 0))
    time_spent_seconds = user.get("time_spent_seconds", 0)
    return max(0, exam_duration_sec + extra_time_sec - int(time_spent_seconds))


def _session_remaining_seconds(request: web.Request, user: dict) -> int:
    state_name = session_state.derive_state(user)
    if state_name in session_state.PAUSED_STATES or state_name == session_state.AWAITING_SUBMISSION:
        paused_remaining = int(user.get("paused_remaining_seconds", 0) or 0)
        return paused_remaining or _remaining_seconds(request, user)
    return _remaining_seconds(request, user)


def _session_reason(user: dict) -> str:
    return str(
        user.get("session_state_reason")
        or user.get("admin_pause_reason")
        or ""
    )


def _session_state_payload(request: web.Request, user: dict, *, reason: str = "") -> str:
    return events.session_state(
        session_state.derive_state(user),
        _session_remaining_seconds(request, user),
        reason=reason or _session_reason(user),
        resume_allowed=session_state.reconnect_resume_allowed(user, state.session_policy()),
        policy_version=state.current_exam_policy().get("policy_version", ""),
        pause_source=session_state.pause_source(user),
    )


def _sync_time_payload(request: web.Request, user: dict, *, reason: str = "") -> str:
    state_name = session_state.derive_state(user)
    remaining = _session_remaining_seconds(request, user)
    timer_state = "paused" if state_name in session_state.PAUSED_STATES else "running"
    pause_source = session_state.pause_source(user)
    return events.sync_time(
        remaining,
        timer_state=timer_state,
        pause_source=pause_source,
        reason=reason or _session_reason(user),
    )


def _configured_process_actions(incident: dict) -> dict:
    actions = incident.get("configured_actions")
    if not isinstance(actions, dict):
        matched = incident.get("matched_definition", {})
        actions = matched.get("actions", {}) if isinstance(matched, dict) else {}
    if not any(normalize_actions(actions).values()):
        matched = incident.get("matched_incident_rule", {})
        actions = matched.get("actions", {}) if isinstance(matched, dict) else {}
    return normalize_actions(actions)


async def _apply_configured_process_actions(
    ws: web.WebSocketResponse,
    request: web.Request,
    client_id: str,
    login_id: str,
    user: dict,
    incident: dict,
) -> list[dict]:
    actions = _configured_process_actions(incident)
    if not any(actions.values()):
        return []

    results: list[dict] = []
    reason = f"Incident policy decision: {incident.get('process_name') or incident.get('rule_id')}"
    pid = int(incident.get("pid", 0) or 0)
    process_name = str(incident.get("process_name", "") or "")

    if actions.get("kill_pid"):
        if pid > 0:
            await ws.send_str(
                _protect_payload(
                    client_id,
                    events.kill_process(
                        pid,
                        incident_id=str(incident.get("incident_id", "") or ""),
                        process_name=process_name,
                        reason=reason,
                    ),
                )
            )
            results.append({"action": "kill_pid", "state": "applied", "reason": "requested"})
        else:
            results.append({"action": "kill_pid", "state": "not_possible", "reason": "no live PID"})

    if actions.get("pause_exam"):
        if session_state.derive_state(user) == session_state.RUNNING:
            remaining = _session_remaining_seconds(request, user)
            session_state.set_state(
                user,
                session_state.ADMIN_PAUSED,
                reason=reason,
                remaining_seconds=remaining,
            )
            await ws.send_str(_protect_payload(client_id, _session_state_payload(request, user, reason=reason)))
            await ws.send_str(
                _protect_payload(
                    client_id,
                    events.pause_exam(remaining, source="admin", reason=reason),
                )
            )
            results.append({"action": "pause_exam", "state": "applied", "reason": "paused"})
        else:
            results.append({"action": "pause_exam", "state": "not_possible", "reason": "exam not running"})

    if actions.get("ban"):
        if session_state.derive_state(user) == session_state.BANNED or user.get("banned"):
            results.append({"action": "ban", "state": "applied", "reason": "already banned"})
        else:
            session_state.set_state(user, session_state.BANNED, reason=reason)
            user["kick_count"] = int(user.get("kick_count", 0)) + 1
            user["last_action"] = "Process policy ban"
            results.append({"action": "ban", "state": "applied", "reason": "banned"})

    if actions.get("kick") and not actions.get("ban"):
        user["kick_count"] = int(user.get("kick_count", 0)) + 1
        user["last_action"] = "Process policy kick"
        results.append({"action": "kick", "state": "applied", "reason": "disconnecting"})

    if results:
        state.save_users()

    if actions.get("ban") or actions.get("kick"):
        close_reason = reason if actions.get("ban") else "kicked by process policy"
        try:
            await ws.close(message=_safe_close_message(close_reason))
        except Exception:
            pass
        state.clients.pop(client_id, None)

    print(f"[PROCESS] Applied configured process action(s) for {login_id}: {results}")
    return results


def _client_ip(request: web.Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    transport = request.transport
    if transport:
        peername = transport.get_extra_info("peername")
        if isinstance(peername, (tuple, list)) and peername:
            return str(peername[0])

    return request.remote or "unknown"


def _user_has_submission(user: dict) -> bool:
    return bool(user.get("submitted_at"))


def _user_needs_submission(user: dict) -> bool:
    return session_state.derive_state(user) == session_state.AWAITING_SUBMISSION


def _login_block_reason(request: web.Request, user: dict | None) -> str | None:
    if user and _user_has_submission(user):
        return "Submission already received for this user."

    if request.app.get("exam_phase") != "finished":
        return None

    if not user:
        return "Exam has already finished."
    if not user.get("exam_started", False):
        return "Exam has already finished."
    return None


def _update_user_incident_summary(user: dict, incident: dict):
    user["latest_incident_id"] = str(incident.get("incident_id", "") or "")
    user["latest_incident_rule_id"] = str(incident.get("rule_id", "") or "")
    user["latest_incident_severity"] = str(incident.get("severity", "") or "")
    user["latest_incident_status"] = str(incident.get("status", "") or "")
    user["latest_incident_summary"] = str(incident.get("summary", "") or "")
    user["latest_incident_artifact_path"] = str(incident.get("artifact_path", "") or "")


def _is_supported_archive(archive_path: Path) -> bool:
    return zipfile.is_zipfile(archive_path) or tarfile.is_tarfile(archive_path)


def _remove_file_if_present(path: Path):
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checksum_matches(expected_checksum: str | None, path: Path) -> bool:
    if not expected_checksum:
        return False
    return _file_sha256(path) == expected_checksum


async def _save_multipart_file(
    file_part,
    destination: Path,
    *,
    max_bytes: int,
) -> tuple[int, Exception | None]:
    bytes_written = 0
    try:
        with destination.open("wb") as output:
            while True:
                chunk = await file_part.read_chunk()
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise ValueError(f"upload exceeds limit of {max_bytes} bytes")
                output.write(chunk)
        return bytes_written, None
    except Exception as exc:
        _remove_file_if_present(destination)
        return 0, exc


async def _read_optional_field(reader, expected_name: str) -> str:
    part = await reader.next()
    if part is None or part.name != expected_name:
        return ""
    return await part.text()


async def _read_remaining_text_fields(reader) -> dict[str, str]:
    fields: dict[str, str] = {}
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.filename:
            # Unexpected extra file field; drain and ignore.
            while True:
                chunk = await part.read_chunk()
                if not chunk:
                    break
            continue
        fields[part.name] = await part.text()
    return fields


async def _find_file_part(reader, expected_name: str) -> tuple[object | None, dict[str, str]]:
    """Find a multipart file field regardless of part ordering."""
    pre_fields: dict[str, str] = {}
    while True:
        part = await reader.next()
        if part is None:
            return None, pre_fields
        if part.name == expected_name and part.filename:
            return part, pre_fields
        if part.filename:
            # Unexpected file field; drain and keep scanning.
            while True:
                chunk = await part.read_chunk()
                if not chunk:
                    break
            continue
        pre_fields[part.name] = await part.text()


async def _handle_ping_event(ws: web.WebSocketResponse, client_id: str, data: dict):
    await ws.send_str(_protect_payload(client_id, events.echo(data, protocol.now_iso())))
    short_id = client_id[:8]
    print(f"[{short_id}] PING: {data}")
    _relay_client_message_to_gui(client_id, data)


def _handle_client_info(client_id: str, data: dict):
    computer_name = str(data.get("computer_name", "")).strip()
    exam_folder_path = str(data.get("exam_folder_path", "") or "").strip()
    exam_files_zip_path = str(data.get("exam_files_zip_path", "") or "").strip()

    client_data = state.clients.get(client_id)
    if client_data is not None:
        if computer_name:
            client_data["computer_name"] = computer_name
        if exam_folder_path:
            client_data["exam_folder_path"] = exam_folder_path
        if exam_files_zip_path:
            client_data["exam_files_zip_path"] = exam_files_zip_path

    _, user = state.find_user_by_uuid(client_id)
    if user is not None:
        if computer_name:
            user["computer_name"] = computer_name
        if exam_folder_path:
            user["exam_folder_path"] = exam_folder_path
        if exam_files_zip_path:
            user["exam_files_zip_path"] = exam_files_zip_path
        state.save_users()


async def _handle_process_catch_event(
    ws: web.WebSocketResponse,
    client_id: str,
    data: dict,
):
    matches = data.get("matches", [])
    if not isinstance(matches, list):
        await ws.send_str(_protect_payload(client_id, events.error("Invalid process catch payload.")))
        return

    login_id, user = state.find_user_by_uuid(client_id)
    if not user:
        return

    blacklist_names = [str(entry or "").strip().lower() for entry in state.process_blacklist if str(entry or "").strip()]
    cleaned_matches = []
    seen_match_keys = set()
    for match in matches:
        if not isinstance(match, dict):
            continue
        pid = int(match.get("pid", 0) or 0)
        name = str(match.get("name", "")).strip()
        if not name:
            continue
        normalized_name = Path(name).name.lower()
        if not process_name_matches_any(normalized_name, blacklist_names):
            continue
        match_key = (pid, normalized_name)
        if match_key in seen_match_keys:
            continue
        seen_match_keys.add(match_key)
        cleaned_matches.append({"pid": pid, "name": name})
        if len(cleaned_matches) >= 50:
            break

    if not cleaned_matches:
        return

    user["blacklist_catch_count"] = int(user.get("blacklist_catch_count", 0)) + len(cleaned_matches)
    user["last_blacklist_match"] = [match["name"] for match in cleaned_matches]
    user["last_action"] = "Blacklist catch"
    state.save_users()

    match_text = ", ".join(f"{match['name']} (pid {match['pid']})" for match in cleaned_matches)
    version = str(data.get("blacklist_version", "0"))
    print(f"[PROCESS] Blacklist catch from {login_id} ({client_id}): {match_text} [v{version}]")
    _relay_text_to_gui(client_id, f"[BLACKLIST] {match_text} [v{version}]")


async def _handle_policy_applied_event(
    ws: web.WebSocketResponse,
    client_id: str,
    data: dict,
):
    _, user = state.find_user_by_uuid(client_id)
    if not user:
        return

    policy_version = str(data.get("policy_version", "")).strip()
    ok = bool(data.get("ok", False))
    reason = str(data.get("reason", "")).strip()
    user["applied_policy_version"] = policy_version if ok else user.get("applied_policy_version", "")
    user["last_action"] = f"Policy {'applied' if ok else 'rejected'}"
    state.save_users()
    if ok:
        print(f"[POLICY] Client {client_id} applied policy {policy_version}.")
    else:
        await ws.send_str(_protect_payload(client_id, events.error(f"Policy rejected by client: {reason or 'unknown reason'}")))
        print(f"[POLICY] Client {client_id} rejected policy {policy_version}: {reason or 'unknown reason'}")


async def _handle_client_monitor_event(
    ws: web.WebSocketResponse,
    client_id: str,
    data: dict,
):
    _ = ws
    login_id, user = state.find_user_by_uuid(client_id)
    if not user:
        return

    source = str(data.get("source", "") or "").strip()
    event_type = str(data.get("event_type", "") or "").strip()
    severity = str(data.get("severity", "info") or "info").strip().lower()
    timestamp = str(data.get("timestamp", "") or "").strip() or protocol.now_iso()
    window = data.get("window", {}) if isinstance(data.get("window"), dict) else {}

    if source != "focused_window":
        return

    process_name = normalize_display_text(window.get("process_name", "") or "")
    window_title = sanitize_window_title(window.get("window_title", "") or "")
    focus_signature = f"{process_name}|{window_title}"

    client_data = state.clients.get(client_id, {})
    if client_data.get("_last_focus_signature") != focus_signature:
        client_data["_last_focus_signature"] = focus_signature
        if process_name or window_title:
            _relay_text_to_gui(
                client_id,
                safe_console_text(
                    f"[FOCUS] {event_type or 'status'} {severity}: {process_name or '-'} / {window_title or '-'}"
                ),
            )

    user["last_focus_event_at"] = timestamp
    user["last_focus_event_type"] = event_type or "focused_window_status"
    user["last_focus_severity"] = severity
    user["last_focus_process"] = process_name
    user["last_focus_window"] = window_title


async def _handle_incident_report_event(
    ws: web.WebSocketResponse,
    request: web.Request,
    client_id: str,
    data: dict,
):
    login_id, user = state.find_user_by_uuid(client_id)
    if not user:
        await ws.send_str(_protect_payload(client_id, events.error("Unknown client for incident report.")))
        return

    incident_id = str(data.get("incident_id", "")).strip()
    rule_id = str(data.get("rule_id", "")).strip()
    status = str(data.get("status", "")).strip()
    if not incident_id or not rule_id or not status:
        await ws.send_str(_protect_payload(client_id, events.error("Incident report requires incident_id, rule_id, and status.")))
        return

    incident = dict(data)
    incident["client_id"] = client_id
    incident["login_id"] = login_id
    incident["server_received_at"] = protocol.now_iso()
    incident["incident_id"] = incident_id
    incident["rule_id"] = rule_id
    incident["status"] = status

    should_violation_pause = (
        status == "opened"
        and str(incident.get("severity", "")).strip().lower() == "violation"
        and bool(state.rule_config(rule_id).get("auto_violation_pause", False))
    )
    if should_violation_pause:
        remaining = _session_remaining_seconds(request, user)
        session_state.set_state(
            user,
            session_state.VIOLATION_PAUSED,
            reason=str(incident.get("summary", "") or rule_id),
            remaining_seconds=remaining,
            blocking_incident_id=incident_id,
            blocking_rule_id=rule_id,
        )
        incident["blocking"] = True

    state.append_incident(incident)

    user["last_action"] = (
        f"Violation paused: {rule_id}" if should_violation_pause else f"Incident {status}: {rule_id}"
    )
    if rule_id == "process_blacklist" and incident.get("process_name"):
        user["blacklist_catch_count"] = int(user.get("blacklist_catch_count", 0)) + (1 if status == "opened" else 0)
        user["last_blacklist_match"] = [str(incident.get("process_name"))]
    _update_user_incident_summary(user, incident)
    state.save_users()

    if status == "opened":
        action_results = await _apply_configured_process_actions(ws, request, client_id, login_id, user, incident)
        if action_results:
            incident["auto_action_results"] = action_results
            incident["process_auto_action_results"] = action_results
            state.save_incidents()

    summary = normalize_display_text(incident.get("summary", "") or rule_id)
    print(safe_console_text(f"[INCIDENT] {login_id} ({client_id}) {status} {rule_id}: {summary}"))
    _relay_text_to_gui(client_id, safe_console_text(f"[INCIDENT] {status} {rule_id}: {summary}"))
    if should_violation_pause and not getattr(ws, "closed", False):
        remaining = _session_remaining_seconds(request, user)
        await ws.send_str(_protect_payload(client_id, _session_state_payload(request, user)))
        await ws.send_str(
            _protect_payload(client_id, events.pause_exam(
                remaining,
                source="violation",
                reason=str(incident.get("summary", "") or rule_id),
            ))
        )
    if not getattr(ws, "closed", False):
        await ws.send_str(
            _protect_payload(client_id, events.incident_received(
                incident_id,
                artifact_path=str(incident.get("artifact_path", "") or ""),
            ))
        )


async def _handle_kill_process_result_event(
    ws: web.WebSocketResponse,
    client_id: str,
    data: dict,
):
    login_id, user = state.find_user_by_uuid(client_id)
    if not user:
        await ws.send_str(_protect_payload(client_id, events.error("Unknown client for kill result.")))
        return

    pid = int(data.get("pid", 0) or 0)
    incident_id = str(data.get("incident_id", "")).strip()
    ok = bool(data.get("ok", False))
    process_name = str(data.get("process_name", "")).strip()
    message = str(data.get("message", "")).strip()
    result_text = f"{'succeeded' if ok else 'failed'} for pid {pid}"
    if process_name:
        result_text = f"{result_text} ({process_name})"
    if message:
        result_text = f"{result_text}: {message}"

    user["last_action"] = f"Kill PID {'ok' if ok else 'failed'}"
    state.save_users()

    if incident_id and incident_id in state.active_incidents:
        state.active_incidents[incident_id]["last_kill_result"] = {
            "ok": ok,
            "pid": pid,
            "process_name": process_name,
            "message": message,
            "at": protocol.now_iso(),
        }

    print(f"[INCIDENT] Kill result from {login_id} ({client_id}): {result_text}")
    _relay_text_to_gui(client_id, f"[KILL] {result_text}")


async def _handle_start_exam(
    ws: web.WebSocketResponse,
    request: web.Request,
    client_id: str,
):
    _, user = state.find_user_by_uuid(client_id)
    if not user:
        return
    if _user_has_submission(user):
        await ws.send_str(_protect_payload(client_id, events.error("Submission already received for this user.")))
        return
    state_name = session_state.derive_state(user)
    if state_name in {session_state.AWAITING_SUBMISSION, session_state.SUBMITTED}:
        await ws.send_str(_protect_payload(client_id, events.error("Exam has already finished.")))
        return
    if state_name in {
        session_state.RUNNING,
        session_state.ADMIN_PAUSED,
        session_state.DISCONNECTED_PAUSED,
        session_state.VIOLATION_PAUSED,
    }:
        await ws.send_str(_protect_payload(client_id, _session_state_payload(request, user)))
        await ws.send_str(_protect_payload(client_id, _sync_time_payload(request, user)))
        return

    exam_phase = request.app.get("exam_phase", "waiting")
    if exam_phase != "running":
        if exam_phase == "finished":
            await ws.send_str(_protect_payload(client_id, events.error("Exam has already finished.")))
        else:
            await ws.send_str(_protect_payload(client_id, events.error("Exam is not started yet.")))
        return

    session_state.set_state(user, session_state.RUNNING, reason="Exam started.")
    user["last_action"] = "Started"
    state.save_users()
    print(f"[EXAM] Client {client_id} started their exam.")
    await ws.send_str(_protect_payload(client_id, _session_state_payload(request, user)))
    await ws.send_str(_protect_payload(client_id, _sync_time_payload(request, user)))


# -- HTTP Routes -----------------------------------------------------------
async def health(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "ok",
        "server_id": request.app["server_id"],
        "clients_connected": len(state.clients),
    })


async def auth_status(request: web.Request) -> web.Response:
    login_id = str(request.query.get("login_id", "") or "").strip()
    allowed_user = bool(login_id and login_id in state.allowed_users)
    cats_until = _auth_bypass_until(request, "cats")
    ad_until = _auth_bypass_until(request, "ad")
    cats_bypass = cats_until > time.time()
    ad_bypass = ad_until > time.time()
    auth_secret = str(request.app.get("auth_secret") or "")
    admin_validation_required = auth_validation.validation_required(
        request.app,
        allowed_user=allowed_user,
    ) if login_id else False
    validation_status = auth_validation.validation_status(request.app, login_id)
    if not login_id:
        reason = "login_id is required"
    elif admin_validation_required:
        reason = f"temporary auth bypass active; admin validation {validation_status}"
    elif not allowed_user:
        reason = "login_id is not in allowed_users.json"
    else:
        reason = "normal auth required"
    return web.json_response(
        {
            "allowed_user": allowed_user,
            "cats_required": not cats_bypass,
            "ad_required": bool(auth_secret) and not ad_bypass,
            "cats_bypass_until": _iso_from_epoch(cats_until),
            "ad_bypass_until": _iso_from_epoch(ad_until),
            "admin_validation_required": admin_validation_required,
            "validation_status": validation_status,
            "validation_approval_until": _iso_from_epoch(auth_validation.approval_until(request.app, login_id)),
            "server_time": protocol.now_iso(),
            "reason": reason,
        }
    )

def _verify_token(login_id: str, token: str, secret: str) -> bool:
    """
    Verify the HMAC-SHA256 token produced by check_user.exe --gen-token.
    Accepts the current 60-second window and one window either side to allow
    clock skew between client and server.
    """
    import hmac as _hmac
    import hashlib
    import time

    secret_bytes = secret.encode("utf-8")
    window_now = int(time.time()) // 60
    for w in (window_now - 1, window_now, window_now + 1):
        msg = f"{login_id}|{w}".encode("utf-8")
        expected = _hmac.new(secret_bytes, msg, hashlib.sha256).hexdigest()
        if _hmac.compare_digest(expected, token):
            return True
    return False


def _validate_token(request: web.Request, login_id: str, token: str) -> web.Response | None:
    """
    Verify the HMAC token sent by the client.
    Returns an error Response on failure, None on success.
    If no auth_secret is configured the token check is skipped (dev mode).
    """
    secret = str(request.app.get("auth_secret") or "")
    if not secret:
        return None  # dev/testing: no secret set, skip token verification
    if _auth_bypass_active(request, "ad") and str(token or "").strip():
        print(f"[AUTH] Temporary AD bypass used for {login_id} after admin validation.")
        return None
    if not _verify_token(login_id, token, secret):
        return _json_error("Invalid credentials.", 401)
    return None


def _validate_admin_auth_bypass(request: web.Request, login_id: str, credential: str) -> web.Response | None:
    modes = auth_validation.active_bypass_modes(
        request.app,
        allowed_user=login_id in state.allowed_users,
    )
    if not modes:
        return None

    if not str(credential or "").strip():
        return _json_error("login_id and password required", 400)

    status = auth_validation.validation_status(request.app, login_id)
    if status == "approved":
        print(f"[AUTH] Admin-approved temporary auth bypass used for {login_id}.")
        return None
    if status == "denied":
        return _json_error("Credentials were denied by the admin.", 403, code="AUTH_REJECTED")

    auth_validation.record_request(
        request.app,
        login_id=login_id,
        ip=_client_ip(request),
        modes=modes,
        password_present=True,
    )
    print(f"[AUTH] Login for {login_id} is waiting for admin validation ({', '.join(modes)} bypass).")
    return web.json_response(
        {
            "status": "pending_validation",
            "reason": "Waiting for admin credential validation.",
            "login_id": login_id,
            "auth_modes": modes,
            "server_time": protocol.now_iso(),
        },
        status=202,
    )


async def login_handler(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return _json_error("Invalid JSON", 400)

    login_id, token = _validate_login_payload(data)
    if not login_id or not token:
        return _json_error("login_id and password required", 400)

    bypass_validation = _validate_admin_auth_bypass(request, login_id, token)
    if bypass_validation is not None:
        return bypass_validation

    approved_temporary_bypass = bool(
        auth_validation.active_bypass_modes(request.app, allowed_user=login_id in state.allowed_users)
        and auth_validation.is_approved(request.app, login_id)
    )
    if login_id not in state.allowed_users and not approved_temporary_bypass:
        return _json_error("User is not allowed to take this exam.", 403)

    token_error = _validate_token(request, login_id, token)
    if token_error:
        return token_error

    user = state.users_db.get(login_id)
    block_reason = _login_block_reason(request, user)
    if block_reason:
        return _json_error(block_reason, 403 if "finished" in block_reason.lower() else 409)

    if not user:
        return _register_new_user(login_id)

    state.ensure_user_defaults(user)
    if user.get("banned", False):
        return _json_error("This user is banned.", 403)

    if user["uuid"] in state.clients:
        return _json_error("This login is already active on another client.", 409)

    ip = _client_ip(request)
    block_reason = ip_guard.check_login(ip, login_id, state.clients, state.users_db)
    if block_reason:
        print(f"[ip_guard] Login blocked for {login_id} from {ip}: {block_reason}")
        return _json_error("Authentication failed.", 403, code="AUTH_REJECTED")

    return web.json_response({"status": "ok", "uuid": user["uuid"]})


async def exam_config(request: web.Request) -> web.Response:
    app = request.app
    return web.json_response({
        "exam_duration_seconds": app["exam_duration"] * 60,
        "has_files": app["exam_files"] is not None
    })

async def exam_files(request: web.Request) -> web.Response:
    app = request.app
    path = app["exam_files"]
    if not path or not os.path.exists(path):
        return web.Response(status=404, text="No exam files available")
    
    if os.path.isdir(path):
        return web.Response(status=400, text="Directory serving not implemented, please provide a .zip file")
        
    return web.FileResponse(path)


async def exam_submission(request: web.Request) -> web.Response:
    client_id = request.query.get("id", "").strip()
    if not client_id or not state.is_valid_session_uuid(client_id):
        return web.json_response({"error": "Invalid or missing session ID."}, status=401)

    login_id, user = state.find_user_by_uuid(client_id)
    if not user:
        return web.json_response({"error": "Unknown client."}, status=404)

    state.ensure_user_defaults(user)
    if user.get("banned", False):
        return web.json_response({"error": "This user is banned."}, status=403)
    if (
        session_state.derive_state(user) == session_state.WAITING
        and request.app.get("exam_phase") != "finished"
    ):
        return web.json_response({"error": "Exam has not started for this client."}, status=409)
    if _user_has_submission(user):
        return web.json_response({"error": "Submission already received for this user."}, status=409)

    reader = await request.multipart()
    file_part, pre_fields = await _find_file_part(reader, "archive")
    if file_part is None or not file_part.filename:
        return web.json_response({"error": "A multipart field named 'archive' is required."}, status=400)
    destination = build_submission_path(client_id, file_part.filename)
    bytes_written, error = await _save_multipart_file(
        file_part,
        destination,
        max_bytes=int(request.app["max_submission_bytes"]),
    )
    if error:
        return web.json_response({"error": f"Failed to save submission: {error}"}, status=500)
    fields = dict(pre_fields)
    fields.update(await _read_remaining_text_fields(reader))
    expected_checksum = str(fields.get("sha256", "")).strip()

    if bytes_written <= 0:
        _remove_file_if_present(destination)
        return web.json_response({"error": "Uploaded submission bundle is empty."}, status=400)

    if not _is_supported_archive(destination):
        _remove_file_if_present(destination)
        return web.json_response({"error": "Uploaded file is not a supported ZIP or TAR archive."}, status=400)

    if not _checksum_matches(expected_checksum, destination):
        _remove_file_if_present(destination)
        return web.json_response({"error": "Uploaded submission checksum mismatch."}, status=400)

    session_state.set_state(
        user,
        session_state.SUBMITTED,
        reason="Submission uploaded successfully.",
        clear_blocking=True,
    )
    user["submitted_at"] = protocol.now_iso()
    user["submission_name"] = Path(file_part.filename).name
    user["submission_path"] = safe_relative_path(destination)
    user["submission_size_bytes"] = bytes_written
    user["last_action"] = "Submitted file"
    state.save_users()

    print(
        f"[SUBMISSION] {login_id} ({client_id}) uploaded "
        f"{user['submission_name']} -> {user['submission_path']}"
    )
    return web.json_response(
        {
            "status": "ok",
            "message": "Submission uploaded successfully.",
            "path": user["submission_path"],
            "size_bytes": bytes_written,
        }
    )


async def client_artifact_upload(request: web.Request) -> web.Response:
    client_id = request.query.get("id", "").strip()
    if not client_id or not state.is_valid_session_uuid(client_id):
        return web.json_response({"error": "Invalid or missing session ID."}, status=401)

    login_id, user = state.find_user_by_uuid(client_id)
    if not user:
        return web.json_response({"error": "Unknown client."}, status=404)

    state.ensure_user_defaults(user)
    if user.get("banned", False):
        return web.json_response({"error": "This user is banned."}, status=403)

    reader = await request.multipart()
    file_part, pre_fields = await _find_file_part(reader, "artifact")
    if file_part is None or not file_part.filename:
        return web.json_response({"error": "A multipart field named 'artifact' is required."}, status=400)

    destination = build_artifact_path(client_id, "artifact", file_part.filename)
    bytes_written, error = await _save_multipart_file(
        file_part,
        destination,
        max_bytes=int(request.app["max_artifact_bytes"]),
    )
    if error:
        return web.json_response({"error": f"Failed to save artifact: {error}"}, status=500)
    fields = dict(pre_fields)
    fields.update(await _read_remaining_text_fields(reader))
    expected_checksum = str(fields.get("sha256", "")).strip()
    artifact_kind = str(fields.get("kind", "")).strip()
    metadata_text = str(fields.get("metadata", ""))
    artifact_kind = artifact_kind.strip() or "artifact"

    if bytes_written <= 0:
        _remove_file_if_present(destination)
        return web.json_response({"error": "Uploaded artifact is empty."}, status=400)

    if not _checksum_matches(expected_checksum, destination):
        _remove_file_if_present(destination)
        return web.json_response({"error": "Uploaded artifact checksum mismatch."}, status=400)

    final_destination = build_artifact_path(client_id, artifact_kind, file_part.filename)
    final_destination.parent.mkdir(parents=True, exist_ok=True)
    if final_destination != destination:
        final_destination = destination.replace(final_destination)
    else:
        final_destination = destination

    metadata = {}
    if metadata_text:
        try:
            metadata = json.loads(metadata_text)
        except json.JSONDecodeError:
            metadata = {"raw_metadata": metadata_text}

    metadata_path = final_destination.with_suffix(final_destination.suffix + ".json")
    metadata_path.write_text(
        json.dumps(
            {
                "client_id": client_id,
                "login_id": login_id,
                "kind": artifact_kind,
                "saved_at": protocol.now_iso(),
                "path": safe_relative_path(final_destination),
                "size_bytes": bytes_written,
                "sha256": expected_checksum,
                "metadata": metadata,
            },
            indent=2,
        )
    )

    print(
        f"[ARTIFACT] {login_id} ({client_id}) uploaded {artifact_kind} -> "
        f"{safe_relative_path(final_destination)}"
    )
    return web.json_response(
        {
            "status": "ok",
            "message": "Artifact uploaded successfully.",
            "path": safe_relative_path(final_destination),
            "size_bytes": bytes_written,
        }
    )

# -- WebSocket Handler -----------------------------------------------------
async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    client_id = request.query.get("id")

    if not client_id or not state.is_valid_session_uuid(client_id):
        return web.Response(status=401, text="Unauthorized: invalid or missing session ID")

    _, user = state.find_user_by_uuid(client_id)
    if user and user.get("banned", False):
        return web.Response(status=403, text="This user is banned.")
    if user:
        state.ensure_user_defaults(user)
        if _user_has_submission(user):
            return web.Response(status=409, text="Submission already received for this user.")
        if request.app.get("exam_phase") == "finished" and not user.get("exam_started", False):
            return web.Response(status=403, text="Exam has already finished.")

    if client_id in state.clients:
        return web.Response(status=409, text="A client is already connected with this login.")

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    short_id = client_id[:8]
    ip = _client_ip(request)

    state.clients[client_id] = {
        "ws": ws,
        "short_id": short_id,
        "ip": ip,
        "computer_name": user.get("computer_name", "") if user else "",
        "security": security.build_session_context(client_id, str(request.app.get("auth_secret") or "")) if user else None,
    }
    if user:
        login_id_for_client, _ = state.find_user_by_uuid(client_id)
        if login_id_for_client:
            ip_guard.register_ip(login_id_for_client, ip, state.clients, client_id, state.users_db, state.save_users)
    print(f"[+] Client connected: {client_id} (short: {short_id}, ip: {ip})")

    # Send welcome with their ID
    await ws.send_str(_protect_payload(client_id, events.welcome(client_id, request.app["server_id"])))
    await ws.send_str(_protect_payload(client_id, events.exam_policy(state.current_exam_policy())))
    await ws.send_str(
        _protect_payload(client_id, events.process_blacklist(
            state.process_blacklist,
            state.process_blacklist_version,
            list(state.rule_config("process_blacklist").get("process_usernames", [])),
        ))
    )
    if user:
        current_state = session_state.derive_state(user)
        if current_state == session_state.DISCONNECTED_PAUSED and session_state.reconnect_resume_allowed(
            user,
            state.session_policy(),
        ):
            session_state.set_state(
                user,
                session_state.RUNNING,
                reason="Reconnected and resumed automatically.",
                remaining_seconds=_session_remaining_seconds(request, user),
                clear_blocking=True,
            )
            current_state = session_state.RUNNING
            user["last_action"] = "Reconnected"
        elif current_state == session_state.AWAITING_SUBMISSION:
            user["last_action"] = "Awaiting submission"
        elif current_state in session_state.PAUSED_STATES:
            user["last_action"] = "Reconnected paused"
        elif current_state == session_state.RUNNING:
            user["last_action"] = "Connected"
        else:
            user["last_action"] = "Connected"
        state.save_users()
        await ws.send_str(_protect_payload(client_id, _session_state_payload(request, user)))
        current_state = session_state.derive_state(user)
        if current_state == session_state.AWAITING_SUBMISSION:
            await ws.send_str(_protect_payload(client_id, events.finish_exam("Your exam has ended. Please upload your file.")))
        elif current_state in {session_state.RUNNING, *session_state.PAUSED_STATES}:
            await ws.send_str(_protect_payload(client_id, _sync_time_payload(request, user)))
            if current_state in session_state.PAUSED_STATES:
                await ws.send_str(
                    _protect_payload(client_id, events.pause_exam(
                        _session_remaining_seconds(request, user),
                        source=session_state.pause_source(user),
                        reason=_session_reason(user),
                    ))
                )

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                event, data = security.decode_wire_message(
                    msg.data,
                    state.clients.get(client_id, {}).get("security"),
                )
                if event == protocol.DECODE_ERROR:
                    await ws.send_str(_protect_payload(client_id, events.error(data.get("reason", "protocol decode failed"))))
                    continue

                if event == events.PING:
                    await _handle_ping_event(ws, client_id, data)
                elif event == events.CLIENT_INFO:
                    _handle_client_info(client_id, data)
                elif event == events.START_EXAM:
                    await _handle_start_exam(ws, request, client_id)
                elif event == events.PROCESS_CATCH:
                    await _handle_process_catch_event(ws, client_id, data)
                elif event == events.POLICY_APPLIED:
                    await _handle_policy_applied_event(ws, client_id, data)
                elif event == events.CLIENT_MONITOR_EVENT:
                    await _handle_client_monitor_event(ws, client_id, data)
                elif event == events.INCIDENT_REPORT:
                    await _handle_incident_report_event(ws, request, client_id, data)
                elif event == events.KILL_PROCESS_RESULT:
                    await _handle_kill_process_result_event(ws, client_id, data)
                else:
                    await ws.send_str(_protect_payload(client_id, events.error(f"unknown event: {event}")))

            elif msg.type == WSMsgType.ERROR:
                print(f"[!] Client {client_id} error: {ws.exception()}")
    finally:
        # Unregister on disconnect
        state.clients.pop(client_id, None)
        if user:
            current_state = session_state.derive_state(user)
            if current_state == session_state.RUNNING:
                session_state.set_state(
                    user,
                    session_state.DISCONNECTED_PAUSED,
                    reason="Disconnected from server.",
                    remaining_seconds=_remaining_seconds(request, user),
                )
                user["last_action"] = "Disconnected paused"
            elif current_state == session_state.WAITING:
                user["last_action"] = "Disconnected"
            state.save_users()
        print(f"[-] Client {client_id} disconnected  ({len(state.clients)} total)")

    return ws
