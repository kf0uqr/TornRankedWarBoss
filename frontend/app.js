const state = {
  warId: null,
  rateLimitUntil: null,
  rateLimitTimer: null,
  session: null,
  liveWarTimer: null,
  liveWarTickTimer: null,
};
const HITS_PER_XANAX = 10;

function toast(msg, isError = false) {
  const el = document.createElement("div");
  el.className = "toast-msg" + (isError ? " error" : "");
  el.textContent = msg;
  document.getElementById("toast").appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

function startRateLimitCountdown(retryAfterSeconds) {
  state.rateLimitUntil = Date.now() + retryAfterSeconds * 1000;
  const banner = document.getElementById("rate-limit-banner");
  const countdown = document.getElementById("rate-limit-countdown");
  banner.classList.remove("hidden");

  if (state.rateLimitTimer) clearInterval(state.rateLimitTimer);
  const tick = () => {
    const remaining = Math.max(0, Math.ceil((state.rateLimitUntil - Date.now()) / 1000));
    countdown.textContent = remaining;
    if (remaining <= 0) {
      banner.classList.add("hidden");
      state.rateLimitUntil = null;
      clearInterval(state.rateLimitTimer);
      state.rateLimitTimer = null;
    }
  };
  tick();
  state.rateLimitTimer = setInterval(tick, 1000);
}

async function api(path, opts = {}) {
  if (state.rateLimitUntil && Date.now() < state.rateLimitUntil) {
    const remaining = Math.ceil((state.rateLimitUntil - Date.now()) / 1000);
    toast(`Still waiting on the Torn API rate limit - ${remaining}s left`, true);
    throw new Error("rate-limited");
  }

  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));

  if (res.status === 429) {
    startRateLimitCountdown(data.retry_after || 60);
    toast(data.detail || "Torn API rate limit reached", true);
    throw new Error(data.detail || "Rate limited");
  }
  if (res.status === 401 && path !== "/api/auth/me") {
    // Session expired mid-use (or was never valid) - drop back to the login
    // screen instead of a wall of toasts from every in-flight request.
    showLogin();
    throw new Error(data.detail || "Not logged in");
  }
  if (!res.ok) {
    const msg = data.detail || res.statusText;
    toast(msg, true);
    throw new Error(msg);
  }
  return data;
}

