"""Discord bot for read-only access to the Torn Ranked War Boss app.

Runs as its own process alongside app.py. It never opens any inbound port -
Discord bots work entirely over an outbound connection to Discord's gateway,
same as any other Discord bot - and it talks to the app over plain localhost
HTTP, since both run on the same machine. Nothing here requires any change to
your router or firewall.

Configure the bot token, an optional guild ID (for instant slash-command sync
during setup - global sync can take up to an hour to propagate), and the list
of allowed Discord user IDs from the app's Settings tab, then run this file
directly (see start-bot.sh).
"""

import io
import random
import sys
import time
from pathlib import Path

import discord
import httpx
from discord import app_commands
from discord.ext import tasks

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import db  # noqa: E402
from bot import activity  # noqa: E402
from bot import decay  # noqa: E402
from bot import format as fmt  # noqa: E402
from bot import giveaways  # noqa: E402
from bot import revives  # noqa: E402
from bot import self_hosp  # noqa: E402
from bot import travel  # noqa: E402
from bot.render import render_tables  # noqa: E402

APP_BASE_URL = "http://localhost:8787"
WAR_STATUS_REFRESH_MINUTES = 1
GIVEAWAY_CHECK_SECONDS = 15

_score_history = decay.ScoreHistory()
_travel_tracker = travel.TravelTracker()
_self_hosp_tracker = self_hosp.SelfHospAlertTracker()
_revives_tracker = revives.RevivesReminderTracker()


class TornBossClient(discord.Client):
    """Slash-commands-only client - discord.ext.commands.Bot's prefix-command
    machinery (and its unrelated "message content intent" warning) isn't
    needed since every command here is a slash command via app_commands."""

    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)


bot = TornBossClient()


def money(n) -> str:
    n = round(n or 0)
    sign = "-" if n < 0 else ""
    return f"{sign}${abs(n):,}"


def is_allowed(user_id: int) -> bool:
    return str(user_id) in db.get_discord_allowed_user_ids()


def is_leadership(user_id: int) -> bool:
    return str(user_id) in db.get_discord_leadership_user_ids()


async def ensure_allowed(interaction: discord.Interaction) -> bool:
    """Base tier - anyone on the allowed-users list, leadership or not. Use
    this for commands meant to be open to the whole faction once any exist;
    right now every command actually uses ensure_leadership() instead."""
    if is_allowed(interaction.user.id):
        return True
    await interaction.response.send_message("You're not authorized to use this bot.", ephemeral=True)
    return False


async def ensure_leadership(interaction: discord.Interaction) -> bool:
    """Leadership tier - on the allowed-users list AND checked as leadership
    there. Everything except /add_api_key (intentionally open to anyone) uses
    this for now."""
    if is_leadership(interaction.user.id):
        return True
    if is_allowed(interaction.user.id):
        await interaction.response.send_message("This command is restricted to leadership.", ephemeral=True)
    else:
        await interaction.response.send_message("You're not authorized to use this bot.", ephemeral=True)
    return False


async def api_get(path: str) -> dict:
    async with httpx.AsyncClient(base_url=APP_BASE_URL, timeout=20) as client:
        resp = await client.get(path)
        resp.raise_for_status()
        return resp.json()


async def api_post(path: str, json: dict) -> dict:
    async with httpx.AsyncClient(base_url=APP_BASE_URL, timeout=20) as client:
        resp = await client.post(path, json=json)
        if resp.status_code >= 400:
            # Surface FastAPI's {"detail": "..."} instead of a generic status
            # code - the caller (e.g. /add_api_key) has an actual message to
            # show for "wrong faction"/"invalid key" instead of "400 Bad Request".
            try:
                detail = resp.json().get("detail", resp.text)
            except ValueError:
                detail = resp.text
            raise RuntimeError(detail)
        return resp.json()


async def api_delete(path: str) -> dict:
    async with httpx.AsyncClient(base_url=APP_BASE_URL, timeout=20) as client:
        resp = await client.delete(path)
        resp.raise_for_status()
        return resp.json()


async def most_recent_war_id() -> int | None:
    wars = await api_get("/api/wars")
    return wars[0]["id"] if wars else None


