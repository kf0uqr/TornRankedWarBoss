// ==UserScript==
// @name         Torn War Manager - Live War Overlay
// @namespace    torn-ranked-war-boss
// @version      1.0.0
// @description  Read-only overlay on the faction page showing enemy online probability, landing ETA, and estimated stats from your Torn Ranked War Boss app.
// @match        https://www.torn.com/factions.php*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @connect      localhost
// @connect      127.0.0.1
// @run-at       document-idle
// ==/UserScript==

(function () {
  "use strict";

  // Change this if your app runs somewhere else (a different port, or the
  // hostname of a Cloudflare Tunnel exposing it beyond localhost). If you
  // change the host, also add a matching @connect line above - Tampermonkey
  // blocks cross-origin requests to hosts it isn't told about.
  const APP_BASE_URL = "http://localhost:8787";
  const TOKEN_KEY = "twm_live_token";
  // Cheap to poll fast - this only re-reads the app's own cached snapshot,
  // never touches Torn's API (the bot's own refresh cadence is what actually
  // bounds how fresh this data can be).
  const POLL_MS = 2000;

  // ---------- Talking to the app ----------

  function gmRequest(method, path, { body, auth = true } = {}) {
    return new Promise((resolve, reject) => {
      const headers = { "Content-Type": "application/json" };
      if (auth) {
        const token = GM_getValue(TOKEN_KEY);
        if (token) headers["Authorization"] = `Bearer ${token}`;
      }
      GM_xmlhttpRequest({
        method,
        url: APP_BASE_URL + path,
        headers,
        data: body ? JSON.stringify(body) : undefined,
        onload: (res) => {
          let data = {};
          try {
            data = JSON.parse(res.responseText);
          } catch (e) {
            /* non-JSON response */
          }
          if (res.status >= 200 && res.status < 300) {
            resolve(data);
          } else {
            const err = new Error(data.detail || `HTTP ${res.status}`);
            err.status = res.status;
            reject(err);
          }
        },
        onerror: () => reject(new Error("Could not reach the app - is it running?")),
        ontimeout: () => reject(new Error("App request timed out")),
        timeout: 15000,
      });
    });
  }

  const api = {
    login: (apiKey) => gmRequest("POST", "/api/auth/login", { body: { api_key: apiKey }, auth: false }),
    liveSnapshot: () => gmRequest("GET", "/api/live/war-snapshot"),
  };

  // ---------- Formatting ----------

  function formatEta(unixTs) {
    if (!unixTs) return "-";
    const diffMs = unixTs * 1000 - Date.now();
    if (diffMs <= 0) return "landed";
    const totalSeconds = Math.floor(diffMs / 1000);
    const mins = Math.floor(totalSeconds / 60);
    const secs = totalSeconds % 60;
    return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
  }

  // ---------- Floating panel UI ----------

  const STYLE = `
    #twm-live-panel { position: fixed; bottom: 16px; left: 16px; width: 420px; max-height: 60vh;
      overflow-y: auto; background: #1b1e27; color: #e6e8ee; border: 1px solid #2e3342; border-radius: 8px;
      font: 13px -apple-system, "Segoe UI", Roboto, sans-serif; z-index: 999999; box-shadow: 0 8px 24px rgba(0,0,0,.4); }
    #twm-live-panel h3 { margin: 0; padding: 10px 12px; font-size: 13px; background: #232735;
      border-bottom: 1px solid #2e3342; display: flex; justify-content: space-between; align-items: center; }
    #twm-live-panel .twm-body { padding: 10px 12px; }
    #twm-live-panel input, #twm-live-panel button { font: inherit; background: #232735; color: #e6e8ee;
      border: 1px solid #2e3342; border-radius: 6px; padding: 4px 8px; cursor: pointer; }
    #twm-live-panel button.twm-primary { background: #2f5b8a; border-color: #5da9ff; }
    #twm-live-panel table { width: 100%; border-collapse: collapse; font-size: 12px; }
    #twm-live-panel th, #twm-live-panel td { padding: 4px 6px; border-bottom: 1px solid #2e3342; text-align: left; }
    #twm-live-panel th { color: #9aa1b2; font-weight: 500; }
    #twm-live-panel .twm-error { color: #e0616b; font-size: 12px; }
    #twm-live-panel .twm-muted { color: #9aa1b2; }
    #twm-live-panel .twm-okay { color: #4ec98a; }
    #twm-live-panel .twm-toggle { cursor: pointer; }
  `;

  function injectStyle() {
    if (document.getElementById("twm-live-style")) return;
    const style = document.createElement("style");
    style.id = "twm-live-style";
    style.textContent = STYLE;
    document.head.appendChild(style);
  }

  function renderLoginForm(body) {
    body.innerHTML = `
      <div style="margin-bottom:8px">Log in with your own Torn API key to see live war data.</div>
      <div style="display:flex; gap:6px">
        <input type="password" id="twm-live-key" placeholder="Torn API key" style="flex:1" />
        <button class="twm-primary" id="twm-live-login">Log in</button>
      </div>
      <div class="twm-error" id="twm-live-login-error"></div>
    `;
    body.querySelector("#twm-live-login").addEventListener("click", async () => {
      const input = body.querySelector("#twm-live-key");
      const errorEl = body.querySelector("#twm-live-login-error");
      const key = input.value.trim();
      if (!key) return;
      errorEl.textContent = "";
      try {
        const res = await api.login(key);
        GM_setValue(TOKEN_KEY, res.token);
        renderSnapshot(body);
      } catch (e) {
        errorEl.textContent = e.message;
      }
    });
  }

  async function renderSnapshot(body) {
    if (!GM_getValue(TOKEN_KEY)) {
      renderLoginForm(body);
      return;
    }

    let snapshot;
    try {
      snapshot = await api.liveSnapshot();
    } catch (e) {
      if (e.status === 401) {
        GM_setValue(TOKEN_KEY, "");
        renderLoginForm(body);
        return;
      }
      body.innerHTML = `<div class="twm-error">${e.message}<br/>Make sure the app is running at ${APP_BASE_URL}.</div>`;
      return;
    }

    if (!snapshot.war_id || !snapshot.members.length) {
      body.innerHTML = `<div class="twm-muted">No live war board running right now - ask leadership to run /current_war start in Discord.</div>`;
      return;
    }

    const rows = [...snapshot.members].sort((a, b) => {
      const aOkay = a.status.state === "Okay" ? 0 : 1;
      const bOkay = b.status.state === "Okay" ? 0 : 1;
      if (aOkay !== bOkay) return aOkay - bOkay;
      return (b.level || 0) - (a.level || 0);
    });

    body.innerHTML = `
      <table>
        <thead>
          <tr><th>Name</th><th>Lvl</th><th>Status</th><th>Online%</th><th>Landing</th></tr>
        </thead>
        <tbody>
          ${rows
            .map(
              (m) => `
            <tr>
              <td>${m.name}</td>
              <td>${m.level ?? "-"}</td>
              <td class="${m.status.state === "Okay" ? "twm-okay" : "twm-muted"}">${m.status.description || m.status.state}</td>
              <td>${m.online_probability_now != null ? Math.round(m.online_probability_now) + "%" : "-"}</td>
              <td data-eta="${m.estimated_landing_at || ""}">${formatEta(m.estimated_landing_at)}</td>
            </tr>
          `
            )
            .join("")}
        </tbody>
      </table>
    `;
  }

  function tickCountdowns(body) {
    body.querySelectorAll("[data-eta]").forEach((el) => {
      const ts = Number(el.dataset.eta);
      if (ts) el.textContent = formatEta(ts);
    });
  }

  let pollTimer = null;
  let tickTimer = null;

  function buildPanel() {
    injectStyle();
    if (document.getElementById("twm-live-panel")) return;

    const panel = document.createElement("div");
    panel.id = "twm-live-panel";
    panel.innerHTML = `
      <h3>
        Live War
        <span class="twm-toggle" id="twm-live-collapse">-</span>
      </h3>
      <div class="twm-body">Loading...</div>
    `;
    document.body.appendChild(panel);

    const body = panel.querySelector(".twm-body");
    const collapseBtn = panel.querySelector("#twm-live-collapse");
    collapseBtn.addEventListener("click", () => {
      const collapsed = body.style.display === "none";
      body.style.display = collapsed ? "" : "none";
      collapseBtn.textContent = collapsed ? "-" : "+";
    });

    renderSnapshot(body);
    pollTimer = setInterval(() => renderSnapshot(body), POLL_MS);
    tickTimer = setInterval(() => tickCountdowns(body), 1000);
  }

  function removePanel() {
    const panel = document.getElementById("twm-live-panel");
    if (panel) panel.remove();
    if (pollTimer) clearInterval(pollTimer);
    if (tickTimer) clearInterval(tickTimer);
    pollTimer = null;
    tickTimer = null;
  }

  // Unlike the payroll helper (which only matters inside one specific
  // control-tab panel), this overlay is useful anywhere on the faction page,
  // so it just stays up for as long as you're on factions.php at all.
  buildPanel();
  window.addEventListener("beforeunload", removePanel);
})();
