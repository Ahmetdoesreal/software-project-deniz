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
    { severity: 'system', message: 'No active notifications', time: '' },
  ];
  for (const item of list) {
    const node = document.createElement('article');
    const severity = ['warning', 'violation', 'resolved', 'system'].includes(item.severity)
      ? item.severity
      : 'info';
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
    try {
      render(JSON.parse(event.data));
    } catch (error) {
      // Ignore malformed transient events and keep the stream alive.
    }
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
