const state = {
      summary: null,
      detail: null,
      selectedId: "",
      tab: "incidents",
      activeReplayKey: "",
      activeReplayUrl: "",
      conversionTimer: null
    };

    const els = {
      rootLine: document.getElementById("rootLine"),
      message: document.getElementById("message"),
      refreshButton: document.getElementById("refreshButton"),
      stats: document.getElementById("stats"),
      search: document.getElementById("search"),
      studentList: document.getElementById("studentList"),
      detailTitle: document.getElementById("detailTitle"),
      detailSub: document.getElementById("detailSub"),
      studentActions: document.getElementById("studentActions"),
      detailBody: document.getElementById("detailBody")
    };

    function esc(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function url(value) {
      return encodeURIComponent(String(value ?? ""));
    }

    function setMessage(text, kind = "") {
      els.message.textContent = text || "";
      els.message.style.color = kind === "error" ? "var(--danger)" : kind === "ok" ? "var(--ok)" : "var(--muted)";
    }

    function countText(count, label) {
      return `${Number(count || 0).toLocaleString()} ${label}`;
    }

    function sourceButton(ref) {
      if (!ref) return "";
      return `<a class="button small" href="/api/source-json?ref=${url(ref)}&download=1" download>JSON</a>`;
    }

    function deltaText(value) {
      if (value === null || value === undefined || value === "") return "";
      const seconds = Number(value);
      if (!Number.isFinite(seconds)) return "";
      if (seconds < 60) return `${Math.round(seconds)}s`;
      return `${(seconds / 60).toFixed(1)}m`;
    }

    function matchReasonText(reason) {
      if (reason === "incident_id") return "incident";
      if (reason === "near_time") return "time";
      return reason || "";
    }

    function replayMatchCell(matches = [], total = 0) {
      if (!matches.length) return "";
      const buttons = matches.slice(0, 2).map(match => {
        const delta = deltaText(match.delta_seconds);
        const reason = matchReasonText(match.match_reason);
        const label = [match.converted ? "MP4" : "Replay", delta || reason].filter(Boolean).join(" ");
        const title = match.path || [match.zip_path, match.member].filter(Boolean).join("!");
        return `<button type="button" class="small open-replay" data-key="${esc(match.replay_key)}" title="${esc(title)}">${esc(label)}</button>`;
      }).join("");
      const hiddenCount = Math.max(0, Number(total || matches.length) - Math.min(matches.length, 2));
      return `<div class="match-stack">${buttons}${hiddenCount ? `<span class="student-sub">+${esc(hiddenCount)} more</span>` : ""}</div>`;
    }

    function incidentMatchBadge(count) {
      return count ? `<span class="badge warn">${esc(count)} incident${count === 1 ? "" : "s"}</span>` : "";
    }

    async function fetchJson(path, options = {}) {
      const response = await fetch(path, options);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || `${response.status} ${response.statusText}`);
      }
      return data;
    }

    async function loadSummary(refresh = false) {
      setMessage("Loading...");
      try {
        state.summary = await fetchJson(`/api/summary${refresh ? "?refresh=1" : ""}`);
        els.rootLine.textContent = state.summary.data_root;
        renderStats();
        renderStudents();
        setMessage(`Updated ${state.summary.generated_at}`, "ok");
        if (state.selectedId) {
          await loadStudent(state.selectedId, false);
        }
      } catch (error) {
        setMessage(error.message, "error");
      }
    }

    function renderStats() {
      const c = state.summary?.counts || {};
      const ffmpeg = state.summary?.ffmpeg || {};
      els.stats.innerHTML = [
        stat(c.students, "Students"),
        stat(c.incidents, "Known incidents"),
        stat(c.retro_blacklist_matches, "Blacklist matches"),
        stat(c.title_history_entries, "Titlebar rows"),
        stat(c.replays, "Replays"),
        stat(ffmpeg.available ? "Yes" : "No", "FFmpeg")
      ].join("");
    }

    function stat(value, label) {
      return `<div class="stat"><strong>${esc(value ?? 0)}</strong><span>${esc(label)}</span></div>`;
    }

    function renderStudents() {
      const filter = els.search.value.trim().toLowerCase();
      const rows = (state.summary?.students || []).filter(student => {
        const text = [
          student.login_id,
          student.client_id,
          student.computer_name,
          student.session_state
        ].join(" ").toLowerCase();
        return !filter || text.includes(filter);
      });
      if (!rows.length) {
        els.studentList.innerHTML = `<div class="empty">No matching students.</div>`;
        return;
      }
      els.studentList.innerHTML = rows.map(student => {
        const id = student.id;
        const active = id === state.selectedId ? " active" : "";
        const riskClass = student.retro_blacklist_match_count || student.known_blacklist_incident_count ? "danger" : student.title_policy_hit_count ? "warn" : "ok";
        return `
          <button class="student-row${active}" type="button" data-id="${esc(id)}">
            <div class="student-main">
              <div class="student-title">${esc(student.login_id || "(no login)")}</div>
              <div class="student-sub">${esc(student.computer_name || "no computer")} | ${esc(student.client_id || "")}</div>
              <div class="student-sub">${esc(student.session_state || "no session")} ${student.submitted_at ? "| submitted " + esc(student.submitted_at) : ""}</div>
            </div>
            <div class="badges">
              <span class="badge ${riskClass}">${esc(student.incident_count)} inc</span>
              <span class="badge ${student.retro_blacklist_match_count ? "danger" : ""}">${esc(student.retro_blacklist_match_count)} retro</span>
              <span class="badge ${student.replay_count ? "ok" : ""}">${esc(student.replay_count)} replay</span>
            </div>
          </button>
        `;
      }).join("");
      for (const button of els.studentList.querySelectorAll(".student-row")) {
        button.addEventListener("click", () => loadStudent(button.dataset.id, true));
      }
    }

    async function loadStudent(id, resetTab) {
      if (!id) return;
      state.selectedId = id;
      if (resetTab) {
        state.tab = "incidents";
        state.activeReplayKey = "";
        state.activeReplayUrl = "";
      }
      renderStudents();
      setMessage("Loading student...");
      try {
        state.detail = await fetchJson(`/api/student?id=${url(id)}`);
        renderDetail();
        setMessage("");
      } catch (error) {
        setMessage(error.message, "error");
      }
    }

    function renderDetail() {
      const detail = state.detail;
      const student = detail.student;
      els.detailTitle.textContent = student.login_id || student.client_id || "Student";
      els.detailSub.textContent = [student.computer_name, student.client_id].filter(Boolean).join(" | ");
      els.studentActions.innerHTML = `
        <a class="button primary" href="/api/export?id=${url(student.id)}" download>Export student ZIP</a>
      `;
      els.detailBody.innerHTML = `
        ${renderMeta(student)}
        ${renderTabs()}
        <div id="tabContent">${renderTabContent()}</div>
      `;
      for (const button of els.detailBody.querySelectorAll(".tab")) {
        button.addEventListener("click", () => {
          state.tab = button.dataset.tab;
          renderDetail();
        });
      }
      bindTabActions();
    }

    function renderMeta(student) {
      return `
        <div class="student-meta">
          ${meta("Known incidents", student.incident_count)}
          ${meta("Retro blacklist", student.retro_blacklist_match_count)}
          ${meta("Titlebar hits", student.title_policy_hit_count)}
          ${meta("Processes seen", student.process_count)}
          ${meta("Submissions", student.submission_count)}
          ${meta("Replays", student.replay_count)}
          ${meta("Submitted", student.submitted_at || "-")}
          ${meta("State", student.session_state || "-")}
        </div>
      `;
    }

    function meta(label, value) {
      return `<div class="meta"><span>${esc(label)}</span><strong title="${esc(value)}">${esc(value)}</strong></div>`;
    }

    function renderTabs() {
      const tabs = [
        ["incidents", "Incidents"],
        ["blacklist", "Blacklist"],
        ["titlebar", "Titlebar"],
        ["processes", "Processes"],
        ["replays", "Replays"],
        ["files", "Files"]
      ];
      return `<div class="tabs">${tabs.map(([id, label]) => `
        <button class="tab ${state.tab === id ? "active" : ""}" type="button" data-tab="${id}">${esc(label)}</button>
      `).join("")}</div>`;
    }

    function renderTabContent() {
      if (!state.detail) return "";
      if (state.tab === "incidents") return renderIncidents();
      if (state.tab === "blacklist") return renderBlacklist();
      if (state.tab === "titlebar") return renderTitlebar();
      if (state.tab === "processes") return renderProcesses();
      if (state.tab === "replays") return renderReplays();
      if (state.tab === "files") return renderFiles();
      return "";
    }

    function table(headers, rows, emptyText) {
      if (!rows.length) return `<div class="empty">${esc(emptyText)}</div>`;
      return `
        <div class="table-wrap">
          <table>
            <thead><tr>${headers.map(h => `<th style="width:${h.width || "auto"}">${esc(h.label)}</th>`).join("")}</tr></thead>
            <tbody>${rows.map(row => `<tr>${headers.map(h => `<td data-label="${esc(h.label)}">${row[h.key] ?? ""}</td>`).join("")}</tr>`).join("")}</tbody>
          </table>
        </div>
      `;
    }

    function renderIncidents() {
      const rows = state.detail.incidents.slice(0, 350).map(item => ({
        at: esc(item.at || item.event_at || item.timestamp || item.server_received_at || ""),
        rule: `<code>${esc(item.rule_id || item.event_type || "")}</code>`,
        status: esc(item.status || ""),
        severity: esc(item.severity || ""),
        summary: esc(item.summary || ""),
        replays: replayMatchCell(item.matched_replays || [], item.matched_replay_count || 0),
        source: sourceButton(item.source_ref)
      }));
      return table(
        [
          {key: "at", label: "Time", width: "170px"},
          {key: "rule", label: "Rule", width: "150px"},
          {key: "status", label: "Status", width: "110px"},
          {key: "severity", label: "Severity", width: "90px"},
          {key: "summary", label: "Summary"},
          {key: "replays", label: "Replay", width: "170px"},
          {key: "source", label: "Source", width: "90px"}
        ],
        rows,
        "No known incidents for this student."
      );
    }

    function renderBlacklist() {
      const matches = state.detail.retro_blacklist_matches || [];
      const rows = matches.slice(0, 500).map(item => ({
        at: esc(item.timestamp || ""),
        match: `<code>${esc(item.matched_blacklist_entry || "")}</code>`,
        process: esc(item.process_name || ""),
        user: esc(item.process_username || ""),
        path: `<code>${esc(item.process_path || "")}</code>`,
        source: sourceButton(item.source_ref)
      }));
      const current = (state.detail.blacklist || []).map(item => `<span class="badge">${esc(item)}</span>`).join(" ");
      return `
        <div class="panel" style="margin-bottom:12px">
          <div class="panel-body">
            <h3>Current server blacklist</h3>
            <div>${current || '<span class="student-sub">No entries.</span>'}</div>
          </div>
        </div>
        ${table(
          [
            {key: "at", label: "Time", width: "170px"},
            {key: "match", label: "Matched", width: "130px"},
            {key: "process", label: "Process", width: "170px"},
            {key: "user", label: "User", width: "150px"},
            {key: "path", label: "Path"},
            {key: "source", label: "Source", width: "90px"}
          ],
          rows,
          "No retroactive blacklist matches found in server-side runtime files."
        )}
      `;
    }

    function renderTitlebar() {
      const rows = (state.detail.title_history || []).slice(0, 500).map(item => {
        const statusClass = item.policy_status === "ok" ? "ok" : item.policy_status ? "warn" : "";
        return {
          at: esc(item.timestamp || ""),
          status: `<span class="badge ${statusClass}">${esc(item.policy_status || "-")}</span>`,
          process: esc(item.process_name || ""),
          title: esc(item.window_title || ""),
          match: esc(item.matched_pattern || item.matched_rule || ""),
          source: sourceButton(item.source_ref)
        };
      });
      return table(
        [
          {key: "at", label: "Time", width: "170px"},
          {key: "status", label: "Policy", width: "110px"},
          {key: "process", label: "Process", width: "160px"},
          {key: "title", label: "Titlebar"},
          {key: "match", label: "Match", width: "170px"},
          {key: "source", label: "Source", width: "90px"}
        ],
        rows,
        "No titlebar history found in uploaded runtime files."
      );
    }

    function renderProcesses() {
      const rows = (state.detail.processes || []).map(item => ({
        count: esc(item.count || 0),
        process: esc(item.process_name || item.normalized_process_name || ""),
        first: esc(item.first_seen || ""),
        last: esc(item.last_seen || ""),
        user: esc(item.process_username || ""),
        path: `<code>${esc(item.process_path || "")}</code>`,
        source: sourceButton(item.source_ref)
      }));
      return table(
        [
          {key: "count", label: "Count", width: "70px"},
          {key: "process", label: "Process", width: "180px"},
          {key: "first", label: "First", width: "165px"},
          {key: "last", label: "Last", width: "165px"},
          {key: "user", label: "User", width: "150px"},
          {key: "path", label: "Path"},
          {key: "source", label: "Source", width: "90px"}
        ],
        rows,
        "No process runtime files found for this student."
      );
    }

    function replayUrl(replay, download = false) {
      if (replay.container === "zip") {
        return `/api/zip-media?zip=${url(replay.zip_path)}&member=${url(replay.member)}${download ? "&download=1" : ""}`;
      }
      return `${download ? "/api/download" : "/api/media"}?path=${url(replay.path)}`;
    }

    function replayKey(replay) {
      return replay.container === "zip" ? `${replay.zip_path}#${replay.member}` : replay.path;
    }

    function renderReplays() {
      const replays = state.detail.replays || [];
      if (!replays.length) return `<div class="empty">No replay files found under server data.</div>`;
      const active = state.activeReplayKey ? replays.find(item => replayKey(item) === state.activeReplayKey) : null;
      state.activeReplayUrl = active ? replayUrl(active) : "";
      return `
        <div class="split">
          <div class="replay-list">
            ${replays.map(replay => renderReplayItem(replay)).join("")}
          </div>
          ${active ? renderReplayPlayer(active, replays) : renderReplayPlaceholder()}
        </div>
      `;
    }

    function renderReplayPlaceholder() {
      return `
        <div class="panel">
          <div class="panel-body">
            <div class="empty">Select a replay to load the video player.</div>
          </div>
        </div>
      `;
    }

    function renderReplayPlayer(active, replays) {
      const activePath = active.container === "zip" ? active.zip_path + "!" + active.member : active.path;
      const convertedReplay = active.converted_path
        ? replays.find(item => item.path === active.converted_path)
        : null;
      const canConvert = active.container === "file" && !active.converted && !active.has_converted;
      return `
        <div>
          <video id="replayPlayer" controls preload="none" src="${esc(state.activeReplayUrl)}"></video>
          <div class="panel" style="margin-top:12px">
            <div class="panel-body">
              <h3>${esc(active.name || "Replay")} ${active.converted ? '<span class="badge ok">converted</span>' : ''}</h3>
              <div class="student-sub">${esc(activePath)}</div>
              ${active.converted && active.original_path ? `<div class="student-sub">Original: <code>${esc(active.original_path)}</code></div>` : ""}
              ${active.has_converted ? `<div class="student-sub">Converted copy: <code>${esc(active.converted_path)}</code></div>` : ""}
              ${active.matched_incident_count ? `<div class="student-sub">Matched incidents: ${esc(active.matched_incident_count)}</div>` : ""}
              <div class="replay-actions">
                <a class="button" href="${esc(replayUrl(active, true))}" download>Download</a>
                ${convertedReplay ? `<button type="button" class="open-replay" data-key="${esc(replayKey(convertedReplay))}">Open converted</button>` : ""}
                ${convertedReplay ? `<a class="button" href="${esc(replayUrl(convertedReplay, true))}" download>Download converted</a>` : ""}
                ${canConvert ? `<button class="primary" type="button" id="convertButton" data-path="${esc(active.path)}">Convert to compatible MP4</button>` : ""}
              </div>
              ${renderReplayIncidentMatches(active)}
              <div id="convertProgress" class="progress hidden"><div id="convertProgressBar"></div></div>
              <div id="convertLog" class="log hidden"></div>
            </div>
          </div>
        </div>
      `;
    }

    function renderReplayIncidentMatches(replay) {
      const matches = replay.matched_incidents || [];
      if (!matches.length) return "";
      const visibleMatches = matches.slice(0, 8);
      const rows = visibleMatches.map(match => {
        const delta = deltaText(match.delta_seconds);
        const reason = matchReasonText(match.match_reason);
        return `
          <div class="match-row">
            <div class="match-row-main">
              <strong>${esc(match.rule_id || "incident")}</strong>
              <span>${esc(match.at || "")}</span>
              <span>${esc([match.status, match.severity].filter(Boolean).join(" | "))}</span>
              <div>${esc(match.summary || "")}</div>
            </div>
            <div class="match-row-actions">
              <span class="badge">${esc(delta || reason)}</span>
              ${sourceButton(match.source_ref)}
            </div>
          </div>
        `;
      }).join("");
      const hiddenCount = Math.max(0, Number(replay.matched_incident_count || matches.length) - visibleMatches.length);
      return `
        <div class="match-list">
          <h3>Matched incidents</h3>
          ${rows}
          ${hiddenCount ? `<div class="student-sub">+${esc(hiddenCount)} more matches</div>` : ""}
        </div>
      `;
    }

    function renderReplayItem(replay) {
      const key = replayKey(replay);
      const active = key === state.activeReplayKey ? " active" : "";
      const path = replay.container === "zip" ? `${replay.zip_path}!${replay.member}` : replay.path;
      return `
        <div class="replay-item${active}">
          <div class="replay-name">${esc(replay.name || "replay")} ${replay.converted ? '<span class="badge ok">converted</span>' : ''} ${replay.has_converted ? '<span class="badge ok">has MP4</span>' : ''} ${incidentMatchBadge(replay.matched_incident_count || 0)}</div>
          <div class="student-sub">${esc(replay.kind || replay.container)} | ${esc(replay.size_label || "")} | ${esc(replay.replay_at || replay.modified_at || "")}</div>
          <div class="student-sub"><code>${esc(path)}</code></div>
          ${replay.converted && replay.original_path ? `<div class="student-sub">Original: <code>${esc(replay.original_path)}</code></div>` : ""}
          <div class="replay-actions">
            <button type="button" class="open-replay" data-key="${esc(key)}">Load</button>
            <a class="button" href="${esc(replayUrl(replay, true))}" download>Download</a>
          </div>
        </div>
      `;
    }

    function renderFiles() {
      const submissions = state.detail.submissions || [];
      const replayRows = (state.detail.replays || []).map(item => ({
        type: esc(item.container || "file"),
        name: esc(item.name || ""),
        size: esc(item.size_label || ""),
        path: `<code>${esc(item.container === "zip" ? item.zip_path + "!" + item.member : item.path)}</code>`,
        action: item.container === "zip"
          ? `<a class="button" href="${esc(replayUrl(item, true))}" download>Download</a>`
          : `<a class="button" href="/api/download?path=${url(item.path)}" download>Download</a>`
      }));
      const submissionRows = submissions.map(item => ({
        type: "submission",
        name: esc(item.name || ""),
        size: esc(item.size_label || ""),
        path: `<code>${esc(item.path || "")}</code>`,
        action: item.path ? `<a class="button" href="/api/download?path=${url(item.path)}" download>Download</a>` : ""
      }));
      return table(
        [
          {key: "type", label: "Type", width: "120px"},
          {key: "name", label: "Name", width: "260px"},
          {key: "size", label: "Size", width: "100px"},
          {key: "path", label: "Path"},
          {key: "action", label: "", width: "120px"}
        ],
        [...submissionRows, ...replayRows],
        "No server-side files found for this student."
      );
    }

    function bindTabActions() {
      for (const button of els.detailBody.querySelectorAll(".open-replay")) {
        button.addEventListener("click", () => {
          state.activeReplayKey = button.dataset.key;
          state.tab = "replays";
          renderDetail();
        });
      }
      const convertButton = document.getElementById("convertButton");
      if (convertButton) {
        convertButton.addEventListener("click", () => convertReplay(convertButton.dataset.path));
      }
    }

    async function convertReplay(path) {
      const log = document.getElementById("convertLog");
      const button = document.getElementById("convertButton");
      const progress = document.getElementById("convertProgress");
      const progressBar = document.getElementById("convertProgressBar");
      if (!path || !log || !button) return;
      log.classList.remove("hidden");
      progress?.classList.remove("hidden");
      if (progressBar) progressBar.style.width = "0%";
      log.textContent = "Starting ffmpeg conversion...";
      button.disabled = true;
      try {
        const job = await fetchJson("/api/convert", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({path})
        });
        await pollConversion(job);
      } catch (error) {
        log.textContent = error.message;
        progress?.classList.add("hidden");
        button.disabled = false;
      }
    }

    async function pollConversion(job) {
      const log = document.getElementById("convertLog");
      const progress = document.getElementById("convertProgress");
      const progressBar = document.getElementById("convertProgressBar");
      const button = document.getElementById("convertButton");
      let current = job;
      while (current && current.id && !["done", "error"].includes(current.status)) {
        if (progressBar) progressBar.style.width = `${Math.max(0, Math.min(100, current.percent || 0))}%`;
        if (log) {
          log.textContent = [
            current.message || current.status,
            `Progress: ${current.percent || 0}%`,
            current.output_path ? `Output: ${current.output_path}` : "",
            "",
            current.stderr_tail || ""
          ].filter(Boolean).join("\n");
        }
        await new Promise(resolve => setTimeout(resolve, 900));
        current = await fetchJson(`/api/convert-status?id=${url(current.id)}`);
      }

      if (progressBar) progressBar.style.width = `${Math.max(0, Math.min(100, current?.percent || 100))}%`;
      if (current?.status === "done") {
        if (log) {
          log.textContent = [
            current.message || "Conversion complete.",
            `Output: ${current.output_path}`,
            `Seconds: ${current.seconds || 0}`,
            "",
            current.stderr_tail || ""
          ].join("\n");
        }
        await loadSummary(true);
        state.activeReplayKey = current.output_path;
        state.tab = "replays";
        await loadStudent(state.selectedId, false);
        if (button) button.disabled = true;
      } else if (current?.status === "error") {
        if (log) {
          log.textContent = [
            current.message || "Conversion failed.",
            current.stderr_tail || ""
          ].join("\n");
        }
        if (button) button.disabled = false;
      }
    }

    els.refreshButton.addEventListener("click", () => loadSummary(true));
    els.search.addEventListener("input", renderStudents);

    loadSummary(false);