async def sync_travel_observations(war_id: int, members: list[dict]) -> dict:
    """Feeds this poll's roster into the travel tracker, ships off any
    completed flights it detected, and pulls back the current observed-average
    estimates for build_enemy_status_message to use in place of the hardcoded
    standard-time table wherever there's enough data."""
    completed = _travel_tracker.record(war_id, members)
    for obs in completed:
        try:
            await api_post("/api/travel-observations", obs)
        except Exception as e:
            print(f"Failed to log travel observation for {obs.get('member_name')}: {e}")
    try:
        return await api_get("/api/travel-observations/estimates")
    except Exception as e:
        print(f"Failed to fetch travel estimates: {e}")
        return {}


async def sync_activity_observations(members: list[dict]) -> dict:
    """Logs this poll's online/idle/offline snapshot for every enemy member
    and pulls back the current per-hour activity-percent estimates for
    build_activity_heatmap_message."""
    observations = activity.build_observations(members)
    try:
        await api_post("/api/activity-observations", {"observations": observations})
    except Exception as e:
        print(f"Failed to log activity observations: {e}")
    try:
        return await api_get("/api/activity-observations/estimates")
    except Exception as e:
        print(f"Failed to fetch activity estimates: {e}")
        return {}


async def _get_alert_channel() -> discord.abc.Messageable | None:
    channel_id = db.get_setting("discord_alert_channel_id")
    if not channel_id:
        return None
    try:
        return bot.get_channel(int(channel_id)) or await bot.fetch_channel(int(channel_id))
    except (discord.NotFound, discord.Forbidden) as e:
        print(f"Couldn't reach the configured alert channel: {e}")
        return None


def _mention_for(member_id: int, member_name: str, torn_id_to_discord: dict[int, str]) -> str:
    discord_id = torn_id_to_discord.get(member_id)
    return f"<@{discord_id}>" if discord_id else f"**{member_name}**"


async def check_self_hosp_alerts(own_members: list[dict]) -> None:
    due = _self_hosp_tracker.check(own_members)
    if not due:
        return
    channel = await _get_alert_channel()
    if channel is None:
        return

    torn_id_to_discord = db.get_torn_id_to_discord_id_map()
    for m in due:
        mention = _mention_for(m["id"], m["name"], torn_id_to_discord)
        await channel.send(
            f"{mention} you're released from hospital <t:{m['status']['until']}:R> and you've been offline "
            f"{self_hosp.OFFLINE_THRESHOLD_SECONDS // 60}+ minutes - self-hospitalize now to protect your "
            "respect before you walk out exposed!"
        )


async def check_revives_reminders(war: dict, own_members: list[dict]) -> None:
    now = time.time()
    due = _revives_tracker.check(war["id"], war["start"], own_members, now)
    if not due:
        return
    channel = await _get_alert_channel()
    if channel is None:
        return

    war_started = now >= war["start"]
    torn_id_to_discord = db.get_torn_id_to_discord_id_map()
    for m in due:
        mention = _mention_for(m["id"], m["name"], torn_id_to_discord)
        if war_started:
            status_line = f"The war against {war['opponent_name']} has started"
        else:
            status_line = f"The war against {war['opponent_name']} starts <t:{war['start']}:R>"
        await channel.send(
            f"{mention} {status_line} and you still have revives on (**{m.get('revive_setting', 'on')}**) - "
            "please turn them off."
        )


def table_block(rows: list[str], header: str | None = None) -> str:
    lines = ([header] if header else []) + rows
    text = "```\n" + "\n".join(lines) + "\n```"
    return text[:1024]


def image_file(png_bytes: bytes, filename: str) -> discord.File:
    """A bare file attachment (as opposed to one bound into the embed via
    set_image) renders at its own full width in Discord's timeline instead of
    being constrained to the embed card's width - confirmed larger in
    practice, despite set_image looking like the "proper" way to do this."""
    return discord.File(io.BytesIO(png_bytes), filename=filename)


def _decay_timestamp(seconds_remaining: float | None) -> str:
    """Discord's <t:...:R> markup ticks down live in every viewer's client -
    same trick as the hospital timers - so this needs no re-render to stay
    accurate between the board's refreshes."""
    if seconds_remaining is None:
        return "-"
    if seconds_remaining <= 0:
        return "Decayed out"
    return f"<t:{int(time.time() + seconds_remaining)}:R>"


