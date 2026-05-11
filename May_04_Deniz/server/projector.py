import asyncio
import json

from aiohttp import web

from common import protocol
from . import session_state
from .state import state

PROJECTOR_NOTIFICATION_LIMIT = 5


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


def projector_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Exam Notifications</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #05070a;
      --panel: #111820;
      --panel-strong: #172231;
      --text: #f4f7fb;
      --muted: #bac6d4;
      --info: #58a6ff;
      --warning: #ffcf5a;
      --violation: #ff5f67;
      --resolved: #57d68d;
      --system: #c6d4e2;
    }
    * { box-sizing: border-box; }
    html, body {
      margin: 0;
      min-height: 100%;
      background: var(--bg);
      color: var(--text);
      font-family: Arial, Helvetica, sans-serif;
    }
    body {
      overflow: hidden;
    }
    .screen {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr auto;
      gap: 18px;
      padding: 22px;
    }
    .top {
      display: grid;
      grid-template-columns: 1.4fr 0.6fr;
      gap: 18px;
      align-items: stretch;
    }
    .hero,
    .clock,
    .metric,
    .notice {
      background: var(--panel);
      border: 3px solid #263548;
      border-radius: 8px;
      box-shadow: 0 0 0 1px #000 inset;
    }
    .hero {
      padding: 22px 28px;
      min-height: 150px;
    }
    .eyebrow {
      color: var(--muted);
      font-size: 28px;
      font-weight: 700;
      text-transform: uppercase;
    }
    .phase {
      margin-top: 6px;
      font-size: 76px;
      line-height: 1;
      font-weight: 900;
    }
    .subline {
      margin-top: 12px;
      color: var(--muted);
      font-size: 30px;
      font-weight: 700;
    }
    .clock {
      padding: 22px;
      display: flex;
      flex-direction: column;
      justify-content: center;
      text-align: center;
    }
    .clock .label {
      color: var(--muted);
      font-size: 24px;
      font-weight: 700;
      text-transform: uppercase;
    }
    .clock .value {
      margin-top: 8px;
      font-size: 52px;
      line-height: 1;
      font-weight: 900;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 14px;
    }
    .metric {
      padding: 18px;
      min-height: 116px;
    }
    .metric .label {
      color: var(--muted);
      font-size: 23px;
      font-weight: 800;
      text-transform: uppercase;
    }
    .metric .value {
      margin-top: 8px;
      font-size: 58px;
      line-height: 1;
      font-weight: 900;
    }
    .metric.warning { border-color: var(--warning); }
    .metric.violation { border-color: var(--violation); }
    .metric.connected { border-color: var(--resolved); }
    .metric.submission { border-color: var(--info); }
    .notices {
      display: grid;
      grid-template-rows: repeat(5, minmax(86px, auto));
      gap: 12px;
      min-height: 0;
    }
    .notice {
      display: grid;
      grid-template-columns: 18px 1fr auto;
      gap: 18px;
      align-items: center;
      padding: 14px 18px;
      min-height: 86px;
    }
    .stripe {
      align-self: stretch;
      border-radius: 3px;
      background: var(--info);
    }
    .notice.warning .stripe { background: var(--warning); }
    .notice.violation .stripe { background: var(--violation); }
    .notice.resolved .stripe { background: var(--resolved); }
    .notice.system .stripe { background: var(--system); }
    .notice .message {
      font-size: 38px;
      line-height: 1.05;
      font-weight: 900;
    }
    .notice .time {
      color: var(--muted);
      font-size: 24px;
      font-weight: 700;
      white-space: nowrap;
    }
    .bottom {
      display: flex;
      justify-content: space-between;
      gap: 18px;
      color: var(--muted);
      font-size: 24px;
      font-weight: 800;
    }
    .offline {
      color: var(--warning);
    }
    @media (max-height: 740px) {
      .screen { gap: 12px; padding: 14px; }
      .phase { font-size: 62px; }
      .metric { min-height: 94px; padding: 14px; }
      .metric .value { font-size: 46px; }
      .notice { min-height: 72px; padding: 10px 14px; }
      .notice .message { font-size: 31px; }
    }
    @media (max-width: 1050px) {
      .top { grid-template-columns: 1fr; }
      .metrics { grid-template-columns: repeat(2, 1fr); }
      .clock { display: none; }
    }
  </style>
