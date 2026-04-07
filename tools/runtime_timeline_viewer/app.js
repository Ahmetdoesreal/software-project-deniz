const LANE_ORDER = [
  { id: "exam_state", label: "Exam State" },
  { id: "incidents", label: "Incidents" },
  { id: "process_monitor", label: "Processes" },
  { id: "focused_window", label: "Focused Window" },
  { id: "hardware_monitor", label: "Hardware" },
  { id: "runtime_log", label: "Runtime Logs" },
  { id: "snapshot", label: "Snapshots" },
  { id: "other", label: "Other" },
];

const appState = {
  files: [],
  derived: {
    policy: emptyPolicy(),
    events: [],
    visibleEvents: [],
    summary: {},
  },
  selectedEventId: "",
  searchText: "",
  policyHitsOnly: false,
  laneFilters: new Set(LANE_ORDER.map((lane) => lane.id)),
  nextEventId: 1,
};

const fileInput = document.getElementById("fileInput");
const folderInput = document.getElementById("folderInput");
const clearButton = document.getElementById("clearButton");
const searchInput = document.getElementById("searchInput");
const policyHitsOnly = document.getElementById("policyHitsOnly");
const laneFilters = document.getElementById("laneFilters");
const summaryGrid = document.getElementById("summaryGrid");
const rulesPanel = document.getElementById("rulesPanel");
const fileList = document.getElementById("fileList");
const timelineSvg = document.getElementById("timelineSvg");
const timelineMeta = document.getElementById("timelineMeta");
const timeRangeLabel = document.getElementById("timeRangeLabel");
const eventRows = document.getElementById("eventRows");
const detailTitle = document.getElementById("detailTitle");
const detailBadges = document.getElementById("detailBadges");
const detailMeta = document.getElementById("detailMeta");
const detailPane = document.getElementById("detailPane");
const dropZone = document.getElementById("dropZone");
const loadStatus = document.getElementById("loadStatus");

initialize();

function initialize() {
  buildLaneFilters();
  bindInputs();
  bindDropZone();
  window.addEventListener("resize", () => renderTimeline());
  renderAll();
}

function bindInputs() {
  fileInput.addEventListener("change", (event) => loadFiles(event.target.files));
  folderInput.addEventListener("change", (event) => loadFiles(event.target.files));
  clearButton.addEventListener("click", clearLoadedData);
  searchInput.addEventListener("input", () => {
    appState.searchText = searchInput.value.trim().toLowerCase();
    renderAll();
  });
  policyHitsOnly.addEventListener("change", () => {
    appState.policyHitsOnly = policyHitsOnly.checked;
    renderAll();
  });
}

function bindDropZone() {
  const cancelDefaults = (event) => {
    event.preventDefault();
    event.stopPropagation();
  };

  ["dragenter", "dragover", "dragleave", "drop"].forEach((eventName) => {
    document.body.addEventListener(eventName, cancelDefaults);
    dropZone.addEventListener(eventName, cancelDefaults);
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, () => {
      dropZone.classList.add("drag-over");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, () => {
      dropZone.classList.remove("drag-over");
    });
  });

  dropZone.addEventListener("drop", async (event) => {
    const files = event.dataTransfer ? event.dataTransfer.files : null;
    await loadFiles(files);
  });
}

function emptyPolicy() {
  return {
    sources: [],
    policyVersion: "",
    processBlacklistEntries: [],
    processBlacklistVersion: "",
    session: {
      auto_resume_on_reconnect: true,
      remember_settings: true,
    },
    operatorDefaults: {
      confirm_kill_pid: true,
      confirm_kick: true,
      confirm_ban: true,
      confirm_pause: true,
    },
    focusedWindow: {
      enabled: false,
      severity: "warning",
      allowedProcessNames: [],
      allowedWindowTitles: [],
      blockedProcessNames: [],
      blockedWindowTitles: [],
      openAfterConsecutive: 3,
      resolveAfterConsecutive: 2,
      autoViolationPause: false,
    },
  };
}

function buildLaneFilters() {
  laneFilters.innerHTML = "";
  for (const lane of LANE_ORDER) {
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        appState.laneFilters.add(lane.id);
      } else {
        appState.laneFilters.delete(lane.id);
      }
      renderAll();
    });
    label.appendChild(checkbox);
    label.appendChild(document.createTextNode(lane.label));
    laneFilters.appendChild(label);
  }
}

function clearLoadedData() {
  appState.files = [];
  appState.selectedEventId = "";
  appState.nextEventId = 1;
  fileInput.value = "";
  folderInput.value = "";
  renderAll();
}

async function loadFiles(fileListObject) {
  const incomingFiles = Array.from(fileListObject || []);
  if (!incomingFiles.length) {
    return;
  }

  const existingKeys = new Set(appState.files.map((file) => file.key));
  const loaded = [];

  for (const file of incomingFiles) {
    const path = file.webkitRelativePath || file.name;
    const key = [path, file.size, file.lastModified].join("::");
    if (existingKeys.has(key)) {
      continue;
    }

    const lowerPath = path.toLowerCase();
    if (!lowerPath.endsWith(".json") && !lowerPath.endsWith(".jsonl") && !lowerPath.endsWith(".txt")) {
      continue;
    }

    const text = await file.text();
    loaded.push({
      key,
      name: file.name,
      path,
      text,
      category: "unknown",
      parseKind: inferParseKind(lowerPath),
      parseErrors: [],
      payload: null,
    });
    existingKeys.add(key);
  }

  if (!loaded.length) {
    renderAll();
    return;
  }

  for (const file of loaded) {
    parseLoadedFile(file);
  }

  appState.files.push(...loaded);
  renderAll();
}

function inferParseKind(lowerPath) {
  if (lowerPath.endsWith(".jsonl")) {
    return "jsonl";
  }
  if (lowerPath.endsWith(".json")) {
    return "json";
  }
  if (lowerPath.endsWith(".txt")) {
    return "text";
  }
  return "text";
}