def _add_decay_fields(embed: discord.Embed, war: dict) -> None:
    """War-decay countdown, catch-up rate, and max-payout threshold - ported
    from a faction leader's own Tampermonkey "War Decay Timer" script. See
    bot/decay.py for the (community-observed, not Torn-documented) formulas."""
    elapsed_hours = (time.time() - war["start"]) / 3600
    own_seconds = decay.compute_seconds_remaining(war["target"], war["own_score"], elapsed_hours)
    opp_seconds = decay.compute_seconds_remaining(war["target"], war["opponent_score"], elapsed_hours)
    original_target = decay.compute_original_target(war["target"], elapsed_hours)

    embed.add_field(
        name="War Decay Countdown",
        value=f"Us: {_decay_timestamp(own_seconds)}\nThem: {_decay_timestamp(opp_seconds)}",
    )

    _score_history.record(war["id"], war["own_score"], war["opponent_score"])
    own_leading = war["own_score"] >= war["opponent_score"]
    gap = abs(war["own_score"] - war["opponent_score"])
    leading_seconds = own_seconds if own_leading else opp_seconds
    leading_hours = leading_seconds / 3600 if leading_seconds else None

    if own_leading:
        catchup_text = "Tied." if gap == 0 else "We're ahead."
        payout_threshold = original_target
    else:
        enemy_rate = _score_history.observed_rate_per_hour("opp")
        if leading_hours:
            required_rate = max(0.0, gap / leading_hours + (enemy_rate or 0.0))
            rate_text = f"{required_rate:.1f} score/hr needed"
        else:
            rate_text = "-"
        enemy_rate_text = f"{enemy_rate:+.1f}/hr" if enemy_rate is not None else "gathering data (~15 min)"
        catchup_text = f"{rate_text}\n(their pace: {enemy_rate_text})"
        payout_threshold = original_target / 2

    embed.add_field(name="Catch-Up Rate" if not own_leading else "Status", value=catchup_text)

    payout_remaining = payout_threshold - war["own_score"]
    payout_text = (
        "Max payout reached" if payout_remaining <= 0 else f"{payout_remaining:,.0f} more score for max payout"
    )
    embed.add_field(name="Max Payout", value=payout_text)


def _auto_update_description() -> str:
    # Embed footers don't render Discord's timestamp markup (plain text only),
    # so the live "auto-updates in" countdown has to live in the description
    # instead - next_iteration is None only in the brief window before the
    # refresh loop's first tick, hence the static fallback.
    next_run = refresh_war_status.next_iteration
    if next_run:
        return f"Auto-updates <t:{int(next_run.timestamp())}:R>"
    return f"Auto-updates every {WAR_STATUS_REFRESH_MINUTES} min while this war is active"


def build_enemy_status_message(data: dict, travel_overrides: dict | None = None) -> tuple[discord.Embed, discord.File]:
    war = data["war"]
    members = sorted(data["members"], key=fmt.war_status_sort_key)

    embed = discord.Embed(title=f"Current War - vs {war['opponent_name']}", color=0x5DA9FF)
    embed.description = _auto_update_description()
    embed.add_field(name="Score", value=f"{war['own_score']} - {war['opponent_score']} (target {war['target']})")
    okay_count = sum(1 for m in members if m["status"]["state"] == "Okay")
    embed.add_field(name="Attackable Now", value=f"{okay_count} / {len(members)}")

    _add_decay_fields(embed, war)

    # Discord's own <t:...:R> timestamp markup counts down live in every
    # viewer's client - unlike the table image, this needs no re-render to stay
    # accurate, so hospital releases show up here instead of only in the image.
    hospitalized = sorted((m for m in members if m["status"].get("until")), key=lambda m: m["status"]["until"])
    if hospitalized:
        # Torn's profile page shows its own live, second-precision countdown
        # for the same release time - linking the name gets you that directly,
        # since Discord's own timestamp markup only ever goes to the minute.
        lines = [
            f"[{m['name']}](https://www.torn.com/profiles.php?XID={m['id']}) - <t:{m['status']['until']}:R>"
            for m in hospitalized[:20]
        ]
        if len(hospitalized) > 20:
            lines.append(f"+{len(hospitalized) - 20} more")
        embed.add_field(name="In Hospital", value="\n".join(lines), inline=False)

    # Torn's API doesn't give an exact arrival time, but this board refreshes
    # regularly - so a member's takeoff (first observed "Traveling") is known
    # accurate to within one refresh interval, and estimated arrival = takeoff +
    # a travel duration for their destination (standard, 70% of standard for a
    # Private Island owner, or an observed average once sync_travel_observations
    # has logged enough real flights - see bot/travel.py for the remaining,
    # unavoidable assumptions this makes).
    landings = []
    for m in members:
        arrival = _travel_tracker.estimated_arrival(m["id"], travel_overrides)
        if arrival:
            landings.append((m, arrival))
    if landings:
        landings.sort(key=lambda pair: pair[1])
        lines = [
            f"[{m['name']}](https://www.torn.com/profiles.php?XID={m['id']})"
            f"{' (PI)' if _travel_tracker.has_private_island(m['id']) else ''} - <t:{arrival}:R>"
            for m, arrival in landings[:20]
        ]
        if len(landings) > 20:
            lines.append(f"+{len(landings) - 20} more")
        embed.add_field(name="Est. Landing", value="\n".join(lines), inline=False)

    embed.set_footer(text="Decay/payout numbers are community-observed estimates, not official Torn data.")

    rows = [fmt.war_status_row(m) for m in members]
    png = render_tables(f"Enemy Roster - {war['opponent_name']}", [{"heading": None, "headers": fmt.WAR_STATUS_HEADERS, "rows": rows}])
    return embed, image_file(png, "enemy_roster.png")


