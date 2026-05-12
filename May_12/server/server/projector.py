import asyncio
import json
from pathlib import Path

from aiohttp import web

from common import protocol
from . import session_state
from .state import state

PROJECTOR_NOTIFICATION_LIMIT = 5
PROJECTOR_ASSET_DIR = Path(__file__).resolve().parent / "static" / "projector"


def _status_name(user: dict) -> str:
    try:
        return session_state.derive_state(user)
    except Exception:
        return "unknown"


def _incident_severity(incident: dict) -> str:
    severity = str(incident.get("severity", "") or "").strip().lower()
    if severity == "violation":
        return "violation"
    if severity in {"warning", "warn"}:
        return "warning"
    if str(incident.get("status", "") or "").strip().lower() == "resolved":
        return "resolved"
    return "info"


def _incident_message(incident: dict) -> str:
    status = str(incident.get("status", "") or "").strip().lower()
    severity = _incident_severity(incident)
    if status == "resolved":
        if severity == "warning":
            return "Warning resolved"
        if severity == "violation":
            return "Violation incident resolved"
        return "Incident resolved"
    if status == "opened":
        if severity == "violation":
            return "New violation incident opened"
        if severity == "warning":
            return "New warning incident opened"
        return "New incident opened"
    if status == "evidence_uploaded":
        return "Incident evidence received"
    if status == "evidence_failed":
        return "Incident evidence pending"
    return "Incident update received"


def _notification_from_incident(incident: dict) -> dict:
    status = str(incident.get("status", "") or "").strip().lower()
    severity = "resolved" if status == "resolved" else _incident_severity(incident)
    return {
        "kind": "incident",
        "severity": severity,
        "message": _incident_message(incident),
        "time": str(
            incident.get("server_received_at")
            or incident.get("reported_at")
            or incident.get("timestamp")
            or ""
        ),
    }


def _system_notification(app: web.Application) -> dict:
    phase = str(app.get("exam_phase", "waiting") or "waiting").lower()
    start_enabled = bool(app.get("exam_start_enabled", False))
    if phase == "running":
        message = "Exam is running"
    elif phase == "finished":
        message = "Exam finished"
    elif start_enabled:
        message = "Exam start is open"
    else:
        message = "Waiting for exam start"
    return {
        "kind": "system",
        "severity": "system",
        "message": message,
        "time": protocol.now_iso(),
    }


def _projection_counts(state_obj) -> dict:
    users = list(getattr(state_obj, "users_db", {}).values())
    connected = len(getattr(state_obj, "clients", {}) or {})
    disconnected = max(0, len(users) - connected)
    active_incidents = list(getattr(state_obj, "active_incidents", {}).values())
    active_warnings = sum(1 for incident in active_incidents if _incident_severity(incident) == "warning")
    active_violations = sum(1 for incident in active_incidents if _incident_severity(incident) == "violation")
    submitted = sum(1 for user in users if _status_name(user) == session_state.SUBMITTED)
    awaiting = sum(1 for user in users if _status_name(user) == session_state.AWAITING_SUBMISSION)
    return {
        "total_users": len(users),
        "connected": connected,
        "disconnected": disconnected,
        "active_incidents": len(active_incidents),
        "active_warnings": active_warnings,
        "active_violations": active_violations,
        "submitted": submitted,
        "awaiting_submission": awaiting,
    }


def _projection_notifications(app: web.Application, state_obj) -> list[dict]:
    notifications: list[dict] = []
    for incident in reversed(getattr(state_obj, "incidents", []) or []):
        if not isinstance(incident, dict):
            continue
        notifications.append(_notification_from_incident(incident))
        if len(notifications) >= PROJECTOR_NOTIFICATION_LIMIT:
            break
    if notifications:
        return notifications
    return [_system_notification(app)]


def build_projection_state(app: web.Application, state_obj=state) -> dict:
    return {
        "server_time": protocol.now_iso(),
        "exam_phase": str(app.get("exam_phase", "waiting") or "waiting"),
        "exam_start_enabled": bool(app.get("exam_start_enabled", False)),
        "connection_status": "live",
        "counts": _projection_counts(state_obj),
        "notifications": _projection_notifications(app, state_obj),
    }


def _projector_asset_text(filename: str) -> str:
    path = PROJECTOR_ASSET_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def projector_html() -> str:
    return _projector_asset_text("index.html")


async def projector_page(_request: web.Request) -> web.Response:
    return web.Response(
        text=projector_html(),
        content_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


async def projector_css(_request: web.Request) -> web.Response:
    return web.Response(
        text=_projector_asset_text("projector.css"),
        content_type="text/css",
        headers={"Cache-Control": "no-store"},
    )


async def projector_js(_request: web.Request) -> web.Response:
    return web.Response(
        text=_projector_asset_text("projector.js"),
        content_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


async def projector_events(request: web.Request) -> web.StreamResponse:
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)
    interval = max(1.0, float(request.app.get("broadcast_interval", 1.0) or 1.0))
    try:
        while True:
            payload = build_projection_state(request.app)
            data = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
            await response.write(f"data: {data}\n\n".encode("utf-8"))
            await asyncio.sleep(interval)
    except (asyncio.CancelledError, ConnectionResetError, RuntimeError):
        pass
    return response


def payload_contains_sensitive_fields(payload: dict) -> bool:
    serialized = json.dumps(payload, ensure_ascii=True).lower()
    sensitive_tokens = (
        "login_id",
        "uuid",
        "client_id",
        "ip",
        "artifact_path",
        "submission_path",
        "window_title",
        "process_name",
        "computer_name",
    )
    return any(token in serialized for token in sensitive_tokens)