function money(n) {
  n = Number(n || 0);
  const sign = n < 0 ? "-" : "";
  return sign + "$" + Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function num(n, digits = 0) {
  return Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function fmtDate(ts) {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleDateString();
}

function tsToDatetimeLocal(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function datetimeLocalToTs(value) {
  if (!value) return null;
  return Math.floor(new Date(value).getTime() / 1000);
}

const STAT_HEADERS = [
  "Name", "Total Hits", "Respect Gained", "Respect Lost",
  "Best Hit", "Avg Respect/Hit",
  "Score", "Overall Rank",
];

function statsRowCells(m) {
  return [
    m.name,
    `${num(m.total_hits)} (#${m.hits_rank})`,
    `${num(m.respect, 2)} (#${m.respect_gained_rank})`,
    `${num(m.respect_lost, 2)} (#${m.respect_lost_rank})`,
    `${num(m.best_hit, 2)} (#${m.best_hit_rank})`,
    `${num(m.avg_respect_per_hit, 2)} (#${m.avg_respect_per_hit_rank})`,
    `${m.score}`,
    `#${m.overall_rank}`,
  ];
}

function renderStatsTable(members) {
  if (!members.length) return `<p class="muted">No members in this group.</p>`;
  const rows = members
    .map((m) => `<tr>${statsRowCells(m).map((c) => `<td>${c}</td>`).join("")}</tr>`)
    .join("");
  return `
    <table>
      <thead><tr>${STAT_HEADERS.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

const PAYSHEET_HEADERS = [
  "Name", "Inside", "Outside", "Assists", "Xanax Used", "Rank", "Fine", "Paid Back", "Gross Pay", "Bonus", "Final Pay", "Paid",
];

function paysheetRowCells(m) {
  const bonus = m.flat_bonus + m.leadership_cut_share;
  return [
    m.name,
    num(m.inside_hits),
    num(m.outside_hits),
    num(m.assist_hits),
    num(m.xanax_used),
    m.pay_rank || "-",
    money(m.calculated_fine),
    m.fine_waived ? "Yes" : "No",
    money(m.gross_pay),
    money(bonus),
    { text: money(m.final_pay), color: m.final_pay < 0 ? IMAGE_COLORS.bad : undefined },
    m.paid ? "Yes" : "No",
  ];
}

function sumBy(members, fn) {
  return members.reduce((total, m) => total + fn(m), 0);
}

function paysheetTotalsCells(members) {
  const totalFinalPay = sumBy(members, (m) => m.final_pay);
  return [
    { text: "Total", color: IMAGE_COLORS.text },
    num(sumBy(members, (m) => m.inside_hits)),
    num(sumBy(members, (m) => m.outside_hits)),
    num(sumBy(members, (m) => m.assist_hits)),
    num(sumBy(members, (m) => m.xanax_used)),
    "",
    money(sumBy(members, (m) => m.calculated_fine)),
    "",
    money(sumBy(members, (m) => m.gross_pay)),
    money(sumBy(members, (m) => m.flat_bonus + m.leadership_cut_share)),
    { text: money(totalFinalPay), color: totalFinalPay < 0 ? IMAGE_COLORS.bad : undefined },
    "",
  ];
}

// ---------- Copy tables as image ----------

const IMAGE_COLORS = {
  panel: "#1b1e27",
  panelAlt: "#232735",
  border: "#2e3342",
  text: "#e6e8ee",
  textDim: "#9aa1b2",
  accent: "#5da9ff",
  bad: "#e0616b",
};

const IMG_HEADER_FONT = "600 13px -apple-system, Segoe UI, Roboto, sans-serif";
const IMG_CELL_FONT = "13px -apple-system, Segoe UI, Roboto, sans-serif";

function cellText(cell) {
  return cell && typeof cell === "object" ? cell.text : String(cell);
}

function measureColWidths(ctx, headers, rowsText) {
  ctx.font = IMG_HEADER_FONT;
  const widths = headers.map((h) => ctx.measureText(h).width);
  ctx.font = IMG_CELL_FONT;
  rowsText.forEach((r) => r.forEach((cell, i) => { widths[i] = Math.max(widths[i], ctx.measureText(cell).width); }));
  return widths;
}

function drawTableBlock(ctx, x, y, headers, rows, colWidths, colPad, rowHeight) {
  const totalWidth = colWidths.reduce((a, b) => a + b + colPad * 2, 0);

  ctx.fillStyle = IMAGE_COLORS.panelAlt;
  ctx.fillRect(x, y, totalWidth, rowHeight);
  ctx.fillStyle = IMAGE_COLORS.textDim;
  ctx.font = IMG_HEADER_FONT;
  ctx.textBaseline = "middle";
  let curX = x;
  headers.forEach((h, i) => {
    ctx.fillText(h, curX + colPad, y + rowHeight / 2);
    curX += colWidths[i] + colPad * 2;
  });

  let curY = y + rowHeight;
  rows.forEach((r, ri) => {
    if (ri % 2 === 1) {
      ctx.fillStyle = "rgba(255,255,255,0.03)";
      ctx.fillRect(x, curY, totalWidth, rowHeight);
    }
    ctx.font = IMG_CELL_FONT;
    curX = x;
    r.forEach((cell, ci) => {
      ctx.fillStyle = (cell && cell.color) || IMAGE_COLORS.text;
      ctx.fillText(cellText(cell), curX + colPad, curY + rowHeight / 2);
      curX += colWidths[ci] + colPad * 2;
    });
    curY += rowHeight;
  });

  ctx.strokeStyle = IMAGE_COLORS.border;
  ctx.lineWidth = 1;
  ctx.strokeRect(x + 0.5, y + 0.5, totalWidth - 1, rowHeight * (rows.length + 1) - 1);

  return { width: totalWidth, height: rowHeight * (rows.length + 1) };
}

async function copyTablesAsImage(title, sections) {
  const measureCanvas = document.createElement("canvas");
  const mctx = measureCanvas.getContext("2d");

  const colPad = 14;
  const rowHeight = 30;
  const padding = 28;
  const titleHeight = 34;
  const sectionGap = 26;
  const subHeaderHeight = 26;

  // Sections sharing identical headers get matching column widths so tables line up.
  const groups = {};
  sections.forEach((s, i) => {
    const key = s.headers.join("␟");
    (groups[key] = groups[key] || []).push(i);
  });
  const colWidthsBySection = new Array(sections.length);
  Object.values(groups).forEach((idxs) => {
    const headers = sections[idxs[0]].headers;
    const rowsText = idxs.flatMap((i) => sections[i].rows.map((r) => r.map(cellText)));
    const widths = measureColWidths(mctx, headers, rowsText);
    idxs.forEach((i) => { colWidthsBySection[i] = widths; });
  });

  const width = Math.max(...sections.map((s, i) => colWidthsBySection[i].reduce((a, b) => a + b + colPad * 2, 0))) + padding * 2;

  let height = padding * 2 + titleHeight;
  sections.forEach((s, i) => {
    if (s.heading) height += subHeaderHeight;
    height += rowHeight * (s.rows.length + 1);
    if (i < sections.length - 1) height += sectionGap;
  });

  const dpr = window.devicePixelRatio || 1;
  const canvas = document.createElement("canvas");
  canvas.width = Math.ceil(width * dpr);
  canvas.height = Math.ceil(height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);

  ctx.fillStyle = IMAGE_COLORS.panel;
  ctx.fillRect(0, 0, width, height);

  let y = padding;
  ctx.fillStyle = IMAGE_COLORS.text;
  ctx.font = "700 18px -apple-system, Segoe UI, Roboto, sans-serif";
  ctx.textBaseline = "top";
  ctx.fillText(title, padding, y);
  y += titleHeight;

  sections.forEach((s, i) => {
    if (s.heading) {
      ctx.font = "700 14px -apple-system, Segoe UI, Roboto, sans-serif";
      ctx.fillStyle = IMAGE_COLORS.accent;
      ctx.textBaseline = "top";
      ctx.fillText(s.heading, padding, y);
      y += subHeaderHeight;
    }
    const block = drawTableBlock(ctx, padding, y, s.headers, s.rows, colWidthsBySection[i], colPad, rowHeight);
    y += block.height;
    if (i < sections.length - 1) y += sectionGap;
  });

  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!blob) {
    toast("Failed to render image", true);
    return;
  }

  try {
    await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
    toast("Copied image to clipboard");
  } catch (err) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${title.replace(/[^a-z0-9]+/gi, "_")}.png`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast("Clipboard unavailable - downloaded image instead", true);
  }
}

// ---------- Tabs ----------

function stopLiveWarTimers() {
  if (state.liveWarTimer) {
    clearInterval(state.liveWarTimer);
    state.liveWarTimer = null;
  }
  if (state.liveWarTickTimer) {
    clearInterval(state.liveWarTickTimer);
    state.liveWarTickTimer = null;
  }
}

function switchTab(name) {
  stopLiveWarTimers();
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("hidden", s.id !== `tab-${name}`));
  if (name === "wars") renderWars();
  if (name === "armory") renderArmory();
  if (name === "stats") renderCareerStats();
  if (name === "live") {
    renderLiveWar();
    startLiveWarPolling();
  }
  if (name === "settings") renderSettings();
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

// ---------- Auth ----------

function showLogin() {
  stopLiveWarTimers();
  state.session = null;
  document.getElementById("app-shell").classList.add("hidden");
  document.getElementById("login-screen").classList.remove("hidden");
  document.getElementById("login-error").textContent = "";
}

function showApp() {
  document.getElementById("login-screen").classList.add("hidden");
  document.getElementById("app-shell").classList.remove("hidden");

  // Stats and Live War are visible to every logged-in member; everything
  // else (Wars, Armory, Settings) is leadership-only.
  const leadershipTabs = ["wars", "armory", "settings"];
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    const restricted = leadershipTabs.includes(btn.dataset.tab);
    btn.classList.toggle("hidden", restricted && !state.session.is_leadership);
  });

  switchTab(state.session.is_leadership ? "wars" : "stats");
}

async function checkSession() {
  try {
    state.session = await api("/api/auth/me");
    showApp();
  } catch (e) {
    showLogin();
  }
}

document.getElementById("login-submit").addEventListener("click", async () => {
  const input = document.getElementById("login-api-key");
  const errorEl = document.getElementById("login-error");
  errorEl.textContent = "";
  const apiKey = input.value.trim();
  if (!apiKey) return;

  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      errorEl.textContent = data.detail || "Login failed.";
      return;
    }
    input.value = "";
    state.session = { player_name: data.player_name, position: data.position, is_leadership: data.is_leadership };
    showApp();
  } catch (e) {
    errorEl.textContent = "Couldn't reach the app.";
  }
});

document.getElementById("login-api-key").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("login-submit").click();
});

document.getElementById("logout-btn").addEventListener("click", async () => {
  try {
    await api("/api/auth/logout", { method: "POST" });
  } catch (e) {
    // already logged out / session gone - fine, still show the login screen
  }
  showLogin();
});

// ---------- Settings ----------