def build_own_status_message(data: dict) -> tuple[discord.Embed, discord.File]:
    war = data["war"]
    embed = discord.Embed(title="Our Roster", color=0x5DA9FF)
    embed.description = _auto_update_description()
    embed.add_field(name="Score", value=f"{war['own_score']} - {war['opponent_score']} (target {war['target']})")
    embed.set_footer(text="Hits/respect are computed live from the attack log - treat them as an estimate.")

    own_members = sorted(data.get("own_members", []), key=fmt.own_war_sort_key)
    rows = [fmt.own_war_row(m) for m in own_members]
    png = render_tables("Our Roster", [{"heading": None, "headers": fmt.OWN_WAR_HEADERS, "rows": rows}])
    return embed, image_file(png, "own_roster.png")


def build_activity_heatmap_message(data: dict, activity_estimates: dict) -> tuple[discord.Embed, discord.File]:
    war = data["war"]
    members = sorted(data["members"], key=lambda m: m["name"].lower())

    embed = discord.Embed(title=f"Activity Heatmap - vs {war['opponent_name']}", color=0x5DA9FF)
    embed.description = _auto_update_description()
    embed.set_footer(
        text=f"Percent of observed 5-min polls each member was Online, by UTC hour - needs "
        f"{activity.MIN_OBSERVED_SAMPLES}+ polls at that hour to show, so this fills in the longer the bot runs."
    )

    rows = [fmt.activity_heatmap_row(m["id"], m["name"], activity_estimates) for m in members]
    png = render_tables(
        f"Activity Heatmap - {war['opponent_name']}",
        [{"heading": None, "headers": fmt.ACTIVITY_HEATMAP_HEADERS, "rows": rows}],
    )
    return embed, image_file(png, "activity_heatmap.png")


def build_giveaway_embed(giveaway: dict, entry_count: int) -> discord.Embed:
    embed = discord.Embed(title="🎉 Giveaway!", description=f"**{giveaway['item']}**", color=0x5DA9FF)
    embed.add_field(name="Winners", value=str(giveaway["num_winners"]))
    embed.add_field(name="Entries", value=str(entry_count))
    embed.add_field(name="Ends", value=f"<t:{giveaway['ends_at']}:R>", inline=False)
    embed.set_footer(text="Click below to enter - one entry per person.")
    return embed


class GiveawayView(discord.ui.View):
    """timeout=None + a fixed custom_id makes this a persistent view - the
    button keeps working across bot restarts as long as on_ready
    re-registers one of these per still-active giveaway (see below)."""

    def __init__(self, giveaway_id: int):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        button = discord.ui.Button(
            label="🎉 Enter", style=discord.ButtonStyle.primary, custom_id=f"giveaway_enter:{giveaway_id}"
        )
        button.callback = self._on_enter
        self.add_item(button)

    async def _on_enter(self, interaction: discord.Interaction) -> None:
        try:
            result = await api_post(f"/api/giveaways/{self.giveaway_id}/enter", {"discord_user_id": str(interaction.user.id)})
        except Exception as e:
            await interaction.response.send_message(f"Couldn't enter: {e}", ephemeral=True)
            return

        if not result["entered"]:
            await interaction.response.send_message("You've already entered this giveaway.", ephemeral=True)
            return
        await interaction.response.send_message("You're entered! Good luck.", ephemeral=True)

        try:
            giveaway = await api_get(f"/api/giveaways/{self.giveaway_id}")
        except Exception:
            return
        if giveaway["status"] != "active" or interaction.message is None:
            return
        try:
            await interaction.message.edit(embed=build_giveaway_embed(giveaway, result["entry_count"]), view=self)
        except discord.HTTPException:
            pass