function parseLoadedFile(file) {
  try {
    if (file.parseKind === "jsonl") {
      file.payload = parseJsonLines(file.text, file.parseErrors);
    } else if (file.parseKind === "json") {
      file.payload = JSON.parse(file.text);
    } else {
      file.payload = file.text;
    }
  } catch (error) {
    file.parseErrors.push(String(error && error.message ? error.message : error));
    file.payload = null;
  }
  file.category = classifyLoadedFile(file);
}

function parseJsonLines(text, parseErrors) {
  const records = [];
  const lines = text.split(/\r?\n/);
  lines.forEach((line, index) => {
    const trimmed = line.trim();
    if (!trimmed) {
      return;
    }
    try {
      records.push(JSON.parse(trimmed));
    } catch (error) {
      parseErrors.push("Line " + (index + 1) + ": " + String(error && error.message ? error.message : error));
    }
  });
  return records;
}

function classifyLoadedFile(file) {
  const lowerPath = file.path.toLowerCase();
  const payload = file.payload;
  if (lowerPath.endsWith("process_blacklist.txt")) {
    return "process_blacklist_txt";
  }
  if (lowerPath.endsWith("processes.jsonl")) {
    return "process_log";
  }
  if (lowerPath.includes("process_report_requested_") && lowerPath.endsWith(".json")) {
    return "process_snapshot";
  }
  if (lowerPath.endsWith("focused_window.jsonl")) {
    return "focused_window_log";
  }
  if (lowerPath.includes("focused_window_snapshot") && lowerPath.endsWith(".json")) {
    return "focused_window_snapshot";
  }
  if (lowerPath.endsWith("hardware_changes.jsonl")) {
    return "hardware_log";
  }
  if (lowerPath.includes("hardware_snapshot") && lowerPath.endsWith(".json")) {
    return "hardware_snapshot";
  }
  if (lowerPath.endsWith("exam_state.jsonl")) {
    return "exam_state_log";
  }
  if (lowerPath.endsWith("incidents.jsonl") || lowerPath.endsWith("/incident.json") || lowerPath === "incident.json") {
    return "incident_log";
  }
  if (lowerPath.endsWith("session_audit.jsonl")) {
    return "audit_log";
  }
  if (lowerPath.endsWith("manifest.json")) {
    return "manifest";
  }
  if (lowerPath.endsWith("exam_policy.json")) {
    return "policy";
  }
  if (payload && typeof payload === "object" && payload !== null) {
    if (payload.schema_version && payload.process_blacklist) {
      return "settings_bundle";
    }
    if (Array.isArray(payload.rules) && payload.policy_version) {
      return "policy";
    }
    if (payload.exam_policy || payload.operator_defaults) {
      return "settings_bundle";
    }
    if (payload.type === "focused_window_snapshot") {
      return "focused_window_snapshot";
    }
    if (payload.type === "snapshot_report" && payload.snapshot) {
      return "hardware_snapshot";
    }
    if (payload.type === "requested" && Array.isArray(payload.processes)) {
      return "process_snapshot";
    }
  }
  if (Array.isArray(payload) && payload.length && looksLikeRuntimeLogEntry(payload[0])) {
    return "runtime_log";
  }
  if (Array.isArray(payload) && payload.length && looksLikeIncidentEntry(payload[0])) {
    return "incident_log";
  }
  if (file.parseKind === "jsonl" && Array.isArray(payload) && payload.length) {
    if (looksLikeRuntimeLogEntry(payload[0])) {
      return "runtime_log";
    }
    if (looksLikeIncidentEntry(payload[0])) {
      return "incident_log";
    }
  }
  return "generic";
}

function looksLikeRuntimeLogEntry(record) {
  return Boolean(record && typeof record === "object" && record.timestamp && record.process && record.stream && record.message !== undefined);
}

function looksLikeIncidentEntry(record) {
  return Boolean(record && typeof record === "object" && (record.incident_id || record.rule_id || record.status));
}

function renderAll() {
  rebuildDerivedState();
  renderLoadStatus();
  renderSummary();
  renderRules();
  renderFileList();
  renderTimeline();
  renderEventTable();
  renderDetails();
}

function rebuildDerivedState() {
  const policy = emptyPolicy();
  for (const file of appState.files) {
    mergePolicyFromFile(policy, file);
  }

  const events = [];
  appState.nextEventId = 1;
  for (const file of appState.files) {
    events.push(...extractEventsFromFile(file, policy));
  }
  events.sort((a, b) => {
    if (a.timeMs !== null && b.timeMs !== null && a.timeMs !== b.timeMs) {
      return a.timeMs - b.timeMs;
    }
    if (a.timeMs !== null) {
      return -1;
    }
    if (b.timeMs !== null) {
      return 1;
    }
    return a.summary.localeCompare(b.summary);
  });

  const visibleEvents = events.filter(matchesFilters);
  appState.derived = {
    policy,
    events,
    visibleEvents,
    summary: summarize(events, visibleEvents, policy),
  };

  if (!visibleEvents.find((event) => event.id === appState.selectedEventId)) {
    appState.selectedEventId = visibleEvents.length ? visibleEvents[0].id : "";
  }
}

