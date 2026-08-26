# Torn Ranked War Boss

A local web app for managing [Torn](https://www.torn.com) faction ranked wars: it pulls war reports, chain reports, and armory data straight from Torn's API and computes member payouts and armory restock costs automatically, replacing a manually-maintained spreadsheet.

## Features

- **Wars** — syncs a ranked war's report and every chain fought during it, aggregating each member's inside/outside/assist hits automatically.
- **Paysheet** — enter the cache sell price and expense line items; per-member pay is computed from a configurable leadership cut, outside-hit pay rate, and rank-based pay rate (selectable per player, defaulted from their live Torn faction position).
- **Xanax fines** — tracks each member's armory Xanax usage since the previous war ended, and auto-calculates a fine for xanax not "backed" by enough hits (10 hits per xanax, rounded up), with a per-player checkbox to waive a fine once it's been paid back.
- **Armory restock** — tracks target stock levels (editable per item) against live on-hand quantities and market prices, and folds the restock cost into the paysheet automatically.
- **Payroll helper (Tampermonkey)** — Torn's API has no way to actually send money, so a companion userscript (`tampermonkey/torn-war-manager-payroll.user.js`) adds a panel to Torn's own faction "Give to User" page that fills in the player, "Add to balance", and amount for you from the app's paysheet. It never clicks Torn's own submit button — you always confirm the real transfer yourself, then mark it paid in the panel.
- **Pooled API keys** — Torn caps each key at 100 requests/minute. Add more keys in Settings (e.g. from other faction members) and the app round-robins requests across all of them, multiplying your effective throughput.
- **Discord bot** — read-only slash commands (`/wars`, `/paysheet`, `/stats`, `/career`, `/armory`) so leadership can check things from Discord without needing access to the machine running the app. No port forwarding or router changes needed — see below.

## Requirements

- Python 3.11+
- A Torn API key ([torn.com/preferences/api](https://www.torn.com/preferences/api)) with faction-level access (Public/Minimal is enough for most endpoints; armory inventory needs a Limited key)

## Install

```bash
git clone https://github.com/kf0uqr/TornRankedWarBoss.git
cd TornRankedWarBoss
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```bash
./start.sh
```

or directly:

```bash
.venv/bin/python app.py
```

Then open **http://localhost:8787**.

On first run, go to the **Settings** tab and enter your Torn API key and faction ID. These are stored locally in `torn_war_manager.db` (a SQLite file created next to `app.py`, ignored by git) and are never sent anywhere but `api.torn.com`.

You can add more API keys in Settings to pool their rate limits together - each key needs at least **Limited** access, and should belong to a member of *this* faction (some endpoints Torn scopes to "my faction" rather than an explicit faction ID, so a key from a different faction would return the wrong data).

## Payroll helper (optional)

1. Install [Tampermonkey](https://www.tampermonkey.net/) in your browser.
2. Open Tampermonkey's dashboard → Create a new script → replace its contents with `tampermonkey/torn-war-manager-payroll.user.js` → save.
3. With the app running, go to **Torn → Faction → Controls → Give to User**. A "War Manager Payroll" panel appears listing everyone with an unpaid Final Pay for the selected war.
4. Click **Fill** next to a player — it fills in their name, selects "Add to balance", and enters their amount. **It does not click Torn's "give money" button.** Review the filled-in amount yourself and click it in Torn.
5. Once you've actually sent it, click **Paid** in the panel to mark them paid (asks for confirmation first). This is the same flag as the "Paid" checkbox on the app's Paysheet.

The script only talks to `http://localhost:8787` (your own machine) and never touches your Torn API key.

## Discord bot (optional)

Lets leadership run read-only commands from Discord — `/wars`, `/paysheet [war_id]`, `/stats [war_id]`, `/career`, `/armory` — without needing to reach the app itself. It works entirely over an **outbound** connection to Discord (same as every Discord bot), so it needs no inbound port, no port forwarding, and no router changes at all. It talks to the app over plain `localhost`, since both run on your machine.

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications) → **New Application** → give it a name → **Bot** tab → **Reset Token** to reveal it, copy it.
2. Under **OAuth2 → URL Generator**, check `bot` and `applications.commands`, then open the generated URL to invite it to your server.
3. In the app's **Settings** tab, paste the bot token under "Discord Bot" and save.
4. (Optional but recommended for testing) Add your Discord server's ID as the "Server (Guild) ID" — this makes new slash commands show up instantly instead of waiting up to an hour for Discord's global sync.
5. Add each leader's Discord **User ID** (not username) under "Allowed Discord Users" — turn on Developer Mode in Discord (Settings → Advanced) to right-click someone and "Copy User ID". Only these accounts can use the bot's commands.
6. Run the bot as its own process:

```bash
./start-bot.sh
```

It needs the main app (`./start.sh`) running too, since it fetches data from it over localhost. Restart the bot after changing the token or guild ID in Settings — the allowed-users list, on the other hand, is checked live on every command, so changes there take effect immediately.

## Project layout

```
app.py              # entrypoint - starts the API and serves the frontend
backend/
  torn_api.py        # Torn API v2 client
  db.py               # SQLite schema + seed data
  sync.py             # pulls and aggregates war/chain/armory data from Torn
  payout.py           # paysheet math (pay pools, rank rates, xanax fines)
  armory.py           # restock calculator + armory-usage news parsing
  routes/              # FastAPI routes
frontend/            # vanilla HTML/CSS/JS, no build step
bot/
  discord_bot.py       # standalone Discord bot process (see "Discord bot" above)
tampermonkey/         # payroll-fill userscript (see "Payroll helper" above)
```