async def _finalize_giveaway(giveaway: dict) -> None:
    giveaway_id = giveaway["id"]
    try:
        entrants = await api_get(f"/api/giveaways/{giveaway_id}/entries")
    except Exception as e:
        print(f"Failed to fetch entries for giveaway {giveaway_id}: {e}")
        return

    num_winners = min(giveaway["num_winners"], len(entrants))
    winners = random.sample(entrants, num_winners) if num_winners else []

    try:
        await api_post(f"/api/giveaways/{giveaway_id}/finalize", {"winner_discord_user_ids": winners})
    except Exception as e:
        print(f"Failed to finalize giveaway {giveaway_id}: {e}")
        return

    try:
        channel = bot.get_channel(int(giveaway["channel_id"])) or await bot.fetch_channel(int(giveaway["channel_id"]))
    except (discord.NotFound, discord.Forbidden) as e:
        print(f"Couldn't reach channel for giveaway {giveaway_id}: {e}")
        return

    if giveaway.get("message_id"):
        try:
            message = await channel.fetch_message(int(giveaway["message_id"]))
            ended_embed = build_giveaway_embed(giveaway, len(entrants))
            ended_embed.title = "🎉 Giveaway Ended"
            ended_embed.color = 0x888888
            await message.edit(embed=ended_embed, view=None)
        except (discord.NotFound, discord.Forbidden):
            pass

    if winners:
        mentions = " ".join(f"<@{uid}>" for uid in winners)
        await channel.send(f"🎉 Congratulations {mentions} - you won **{giveaway['item']}**!")
    else:
        await channel.send(f"🎉 The giveaway for **{giveaway['item']}** ended, but no one entered.")


@bot.event
async def on_ready():
    # Guild-scoped commands ONLY work inside that one server - Discord never
    # makes them available in DMs, no matter what. /add_api_key needs to run
    # in a DM, so a global sync is required regardless of guild_id; the guild
    # sync (when configured) is purely a speed-up for the *rest* of the
    # commands to show up instantly in that server instead of waiting up to
    # an hour, and is skipped entirely if it fails rather than treated as a
    # fallback-worthy error, since the global sync below still covers everyone.
    guild_id = db.get_setting("discord_guild_id")
    synced_where = "globally (can take up to an hour to show up)"
    if guild_id:
        guild = discord.Object(id=int(guild_id))
        bot.tree.copy_global_to(guild=guild)
        try:
            await bot.tree.sync(guild=guild)
            synced_where = f"to guild {guild_id} (instant) and globally (can take up to an hour, needed for DM commands like /add_api_key)"
        except discord.Forbidden:
            # Almost always means the bot was invited without the
            # applications.commands OAuth2 scope, or the guild ID doesn't
            # match a server the bot is actually in - re-invite it with both
            # `bot` and `applications.commands` checked in the URL Generator.
            print(
                f"Could not sync commands to guild {guild_id} (403 Forbidden). "
                "Falling back to a global-only sync. This usually means the bot was invited "
                "without the 'applications.commands' scope, or the guild ID is wrong - "
                "see the README's Discord bot setup steps."
            )
    await bot.tree.sync()
    print(f"Logged in as {bot.user} - commands synced {synced_where}")
    if not refresh_war_status.is_running():
        refresh_war_status.start()
    if not check_giveaways.is_running():
        check_giveaways.start()

    try:
        active_giveaways = await api_get("/api/giveaways/active")
        for g in active_giveaways:
            bot.add_view(GiveawayView(g["id"]))
        if active_giveaways:
            print(f"Re-registered {len(active_giveaways)} active giveaway button(s).")
    except Exception as e:
        print(f"Failed to re-register active giveaway views: {e}")