function mergePolicyFromFile(policy, file) {
  if (!file.payload) {
    return;
  }

  if (file.category === "process_blacklist_txt") {
    policy.sources.push(file.path);
    policy.processBlacklistEntries = uniqueStrings([
      ...policy.processBlacklistEntries,
      ...parseBlacklistText(file.payload),
    ]);
    return;
  }

  const normalized = normalizePolicyPayload(file.payload);
  if (!normalized) {
    return;
  }

  policy.sources.push(file.path);
  if (normalized.policyVersion) {
    policy.policyVersion = normalized.policyVersion;
  }
  if (normalized.processBlacklistVersion) {
    policy.processBlacklistVersion = normalized.processBlacklistVersion;
  }
  policy.processBlacklistEntries = uniqueStrings([
    ...policy.processBlacklistEntries,
    ...(normalized.processBlacklistEntries || []),
  ]);

  policy.session = {
    ...policy.session,
    ...(normalized.session || {}),
  };
  policy.operatorDefaults = {
    ...policy.operatorDefaults,
    ...(normalized.operatorDefaults || {}),
  };
  policy.focusedWindow = {
    ...policy.focusedWindow,
    ...(normalized.focusedWindow || {}),
  };
  policy.focusedWindow.allowedProcessNames = uniqueStrings(policy.focusedWindow.allowedProcessNames || []);
  policy.focusedWindow.allowedWindowTitles = uniqueStrings(policy.focusedWindow.allowedWindowTitles || []);
  policy.focusedWindow.blockedProcessNames = uniqueStrings(policy.focusedWindow.blockedProcessNames || []);
  policy.focusedWindow.blockedWindowTitles = uniqueStrings(policy.focusedWindow.blockedWindowTitles || []);
}

function normalizePolicyPayload(payload) {
  if (!payload || typeof payload !== "object") {
    return null;
  }

  if (payload.schema_version && payload.process_blacklist) {
    return normalizePolicyPayload({
      ...payload.exam_policy,
      process_blacklist: payload.process_blacklist,
      operator_defaults: payload.operator_defaults,
    });
  }

  if (payload.exam_policy && typeof payload.exam_policy === "object") {
    return normalizePolicyPayload({
      ...payload.exam_policy,
      process_blacklist: payload.process_blacklist,
      operator_defaults: payload.operator_defaults,
    });
  }

  if (Array.isArray(payload.rules)) {
    const normalized = emptyPolicy();
    normalized.policyVersion = String(payload.policy_version || "").trim();
    normalized.session = { ...(payload.session || {}) };
    normalized.operatorDefaults = { ...(payload.operator_defaults || payload.operatorDefaults || {}) };

    for (const rule of payload.rules) {
      if (!rule || typeof rule !== "object") {
        continue;
      }
      if (String(rule.rule_id) === "process_blacklist") {
        normalized.processBlacklistEntries = uniqueStrings(rule.entries || []);
        normalized.processBlacklistVersion = String(rule.blacklist_version || "").trim();
      }
      if (String(rule.rule_id) === "focused_window_policy") {
        normalized.focusedWindow = {
          enabled: Boolean(rule.enabled),
          severity: String(rule.severity || "warning"),
          allowedProcessNames: uniqueStrings(rule.allowed_process_names || []),
          allowedWindowTitles: uniqueStrings(rule.allowed_window_titles || []),
          blockedProcessNames: uniqueStrings(rule.blocked_process_names || []),
          blockedWindowTitles: uniqueStrings(rule.blocked_window_titles || []),
          openAfterConsecutive: toInt(rule.open_after_consecutive, 3),
          resolveAfterConsecutive: toInt(rule.resolve_after_consecutive, 2),
          autoViolationPause: Boolean(rule.auto_violation_pause),
        };
      }
    }
    return normalized;
  }

  const normalized = emptyPolicy();
  const session = payload.session || {};
  const operatorDefaults = payload.operator_defaults || payload.operatorDefaults || {};
  const rules = payload.rules || {};
  const focusedWindowRule = payload.focused_window || rules.focused_window || {};
  const processBlacklistRule = payload.process_blacklist || rules.process_blacklist || {};

  normalized.session = { ...(session || {}) };
  normalized.operatorDefaults = { ...(operatorDefaults || {}) };
  normalized.focusedWindow = {
    enabled: Boolean(focusedWindowRule.enabled),
    severity: String(focusedWindowRule.severity || "warning"),
    allowedProcessNames: uniqueStrings(focusedWindowRule.allowed_process_names || focusedWindowRule.allowedProcessNames || []),
    allowedWindowTitles: uniqueStrings(focusedWindowRule.allowed_window_titles || focusedWindowRule.allowedWindowTitles || []),
    blockedProcessNames: uniqueStrings(focusedWindowRule.blocked_process_names || focusedWindowRule.blockedProcessNames || []),
    blockedWindowTitles: uniqueStrings(focusedWindowRule.blocked_window_titles || focusedWindowRule.blockedWindowTitles || []),
    openAfterConsecutive: toInt(focusedWindowRule.open_after_consecutive || focusedWindowRule.openAfterConsecutive, 3),
    resolveAfterConsecutive: toInt(focusedWindowRule.resolve_after_consecutive || focusedWindowRule.resolveAfterConsecutive, 2),
    autoViolationPause: Boolean(focusedWindowRule.auto_violation_pause || focusedWindowRule.autoViolationPause),
  };
  normalized.processBlacklistEntries = uniqueStrings(
    (processBlacklistRule.entries || payload.process_blacklist_entries || []).map(String)
  );
  normalized.processBlacklistVersion = String(processBlacklistRule.version || payload.process_blacklist_version || "").trim();
  normalized.policyVersion = String(payload.policy_version || payload.policyVersion || "").trim();
  return normalized;
}

function uniqueStrings(values) {
  const seen = new Set();
  const output = [];
  for (const value of values || []) {
    const text = String(value || "").trim();
    if (!text) {
      continue;
    }
    const key = text.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    output.push(text);
  }
  return output;
}

function parseBlacklistText(text) {
  return String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));
}

function extractEventsFromFile(file, policy) {
  if (!file.payload) {
    return [];
  }

  switch (file.category) {
    case "process_log":
      return extractProcessEntries(file, Array.isArray(file.payload) ? file.payload : [], policy, false);
    case "process_snapshot":
      return extractProcessEntries(file, [file.payload], policy, true);
    case "focused_window_log":
      return extractFocusedWindowEntries(file, Array.isArray(file.payload) ? file.payload : [], policy, false);
    case "focused_window_snapshot":
      return extractFocusedWindowEntries(file, [file.payload], policy, true);
    case "hardware_log":
      return extractHardwareEntries(file, Array.isArray(file.payload) ? file.payload : []);
    case "hardware_snapshot":
      return extractHardwareEntries(file, [file.payload]);
    case "exam_state_log":
      return extractExamStateEntries(file, Array.isArray(file.payload) ? file.payload : []);
    case "incident_log":
      return extractIncidentEntries(file, Array.isArray(file.payload) ? file.payload : [file.payload]);
    case "audit_log":
      return extractAuditEntries(file, Array.isArray(file.payload) ? file.payload : []);
    case "runtime_log":
      return extractRuntimeLogEntries(file, Array.isArray(file.payload) ? file.payload : []);
    case "generic":
      return extractGenericEntries(file, file.payload);
    default:
      return [];
  }
}

