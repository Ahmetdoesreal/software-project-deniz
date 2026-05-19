const state = {
      summary: null,
      detail: null,
      selectedId: "",
      tab: "incidents",
      activeReplayKey: "",
      activeReplayUrl: ""
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
            <tbody>${rows.map(row => `<tr>${headers.map(h => `<td>${row[h.key] ?? ""}</td>`).join("")}</tr>`).join("")}</tbody>
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
        source: sourceButton(item.source_ref)
      }));
      return table(
        [
          {key: "at", label: "Time", width: "170px"},
          {key: "rule", label: "Rule", width: "150px"},
          {key: "status", label: "Status", width: "110px"},
          {key: "severity", label: "Severity", width: "90px"},
          {key: "summary", label: "Summary"},
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
        pid: esc(item.pid || ""),
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
            {key: "pid", label: "PID", width: "80px"},
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
      const rows = (state.detail.processes || []).slice(0, 500).map(item => ({
        count: esc(item.count || 0),
        process: esc(item.process_name || item.normalized_process_name || ""),
        first: esc(item.first_seen || ""),
        last: esc(item.last_seen || ""),
        user: esc(item.process_username || ""),
        pids: esc((item.pids || []).join(", ")),
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
          {key: "pids", label: "PIDs", width: "120px"},
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
      if (!state.activeReplayKey) {
        state.activeReplayKey = replayKey(replays[0]);
        state.activeReplayUrl = replayUrl(replays[0]);
      }
      const active = replays.find(item => replayKey(item) === state.activeReplayKey) || replays[0];
      state.activeReplayUrl = replayUrl(active);
      return `
        <div class="split">
          <div class="replay-list">
            ${replays.map(replay => renderReplayItem(replay)).join("")}
          </div>
          <div>
            <video id="replayPlayer" controls preload="metadata" src="${esc(state.activeReplayUrl)}"></video>
            <div class="panel" style="margin-top:12px">
              <div class="panel-body">
                <h3>${esc(active.name || "Replay")}</h3>
                <div class="student-sub">${esc(active.container === "zip" ? active.zip_path + "!" + active.member : active.path)}</div>
                <div class="replay-actions">
                  <a class="button" href="${esc(replayUrl(active, true))}" download>Download</a>
                  ${active.container === "file" ? `<button class="primary" type="button" id="convertButton" data-path="${esc(active.path)}">Convert to compatible MP4</button>` : ""}
                </div>
                <div id="convertLog" class="log hidden"></div>
              </div>
            </div>
          </div>
        </div>
      `;
    }

    function renderReplayItem(replay) {
      const key = replayKey(replay);
      const active = key === state.activeReplayKey ? " active" : "";
      const path = replay.container === "zip" ? `${replay.zip_path}!${replay.member}` : replay.path;
      return `
        <div class="replay-item${active}">
          <div class="replay-name">${esc(replay.name || "replay")}</div>
          <div class="student-sub">${esc(replay.kind || replay.container)} | ${esc(replay.size_label || "")} | ${esc(replay.modified_at || "")}</div>
          <div class="student-sub"><code>${esc(path)}</code></div>
          <div class="replay-actions">
            <button type="button" class="open-replay" data-key="${esc(key)}">Open</button>
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
      if (!path || !log || !button) return;
      log.classList.remove("hidden");
      log.textContent = "Running ffmpeg conversion...";
      button.disabled = true;
      try {
        const result = await fetchJson("/api/convert", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({path})
        });
        log.textContent = [
          `Return code: ${result.returncode}`,
          `Output: ${result.output_path}`,
          `Seconds: ${result.seconds}`,
          "",
          result.stderr_tail || ""
        ].join("\n");
        await loadSummary(true);
        state.activeReplayKey = result.output_path;
        state.tab = "replays";
        await loadStudent(state.selectedId, false);
      } catch (error) {
        log.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    }

    els.refreshButton.addEventListener("click", () => loadSummary(true));
    els.search.addEventListener("input", renderStudents);

    loadSummary(false);