async function renderSettings() {
  const root = document.getElementById("tab-settings");
  const settings = await api("/api/settings");
  const rates = await api("/api/settings/rank-pay-rates");
  const apiKeys = await api("/api/settings/api-keys");
  const discordUsers = await api("/api/settings/discord-allowed-users");

  root.innerHTML = `
    <div class="card">
      <h2>Faction</h2>
      <div class="row">
        <label>Faction ID<br/><input type="number" id="faction-id" value="${settings.faction_id ?? ""}" style="width:120px" /></label>
        <button class="action" id="save-faction-id" style="align-self:flex-end">Save</button>
      </div>
    </div>

    <div class="card">
      <h2>Torn API Keys</h2>
      <p class="muted">
        Torn caps each key at 100 requests/minute (this app self-limits to 50/key to stay safe). Adding more
        keys - e.g. from other faction members - pools their budgets together for more total throughput.
        Each key needs at least <strong>Limited</strong> access, and should belong to a member of this faction
        (some endpoints are scoped to "my faction", not an explicit faction ID).
      </p>
      <table>
        <thead><tr><th>Label</th><th>Key</th><th></th></tr></thead>
        <tbody id="api-key-rows">
          ${apiKeys
            .map(
              (k) => `
            <tr>
              <td>${k.label || "-"}</td>
              <td class="muted">${k.masked_key}</td>
              <td><button class="danger" data-del-key="${k.id}">Remove</button></td>
            </tr>`
            )
            .join("") || `<tr><td colspan="3" class="muted">No keys added yet.</td></tr>`}
        </tbody>
      </table>
      <div class="row" style="margin-top:10px">
        <input type="password" id="new-api-key" placeholder="Torn API key" style="width:220px" />
        <input id="new-api-key-label" placeholder="Label (e.g. a player's name)" style="width:200px" />
        <button class="action" id="add-api-key">Add Key</button>
      </div>
      <p class="muted">Stored locally in the sqlite db on this machine only, sent only to api.torn.com.</p>
    </div>

    <div class="card">
      <h2>Discord Bot</h2>
      <p class="muted">
        Lets leadership run read-only commands (<code>/wars</code>, <code>/paysheet</code>, <code>/stats</code>,
        <code>/career</code>, <code>/armory</code>) from Discord. The bot only makes an outbound connection to
        Discord and talks to this app over localhost - no port forwarding or router changes needed. Runs as its
        own process: <code>./start-bot.sh</code>. Create a bot application at
        <a href="https://discord.com/developers/applications" target="_blank" rel="noopener">discord.com/developers/applications</a>
        to get a token.
      </p>
      <div class="row">
        <label>Bot Token<br/><input type="password" id="discord-token" placeholder="${settings.has_discord_bot_token ? settings.discord_bot_token_masked + " (already set)" : "paste bot token"}" style="width:280px" /></label>
        <button class="action" id="save-discord-token" style="align-self:flex-end">Save Token</button>
      </div>
      <div class="row" style="margin-top:10px">
        <label>Server (Guild) ID <span class="muted">(optional - instant command sync)</span><br/><input id="discord-guild-id" value="${settings.discord_guild_id ?? ""}" style="width:200px" /></label>
        <button class="action" id="save-discord-guild" style="align-self:flex-end">Save</button>
      </div>
      <div class="row" style="margin-top:10px">
        <label>Alert Channel ID <span class="muted">(self-hosp / revives-off reminders)</span><br/><input id="discord-alert-channel-id" value="${settings.discord_alert_channel_id ?? ""}" style="width:200px" /></label>
        <button class="action" id="save-discord-alert-channel" style="align-self:flex-end">Save</button>
      </div>

      <h3 style="margin-top:16px">Allowed Discord Users</h3>
      <p class="muted">
        Only these Discord accounts can use the bot's commands - everyone else is ignored. Leadership controls
        which commands they can run: leadership-only commands reject anyone unchecked here (right now that's
        every command except <code>/add_api_key</code>, which is open to any Discord user). Torn Player ID is
        separate from both - it's how the bot knows who to @mention for self-hosp and revives-off alerts.
      </p>
      <table>
        <thead><tr><th>Label</th><th>Discord User ID</th><th>Torn Player ID</th><th>Leadership</th><th></th></tr></thead>
        <tbody id="discord-user-rows">
          ${discordUsers
            .map(
              (u) => `
            <tr>
              <td>${u.label || "-"}</td>
              <td class="muted">${u.discord_user_id}</td>
              <td class="muted">${u.torn_player_id ?? "-"}</td>
              <td><input type="checkbox" data-leadership-toggle="${u.discord_user_id}" ${u.is_leadership ? "checked" : ""} /></td>
              <td><button class="danger" data-del-discord-user="${u.id}">Remove</button></td>
            </tr>`
            )
            .join("") || `<tr><td colspan="5" class="muted">No one added yet.</td></tr>`}
        </tbody>
      </table>
      <div class="row" style="margin-top:10px">
        <input id="new-discord-user-id" placeholder="Discord User ID" style="width:180px" />
        <input id="new-discord-user-label" placeholder="Label (e.g. a name)" style="width:200px" />
        <input id="new-discord-user-torn-id" placeholder="Torn Player ID (optional)" type="number" style="width:180px" />
        <label class="muted" style="display:flex;align-items:center;gap:4px"><input type="checkbox" id="new-discord-user-leadership" /> Leadership</label>
        <button class="action" id="add-discord-user">Add</button>
      </div>
      <p class="muted">Re-adding an existing Discord User ID updates its label/Torn Player ID instead of duplicating the row.</p>
      <p class="muted">Turn on Discord's Developer Mode (Settings → Advanced) to right-click a user and "Copy User ID".</p>
    </div>

    <div class="card">
      <h2>FFScouter (Estimated Stats)</h2>
      <p class="muted">
        Torn's own API doesn't expose enemy battle stats, so the Discord bot's <code>/current_war</code> board pulls
        estimated stats from <a href="https://ffscouter.com" target="_blank" rel="noopener">ffscouter.com</a>
        instead, if you have an account there. This is a separate key from your Torn API key - register one at
        <a href="https://ffscouter.com/api-docs" target="_blank" rel="noopener">ffscouter.com/api-docs</a>. Optional -
        without it, the board just shows "-" for that column.
      </p>
      <div class="row">
        <label>FFScouter API Key<br/><input type="password" id="ffscouter-key" placeholder="${settings.has_ffscouter_api_key ? settings.ffscouter_api_key_masked + " (already set)" : "paste FFScouter API key"}" style="width:280px" /></label>
        <button class="action" id="save-ffscouter-key" style="align-self:flex-end">Save</button>
      </div>
    </div>

    <div class="card">
      <h2>Rank Pay Rates</h2>
      <p class="muted">Applied to each member's final pay based on their selected rank for a given war.</p>
      <table>
        <thead><tr><th>Rank</th><th>Pay Rate %</th><th></th></tr></thead>
        <tbody id="rank-rows"></tbody>
      </table>
      <div class="row" style="margin-top:10px">
        <input id="new-rank-name" placeholder="Rank name" style="width:220px" />
        <input id="new-rank-pct" type="number" placeholder="%" style="width:90px" />
        <button class="action" id="add-rank">Add / Update</button>
      </div>
    </div>

    <div class="card">
      <h2>Backup / Transfer</h2>
      <p class="muted">
        Exports everything on this Settings page - faction ID, Torn API keys, Discord bot token, allowed users,
        FFScouter key, rank pay rates, and armory targets - to a JSON file, for moving to another machine.
        <strong>The file contains real, unmasked secrets</strong> (your Torn API keys and Discord bot token) -
        handle it like any other credentials backup: don't post it anywhere, and store it somewhere private.
        War history and accumulated observation logs (travel/activity) aren't included.
      </p>
      <div class="row">
        <button class="action" id="export-settings">Export Settings</button>
        <input type="file" id="import-settings-file" accept="application/json" style="display:none" />
        <button class="action" id="import-settings">Import Settings</button>
      </div>
      <p class="muted">Importing is safe to run more than once or onto an existing setup - matching entries (by API key, Discord user, rank, or armory item) are updated in place rather than duplicated.</p>
    </div>
  `;

  const tbody = root.querySelector("#rank-rows");
  rates.forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.rank_name}</td>
      <td><input type="number" value="${r.pay_rate_pct}" data-rank="${r.rank_name}" class="rank-pct" /></td>
      <td><button class="danger" data-del-rank="${r.rank_name}">Remove</button></td>
    `;
    tbody.appendChild(tr);
  });

  tbody.querySelectorAll(".rank-pct").forEach((inp) => {
    inp.addEventListener("change", async () => {
      await api("/api/settings/rank-pay-rates", {
        method: "POST",
        body: JSON.stringify({ rank_name: inp.dataset.rank, pay_rate_pct: Number(inp.value) }),
      });
      toast("Rank pay rate updated");
    });
  });

  tbody.querySelectorAll("[data-del-rank]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await api(`/api/settings/rank-pay-rates/${encodeURIComponent(btn.dataset.delRank)}`, { method: "DELETE" });
      renderSettings();
    });
  });

  root.querySelector("#add-rank").addEventListener("click", async () => {
    const name = root.querySelector("#new-rank-name").value.trim();
    const pct = Number(root.querySelector("#new-rank-pct").value);
    if (!name) return;
    await api("/api/settings/rank-pay-rates", { method: "POST", body: JSON.stringify({ rank_name: name, pay_rate_pct: pct }) });
    renderSettings();
  });

  root.querySelector("#export-settings").addEventListener("click", async () => {
    const data = await api("/api/settings/export");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const date = new Date().toISOString().slice(0, 10);
    a.href = url;
    a.download = `torn-war-boss-settings-${date}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast("Settings exported - keep that file private, it has your real API keys/token in it");
  });

  root.querySelector("#import-settings").addEventListener("click", () => {
    root.querySelector("#import-settings-file").click();
  });

  root.querySelector("#import-settings-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      await api("/api/settings/import", { method: "POST", body: JSON.stringify(data) });
      toast("Settings imported");
      renderSettings();
    } catch (err) {
      toast(`Import failed: ${err.message}`, true);
    }
    e.target.value = "";
  });

  root.querySelector("#save-faction-id").addEventListener("click", async () => {
    const fid = root.querySelector("#faction-id").value.trim();
    if (!fid) return;
    await api("/api/settings", { method: "POST", body: JSON.stringify({ faction_id: Number(fid) }) });
    toast("Faction ID saved");
    renderSettings();
  });

  root.querySelector("#add-api-key").addEventListener("click", async () => {
    const key = root.querySelector("#new-api-key").value.trim();
    const label = root.querySelector("#new-api-key-label").value.trim();
    if (!key) return;
    await api("/api/settings/api-keys", { method: "POST", body: JSON.stringify({ api_key: key, label: label || null }) });
    toast("API key added");
    renderSettings();
  });

  root.querySelectorAll("[data-del-key]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await api(`/api/settings/api-keys/${btn.dataset.delKey}`, { method: "DELETE" });
      renderSettings();
    });
  });

  root.querySelector("#save-discord-token").addEventListener("click", async () => {
    const token = root.querySelector("#discord-token").value.trim();
    if (!token) return;
    await api("/api/settings/discord-bot-token", { method: "POST", body: JSON.stringify({ token }) });
    toast("Discord bot token saved - (re)start the bot to pick it up");
    renderSettings();
  });

  root.querySelector("#save-ffscouter-key").addEventListener("click", async () => {
    const key = root.querySelector("#ffscouter-key").value.trim();
    if (!key) return;
    await api("/api/settings/ffscouter-api-key", { method: "POST", body: JSON.stringify({ api_key: key }) });
    toast("FFScouter API key saved");
    renderSettings();
  });

  root.querySelector("#save-discord-guild").addEventListener("click", async () => {
    const guildId = root.querySelector("#discord-guild-id").value.trim();
    await api("/api/settings/discord-guild-id", { method: "POST", body: JSON.stringify({ guild_id: guildId }) });
    toast("Saved - (re)start the bot to pick it up");
    renderSettings();
  });

  root.querySelector("#save-discord-alert-channel").addEventListener("click", async () => {
    const channelId = root.querySelector("#discord-alert-channel-id").value.trim();
    await api("/api/settings/discord-alert-channel-id", { method: "POST", body: JSON.stringify({ channel_id: channelId }) });
    toast("Saved");
    renderSettings();
  });

  root.querySelector("#add-discord-user").addEventListener("click", async () => {
    const id = root.querySelector("#new-discord-user-id").value.trim();
    const label = root.querySelector("#new-discord-user-label").value.trim();
    const tornId = root.querySelector("#new-discord-user-torn-id").value.trim();
    const isLeadership = root.querySelector("#new-discord-user-leadership").checked;
    if (!id) return;
    await api("/api/settings/discord-allowed-users", {
      method: "POST",
      body: JSON.stringify({
        discord_user_id: id,
        label: label || null,
        torn_player_id: tornId ? Number(tornId) : null,
        is_leadership: isLeadership,
      }),
    });
    toast("Discord user added");
    renderSettings();
  });

  root.querySelectorAll("[data-leadership-toggle]").forEach((checkbox) => {
    checkbox.addEventListener("change", async () => {
      const u = discordUsers.find((u) => u.discord_user_id === checkbox.dataset.leadershipToggle);
      if (!u) return;
      await api("/api/settings/discord-allowed-users", {
        method: "POST",
        body: JSON.stringify({
          discord_user_id: u.discord_user_id,
          label: u.label,
          torn_player_id: u.torn_player_id,
          is_leadership: checkbox.checked,
        }),
      });
      toast(checkbox.checked ? `${u.label || u.discord_user_id} is now leadership` : `${u.label || u.discord_user_id} is no longer leadership`);
    });
  });

  root.querySelectorAll("[data-del-discord-user]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await api(`/api/settings/discord-allowed-users/${btn.dataset.delDiscordUser}`, { method: "DELETE" });
      renderSettings();
    });
  });
}