function extractProcessEntries(file, records, policy, isSnapshot) {
  const events = [];
  for (const record of records) {
    if (!record || typeof record !== "object") {
      continue;
    }

    if (record.type === "exam_state_marker") {
      events.push(makeEvent(file, {
        lane: "exam_state",
        timeIso: record.timestamp,
        remainingSeconds: record.remaining_seconds ?? record.remaining_time,
        severity: record.timer_state === "paused" ? "warning" : "info",
        summary: "Process monitor state marker: " + String(record.timer_state || "unknown"),
        status: String(record.timer_state || ""),
        tags: [String(record.timer_state || ""), "state-marker", "process-monitor"],
        raw: record,
      }));
      continue;
    }

    const blacklistMatches = [];
    if (Array.isArray(record.processes)) {
      blacklistMatches.push(...findBlacklistedProcesses(record.processes, policy));
    }
    if (Array.isArray(record.added)) {
      blacklistMatches.push(...findBlacklistedProcesses(record.added, policy));
    }

    let summary = "";
    if (record.type === "diff") {
      summary = "Process diff";
      summary += " +" + (Array.isArray(record.added) ? record.added.length : 0);
      summary += " / -" + (Array.isArray(record.removed) ? record.removed.length : 0);
    } else if (record.type === "requested" || record.type === "full_list") {
      summary = "Process snapshot (" + (Array.isArray(record.processes) ? record.processes.length : 0) + ")";
    } else {
      summary = "Process event: " + String(record.type || (isSnapshot ? "snapshot" : "entry"));
    }

    const tags = [String(record.type || "process")];
    let severity = "info";
    if (blacklistMatches.length) {
      severity = "violation";
      tags.push("blacklisted-process");
      summary += " | Blacklist hit: " + blacklistMatches.join(", ");
    }

    events.push(makeEvent(file, {
      lane: isSnapshot ? "snapshot" : "process_monitor",
      timeIso: record.timestamp,
      remainingSeconds: record.remaining_seconds ?? record.remaining_time,
      severity,
      summary,
      status: blacklistMatches.length ? "blacklisted" : String(record.type || ""),
      tags,
      raw: {
        ...record,
        derived_blacklisted_processes: blacklistMatches,
      },
    }));
  }
  return events;
}

function findBlacklistedProcesses(processes, policy) {
  const blacklist = new Set((policy.processBlacklistEntries || []).map((entry) => basename(entry).toLowerCase()));
  if (!blacklist.size) {
    return [];
  }

  const matches = [];
  for (const item of processes || []) {
    const name = Array.isArray(item) ? item[1] : item && item.name;
    const normalized = basename(name).toLowerCase();
    if (!normalized || !blacklist.has(normalized)) {
      continue;
    }
    matches.push(String(name));
  }
  return uniqueStrings(matches);
}

function extractFocusedWindowEntries(file, records, policy, isSnapshot) {
  const events = [];
  for (const record of records) {
    if (!record || typeof record !== "object") {
      continue;
    }

    if (record.type === "exam_state_marker") {
      events.push(makeEvent(file, {
        lane: "exam_state",
        timeIso: record.timestamp,
        remainingSeconds: record.remaining_seconds,
        severity: record.timer_state === "paused" ? "warning" : "info",
        summary: "Focused-window state marker: " + String(record.timer_state || "unknown"),
        status: String(record.timer_state || ""),
        tags: [String(record.timer_state || ""), "state-marker", "focused-window"],
        raw: record,
      }));
      continue;
    }

    const snapshot = record.window || record.current || record.snapshot || null;
    const evaluation = evaluateFocusedWindow(snapshot, policy.focusedWindow);
    const processName = snapshot && snapshot.process_name ? String(snapshot.process_name) : "";
    const windowTitle = snapshot && snapshot.window_title ? String(snapshot.window_title) : "";
    let summary = processName || windowTitle
      ? "Focused window: " + [processName, windowTitle].filter(Boolean).join(" / ")
      : "Focused window event: " + String(record.type || "entry");

    const tags = [String(record.type || "focused-window")];
    let severity = "info";
    if (evaluation.status === "blocked") {
      severity = policy.focusedWindow.severity === "violation" ? "violation" : "warning";
      tags.push("focus-blocked");
      summary += " | Out of policy";
    } else if (evaluation.status === "whitelisted") {
      severity = "success";
      tags.push("focus-whitelisted");
      summary += " | Whitelisted";
    } else if (evaluation.status === "unavailable") {
      tags.push("focus-unavailable");
      summary += " | Unavailable";
    } else if (evaluation.status === "observed") {
      tags.push("focus-observed");
    }

    events.push(makeEvent(file, {
      lane: isSnapshot ? "snapshot" : "focused_window",
      timeIso: record.timestamp,
      severity,
      summary,
      status: evaluation.status,
      tags,
      raw: {
        ...record,
        derived_policy_evaluation: evaluation,
      },
    }));
  }
  return events;
}