</head>
<body>
  <main class="screen" aria-live="polite">
    <section class="top">
      <div class="hero">
        <div class="eyebrow">Exam Notifications</div>
        <div id="phase" class="phase">Waiting</div>
        <div id="subline" class="subline">Connecting to server feed...</div>
      </div>
      <div class="clock">
        <div class="label">Server Time</div>
        <div id="serverTime" class="value">--:--</div>
      </div>
    </section>
    <section>
      <div class="metrics">
        <div class="metric connected"><div class="label">Connected</div><div id="connected" class="value">0</div></div>
        <div class="metric violation"><div class="label">Violations</div><div id="violations" class="value">0</div></div>
        <div class="metric warning"><div class="label">Warnings</div><div id="warnings" class="value">0</div></div>
        <div class="metric submission"><div class="label">Submission</div><div id="submission" class="value">0</div></div>
      </div>
    </section>
    <section id="notices" class="notices"></section>
    <footer class="bottom">
      <span id="connection" class="offline">Connecting</span>
      <span id="updated">Last update: never</span>
    </footer>
  </main>
  <script>
    const notices = document.getElementById('notices');
    const state = { lastUpdate: 0 };

    function text(id, value) {
      document.getElementById(id).textContent = String(value);
    }

    function formatPhase(raw) {
      const phase = String(raw || 'waiting').replace(/_/g, ' ');
      return phase.charAt(0).toUpperCase() + phase.slice(1);
    }

    function formatTime(value) {
      if (!value) return '--:--';
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value).slice(11, 16) || '--:--';
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    function renderNotifications(items) {
      notices.textContent = '';
      const list = Array.isArray(items) && items.length ? items.slice(0, 5) : [
        { severity: 'system', message: 'No active notifications', time: '' }
      ];
      for (const item of list) {
        const node = document.createElement('article');
        const severity = ['warning', 'violation', 'resolved', 'system'].includes(item.severity) ? item.severity : 'info';
        node.className = `notice ${severity}`;
        node.innerHTML = '<div class="stripe"></div><div class="message"></div><div class="time"></div>';
        node.querySelector('.message').textContent = item.message || 'Notification update';
        node.querySelector('.time').textContent = formatTime(item.time);
        notices.appendChild(node);
      }
    }

    function render(payload) {
      state.lastUpdate = Date.now();
      const counts = payload.counts || {};
      text('phase', formatPhase(payload.exam_phase));
      text('subline', payload.exam_start_enabled ? 'Exam start is open' : 'Read-only public notification display');
      text('serverTime', formatTime(payload.server_time));
      text('connected', counts.connected || 0);
      text('violations', counts.active_violations || 0);
      text('warnings', counts.active_warnings || 0);
      text('submission', (counts.awaiting_submission || 0) + (counts.submitted || 0));
      text('connection', 'Live feed connected');
      document.getElementById('connection').classList.remove('offline');
      text('updated', `Last update: ${formatTime(payload.server_time)}`);
      renderNotifications(payload.notifications || []);
    }

    function connect() {
      const stream = new EventSource('/projector/events');
      stream.onmessage = (event) => {
        try { render(JSON.parse(event.data)); } catch (error) {}
      };
      stream.onerror = () => {
        text('connection', 'Reconnecting to live feed');
        document.getElementById('connection').classList.add('offline');
      };
    }

    setInterval(() => {
      if (state.lastUpdate && Date.now() - state.lastUpdate > 6000) {
        text('connection', 'Reconnecting to live feed');
        document.getElementById('connection').classList.add('offline');
      }
    }, 1000);

    renderNotifications([]);
    connect();
  </script>
</body>
</html>"""


async def projector_page(_request: web.Request) -> web.Response:
    return web.Response(text=projector_html(), content_type="text/html")


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