// ---------- Wars ----------

async function renderWars() {
  if (state.warId) {
    renderWarDetail(state.warId);
    return;
  }
  const root = document.getElementById("tab-wars");
  root.innerHTML = `<div class="card"><p class="muted">Loading...</p></div>`;

  const synced = await api("/api/wars");

  root.innerHTML = `
    <div class="card">
      <div class="row between">
        <h2>Synced Wars</h2>
        <button class="action" id="load-available">Load from Torn</button>
      </div>
      <div id="synced-list">
        ${
          synced.length
            ? synced
                .map(
                  (w) => `
          <div class="war-list-item" data-war="${w.id}">
            <span>vs ${w.opponent_name ?? "?"} <span class="muted">(${fmtDate(w.start)} - ${fmtDate(w.end)})</span></span>
            <span class="badge synced">synced</span>
          </div>`
                )
                .join("")
            : `<p class="muted">No wars synced yet. Click "Load from Torn" to pick one.</p>`
        }
      </div>
    </div>
    <div id="available-wars"></div>
  `;

  root.querySelectorAll("[data-war]").forEach((el) => {
    el.addEventListener("click", () => {
      state.warId = Number(el.dataset.war);
      renderWarDetail(state.warId);
    });
  });

  root.querySelector("#load-available").addEventListener("click", async () => {
    const list = await api("/api/wars/available");
    const container = root.querySelector("#available-wars");
    container.innerHTML = `
      <div class="card">
        <h2>Available Ranked Wars</h2>
        ${list
          .map(
            (w) => `
          <div class="war-list-item">
            <span>vs ${w.opponent_name ?? "?"} <span class="muted">(${fmtDate(w.start)} - ${fmtDate(w.end)})</span></span>
            ${
              w.already_synced
                ? `<span class="badge synced">synced</span>`
                : `<button class="action" data-sync="${w.id}">Sync</button>`
            }
          </div>`
          )
          .join("")}
      </div>
    `;
    container.querySelectorAll("[data-sync]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.textContent = "Syncing...";
        btn.disabled = true;
        const id = Number(btn.dataset.sync);
        await api(`/api/wars/${id}/sync`, { method: "POST" });
        toast("War synced");
        state.warId = id;
        renderWarDetail(id);
      });
    });
  });
}