function evaluateFocusedWindow(snapshot, focusedRule) {
  if (!snapshot || typeof snapshot !== "object") {
    return { status: "observed", reason: "no_snapshot" };
  }

  if (snapshot.available === false) {
    return {
      status: "unavailable",
      reason: String(snapshot.reason || "unavailable"),
    };
  }

  const processName = normalizeName(snapshot.process_name);
  const windowTitle = normalizeName(snapshot.window_title);
  const blockedProcesses = new Set((focusedRule.blockedProcessNames || []).map(normalizeName));
  const blockedTitles = new Set((focusedRule.blockedWindowTitles || []).map(normalizeName));
  const allowedProcesses = new Set((focusedRule.allowedProcessNames || []).map(normalizeName));
  const allowedTitles = new Set((focusedRule.allowedWindowTitles || []).map(normalizeName));

  if (processName && blockedProcesses.has(processName)) {
    return { status: "blocked", reason: "blocked_process_name" };
  }
  if (windowTitle && blockedTitles.has(windowTitle)) {
    return { status: "blocked", reason: "blocked_window_title" };
  }
  if (allowedProcesses.size && !allowedProcesses.has(processName)) {
    return { status: "blocked", reason: "outside_allowed_processes" };
  }
  if (allowedTitles.size && !allowedTitles.has(windowTitle)) {
    return { status: "blocked", reason: "outside_allowed_titles" };
  }
  if (allowedProcesses.size || allowedTitles.size) {
    return { status: "whitelisted", reason: "allowed_match" };
  }
  return { status: "observed", reason: "no_restriction_match" };
}

function extractHardwareEntries(file, records) {
  const events = [];
  for (const record of records) {
    if (!record || typeof record !== "object") {
      continue;
    }

    if (record.type === "exam_state_marker") {
      events.push(makeEvent(file, {
        lane: "exam_state",
        timeIso: record.timestamp,
        remainingSeconds: record.remaining_seconds,
        severity: record.timer_state === "paused" ? "warning" : "info",
        summary: "Hardware monitor state marker: " + String(record.timer_state || "unknown"),
        status: String(record.timer_state || ""),
        tags: [String(record.timer_state || ""), "state-marker", "hardware-monitor"],
        raw: record,
      }));
      continue;
    }

    const isSnapshot = record.type === "snapshot_report";
    const counts = summarizeHardwareChange(record.changes || {});
    let summary = isSnapshot ? "Hardware snapshot" : "Hardware change";
    if (counts.total) {
      summary += " | " + counts.total + " delta(s)";
    }

    events.push(makeEvent(file, {
      lane: isSnapshot ? "snapshot" : "hardware_monitor",
      timeIso: record.timestamp,
      severity: counts.total ? "warning" : "info",
      summary,
      status: isSnapshot ? "snapshot" : "change",
      tags: [String(record.type || "hardware")],
      raw: {
        ...record,
        derived_change_counts: counts,
      },
    }));
  }
  return events;
}

function summarizeHardwareChange(changes) {
  const result = {
    added: 0,
    removed: 0,
    changed: 0,
    total: 0,
  };
  for (const value of Object.values(changes || {})) {
    if (!value) {
      continue;
    }
    if (Array.isArray(value.added)) {
      result.added += value.added.length;
    }
    if (Array.isArray(value.removed)) {
      result.removed += value.removed.length;
    }
    if (Array.isArray(value.changed)) {
      result.changed += value.changed.length;
    }
    if (value.before !== undefined || value.after !== undefined) {
      result.changed += 1;
    }
  }
  result.total = result.added + result.removed + result.changed;
  return result;
}

function extractExamStateEntries(file, records) {
  const events = [];
  for (const record of records) {
    if (!record || typeof record !== "object") {
      continue;
    }
    const timerState = String(record.timer_state || "unknown");
    const tags = [timerState, "exam-state"];
    events.push(makeEvent(file, {
      lane: "exam_state",
      timeIso: record.timestamp,
      remainingSeconds: record.remaining_seconds,
      severity: timerState.includes("paused") ? "warning" : "info",
      summary: "Exam state: " + timerState + (record.reason ? " | " + record.reason : ""),
      status: timerState,
      tags,
      raw: record,
    }));
  }
  return events;
}

function extractIncidentEntries(file, records) {
  const events = [];
  for (const record of records) {
    if (!record || typeof record !== "object") {
      continue;
    }
    const severity = String(record.severity || "").toLowerCase() || "warning";
    const summary = [
      String(record.rule_name || record.rule_id || "incident"),
      String(record.status || "event"),
      record.summary ? String(record.summary) : "",
    ].filter(Boolean).join(" | ");
    const tags = [
      "incident",
      String(record.status || "").toLowerCase(),
      String(record.rule_id || "").toLowerCase(),
    ];
    if (record.blocking) {
      tags.push("blocking");
    }
    events.push(makeEvent(file, {
      lane: "incidents",
      timeIso: record.server_received_at || record.reported_at || record.event_at || record.timestamp,
      severity,
      summary,
      status: String(record.status || ""),
      tags,
      raw: record,
    }));
  }
  return events;
}

function extractAuditEntries(file, records) {
  const events = [];
  for (const record of records) {
    if (!record || typeof record !== "object") {
      continue;
    }
    const action = String(record.action || record.type || "audit");
    events.push(makeEvent(file, {
      lane: "exam_state",
      timeIso: record.timestamp || record.event_at || record.server_received_at,
      severity: action.includes("forgive") ? "success" : "info",
      summary: "Audit: " + action + (record.reason ? " | " + record.reason : ""),
      status: action,
      tags: ["audit", action.toLowerCase()],
      raw: record,
    }));
  }
  return events;
}

function extractRuntimeLogEntries(file, records) {
  const events = [];
  for (const record of records) {
    if (!record || typeof record !== "object") {
      continue;
    }
    const severity = String(record.level || "info").toLowerCase();
    const summary = "[" + String(record.component || record.process || "log") + "] " + String(record.message || "");
    const tags = [
      "runtime-log",
      String(record.event_type || "").toLowerCase(),
      String(record.component || "").toLowerCase(),
    ].filter(Boolean);
    events.push(makeEvent(file, {
      lane: "runtime_log",
      timeIso: record.timestamp,
      severity,
      summary,
      status: String(record.event_type || ""),
      tags,
      raw: record,
    }));
  }
  return events;
}