@bot.tree.command(name="add_api_key", description="Add your Torn API key to the app's key pool (DM me this - never use it in a server channel)")
@app_commands.describe(key="Your Torn API key (Limited access or higher)", label="Optional label - defaults to your player name")
async def add_api_key_command(interaction: discord.Interaction, key: str, label: str | None = None):
    # Deliberately NOT gated by ensure_allowed - the point is to let any
    # faction member submit their own key without needing to be on the
    # leadership allowlist. Torn's own key/info lookup (in the backend) is
    # the actual gate: only keys belonging to a real member of this faction
    # get accepted.
    if interaction.guild is not None:
        await interaction.response.send_message(
            "Please send me this command in a DM instead - anyone in this channel could see your key otherwise "
            "(the invocation itself stays visible even though my reply is private).",
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        result = await api_post("/api/settings/api-keys/validated", {"api_key": key.strip(), "label": label})
    except RuntimeError as e:
        await interaction.followup.send(f"Couldn't add that key: {e}", ephemeral=True)
        return
    except Exception as e:
        await interaction.followup.send(f"Couldn't reach the app: {e}", ephemeral=True)
        return

    name = result.get("player_name") or "unknown player"
    await interaction.followup.send(
        f"Added - this key belongs to **{name}** ({result['access_type']} access). Thanks!",
        ephemeral=True,
    )


@bot.tree.command(name="wars", description="List synced ranked wars")
async def wars_command(interaction: discord.Interaction):
    if not await ensure_leadership(interaction):
        return
    await interaction.response.defer()
    try:
        wars = await api_get("/api/wars")
    except Exception as e:
        await interaction.followup.send(f"Couldn't reach the app: {e}")
        return
    if not wars:
        await interaction.followup.send("No wars synced yet.")
        return
    rows = [f"{w['id']:<10} vs {w['opponent_name'] or '?'}" for w in wars[:15]]
    await interaction.followup.send(table_block(rows, header=f"{'War ID':<10} Opponent"))


@bot.tree.command(name="current_war", description="Post live-updating status boards for the current ranked war")
async def current_war_command(interaction: discord.Interaction):
    if not await ensure_leadership(interaction):
        return
    if interaction.channel is None:
        await interaction.response.send_message("This command needs to be run in a channel.", ephemeral=True)
        return
    await interaction.response.defer()
    try:
        data = await api_get("/api/wars/current")
    except Exception as e:
        await interaction.followup.send(f"Couldn't reach the app: {e}")
        return
    if data["war"] is None:
        await interaction.followup.send("No active ranked war right now.")
        return

    travel_overrides = await sync_travel_observations(data["war"]["id"], data["members"])
    activity_estimates = await sync_activity_observations(data["members"])

    # Separate posts, not one combined image - each renders as large as
    # Discord will show it, instead of being squeezed into a shared image.
    enemy_embed, enemy_file = build_enemy_status_message(data, travel_overrides)
    enemy_message = await interaction.channel.send(embed=enemy_embed, file=enemy_file)
    own_embed, own_file = build_own_status_message(data)
    own_message = await interaction.channel.send(embed=own_embed, file=own_file)
    activity_embed, activity_file = build_activity_heatmap_message(data, activity_estimates)
    activity_message = await interaction.channel.send(embed=activity_embed, file=activity_file)

    await api_post(
        "/api/settings/discord-war-status",
        {
            "war_id": data["war"]["id"],
            "channel_id": str(enemy_message.channel.id),
            "enemy_message_id": str(enemy_message.id),
            "own_message_id": str(own_message.id),
            "activity_message_id": str(activity_message.id),
        },
    )
    await interaction.followup.send(
        f"Posted - I'll refresh all three every {WAR_STATUS_REFRESH_MINUTES} minutes while this war is active.",
        ephemeral=True,
    )


@bot.tree.command(name="paysheet", description="Show the paysheet for a war (defaults to most recent)")
@app_commands.describe(war_id="War ID from /wars - leave blank for the most recent")
async def paysheet_command(interaction: discord.Interaction, war_id: int | None = None):
    if not await ensure_leadership(interaction):
        return
    await interaction.response.defer()
    try:
        if war_id is None:
            war_id = await most_recent_war_id()
            if war_id is None:
                await interaction.followup.send("No wars synced yet.")
                return
        data = await api_get(f"/api/wars/{war_id}")
    except Exception as e:
        await interaction.followup.send(f"Couldn't reach the app: {e}")
        return

    war = data["war"]
    totals = data["totals"]
    members = sorted(data["members"], key=lambda m: m["final_pay"], reverse=True)

    embed = discord.Embed(title=f"Paysheet - vs {war['opponent_name'] or '?'} (war {war_id})", color=0x5DA9FF)
    embed.add_field(name="War Pay", value=money(totals["war_pay"]))
    embed.add_field(name="Pay For Hits", value=money(totals["pay_for_hits"]))
    embed.add_field(name="Total Expenses", value=money(totals["total_expenses"]))

    rows = [fmt.paysheet_row(m) for m in members] + [fmt.paysheet_totals_row(members)]
    png = render_tables(embed.title, [{"heading": None, "headers": fmt.PAYSHEET_HEADERS, "rows": rows}])
    await interaction.followup.send(embed=embed, file=image_file(png, "paysheet.png"))


@bot.tree.command(name="stats", description="Show player stats for a war (defaults to most recent)")
@app_commands.describe(war_id="War ID from /wars - leave blank for the most recent")
async def stats_command(interaction: discord.Interaction, war_id: int | None = None):
    if not await ensure_leadership(interaction):
        return
    await interaction.response.defer()
    try:
        if war_id is None:
            war_id = await most_recent_war_id()
            if war_id is None:
                await interaction.followup.send("No wars synced yet.")
                return
        data = await api_get(f"/api/wars/{war_id}/stats")
    except Exception as e:
        await interaction.followup.send(f"Couldn't reach the app: {e}")
        return

    embed = discord.Embed(title=f"Player Stats - war {war_id}", color=0x5DA9FF)
    sections = []
    for section_name, key in (("Leadership", "leadership"), ("Everyone Else", "others")):
        members = sorted(data[key], key=lambda m: m["overall_rank"])
        if not members:
            continue
        sections.append({
            "heading": section_name,
            "headers": fmt.STAT_HEADERS,
            "rows": [fmt.stats_row(m) for m in members],
        })
    if not sections:
        await interaction.followup.send("No stats for this war.")
        return
    png = render_tables(embed.title, sections)
    await interaction.followup.send(embed=embed, file=image_file(png, "stats.png"))


@bot.tree.command(name="career", description="Show the career stats leaderboard (all synced wars)")
async def career_command(interaction: discord.Interaction):
    if not await ensure_leadership(interaction):
        return
    await interaction.response.defer()
    try:
        members = await api_get("/api/stats/career")
    except Exception as e:
        await interaction.followup.send(f"Couldn't reach the app: {e}")
        return

    members = sorted(members, key=lambda m: m["overall_rank"])
    if not members:
        await interaction.followup.send("No stats yet - sync a war first.")
        return
    embed = discord.Embed(title="Career Leaderboard", color=0x5DA9FF)
    rows = [fmt.career_row(m) for m in members]
    png = render_tables(embed.title, [{"heading": None, "headers": fmt.CAREER_HEADERS, "rows": rows}])
    await interaction.followup.send(embed=embed, file=image_file(png, "career.png"))


@bot.tree.command(name="armory", description="Show the armory restock summary")
async def armory_command(interaction: discord.Interaction):
    if not await ensure_leadership(interaction):
        return
    await interaction.response.defer()
    try:
        restock = await api_get("/api/armory/restock")
    except Exception as e:
        await interaction.followup.send(f"Couldn't reach the app: {e}")
        return

    needed = sorted((l for l in restock["lines"] if l["needed"] > 0), key=lambda l: l["cost"], reverse=True)
    embed = discord.Embed(title="Armory Restock", color=0x5DA9FF)
    embed.add_field(name="Total Cost", value=money(restock["total_cost"]), inline=False)
    if not needed:
        embed.add_field(name="Items Needing Restock", value="Fully stocked.", inline=False)
        await interaction.followup.send(embed=embed)
        return
    rows = [fmt.armory_row(l) for l in needed] + [fmt.armory_totals_row(needed)]
    png = render_tables(embed.title, [{"heading": None, "headers": fmt.ARMORY_HEADERS, "rows": rows}])
    await interaction.followup.send(embed=embed, file=image_file(png, "armory.png"))


@bot.tree.command(name="new_giveaway", description="Start a giveaway - anyone can enter with a button, winner(s) chosen at random when it ends")
@app_commands.describe(
    duration="How long it runs, e.g. 1h30m, 2d, 45s",
    winners="Number of winners",
    item="What's being given away",
)
async def new_giveaway_command(interaction: discord.Interaction, duration: str, winners: int, item: str):
    # Base tier, not leadership - open to everyone on the allowed list.
    if not await ensure_allowed(interaction):
        return
    if interaction.channel is None:
        await interaction.response.send_message("This command needs to be run in a channel.", ephemeral=True)
        return

    seconds = giveaways.parse_duration(duration)
    if seconds is None:
        await interaction.response.send_message(
            f"Couldn't parse `{duration}` as a duration - try something like `1h30m`, `2d`, or `45s` "
            f"(between {giveaways.MIN_SECONDS}s and {giveaways.MAX_SECONDS // 86400}d).",
            ephemeral=True,
        )
        return
    if winners < 1:
        await interaction.response.send_message("Need at least 1 winner.", ephemeral=True)
        return
    if not item.strip():
        await interaction.response.send_message("Need to say what's being given away.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    ends_at = int(time.time()) + seconds
    try:
        giveaway = await api_post(
            "/api/giveaways",
            {
                "channel_id": str(interaction.channel.id),
                "item": item.strip(),
                "num_winners": winners,
                "ends_at": ends_at,
                "created_by": str(interaction.user.id),
            },
        )
    except Exception as e:
        await interaction.followup.send(f"Couldn't reach the app: {e}", ephemeral=True)
        return

    # Posted as a normal channel message, not the interaction's own followup -
    # a giveaway can run for days, well past a webhook token's 15-minute
    # lifetime, and the ending task needs to be able to fetch and edit it later.
    view = GiveawayView(giveaway["id"])
    bot.add_view(view)
    message = await interaction.channel.send(embed=build_giveaway_embed(giveaway, 0), view=view)
    await api_post(f"/api/giveaways/{giveaway['id']}/message", {"message_id": str(message.id)})

    await interaction.followup.send(f"Giveaway started - ends <t:{ends_at}:R>.", ephemeral=True)


@tasks.loop(seconds=GIVEAWAY_CHECK_SECONDS)
async def check_giveaways():
    try:
        active = await api_get("/api/giveaways/active")
    except Exception as e:
        print(f"Failed to fetch active giveaways: {e}")
        return
    now = time.time()
    for g in active:
        if g["ends_at"] <= now:
            await _finalize_giveaway(g)


@check_giveaways.before_loop
async def before_check_giveaways():
    await bot.wait_until_ready()


@tasks.loop(minutes=WAR_STATUS_REFRESH_MINUTES)
async def refresh_war_status():
    try:
        data = await api_get("/api/wars/current")
    except Exception as e:
        print(f"current_war refresh: couldn't reach the app: {e}")
        return

    # Self-hosp and revives reminders run off this same poll whether or not
    # anyone has posted the /current_war boards - revives in particular needs
    # to start nagging people up to 5 hours before the war even begins, well
    # before leadership would think to run that command.
    war = data["war"]
    if war is not None:
        if time.time() >= war["start"]:
            await check_self_hosp_alerts(data["own_members"])
        await check_revives_reminders(war, data["own_members"])

    ref = await api_get("/api/settings/discord-war-status")
    if not ref.get("enemy_message_id") or not ref.get("own_message_id") or not ref.get("activity_message_id"):
        return

    channel_id = int(ref["channel_id"])
    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        enemy_message = await channel.fetch_message(int(ref["enemy_message_id"]))
        own_message = await channel.fetch_message(int(ref["own_message_id"]))
        activity_message = await channel.fetch_message(int(ref["activity_message_id"]))
    except (discord.NotFound, discord.Forbidden):
        # A message or the channel is gone - stop chasing it until /current_war
        # is run again, rather than editing just whichever ones still exist.
        await api_delete("/api/settings/discord-war-status")
        return

    if war is None or war["id"] != ref["war_id"]:
        ended_note = "*This war has ended - this board is no longer being updated.*"
        await enemy_message.edit(content=ended_note)
        await own_message.edit(content=ended_note)
        await activity_message.edit(content=ended_note)
        await api_delete("/api/settings/discord-war-status")
        return

    travel_overrides = await sync_travel_observations(war["id"], data["members"])
    activity_estimates = await sync_activity_observations(data["members"])

    enemy_embed, enemy_file = build_enemy_status_message(data, travel_overrides)
    await enemy_message.edit(embed=enemy_embed, attachments=[enemy_file])
    own_embed, own_file = build_own_status_message(data)
    await own_message.edit(embed=own_embed, attachments=[own_file])
    activity_embed, activity_file = build_activity_heatmap_message(data, activity_estimates)
    await activity_message.edit(embed=activity_embed, attachments=[activity_file])


@refresh_war_status.before_loop
async def before_refresh_war_status():
    await bot.wait_until_ready()


def main():
    token = db.get_discord_bot_token()
    if not token:
        print("No Discord bot token configured. Add one in the app's Settings tab first.")
        raise SystemExit(1)
    bot.run(token)


if __name__ == "__main__":
    main()