async function renderWarDetail(warId) {
  const root = document.getElementById("tab-wars");
  root.innerHTML = `<div class="card"><p class="muted">Loading war...</p></div>`;
  const [data, playerStats] = await Promise.all([
    api(`/api/wars/${warId}`),
    api(`/api/wars/${warId}/stats`),
  ]);

  const w = data.war;
  const t = data.totals;
  const warTitle = `vs ${w.opponent_name ?? "?"} (${fmtDate(w.start)} - ${fmtDate(w.end)})`;

  root.innerHTML = `
    <button class="action" id="back-to-wars" style="margin-bottom:14px">&larr; All Wars</button>

    <div class="card">
      <h2>vs ${w.opponent_name ?? "?"} <span class="muted">(${fmtDate(w.start)} - ${fmtDate(w.end)})</span></h2>
      <div class="row">
        <label>Cache Sell Price<br/><input type="number" id="cache-price" value="${w.cache_sell_price}" style="width:180px" /></label>
        <label>Leadership Cut %<br/><input type="number" id="leadership-cut" value="${w.leadership_cut_pct}" style="width:100px" /></label>
        <label>Outside Pay Rate %<br/><input type="number" id="outside-rate" value="${w.outside_pay_rate_pct}" style="width:100px" /></label>
        <button class="action" id="save-war-settings" style="align-self:flex-end">Apply</button>
        <button class="action" id="resync-war" style="align-self:flex-end">Re-sync</button>
      </div>
      <div class="row" style="margin-top:10px">
        <label style="display:flex;align-items:center;gap:6px"><input type="checkbox" id="is-termed" ${w.is_termed ? "checked" : ""} /> War was termed</label>
        <label>Termed At<br/><input type="datetime-local" id="termed-at" value="${tsToDatetimeLocal(w.termed_at)}" ${w.is_termed ? "" : "disabled"} /></label>
        <span class="muted">Respect Lost only counts up to this point (or not at all if termed with no time set). Re-sync to recompute it.</span>
      </div>
    </div>

    <div class="card">
      <div class="stat-grid">
        <div class="stat"><div class="label">Total Expenses</div><div class="value">${money(t.total_expenses)}</div></div>
        <div class="stat"><div class="label">War Pay</div><div class="value">${money(t.war_pay)}</div></div>
        <div class="stat"><div class="label">Pay For Hits</div><div class="value">${money(t.pay_for_hits)}</div></div>
        <div class="stat"><div class="label">Leadership Cut</div><div class="value">${money(t.leadership_cut_amount)}</div></div>
        <div class="stat"><div class="label">Inside Hits</div><div class="value">${num(t.total_inside_hits)}</div></div>
        <div class="stat"><div class="label">Outside+Assist Hits</div><div class="value">${num(t.total_outside_assist_hits)}</div></div>
        <div class="stat"><div class="label">$ / Inside Hit</div><div class="value">${money(t.per_inside_hit_rate)}</div></div>
        <div class="stat"><div class="label">$ / Outside Hit</div><div class="value">${money(t.per_outside_hit_rate)}</div></div>
      </div>
    </div>

    <div class="card" id="budget-check-card"></div>

    <div class="card">
      <h2>Expenses</h2>
      ${data.armory_error ? `<p class="muted negative">Armory cost unavailable: ${data.armory_error}</p>` : ""}
      <table>
        <thead><tr><th>Label</th><th>Amount</th><th></th></tr></thead>
        <tbody id="expense-rows">
          ${data.expense_lines
            .map(
              (e) => `
            <tr data-line="${e.id}">
              <td><input value="${e.label}" class="exp-label" /></td>
              <td><input type="number" value="${e.amount}" class="exp-amount" /></td>
              <td><button class="danger" data-del-expense="${e.id}">Remove</button></td>
            </tr>`
            )
            .join("")}
          <tr>
            <td><em>${data.armory_line.label} (computed)</em></td>
            <td>${money(data.armory_line.amount)}</td>
            <td></td>
          </tr>
          <tr>
            <td><em>${data.salary_line.label} (computed)</em></td>
            <td>${money(data.salary_line.amount)}</td>
            <td></td>
          </tr>
        </tbody>
      </table>
      <div class="row" style="margin-top:10px">
        <input id="new-exp-label" placeholder="Expense label" style="width:220px" />
        <input id="new-exp-amount" type="number" placeholder="Amount" style="width:140px" />
        <button class="action" id="add-expense">Add</button>
      </div>
    </div>

    <div class="card">
      <div class="row between">
        <h2>Paysheet</h2>
        <button class="action" id="copy-paysheet-image">Copy as Image</button>
      </div>
      <table>
        <thead>
          <tr>
            <th>Name</th><th>Inside</th><th>Outside</th><th>Assists</th><th>Xanax Used</th>
            <th>Rank</th><th>Fine</th><th>Paid Back</th><th>Gross Pay</th><th>Bonus</th><th>Final Pay</th><th>Paid</th>
          </tr>
        </thead>
        <tbody id="member-rows"></tbody>
        <tfoot id="paysheet-totals"></tfoot>
      </table>
    </div>

    <div class="card">
      <div class="row between">
        <h2>Player Stats</h2>
        <button class="action" id="copy-stats-image">Copy as Image</button>
      </div>
      <p class="muted">Score/Overall Rank are total hits + respect gained + respect lost, summed and re-ranked (lower is better). Best Hit, Avg Respect/Hit, Win Rate, Retaliation Hits, and Bonus Hits are shown for reference and aren't part of the Score yet.</p>
      <h3>Leadership</h3>
      ${renderStatsTable(playerStats.leadership)}
      <h3 style="margin-top:18px">Everyone Else</h3>
      ${renderStatsTable(playerStats.others)}
    </div>
  `;

  root.querySelector("#copy-stats-image").addEventListener("click", () => {
    copyTablesAsImage(`Player Stats ${warTitle}`, [
      { heading: "Leadership", headers: STAT_HEADERS, rows: playerStats.leadership.map(statsRowCells) },
      { heading: "Everyone Else", headers: STAT_HEADERS, rows: playerStats.others.map(statsRowCells) },
    ]);
  });

  root.querySelector("#copy-paysheet-image").addEventListener("click", () => {
    copyTablesAsImage(`Paysheet ${warTitle}`, [
      { headers: PAYSHEET_HEADERS, rows: [...data.members.map(paysheetRowCells), paysheetTotalsCells(data.members)] },
    ]);
  });

  root.querySelector("#back-to-wars").addEventListener("click", () => {
    state.warId = null;
    renderWars();
  });

  root.querySelector("#is-termed").addEventListener("change", (e) => {
    root.querySelector("#termed-at").disabled = !e.target.checked;
  });

  root.querySelector("#save-war-settings").addEventListener("click", async () => {
    await api(`/api/wars/${warId}`, {
      method: "PATCH",
      body: JSON.stringify({
        cache_sell_price: Number(root.querySelector("#cache-price").value),
        leadership_cut_pct: Number(root.querySelector("#leadership-cut").value),
        outside_pay_rate_pct: Number(root.querySelector("#outside-rate").value),
        is_termed: root.querySelector("#is-termed").checked,
        termed_at: datetimeLocalToTs(root.querySelector("#termed-at").value),
      }),
    });
    toast("Saved - re-sync to recompute Respect Lost");
    renderWarDetail(warId);
  });

  root.querySelector("#resync-war").addEventListener("click", async () => {
    toast("Re-syncing...");
    await api(`/api/wars/${warId}/sync`, { method: "POST" });
    renderWarDetail(warId);
  });

  root.querySelectorAll("[data-del-expense]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await api(`/api/wars/${warId}/expenses/${btn.dataset.delExpense}`, { method: "DELETE" });
      renderWarDetail(warId);
    });
  });

  root.querySelectorAll("#expense-rows tr[data-line]").forEach((tr) => {
    const lineId = tr.dataset.line;
    const commit = async () => {
      await api(`/api/wars/${warId}/expenses/${lineId}`, {
        method: "PATCH",
        body: JSON.stringify({
          label: tr.querySelector(".exp-label").value,
          amount: Number(tr.querySelector(".exp-amount").value),
        }),
      });
      renderWarDetail(warId);
    };
    tr.querySelector(".exp-label").addEventListener("change", commit);
    tr.querySelector(".exp-amount").addEventListener("change", commit);
  });

  root.querySelector("#add-expense").addEventListener("click", async () => {
    const label = root.querySelector("#new-exp-label").value.trim();
    const amount = Number(root.querySelector("#new-exp-amount").value);
    if (!label) return;
    await api(`/api/wars/${warId}/expenses`, { method: "POST", body: JSON.stringify({ label, amount }) });
    renderWarDetail(warId);
  });

  const rankRates = await api("/api/settings/rank-pay-rates");
  const memberBody = root.querySelector("#member-rows");
  data.members.forEach((m) => {
    const tr = document.createElement("tr");
    const rankOptions = rankRates
      .map((r) => `<option value="${r.rank_name}" ${m.pay_rank === r.rank_name ? "selected" : ""}>${r.rank_name}</option>`)
      .join("");
    const fineTitle = m.unpaid_xanax
      ? `${num(m.unpaid_xanax)} xanax not covered by hits (${HITS_PER_XANAX} hits/xanax, rounded up)`
      : "";
    const bonus = m.flat_bonus + m.leadership_cut_share;
    const bonusTitle = m.leadership_cut_share
      ? "Leadership cut (share)"
      : m.flat_bonus
        ? "Flat rank salary"
        : "";
    tr.innerHTML = `
      <td>${m.name}</td>
      <td>${num(m.inside_hits)}</td>
      <td>${num(m.outside_hits)}</td>
      <td>${num(m.assist_hits)}</td>
      <td>${num(m.xanax_used)}</td>
      <td><select class="member-rank" data-member="${m.member_id}"><option value="">-- select --</option>${rankOptions}</select></td>
      <td title="${fineTitle}">${money(m.calculated_fine)}</td>
      <td><input type="checkbox" class="member-fine-waived" data-member="${m.member_id}" ${m.fine_waived ? "checked" : ""} ${m.calculated_fine ? "" : "disabled"} /></td>
      <td>${money(m.gross_pay)}</td>
      <td title="${bonusTitle}">${money(bonus)}</td>
      <td><strong class="${m.final_pay < 0 ? "negative" : ""}">${money(m.final_pay)}</strong></td>
      <td><input type="checkbox" class="member-paid" data-member="${m.member_id}" ${m.paid ? "checked" : ""} /></td>
    `;
    memberBody.appendChild(tr);
  });

  const totals = paysheetTotalsCells(data.members);
  root.querySelector("#paysheet-totals").innerHTML = `
    <tr>${totals.map((c) => `<td><strong class="${c && c.color === IMAGE_COLORS.bad ? "negative" : ""}">${cellText(c)}</strong></td>`).join("")}</tr>
  `;

  // Budget check: does the cache sell price actually cover everyone's final
  // pay plus restocking the armory? A meaningful (not just rounding-noise)
  // diff is expected here whenever any rank is paid below 100% - that
  // difference is money that stays with the faction rather than going to
  // any single member's payout, not a bug.
  const totalPayout = sumBy(data.members, (m) => m.final_pay);
  const armoryCost = data.armory_line.amount;
  const budgetDiff = w.cache_sell_price - (totalPayout + armoryCost);
  root.querySelector("#budget-check-card").innerHTML = `
    <h2>Budget Check</h2>
    <div class="stat-grid">
      <div class="stat"><div class="label">Cache Sell Price</div><div class="value">${money(w.cache_sell_price)}</div></div>
      <div class="stat"><div class="label">Total Payouts</div><div class="value">${money(totalPayout)}</div></div>
      <div class="stat"><div class="label">Armory Restock Cost</div><div class="value">${money(armoryCost)}</div></div>
      <div class="stat"><div class="label">Difference</div><div class="value ${budgetDiff < 0 ? "negative" : "positive"}">${money(budgetDiff)}</div></div>
    </div>
    <p class="muted">Difference = Cache Sell Price - (Total Payouts + Armory Restock Cost). Positive means money is left over after paying everyone and restocking; negative means the cache sell price didn't cover it.</p>
  `;

  memberBody.querySelectorAll(".member-rank").forEach((sel) => {
    sel.addEventListener("change", async () => {
      await api(`/api/wars/${warId}/members/${sel.dataset.member}`, {
        method: "PATCH",
        body: JSON.stringify({ pay_rank: sel.value }),
      });
      renderWarDetail(warId);
    });
  });

  memberBody.querySelectorAll(".member-fine-waived").forEach((cb) => {
    cb.addEventListener("change", async () => {
      await api(`/api/wars/${warId}/members/${cb.dataset.member}`, {
        method: "PATCH",
        body: JSON.stringify({ fine_waived: cb.checked }),
      });
      renderWarDetail(warId);
    });
  });

  memberBody.querySelectorAll(".member-paid").forEach((cb) => {
    cb.addEventListener("change", async () => {
      await api(`/api/wars/${warId}/members/${cb.dataset.member}`, {
        method: "PATCH",
        body: JSON.stringify({ paid: cb.checked }),
      });
      renderWarDetail(warId);
    });
  });
}