function extractGenericEntries(file, payload) {
  const events = [];
  const records = Array.isArray(payload) ? payload : [payload];
  for (const record of records) {
    if (!record || typeof record !== "object") {
      continue;
    }
    const timeIso = record.timestamp || record.event_at || record.server_received_at || record.reported_at;
    if (!timeIso) {
      continue;
    }
    events.push(makeEvent(file, {
      lane: "other",
      timeIso,
      remainingSeconds: record.remaining_seconds ?? record.remaining_time,
      severity: "info",
      summary: String(record.type || record.action || file.name),
      status: String(record.type || record.action || ""),
      tags: ["generic"],
      raw: record,
    }));
  }
  return events;
}

function makeEvent(file, descriptor) {
  const timeIso = descriptor.timeIso ? String(descriptor.timeIso) : "";
  const timeMs = timeIso ? Date.parse(timeIso) : null;
  return {
    id: "event-" + appState.nextEventId++,
    filePath: file.path,
    fileName: file.name,
    category: file.category,
    lane: descriptor.lane || "other",
    timeIso,
    timeMs: Number.isFinite(timeMs) ? timeMs : null,
    remainingSeconds: descriptor.remainingSeconds !== undefined && descriptor.remainingSeconds !== null
      ? Number(descriptor.remainingSeconds)
      : null,
    severity: normalizeSeverity(descriptor.severity),
    summary: String(descriptor.summary || file.name),
    status: String(descriptor.status || ""),
    tags: Array.isArray(descriptor.tags) ? descriptor.tags.filter(Boolean).map(String) : [],
    raw: descriptor.raw ?? null,
  };
}

function normalizeSeverity(value) {
  const normalized = String(value || "info").toLowerCase();
  if (normalized === "error") {
    return "error";
  }
  if (normalized === "violation") {
    return "violation";
  }
  if (normalized === "warning" || normalized === "warn") {
    return "warning";
  }
  if (normalized === "success" || normalized === "allowed") {
    return "success";
  }
  return "info";
}

function summarize(allEvents, visibleEvents, policy) {
  return {
    fileCount: appState.files.length,
    eventCount: allEvents.length,
    visibleEventCount: visibleEvents.length,
    parseIssueCount: appState.files.reduce((count, file) => count + file.parseErrors.length, 0),
    blacklistedProcessCount: allEvents.filter((event) => event.tags.includes("blacklisted-process")).length,
    focusBlockedCount: allEvents.filter((event) => event.tags.includes("focus-blocked")).length,
    focusWhitelistedCount: allEvents.filter((event) => event.tags.includes("focus-whitelisted")).length,
    incidentCount: allEvents.filter((event) => event.lane === "incidents").length,
    pauseCount: allEvents.filter((event) => event.status.toLowerCase().includes("paused")).length,
    policySourceCount: policy.sources.length,
  };
}

function matchesFilters(event) {
  if (!appState.laneFilters.has(event.lane)) {
    return false;
  }
  if (appState.policyHitsOnly && !event.tags.some((tag) => tag.includes("blacklisted") || tag.includes("whitelist") || tag.includes("focus-blocked") || tag === "blocking")) {
    return false;
  }
  if (!appState.searchText) {
    return true;
  }
  const haystack = [
    event.summary,
    event.status,
    event.filePath,
    event.lane,
    ...(event.tags || []),
  ].join(" ").toLowerCase();
  return haystack.includes(appState.searchText);
}

function renderLoadStatus() {
  if (!appState.files.length) {
    loadStatus.textContent = "No data loaded yet.";
    return;
  }

  const summary = appState.derived.summary;
  const policy = appState.derived.policy;
  const parts = [
    summary.fileCount + " file(s) loaded",
    summary.eventCount + " event(s) derived",
  ];
  if (summary.parseIssueCount) {
    parts.push(summary.parseIssueCount + " parse issue(s)");
  }
  if (policy.policyVersion) {
    parts.push("policy " + policy.policyVersion);
  } else if (policy.processBlacklistEntries.length || policy.focusedWindow.enabled) {
    parts.push("rules loaded");
  } else {
    parts.push("no policy loaded");
  }
  loadStatus.textContent = parts.join(" | ");
}

function renderSummary() {
  const summary = appState.derived.summary;
  const cards = [
    ["Loaded files", summary.fileCount || 0],
    ["Parse issues", summary.parseIssueCount || 0],
    ["All events", summary.eventCount || 0],
    ["Visible events", summary.visibleEventCount || 0],
    ["Blacklist hits", summary.blacklistedProcessCount || 0],
    ["Focus blocked", summary.focusBlockedCount || 0],
    ["Incidents", summary.incidentCount || 0],
    ["Paused states", summary.pauseCount || 0],
  ];

  summaryGrid.innerHTML = "";
  for (const [label, value] of cards) {
    const card = document.createElement("div");
    card.className = "summary-card";
    const strong = document.createElement("strong");
    strong.textContent = String(value);
    const span = document.createElement("span");
    span.textContent = label;
    card.appendChild(strong);
    card.appendChild(span);
    summaryGrid.appendChild(card);
  }
}

