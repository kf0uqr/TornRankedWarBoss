// ==UserScript==
// @name         Torn War Manager - Payroll Helper
// @namespace    torn-ranked-war-boss
// @version      1.0.0
// @description  Fills the faction "add to balance" form from your locally-running Torn Ranked War Boss app. Never submits automatically - you always click Torn's own button yourself.
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
    markPaid: (warId, memberId, paid) =>
      gmRequest("PATCH", `/api/wars/${warId}/members/${memberId}`, { paid }),
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

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  // Fills the search box, "Add to balance" radio, and amount field for one member.
  // Deliberately stops there - never touches the actual submit button.
  async function fillFormForMember(member) {
    const panel = document.querySelector(".give.control-tab-section");
    if (!panel) {
      throw new Error('Open Faction > Controls > "Give to User" first.');
    }

    const searchInput = panel.querySelector('input[data-testid="autocomplete-input"]');
    if (!searchInput) throw new Error("Couldn't find the player search box - Torn may have changed its page.");

    searchInput.focus();
    setNativeValue(searchInput, member.name);

    const suggestion = await waitFor(() => {
      const buttons = document.querySelectorAll("button.item");
      return Array.from(buttons).find((b) => b.textContent.trim().endsWith(`[${member.member_id}]`));
    });
    suggestion.click();

    const addToBalanceRadio = panel.querySelector("#add-money-to-balance");
    if (!addToBalanceRadio) throw new Error("Couldn't find the 'Add to balance' option - Torn may have changed its page.");
    addToBalanceRadio.click();

    // Give React a moment to settle after the player selection before touching the amount field.
    await sleep(200);

    const amountInput = panel.querySelector('input[data-testid="legacy-money-input"][type="text"]');
    if (!amountInput) throw new Error("Couldn't find the amount field - Torn may have changed its page.");
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
      <div class="twm-row" data-member="${m.member_id}">
        <span class="twm-name" title="${m.name}">${m.name}</span>
        <span class="twm-amount">${money(m.final_pay)}</span>
        <button class="twm-primary" data-action="fill">Fill</button>
        <button data-action="paid">Paid</button>
      </div>`
        )
        .join("");

    body.querySelectorAll("[data-action]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const row = btn.closest(".twm-row");
        const memberId = Number(row.dataset.member);
        const member = unpaid.find((m) => m.member_id === memberId);
        if (btn.dataset.action === "fill") {
          btn.textContent = "Filling...";
          try {
            await fillFormForMember(member);
            btn.textContent = "Filled";
          } catch (e) {
            alert(e.message);
            btn.textContent = "Fill";
          }
        } else {
          if (!confirm(`Mark ${member.name} (${money(member.final_pay)}) as paid?\n\nOnly do this after you've actually clicked "give money" in Torn.`)) {
            return;
          }
          try {
            await api.markPaid(warId, memberId, true);
            row.remove();
          } catch (e) {
            alert(e.message);
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
