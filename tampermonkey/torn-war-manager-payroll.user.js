// ==UserScript==
// @name         Torn War Manager - Payroll Helper
// @namespace    torn-ranked-war-boss
// @version      1.1.0
// @description  Fills the faction "add to balance" form from your locally-running Torn Ranked War Boss app. Never submits automatically - you always click Torn's own button yourself.
// @match        https://www.torn.com/factions.php*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @connect      war.taxevasionunit.uk
// @connect      localhost
// @connect      127.0.0.1
// @run-at       document-idle
// ==/UserScript==

(function () {
  "use strict";

  // Change this if your app is reachable somewhere else (a different Cloudflare
  // Tunnel hostname, or plain http://localhost:8787 if you're running Chrome on
  // the same machine as the app). If you change the host, also add a matching
  // @connect line above - Tampermonkey blocks cross-origin requests to hosts
  // it isn't told about.
  const APP_BASE_URL = "https://war.taxevasionunit.uk";
  const TOKEN_KEY = "twm_payroll_token";

  // ---------- Talking to the app ----------
  // Every route needs a logged-in session now, so requests (besides login
  // itself) carry the bearer token from the last successful login - same
  // pattern as the Live War overlay script, since a Tampermonkey script can't
  // rely on cookie-jar behavior across contexts.

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
    listWars: () => gmRequest("GET", "/api/wars"),
    getWar: (warId) => gmRequest("GET", `/api/wars/${warId}`),
    markPaid: (warId, memberId, paid) =>
      gmRequest("PATCH", `/api/wars/${warId}/members/${memberId}`, { body: { paid } }),
  };

  // ---------- React-compatible form filling ----------
  // React tracks input values through its own property descriptor, so a plain
  // `input.value = x` gets silently ignored on the next render. Setting the value
  // through the native (non-React) setter first, then dispatching a real input
  // event, is the standard way to make a controlled React input pick up a change
  // it didn't originate itself.
  function setNativeValue(input, value) {
    const proto = input.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }

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

  // Fills the search box, "Add to balance" radio, and amount field for one member.
  // Deliberately stops there - never touches the actual submit button.
  //
  // React re-renders this section after the player is selected and again after the
  // radio is clicked, which can detach a DOM reference grabbed beforehand. So every
  // lookup here is re-queried fresh from `document` and polled with waitFor rather
  // than looked up once against a cached `panel` variable.
  function getPanel() {
    return document.querySelector(".give.control-tab-section");
  }

  function findAmountInput() {
    const panel = getPanel();
    if (!panel) return null;
    // Torn renders more than one .legacy-money-input in this panel (give-money vs
    // add-to-balance modes; only one is ever visible at a time), and the visible
    // (text) ones have no literal type="..." attribute at all - it's left to the
    // browser's default, so filtering by the .type *property* (not a [type=...]
    // CSS attribute selector, which only matches an explicit attribute) is required.
    const candidates = Array.from(panel.querySelectorAll('input[data-testid="legacy-money-input"]'));
    return candidates.find((el) => el.type === "text" && el.offsetParent !== null) || null;
  }

  async function fillFormForMember(member) {
    if (!getPanel()) {
      throw new Error('Open Faction > Controls > "Give to User" first.');
    }

    const searchInput = await waitFor(() => getPanel()?.querySelector('input[data-testid="autocomplete-input"]')).catch(() => {
      throw new Error("Couldn't find the player search box - Torn may have changed its page.");
    });
    searchInput.focus();
    setNativeValue(searchInput, member.name);

    const suggestion = await waitFor(() => {
      const buttons = document.querySelectorAll("button.item");
      return Array.from(buttons).find((b) => b.textContent.trim().endsWith(`[${member.member_id}]`));
    }).catch(() => {
      throw new Error(`Couldn't find "${member.name}" in the suggestions - check the name matches Torn exactly.`);
    });
    suggestion.click();

    const addToBalanceRadio = await waitFor(() => getPanel()?.querySelector("#add-money-to-balance")).catch(() => {
      throw new Error("Couldn't find the 'Add to balance' option - Torn may have changed its page.");
    });
    addToBalanceRadio.click();

    const amountInput = await waitFor(findAmountInput, { timeout: 6000 }).catch(() => {
      throw new Error("Couldn't find the amount field - Torn may have changed its page.");
    });
    setNativeValue(amountInput, String(Math.round(member.final_pay)));

    amountInput.scrollIntoView({ block: "center", behavior: "smooth" });
    amountInput.style.outline = "2px solid #4ec98a";
    setTimeout(() => {
      amountInput.style.outline = "";
    }, 3000);
  }

  // ---------- Floating panel UI ----------

  const STYLE = `
    #twm-payroll-panel { position: fixed; bottom: 16px; right: 16px; width: 340px; max-height: 70vh;
      overflow-y: auto; background: #1b1e27; color: #e6e8ee; border: 1px solid #2e3342; border-radius: 8px;
      font: 13px -apple-system, "Segoe UI", Roboto, sans-serif; z-index: 999999; box-shadow: 0 8px 24px rgba(0,0,0,.4); }
    #twm-payroll-panel h3 { margin: 0; padding: 10px 12px; font-size: 13px; background: #232735;
      border-bottom: 1px solid #2e3342; display: flex; justify-content: space-between; align-items: center; }
    #twm-payroll-panel .twm-body { padding: 10px 12px; }
    #twm-payroll-panel select, #twm-payroll-panel button { font: inherit; background: #232735; color: #e6e8ee;
      border: 1px solid #2e3342; border-radius: 6px; padding: 4px 8px; cursor: pointer; }
    #twm-payroll-panel button.twm-primary { background: #2f5b8a; border-color: #5da9ff; }
    #twm-payroll-panel .twm-row { display: flex; justify-content: space-between; align-items: center;
      gap: 6px; padding: 6px 0; border-bottom: 1px solid #2e3342; }
    #twm-payroll-panel .twm-row:last-child { border-bottom: none; }
    #twm-payroll-panel .twm-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    #twm-payroll-panel .twm-amount { color: #9aa1b2; }
    #twm-payroll-panel .twm-error { color: #e0616b; font-size: 12px; }
    #twm-payroll-panel .twm-toggle { cursor: pointer; }
  `;

  function injectStyle() {
    if (document.getElementById("twm-payroll-style")) return;
    const style = document.createElement("style");
    style.id = "twm-payroll-style";
    style.textContent = STYLE;
    document.head.appendChild(style);
  }

  function money(n) {
    return "$" + Math.round(n).toLocaleString();
  }

  function renderLoginForm(body) {
    body.innerHTML = `
      <div style="margin-bottom:8px">Log in with your own Torn API key to see unpaid members.</div>
      <div style="display:flex; gap:6px">
        <input type="password" id="twm-payroll-key" placeholder="Torn API key" style="flex:1" />
        <button class="twm-primary" id="twm-payroll-login">Log in</button>
      </div>
      <div class="twm-error" id="twm-payroll-login-error"></div>
    `;
    body.querySelector("#twm-payroll-login").addEventListener("click", async () => {
      const input = body.querySelector("#twm-payroll-key");
      const errorEl = body.querySelector("#twm-payroll-login-error");
      const key = input.value.trim();
      if (!key) return;
      errorEl.textContent = "";
      try {
        const res = await api.login(key);
        GM_setValue(TOKEN_KEY, res.token);
        loadWarsIntoPanel(body.closest("#twm-payroll-panel"));
      } catch (e) {
        errorEl.textContent = e.message;
      }
    });
  }

  async function renderPanel(panelEl, warId) {
    const body = panelEl.querySelector(".twm-body");
    if (!GM_getValue(TOKEN_KEY)) {
      renderLoginForm(body);
      return;
    }
    body.innerHTML = "Loading...";
    let war;
    try {
      war = await api.getWar(warId);
    } catch (e) {
      if (e.status === 401) {
        GM_setValue(TOKEN_KEY, "");
        renderLoginForm(body);
        return;
      }
      body.innerHTML = `<div class="twm-error">${e.message}</div>`;
      return;
    }

    const unpaid = war.members
      .filter((m) => m.final_pay > 0.5 && !m.paid)
      .sort((a, b) => b.final_pay - a.final_pay);

    if (!unpaid.length) {
      body.innerHTML = `<div>Everyone's marked paid for this war.</div>`;
      return;
    }

    const total = unpaid.reduce((sum, m) => sum + m.final_pay, 0);
    body.innerHTML =
      `<div style="margin-bottom:8px">${unpaid.length} unpaid - ${money(total)} total</div>` +
      unpaid
        .map(
          (m) => `
      <div class="twm-row-wrap">
        <div class="twm-row" data-member="${m.member_id}">
          <span class="twm-name" title="${m.name}">${m.name}</span>
          <span class="twm-amount">${money(m.final_pay)}</span>
          <button class="twm-primary" data-action="fill">Fill</button>
          <button data-action="paid">Paid</button>
        </div>
        <div class="twm-error" data-error-for="${m.member_id}"></div>
      </div>`
        )
        .join("");

    body.querySelectorAll("[data-action]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const row = btn.closest(".twm-row");
        const memberId = Number(row.dataset.member);
        const member = unpaid.find((m) => m.member_id === memberId);
        const errorEl = row.parentElement.querySelector(`[data-error-for="${memberId}"]`);
        errorEl.textContent = "";

        if (btn.dataset.action === "fill") {
          btn.textContent = "Filling...";
          try {
            await fillFormForMember(member);
            btn.textContent = "Filled";
          } catch (e) {
            errorEl.textContent = e.message;
            btn.textContent = "Fill";
          }
        } else {
          if (!confirm(`Mark ${member.name} (${money(member.final_pay)}) as paid?\n\nOnly do this after you've actually clicked "give money" in Torn.`)) {
            return;
          }
          try {
            await api.markPaid(warId, memberId, true);
            row.parentElement.remove();
          } catch (e) {
            errorEl.textContent = e.message;
          }
        }
      });
    });
  }

  async function buildPanel() {
    injectStyle();
    if (document.getElementById("twm-payroll-panel")) return;

    const panel = document.createElement("div");
    panel.id = "twm-payroll-panel";
    panel.innerHTML = `
      <h3>
        War Manager Payroll
        <span>
          <select id="twm-war-select" style="max-width:150px"></select>
          <span class="twm-toggle" id="twm-collapse">-</span>
        </span>
      </h3>
      <div class="twm-body">Loading wars...</div>
    `;
    document.body.appendChild(panel);

    const body = panel.querySelector(".twm-body");
    const collapseBtn = panel.querySelector("#twm-collapse");
    collapseBtn.addEventListener("click", () => {
      const collapsed = body.style.display === "none";
      body.style.display = collapsed ? "" : "none";
      collapseBtn.textContent = collapsed ? "-" : "+";
    });

    await loadWarsIntoPanel(panel);
  }

  async function loadWarsIntoPanel(panel) {
    const body = panel.querySelector(".twm-body");
    if (!GM_getValue(TOKEN_KEY)) {
      renderLoginForm(body);
      return;
    }

    let wars;
    try {
      wars = await api.listWars();
    } catch (e) {
      if (e.status === 401) {
        GM_setValue(TOKEN_KEY, "");
        renderLoginForm(body);
        return;
      }
      body.innerHTML = `<div class="twm-error">${e.message}<br/>Make sure the app is running at ${APP_BASE_URL}.</div>`;
      return;
    }
    if (!wars.length) {
      body.innerHTML = "<div>No synced wars yet.</div>";
      return;
    }

    const select = panel.querySelector("#twm-war-select");
    select.innerHTML = wars
      .map((w) => `<option value="${w.id}">vs ${w.opponent_name || "?"}</option>`)
      .join("");
    select.addEventListener("change", () => renderPanel(panel, Number(select.value)));

    renderPanel(panel, wars[0].id);
  }

  function removePanel() {
    const panel = document.getElementById("twm-payroll-panel");
    if (panel) panel.remove();
  }

  // The faction page is a hash-routed SPA - the "Give to User" form appears and
  // disappears without a full page load, so poll for it rather than relying on
  // a single run-at-load check.
  setInterval(() => {
    const onGiveToUserTab = !!document.querySelector(".give.control-tab-section");
    if (onGiveToUserTab) {
      buildPanel();
    } else {
      removePanel();
    }
  }, 1000);
})();