function renderRules() {
  const policy = appState.derived.policy;
  rulesPanel.innerHTML = "";

  const overview = document.createElement("div");
  overview.className = "rule-box";
  overview.innerHTML = [
    "<h3>Policy Overview</h3>",
    "<div class=\"pill\">Policy version: " + escapeHtml(policy.policyVersion || "not provided") + "</div>",
    "<div class=\"pill\">Policy sources: " + String(policy.sources.length) + "</div>",
    "<div class=\"pill\">Blacklist version: " + escapeHtml(policy.processBlacklistVersion || "not provided") + "</div>",
    "<div class=\"pill\">Auto resume: " + String(Boolean(policy.session.auto_resume_on_reconnect)) + "</div>",
    "<div class=\"pill\">Remember settings: " + String(Boolean(policy.session.remember_settings)) + "</div>",
  ].join("");
  rulesPanel.appendChild(overview);

  const processRule = document.createElement("div");
  processRule.className = "rule-box";
  processRule.innerHTML = "<h3>Process Blacklist</h3>";
  processRule.appendChild(renderSimpleList(
    policy.processBlacklistEntries.length
      ? policy.processBlacklistEntries
      : ["No process blacklist entries loaded."]
  ));
  rulesPanel.appendChild(processRule);

  const focusRule = document.createElement("div");
  focusRule.className = "rule-box";
  focusRule.innerHTML = [
    "<h3>Focused Window Rule</h3>",
    "<div class=\"pill\">Enabled: " + String(Boolean(policy.focusedWindow.enabled)) + "</div>",
    "<div class=\"pill\">Severity: " + escapeHtml(policy.focusedWindow.severity || "warning") + "</div>",
    "<div class=\"pill\">Open after: " + String(policy.focusedWindow.openAfterConsecutive) + "</div>",
    "<div class=\"pill\">Resolve after: " + String(policy.focusedWindow.resolveAfterConsecutive) + "</div>",
  ].join("");
  focusRule.appendChild(renderNestedRuleLists(policy.focusedWindow));
  rulesPanel.appendChild(focusRule);
}

function renderSimpleList(items) {
  const list = document.createElement("ul");
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = String(item);
    list.appendChild(li);
  }
  return list;
}

function renderNestedRuleLists(focusedWindow) {
  const wrapper = document.createElement("div");
  const sections = [
    ["Allowed process names", focusedWindow.allowedProcessNames],
    ["Allowed window titles", focusedWindow.allowedWindowTitles],
    ["Blocked process names", focusedWindow.blockedProcessNames],
    ["Blocked window titles", focusedWindow.blockedWindowTitles],
  ];
  for (const [title, values] of sections) {
    const box = document.createElement("div");
    box.className = "rule-box";
    const heading = document.createElement("h3");
    heading.textContent = title;
    box.appendChild(heading);
    box.appendChild(renderSimpleList(values && values.length ? values : ["None"]));
    wrapper.appendChild(box);
  }
  return wrapper;
}

function renderFileList() {
  if (!appState.files.length) {
    fileList.textContent = "No files loaded.";
    return;
  }

  const lines = [];
  for (const file of appState.files) {
    lines.push(file.path + " [" + file.category + "]");
    if (file.parseErrors.length) {
      for (const error of file.parseErrors) {
        lines.push("  ! " + error);
      }
    }
  }
  fileList.textContent = lines.join("\n");
}

function renderTimeline() {
  const events = appState.derived.visibleEvents;
  const laneIndex = new Map(LANE_ORDER.map((lane, index) => [lane.id, index]));
  const width = Math.max(timelineSvg.parentElement.clientWidth || 1200, 1200, 240 + (events.length * 14));
  const leftMargin = 160;
  const rightMargin = 30;
  const topMargin = 30;
  const laneHeight = 64;
  const height = topMargin + 22 + (LANE_ORDER.length * laneHeight);
  const axisWidth = width - leftMargin - rightMargin;
  const timedEvents = events.filter((event) => event.timeMs !== null);
  const minMs = timedEvents.length ? Math.min(...timedEvents.map((event) => event.timeMs)) : null;
  const maxMs = timedEvents.length ? Math.max(...timedEvents.map((event) => event.timeMs)) : null;
  const spanMs = minMs !== null && maxMs !== null ? Math.max(1, maxMs - minMs) : 1;

  timelineSvg.setAttribute("viewBox", "0 0 " + width + " " + height);
  timelineSvg.innerHTML = "";

  const background = svgElement("rect", {
    x: 0,
    y: 0,
    width,
    height,
    fill: "transparent",
  });
  timelineSvg.appendChild(background);

  for (let index = 0; index < LANE_ORDER.length; index += 1) {
    const lane = LANE_ORDER[index];
    const y = topMargin + (index * laneHeight);
    timelineSvg.appendChild(svgElement("line", {
      x1: leftMargin,
      y1: y + laneHeight,
      x2: width - rightMargin,
      y2: y + laneHeight,
      stroke: "var(--border)",
      "stroke-width": 1,
      opacity: 0.45,
    }));

    const label = svgElement("text", {
      x: 12,
      y: y + (laneHeight / 2) + 4,
      class: "lane-label",
    });
    label.textContent = lane.label;
    timelineSvg.appendChild(label);
  }

  if (timedEvents.length) {
    const tickCount = Math.min(8, Math.max(2, Math.floor(axisWidth / 150)));
    for (let tick = 0; tick <= tickCount; tick += 1) {
      const ratio = tick / tickCount;
      const x = leftMargin + (axisWidth * ratio);
      const ms = minMs + (spanMs * ratio);
      timelineSvg.appendChild(svgElement("line", {
        x1: x,
        y1: topMargin - 12,
        x2: x,
        y2: height - 18,
        stroke: "var(--border)",
        "stroke-width": 1,
        opacity: 0.25,
      }));
      const text = svgElement("text", {
        x,
        y: 18,
        class: "axis-label",
        "text-anchor": tick === 0 ? "start" : tick === tickCount ? "end" : "middle",
      });
      text.textContent = formatShortDateTime(ms);
      timelineSvg.appendChild(text);
    }
  }

  const laneStacks = new Map();
  for (const event of events) {
    const lane = laneIndex.get(event.lane) ?? laneIndex.get("other");
    const laneKey = event.lane + "::" + (event.timeMs ?? "no-time");
    const stack = laneStacks.get(laneKey) || 0;
    laneStacks.set(laneKey, stack + 1);
    const x = event.timeMs === null || minMs === null
      ? leftMargin + 8 + (stack * 8)
      : leftMargin + (((event.timeMs - minMs) / spanMs) * axisWidth);
    const y = topMargin + (lane * laneHeight) + 18 + ((stack % 4) * 10);
    const marker = buildMarker(event, x, y);
    timelineSvg.appendChild(marker);
  }

  timelineMeta.textContent = String(events.length) + " visible event(s)";
  if (timedEvents.length) {
    timeRangeLabel.textContent = formatLongDateTime(minMs) + " to " + formatLongDateTime(maxMs);
  } else {
    timeRangeLabel.textContent = "No timestamped events loaded yet.";
  }
}

