# Torn Ranked War Boss

A local web app for managing [Torn](https://www.torn.com) faction ranked wars: it pulls war reports, chain reports, and armory data straight from Torn's API and computes member payouts and armory restock costs automatically, replacing a manually-maintained spreadsheet.

## Features

- **Wars** — syncs a ranked war's report and every chain fought during it, aggregating each member's inside/outside/assist hits automatically.
- **Paysheet** — enter the cache sell price and expense line items; per-member pay is computed from a configurable leadership cut, outside-hit pay rate, and rank-based pay rate (selectable per player, defaulted from their live Torn faction position).
- **Xanax fines** — tracks each member's armory Xanax usage since the previous war ended, and auto-calculates a fine for xanax not "backed" by enough hits (10 hits per xanax, rounded up), with a per-player checkbox to waive a fine once it's been paid back.
- **Armory restock** — tracks target stock levels (editable per item) against live on-hand quantities and market prices, and folds the restock cost into the paysheet automatically.

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
```
