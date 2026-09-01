// ==UserScript==
// @name         Torn War Manager - Rank Promotion Helper
// @namespace    torn-ranked-war-boss
// @version      1.0.0
// @description  Compares each member's live Torn position against the rank your locally-running Torn Ranked War Boss app computed for them, and highlights the correct dropdown option to click. Never selects it for you - you always click Torn's own option yourself.
// @match        https://www.torn.com/factions.php*
// @grant        GM_xmlhttpRequest
// @connect      localhost
// @connect      127.0.0.1
// @run-at       document-idle
// ==/UserScript==

(function () {
  "use strict";

  // Change this if your app runs on a different port (see start.sh / app.py).
  const APP_BASE_URL = "http://localhost:8787";

  // Exzo's Torn position is always left as "Apple Man" - a cosmetic vanity rank,
  // regardless of whatever the ladder would otherwise compute for him. Keyed by
  // name rather than member_id since his id hasn't been independently confirmed.
  const VANITY_OVERRIDES = { exzo: "Apple Man" };

  // ---------- Talking to the local app ----------

  function gmRequest(method, path, body) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method,
        url: APP_BASE_URL + path,
        headers: { "Content-Type": "application/json" },
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
            reject(new Error(data.detail || `HTTP ${res.status}`));
          }
        },
        onerror: () => reject(new Error("Could not reach the local app - is it running?")),
        ontimeout: () => reject(new Error("Local app request timed out")),
        timeout: 15000,
      });
    });
  }

  const api = {
    listWars: () => gmRequest("GET", "/api/wars"),
    getWar: (warId) => gmRequest("GET", `/api/wars/${warId}`),
  };

  function waitFor(check, { timeout = 5000, interval = 150 } = {}) {
    return new Promise((resolve, reject) => {
      const start = Date.now();
      const tick = () => {
        const result = check();
        if (result) return resolve(result);
        if (Date.now() - start > timeout) return reject(new Error("Timed out waiting for the page"));
        setTimeout(tick, interval);
      };
      tick();
    });
  }

  // ---------- Finding things on Torn's members page ----------

  // Torn renders the position control as a plain <button data-testid="dropdown-toggler">
  // whose own text is the member's current position. Row wrapper class names are
  // hashed CSS modules (not stable across deploys), but each row also has a profile
  // link with the player's Torn id in it (/profiles.php?XID=<id>) - the same id
  // war.members already carries as member_id - so we anchor on that instead of
  // matching on name text, then walk up to find the toggler button living in the
  // same row.
  function findTogglerForMember(memberId) {
    const profileLink = document.querySelector(`a[href*="XID=${memberId}"]`);
    if (!profileLink) return null;
    let el = profileLink;
    for (let i = 0; i < 10 && el; i++) {
      const btn = el.querySelector('button[data-testid="dropdown-toggler"]');
      if (btn) return btn;
      el = el.parentElement;
    }
    return null;
  }

  function targetRankFor(member) {
    const override = VANITY_OVERRIDES[member.name.trim().toLowerCase()];
    return override || member.pay_rank;
  }

  // Opens the member's dropdown (if not already open) and highlights the option
  // matching the target rank - it never clicks the option itself. Applying a
  // position change is immediate and permanent in Torn, so same as the payroll
  // script's "fill the form, you click submit" split, the actual click here always
  // stays a deliberate, manual action.
  async function locateAndHighlight(memberId, name, target) {
    const btn = findTogglerForMember(memberId);
    if (!btn) {
      throw new Error(`Couldn't find "${name}" on this page - make sure you're on Faction > Controls > Members.`);
    }
    btn.scrollIntoView({ block: "center", behavior: "smooth" });
    if (btn.getAttribute("aria-expanded") !== "true") {
      btn.click();
    }
    const option = await waitFor(() => {
      const opts = Array.from(document.querySelectorAll('li[role="option"]'));
      return opts.find((o) => o.textContent.trim().toLowerCase() === target.trim().toLowerCase());
    }).catch(() => {
      throw new Error(`Couldn't find "${target}" in ${name}'s dropdown - Torn may have changed its page, or that position isn't offered for this member.`);
    });
    option.scrollIntoView({ block: "center" });
    option.style.outline = "2px solid #4ec98a";
    option.style.outlineOffset = "2px";
    setTimeout(() => {
      option.style.outline = "";
    }, 5000);
  }

  // ---------- Floating panel UI ----------

  const STYLE = `
    #twm-rank-panel { position: fixed; bottom: 16px; left: 16px; width: 360px; max-height: 70vh;
      overflow-y: auto; background: #1b1e27; color: #e6e8ee; border: 1px solid #2e3342; border-radius: 8px;
      font: 13px -apple-system, "Segoe UI", Roboto, sans-serif; z-index: 999999; box-shadow: 0 8px 24px rgba(0,0,0,.4); }
    #twm-rank-panel h3 { margin: 0; padding: 10px 12px; font-size: 13px; background: #232735;
      border-bottom: 1px solid #2e3342; display: flex; justify-content: space-between; align-items: center; }
    #twm-rank-panel .twm-body { padding: 10px 12px; }
    #twm-rank-panel select, #twm-rank-panel button { font: inherit; background: #232735; color: #e6e8ee;
      border: 1px solid #2e3342; border-radius: 6px; padding: 4px 8px; cursor: pointer; }
    #twm-rank-panel button.twm-primary { background: #2f5b8a; border-color: #5da9ff; }
    #twm-rank-panel .twm-row { display: flex; justify-content: space-between; align-items: center;
      gap: 6px; padding: 6px 0; border-bottom: 1px solid #2e3342; }
    #twm-rank-panel .twm-row:last-child { border-bottom: none; }
    #twm-rank-panel .twm-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    #twm-rank-panel .twm-change { color: #9aa1b2; font-size: 12px; }
    #twm-rank-panel .twm-error { color: #e0616b; font-size: 12px; }
    #twm-rank-panel .twm-toggle { cursor: pointer; }
    #twm-rank-panel .twm-hint { color: #9aa1b2; font-size: 11px; margin-top: 8px; }
  `;

  function injectStyle() {
    if (document.getElementById("twm-rank-style")) return;
    const style = document.createElement("style");
    style.id = "twm-rank-style";
    style.textContent = STYLE;
    document.head.appendChild(style);
  }

  async function renderPanel(panelEl, warId) {
    const body = panelEl.querySelector(".twm-body");
    body.innerHTML = "Loading...";
    let war;
    try {
      war = await api.getWar(warId);
    } catch (e) {
      body.innerHTML = `<div class="twm-error">${e.message}</div>`;
      return;
    }

    const mismatches = [];
    for (const m of war.members) {
      const target = targetRankFor(m);
      if (!target) continue;
      const btn = findTogglerForMember(m.member_id);
      const current = btn ? btn.textContent.trim() : null;
      if (current === null) continue; // not on this page (left faction, scrolled out, etc.)
      if (current.toLowerCase() !== target.toLowerCase()) {
        mismatches.push({ memberId: m.member_id, name: m.name, current, target });
      }
    }

    if (!mismatches.length) {
      body.innerHTML = `<div>Everyone visible on this page already matches their computed rank.</div>`;
      return;
    }

    body.innerHTML =
      `<div style="margin-bottom:8px">${mismatches.length} out of sync</div>` +
      mismatches
        .map(
          (mm) => `
      <div class="twm-row-wrap">
        <div class="twm-row" data-member="${mm.memberId}" data-name="${mm.name}" data-target="${mm.target}">
          <span class="twm-name" title="${mm.name}">${mm.name}</span>
          <span class="twm-change">${mm.current} &rarr; ${mm.target}</span>
          <button class="twm-primary" data-action="locate">Locate</button>
        </div>
        <div class="twm-error" data-error-for="${mm.memberId}"></div>
      </div>`
        )
        .join("") +
      `<div class="twm-hint">Locate opens their dropdown and highlights the right option in green - click it yourself to actually apply it.</div>`;

    body.querySelectorAll('[data-action="locate"]').forEach((btn) => {
      btn.addEventListener("click", async () => {
        const row = btn.closest(".twm-row");
        const memberId = Number(row.dataset.member);
        const name = row.dataset.name;
        const target = row.dataset.target;
        const errorEl = row.parentElement.querySelector(`[data-error-for="${memberId}"]`);
        errorEl.textContent = "";
        try {
          await locateAndHighlight(memberId, name, target);
        } catch (e) {
          errorEl.textContent = e.message;
        }
      });
    });
  }

  async function buildPanel() {
    injectStyle();
    if (document.getElementById("twm-rank-panel")) return;

    const panel = document.createElement("div");
    panel.id = "twm-rank-panel";
    panel.innerHTML = `
      <h3>
        War Manager Ranks
        <span>
          <select id="twm-rank-war-select" style="max-width:150px"></select>
          <span class="twm-toggle" id="twm-rank-collapse">-</span>
        </span>
      </h3>
      <div class="twm-body">Loading wars...</div>
    `;
    document.body.appendChild(panel);

    const body = panel.querySelector(".twm-body");
    const collapseBtn = panel.querySelector("#twm-rank-collapse");
    collapseBtn.addEventListener("click", () => {
      const collapsed = body.style.display === "none";
      body.style.display = collapsed ? "" : "none";
      collapseBtn.textContent = collapsed ? "-" : "+";
    });

    let wars;
    try {
      wars = await api.listWars();
    } catch (e) {
      body.innerHTML = `<div class="twm-error">${e.message}<br/>Make sure the app is running at ${APP_BASE_URL}.</div>`;
      return;
    }
    if (!wars.length) {
      body.innerHTML = "<div>No synced wars yet.</div>";
      return;
    }

    const select = panel.querySelector("#twm-rank-war-select");
    select.innerHTML = wars
      .map((w) => `<option value="${w.id}">vs ${w.opponent_name || "?"}</option>`)
      .join("");
    select.addEventListener("change", () => renderPanel(panel, Number(select.value)));

    renderPanel(panel, wars[0].id);
  }

  function removePanel() {
    const panel = document.getElementById("twm-rank-panel");
    if (panel) panel.remove();
  }

  // The faction page is a hash-routed SPA - the members list appears and disappears
  // without a full page load, so poll for it rather than relying on a single
  // run-at-load check (same approach as the payroll script).
  setInterval(() => {
    const onMembersTab = !!document.querySelector('button[data-testid="dropdown-toggler"]');
    if (onMembersTab) {
      buildPanel();
    } else {
      removePanel();
    }
  }, 1000);
})();
