# Torn Ranked War Boss

A local web app for managing [Torn](https://www.torn.com) faction ranked wars: it pulls war reports, chain reports, and armory data straight from Torn's API and computes member payouts and armory restock costs automatically, replacing a manually-maintained spreadsheet.

## Features

- **Wars** — syncs a ranked war's report and every chain fought during it, aggregating each member's inside/outside/assist hits automatically.
- **Paysheet** — enter the cache sell price and expense line items; per-member pay is computed from a configurable leadership cut, outside-hit pay rate, and rank-based pay rate (selectable per player, defaulted from their live Torn faction position).
- **Xanax fines** — tracks each member's armory Xanax usage since the previous war ended, and auto-calculates a fine for xanax not "backed" by enough hits (10 hits per xanax, rounded up), with a per-player checkbox to waive a fine once it's been paid back.
- **Armory restock** — tracks target stock levels (editable per item) against live on-hand quantities and market prices, and folds the restock cost into the paysheet automatically.
- **Payroll helper (Tampermonkey)** — Torn's API has no way to actually send money, so a companion userscript (`tampermonkey/torn-war-manager-payroll.user.js`) adds a panel to Torn's own faction "Give to User" page that fills in the player, "Add to balance", and amount for you from the app's paysheet. It never clicks Torn's own submit button — you always confirm the real transfer yourself, then mark it paid in the panel.
- **Pooled API keys** — Torn caps each key at 100 requests/minute. Add more keys in Settings (e.g. from other faction members) and the app round-robins requests across all of them, multiplying your effective throughput.
- **Discord bot** — read-only slash commands (`/wars`, `/paysheet`, `/stats`, `/career`, `/armory`, `/current_war`) so leadership can check things from Discord without needing access to the machine running the app, plus `/add_api_key` (open to any faction member, not just leadership) to submit their own Torn API key into the app's pool without needing app access at all. `/current_war` posts live status boards for the active ranked war - enemy roster, your own, and an enemy activity heatmap - and keeps editing them in place every few minutes. No port forwarding or router changes needed — see below.

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

Lets leadership run read-only commands from Discord — `/wars`, `/paysheet [war_id]`, `/stats [war_id]`, `/career`, `/armory`, `/current_war` — without needing to reach the app itself. It works entirely over an **outbound** connection to Discord (same as every Discord bot), so it needs no inbound port, no port forwarding, and no router changes at all. It talks to the app over plain `localhost`, since both run on your machine.

`/add_api_key key:<key> [label]` lets faction members add their own Torn API key to the app's pool directly - unlike every other command, it's **not** restricted to the leadership allowlist, since the point is to make it easy for anyone to contribute a key without needing app access or a leader to do it for them. It's gated instead by Torn itself: the bot looks up the key via Torn's own `/key/info` and rejects it unless it actually belongs to a member of this faction, so it can't be used to add a stranger's or a garbage key. It must be run in a **DM to the bot**, not a server channel - the command refuses to run anywhere else, since a slash command's parameters (the key itself) stay visible in the channel's history even though the bot's reply is private. Note: guild-scoped commands (the instant-sync path when a Server/Guild ID is set) never work in DMs, no matter what - so DM commands always need Discord's slower global sync, which can take up to an hour to propagate after the bot (re)starts. If `/add_api_key` doesn't show up in a DM right after starting the bot, that's normal - wait a bit and try again.

`/current_war` posts three separate messages for whichever ranked war is currently active - enemy roster, your own roster, and an enemy activity heatmap - each edited in place every `WAR_STATUS_REFRESH_MINUTES` (default 1 minute, `bot/discord_bot.py`) for as long as the war runs. Separate posts instead of one combined image so each table renders as large as Discord will show it, rather than being squeezed into a shared image. The enemy roster has level, estimated stats, status, last action, position, and wall/revivable flags; your own roster has live hits, respect gained, and respect lost *for this war* - computed directly from the attack log, since Torn's own rankedwarreport (used for the post-war paysheet) isn't available until the war ends, so treat these as an estimate rather than the official score. Anyone currently hospitalized also gets an "In Hospital" field with a live-counting-down release timer (Discord's own timestamp markup, so it stays accurate to the second between refreshes without the bot doing anything). The enemy board also estimates landing times: since it refreshes regularly, a member's takeoff is caught within one refresh interval, and estimated arrival is takeoff + travel duration for their destination - standard, or 70% of standard (marked "(PI)") if they own a Private Island, checked via a profile lookup at takeoff. Can't account for WLT/Business Class/the Airstrip faction perk, and anyone already traveling before their takeoff was observed (e.g. right after the bot starts) has no estimate at all rather than a wrong one, so treat it as an upper bound (see `bot/travel.py`). Every completed flight it actually observes (member, destination, PI status, real duration) is logged to the database via `/api/travel-observations` - once a destination+PI combination has 3+ logged flights, the bot automatically starts using that observed average instead of the hardcoded standard time, so estimates get more accurate the longer the bot runs. Pull the raw log yourself at `/api/travel-observations` (`?limit=`) or the aggregated averages at `/api/travel-observations/estimates`.

The activity heatmap shows each enemy member's percent chance of being Online, broken out by UTC hour (0-23) - built the same way as the travel log: every refresh, each member's current online/idle/offline status gets logged (`bot/activity.py`, `/api/activity-observations`) against the current hour, and the heatmap cell for a given member+hour is just observed-Online-count / observed-total-count at that hour. A cell needs 5+ logged polls at that hour before it shows a percentage instead of "-", so this fills in gradually - it only has data for hours the bot has actually been running and polling during a war, not a full 24-hour picture from day one.

All three boards stop updating on their own once the war ends; run `/current_war` again for the next one.

It also shows a war-decay countdown (both sides' time until the war's decaying target score falls to their current score), a catch-up rate if your faction is trailing (factoring in the enemy's own observed scoring pace), and how much more score your faction needs for max payout - ported from a faction leader's own Tampermonkey "War Decay Timer" script (see `bot/decay.py`). These are community-observed formulas, not documented by Torn, so treat them as estimates.

Estimated stats come from [ffscouter.com](https://ffscouter.com) (Torn's own API doesn't expose enemy battle stats - that needs a spy report). Register an API key there and add it under **Settings → FFScouter** to enable that column; without one, the board still works but shows "-" for it. Fair Fight itself isn't shown - it's computed relative to your own stats, so it isn't a meaningful number to broadcast to the whole team.

### Alerts (self-hosp and revives-off reminders)

The bot also proactively @mentions people in a configurable **Alert Channel** (Settings → Discord Bot → Alert Channel ID) when either of these happens, independent of whether `/current_war` has been run:

- **Self-hospitalize reminder** (`bot/self_hosp.py`) - once a war has started, if a member has been offline 30+ minutes *and* is in hospital with 5 minutes or less left on the clock, they're about to walk out exposed with no chance to protect their respect. Repeats up to 3 times for that same hospital stay, stopping early if they come back online.
- **Revives-off reminder** (`bot/revives.py`) - starting 5 hours before a declared war's start time (Torn lists a not-yet-started war the same way as an active one, so this can fire before the war begins) and repeating every 4 hours per member, anyone with revives enabled gets pinged to turn them off. Keeps firing on the same schedule after the war starts too - the wording just changes from "starts in..." to "has started" - until they actually turn revives off.

Both need each player's Torn ID linked to their Discord ID to @mention them by name - add it as the optional **Torn Player ID** field on the existing Allowed Discord Users list in Settings (separate from bot command access; someone can have one without the other). Anyone without a linked Torn ID still gets flagged, just by name instead of a mention.

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications) → **New Application** → give it a name → **Bot** tab → **Reset Token** to reveal it, copy it.
2. Under **OAuth2 → URL Generator**, check **both** `bot` and `applications.commands`, then open the generated URL to invite it to your server. If you only check `bot`, the bot joins fine but slash commands fail to register with a `403 Forbidden` error — if you hit that, re-generate the URL with both boxes checked and re-invite it (re-inviting with the extra scope is safe, it won't duplicate the bot).
3. In the app's **Settings** tab, paste the bot token under "Discord Bot" and save.
4. (Optional but recommended for testing) Add your Discord server's ID as the "Server (Guild) ID" — this makes new slash commands show up instantly instead of waiting up to an hour for Discord's global sync.
5. Add each faction member's Discord **User ID** (not username) under "Allowed Discord Users" — turn on Developer Mode in Discord (Settings → Advanced) to right-click someone and "Copy User ID". Only these accounts can use the bot's commands at all, and check **Leadership** for anyone who should have access to leadership-only commands (currently that's every command except `/add_api_key`, which is open to any Discord user - see below for what "leadership-only" gates).
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