function buildMarker(event, x, y) {
  const color = severityColor(event.severity);
  let marker;
  if (event.lane === "incidents") {
    marker = svgElement("rect", {
      x: x - 5,
      y: y - 5,
      width: 10,
      height: 10,
      fill: color,
      rx: 1,
      class: markerClass(event),
    });
  } else if (event.lane === "exam_state") {
    marker = svgElement("polygon", {
      points: [x, y - 6, x + 6, y, x, y + 6, x - 6, y].join(" "),
      fill: color,
      class: markerClass(event),
    });
  } else if (event.lane === "snapshot") {
    marker = svgElement("rect", {
      x: x - 4,
      y: y - 4,
      width: 8,
      height: 8,
      fill: color,
      class: markerClass(event),
    });
  } else {
    marker = svgElement("circle", {
      cx: x,
      cy: y,
      r: 5,
      fill: color,
      class: markerClass(event),
    });
  }

  marker.dataset.eventId = event.id;
  marker.addEventListener("click", () => {
    appState.selectedEventId = event.id;
    renderAll();
  });

  const title = svgElement("title");
  title.textContent = [
    event.summary,
    event.timeIso || "no timestamp",
    "Lane: " + laneLabel(event.lane),
    event.filePath,
  ].join("\n");
  marker.appendChild(title);
  return marker;
}

function markerClass(event) {
  return "timeline-event" + (event.id === appState.selectedEventId ? " selected" : "");
}

function severityColor(severity) {
  switch (severity) {
    case "violation":
    case "error":
      return "var(--danger)";
    case "warning":
      return "var(--warning)";
    case "success":
      return "var(--success)";
    default:
      return "var(--accent)";
  }
}

function renderEventTable() {
  const rows = appState.derived.visibleEvents;
  eventRows.innerHTML = "";
  if (!rows.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 5;
    cell.className = "empty-state";
    cell.textContent = "No events match the current filters.";
    row.appendChild(cell);
    eventRows.appendChild(row);
    return;
  }

  for (const event of rows) {
    const row = document.createElement("tr");
    if (event.id === appState.selectedEventId) {
      row.classList.add("selected");
    }
    row.addEventListener("click", () => {
      appState.selectedEventId = event.id;
      renderAll();
    });

    appendCell(row, event.timeMs !== null ? formatLongDateTime(event.timeMs) : "No timestamp");
    appendCell(row, laneLabel(event.lane));
    appendCell(row, event.severity);
    appendCell(row, event.summary);
    appendCell(row, event.filePath);
    eventRows.appendChild(row);
  }
}

function appendCell(row, text) {
  const cell = document.createElement("td");
  cell.textContent = text;
  row.appendChild(cell);
}

function renderDetails() {
  const event = appState.derived.visibleEvents.find((entry) => entry.id === appState.selectedEventId)
    || appState.derived.events.find((entry) => entry.id === appState.selectedEventId)
    || null;

  detailBadges.innerHTML = "";
  if (!event) {
    detailTitle.textContent = "Event Details";
    detailMeta.textContent = "No event selected.";
    detailPane.textContent = "Select a timeline marker or event row.";
    return;
  }

  detailTitle.textContent = event.summary;
  detailMeta.textContent = [
    event.timeMs !== null ? formatLongDateTime(event.timeMs) : "No timestamp",
    "Lane: " + laneLabel(event.lane),
    "Severity: " + event.severity,
    event.remainingSeconds !== null ? "Remaining: " + formatRemaining(event.remainingSeconds) : "",
    event.filePath,
  ].filter(Boolean).join(" | ");

  const badges = [event.severity, event.status, ...event.tags].filter(Boolean);
  for (const badgeText of badges) {
    const badge = document.createElement("span");
    badge.className = "badge " + badgeClassForText(badgeText);
    badge.textContent = badgeText;
    detailBadges.appendChild(badge);
  }

  detailPane.textContent = JSON.stringify({
    summary: event.summary,
    time: event.timeIso || null,
    remaining_seconds: event.remainingSeconds,
    lane: event.lane,
    severity: event.severity,
    status: event.status,
    tags: event.tags,
    source_file: event.filePath,
    raw: event.raw,
  }, null, 2);
}

function badgeClassForText(text) {
  const lowered = String(text || "").toLowerCase();
  if (lowered.includes("violation") || lowered.includes("error") || lowered.includes("blocked") || lowered.includes("blacklisted")) {
    return "violation";
  }
  if (lowered.includes("warning") || lowered.includes("paused")) {
    return "warning";
  }
  if (lowered.includes("success") || lowered.includes("allowed") || lowered.includes("whitelisted") || lowered.includes("resolved")) {
    return "success";
  }
  return "info";
}

function svgElement(tagName, attrs = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tagName);
  for (const [key, value] of Object.entries(attrs)) {
    element.setAttribute(key, String(value));
  }
  return element;
}

function basename(value) {
  return String(value || "").split(/[\\/]/).pop() || "";
}

function normalizeName(value) {
  return String(value || "").trim().toLowerCase();
}

function laneLabel(laneId) {
  return (LANE_ORDER.find((lane) => lane.id === laneId) || { label: laneId }).label;
}

function formatRemaining(value) {
  const seconds = Math.max(0, Number(value) || 0);
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return String(minutes).padStart(2, "0") + ":" + String(remainder).padStart(2, "0");
}

function formatShortDateTime(ms) {
  const date = new Date(ms);
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatLongDateTime(ms) {
  const date = new Date(ms);
  return date.toLocaleString([], {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function toInt(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.trunc(number) : fallback;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