// ---------- Armory ----------

async function renderArmory() {
  const root = document.getElementById("tab-armory");
  root.innerHTML = `<div class="card"><p class="muted">Loading targets...</p></div>`;
  const targets = await api("/api/armory/targets");

  root.innerHTML = `
    <div class="card">
      <div class="row between">
        <h2>Armory Restock</h2>
        <button class="action" id="refresh-restock">Refresh from Torn</button>
      </div>
      <table>
        <thead>
          <tr><th>Item</th><th>Category</th><th>Target Qty</th><th>On Hand</th><th>Needed</th><th>Unit Price</th><th>Cost</th><th></th></tr>
        </thead>
        <tbody id="armory-rows">
          ${targets
            .map(
              (t) => `
            <tr data-item="${t.item_id}">
              <td>${t.item_name}</td>
              <td class="muted">${t.armory_category}</td>
              <td><input type="number" class="target-qty" data-item="${t.item_id}" value="${t.target_qty}" style="width:90px" /></td>
              <td class="on-hand">-</td>
              <td class="needed">-</td>
              <td class="unit-price">-</td>
              <td class="cost">-</td>
              <td><button class="danger" data-del-item="${t.item_id}">Remove</button></td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>
      <p class="muted">Xanax's On Hand figure includes whatever's currently in your personal display case automatically, since Torn's inventory API stops listing an item entirely once every unit is parked there.</p>
      <div class="row" style="margin-top:6px"><strong>Total: <span id="armory-total">-</span></strong></div>
    </div>

    <div class="card">
      <h3>Track a new item</h3>
      <div class="row">
        <input id="new-item-id" type="number" placeholder="Item ID" style="width:100px" />
        <input id="new-item-name" placeholder="Item name" style="width:200px" />
        <select id="new-item-armory-cat">
          <option value="weapons">weapons</option>
          <option value="armor">armor</option>
          <option value="temporary">temporary</option>
          <option value="medical" selected>medical</option>
          <option value="consumables">consumables</option>
          <option value="drugs">drugs</option>
          <option value="boosters">boosters</option>
          <option value="utilities">utilities</option>
          <option value="loot">loot</option>
        </select>
        <select id="new-item-torn-cat">
          <option value="Medical" selected>Medical</option>
          <option value="Drug">Drug</option>
          <option value="Temporary">Temporary</option>
          <option value="Weapon">Weapon</option>
          <option value="Armor">Armor</option>
          <option value="Defensive">Defensive</option>
          <option value="Supply Pack">Supply Pack</option>
        </select>
        <input id="new-item-target" type="number" placeholder="Target qty" style="width:110px" />
        <button class="action" id="add-item">Add</button>
      </div>
      <p class="muted">Armory category filters faction inventory stock; Torn category filters market price lookup.</p>
    </div>
  `;

  root.querySelectorAll(".target-qty").forEach((inp) => {
    inp.addEventListener("change", async () => {
      await api(`/api/armory/targets/${inp.dataset.item}`, {
        method: "PATCH",
        body: JSON.stringify({ target_qty: Number(inp.value) }),
      });
      toast("Target updated");
      loadRestock();
    });
  });

  root.querySelectorAll("[data-del-item]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await api(`/api/armory/targets/${btn.dataset.delItem}`, { method: "DELETE" });
      renderArmory();
    });
  });

  root.querySelector("#add-item").addEventListener("click", async () => {
    const item_id = Number(root.querySelector("#new-item-id").value);
    const item_name = root.querySelector("#new-item-name").value.trim();
    const armory_category = root.querySelector("#new-item-armory-cat").value;
    const torn_item_category = root.querySelector("#new-item-torn-cat").value;
    const target_qty = Number(root.querySelector("#new-item-target").value) || 0;
    if (!item_id || !item_name) return;
    await api("/api/armory/targets", {
      method: "POST",
      body: JSON.stringify({ item_id, item_name, armory_category, torn_item_category, target_qty }),
    });
    renderArmory();
  });

  root.querySelector("#refresh-restock").addEventListener("click", loadRestock);
  loadRestock();

  async function loadRestock() {
    const restock = await api("/api/armory/restock").catch(() => null);
    if (!restock) return;
    let total = 0;
    restock.lines.forEach((l) => {
      const tr = root.querySelector(`tr[data-item="${l.item_id}"]`);
      if (!tr) return;
      tr.querySelector(".on-hand").textContent = num(l.on_hand);
      tr.querySelector(".needed").textContent = num(l.needed);
      tr.querySelector(".unit-price").textContent = money(l.unit_price);
      tr.querySelector(".cost").textContent = money(l.cost);
      total += l.cost;
    });
    root.querySelector("#armory-total").textContent = money(total);
  }
}

// ---------- Career Stats ----------

const CAREER_STAT_TABS = [
  { key: "overall", rankKey: "overall_rank", label: "Overall" },
  { key: "avg_hits", rankKey: "avg_hits_rank", label: "Avg Hits Made" },
  { key: "avg_respect_gained", rankKey: "avg_respect_gained_rank", label: "Avg Respect Gained" },
  { key: "avg_respect_lost", rankKey: "avg_respect_lost_rank", label: "Avg Respect Lost" },
  { key: "avg_best_hit", rankKey: "avg_best_hit_rank", label: "Avg Best Hit" },
  { key: "avg_respect_per_hit", rankKey: "avg_respect_per_hit_rank", label: "Avg Respect/Hit" },
];

async function renderCareerStats() {
  const root = document.getElementById("tab-stats");
  root.innerHTML = `<div class="card"><p class="muted">Loading stats...</p></div>`;
  const members = await api("/api/stats/career").catch(() => null);
  if (!members) return;

  if (!state.statsMetric) state.statsMetric = CAREER_STAT_TABS[0].key;

  const renderTable = () => {
    const active = CAREER_STAT_TABS.find((t) => t.key === state.statsMetric);
    const sorted = [...members].sort((a, b) => a[active.rankKey] - b[active.rankKey]);
    const rows = sorted
      .map(
        (m) => `
      <tr>
        <td>${m.name}</td>
        <td class="muted">${m.position || "-"}</td>
        <td>${num(m.wars_played)}</td>
        <td>${num(m.avg_hits, 1)} <span class="muted">(#${m.avg_hits_rank})</span></td>
        <td>${num(m.avg_respect_gained, 2)} <span class="muted">(#${m.avg_respect_gained_rank})</span></td>
        <td>${num(m.avg_respect_lost, 2)} <span class="muted">(#${m.avg_respect_lost_rank})</span></td>
        <td>${num(m.avg_best_hit, 2)} <span class="muted">(#${m.avg_best_hit_rank})</span></td>
        <td>${num(m.avg_respect_per_hit, 2)} <span class="muted">(#${m.avg_respect_per_hit_rank})</span></td>
        <td>${m.score}</td>
        <td><strong>#${m.overall_rank}</strong></td>
      </tr>`
      )
      .join("");
    root.querySelector("#career-stats-table").innerHTML = `
      <table>
        <thead>
          <tr>
            <th>Name</th><th>Position</th><th>Wars Played</th>
            <th>Avg Hits Made</th><th>Avg Respect Gained</th><th>Avg Respect Lost</th>
            <th>Avg Best Hit</th><th>Avg Respect/Hit</th>
            <th>Score</th><th>Overall Rank</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  };

  root.innerHTML = `
    <div class="card">
      <div class="row between">
        <h2>Player Stats</h2>
      </div>
      <p class="muted">Per-war averages across every synced war, for everyone currently in the faction. Score/Overall Rank are Avg Hits + Avg Respect Gained + Avg Respect Lost, summed and re-ranked. The rest are shown for reference and aren't part of the Score yet.</p>
      <div class="row" id="career-stat-tabs" style="margin-bottom:14px">
        ${CAREER_STAT_TABS.map(
          (t) => `<button class="tab-btn ${t.key === state.statsMetric ? "active" : ""}" data-metric="${t.key}">${t.label}</button>`
        ).join("")}
      </div>
      <div id="career-stats-table"></div>
    </div>
  `;

  root.querySelectorAll("#career-stat-tabs .tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.statsMetric = btn.dataset.metric;
      root.querySelectorAll("#career-stat-tabs .tab-btn").forEach((b) => b.classList.toggle("active", b === btn));
      renderTable();
    });
  });

  renderTable();
}

// ---------- Live War ----------

function formatEta(unixTs) {
  if (!unixTs) return "-";
  const diffMs = unixTs * 1000 - Date.now();
  if (diffMs <= 0) return "landed";
  const totalSeconds = Math.floor(diffMs / 1000);
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}

function tickLiveWarCountdowns() {
  document.querySelectorAll("#tab-live [data-eta]").forEach((el) => {
    const ts = Number(el.dataset.eta);
    el.textContent = formatEta(ts);
  });
}

async function renderLiveWar() {
  const root = document.getElementById("tab-live");
  let snapshot;
  try {
    snapshot = await api("/api/live/war-snapshot");
  } catch (e) {
    return;
  }

  if (!snapshot.war_id || !snapshot.members.length) {
    root.innerHTML = `
      <div class="card">
        <h2>Live War</h2>
        <p class="muted">No live war board is currently running - ask leadership to run /current_war start in Discord.</p>
      </div>
    `;
    return;
  }

  const rows = [...snapshot.members].sort((a, b) => {
    const aOkay = a.status.state === "Okay" ? 0 : 1;
    const bOkay = b.status.state === "Okay" ? 0 : 1;
    if (aOkay !== bOkay) return aOkay - bOkay;
    return (b.level || 0) - (a.level || 0);
  });

  root.innerHTML = `
    <div class="card">
      <div class="row between">
        <h2>Live War</h2>
        <span class="muted">Updated ${snapshot.updated_at ? new Date(snapshot.updated_at * 1000).toLocaleTimeString() : "-"}</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>Name</th><th>Level</th><th>Est. Stats</th><th>Status</th><th>Last Action</th>
            <th>Position</th><th>Wall</th><th>Revivable</th><th>Online %</th><th>Landing ETA</th>
          </tr>
        </thead>
        <tbody>
          ${rows
            .map(
              (m) => `
            <tr>
              <td><a href="https://www.torn.com/page.php?sid=attack&user2ID=${m.id}" target="_blank" rel="noopener">${m.name}</a></td>
              <td>${m.level ?? "-"}</td>
              <td>${m.bs_estimate_human || "-"}</td>
              <td class="${m.status.state === "Okay" ? "positive" : "muted"}">${m.status.description || m.status.state}</td>
              <td>${m.last_action?.relative || "-"}</td>
              <td>${m.position || "-"}</td>
              <td>${m.is_on_wall ? "Yes" : "No"}</td>
              <td>${m.is_revivable ? "Yes" : "No"}</td>
              <td>${m.online_probability_now != null ? Math.round(m.online_probability_now) + "%" : "-"}</td>
              <td>${m.estimated_landing_at ? `<span data-eta="${m.estimated_landing_at}">${formatEta(m.estimated_landing_at)}</span>` : "-"}</td>
            </tr>
          `
            )
            .join("")}
        </tbody>
      </table>
    </div>
    <div class="card">
      <h2>Activity Heatmap</h2>
      <p class="muted">Percent of observed polls each member was Online, by UTC hour - needs 5+ polls at that hour to show, so this fills in the longer the bot runs.</p>
      <div class="table-scroll">
        <table>
          <thead>
            <tr><th>Name</th>${Array.from({ length: 24 }, (_, h) => `<th>${String(h).padStart(2, "0")}</th>`).join("")}</tr>
          </thead>
          <tbody>
            ${rows.map((m) => `<tr><td>${m.name}</td>${heatmapCells(m.activity_by_hour)}</tr>`).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function heatmapCells(activityByHour) {
  return Array.from({ length: 24 }, (_, h) => {
    const pct = (activityByHour || {})[String(h)];
    if (pct == null) return `<td class="heatmap-cell muted">-</td>`;
    const cls = pct >= 50 ? "positive" : pct < 20 ? "muted" : "";
    const style = pct >= 20 && pct < 50 ? ' style="color: var(--warn)"' : "";
    return `<td class="heatmap-cell ${cls}"${style}>${Math.round(pct)}%</td>`;
  }).join("");
}

function startLiveWarPolling() {
  stopLiveWarTimers();
  // Cheap to poll fast - this only re-reads the app's own cached snapshot,
  // never touches Torn's API (the bot's own refresh cadence, currently 30s,
  // is what actually bounds how fresh this data can be).
  state.liveWarTimer = setInterval(renderLiveWar, 2000);
  state.liveWarTickTimer = setInterval(tickLiveWarCountdowns, 1000);
}

// ---------- Init ----------

checkSession();
