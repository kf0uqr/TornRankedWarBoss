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
import sys
from pathlib import Path

import discord
import httpx
from discord import app_commands
from discord.ext import tasks

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import db  # noqa: E402
from bot import format as fmt  # noqa: E402
from bot.render import render_tables  # noqa: E402

APP_BASE_URL = "http://localhost:8787"
WAR_STATUS_REFRESH_MINUTES = 5


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


async def ensure_allowed(interaction: discord.Interaction) -> bool:
    if is_allowed(interaction.user.id):
        return True
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
        resp.raise_for_status()
        return resp.json()


async def api_delete(path: str) -> dict:
    async with httpx.AsyncClient(base_url=APP_BASE_URL, timeout=20) as client:
        resp = await client.delete(path)
        resp.raise_for_status()
        return resp.json()


async def most_recent_war_id() -> int | None:
    wars = await api_get("/api/wars")
    return wars[0]["id"] if wars else None


def table_block(rows: list[str], header: str | None = None) -> str:
    lines = ([header] if header else []) + rows
    text = "```\n" + "\n".join(lines) + "\n```"
    return text[:1024]


def image_file(png_bytes: bytes, filename: str) -> discord.File:
    return discord.File(io.BytesIO(png_bytes), filename=filename)


def build_war_status_message(data: dict) -> tuple[discord.Embed, discord.File]:
    war = data["war"]
    members = sorted(data["members"], key=fmt.war_status_sort_key)

    embed = discord.Embed(title=f"Current War - vs {war['opponent_name']}", color=0x5DA9FF)
    embed.add_field(name="Score", value=f"{war['own_score']} - {war['opponent_score']} (target {war['target']})")
    okay_count = sum(1 for m in members if m["status"]["state"] == "Okay")
    embed.add_field(name="Attackable Now", value=f"{okay_count} / {len(members)}")

    # Discord's own <t:...:R> timestamp markup counts down live in every
    # viewer's client - unlike the table image, this needs no re-render to stay
    # accurate, so hospital releases show up here instead of only in the image.
    hospitalized = sorted((m for m in members if m["status"].get("until")), key=lambda m: m["status"]["until"])
    if hospitalized:
        lines = [f"{m['name']} - <t:{m['status']['until']}:R>" for m in hospitalized[:20]]
        if len(hospitalized) > 20:
            lines.append(f"+{len(hospitalized) - 20} more")
        embed.add_field(name="In Hospital", value="\n".join(lines), inline=False)

    embed.set_footer(text=f"Auto-updates every {WAR_STATUS_REFRESH_MINUTES} min while this war is active")

    rows = [fmt.war_status_row(m) for m in members]
    png = render_tables(f"Enemy Roster - {war['opponent_name']}", [{"heading": None, "headers": fmt.WAR_STATUS_HEADERS, "rows": rows}])
    return embed, image_file(png, "war_status.png")


@bot.event
async def on_ready():
    guild_id = db.get_setting("discord_guild_id")
    synced_where = "globally (can take up to an hour to show up)"
    if guild_id:
        guild = discord.Object(id=int(guild_id))
        bot.tree.copy_global_to(guild=guild)
        try:
            await bot.tree.sync(guild=guild)
            synced_where = f"to guild {guild_id}"
        except discord.Forbidden:
            # Almost always means the bot was invited without the
            # applications.commands OAuth2 scope, or the guild ID doesn't
            # match a server the bot is actually in - re-invite it with both
            # `bot` and `applications.commands` checked in the URL Generator.
            print(
                f"Could not sync commands to guild {guild_id} (403 Forbidden). "
                "Falling back to a global sync. This usually means the bot was invited "
                "without the 'applications.commands' scope, or the guild ID is wrong - "
                "see the README's Discord bot setup steps."
            )
            await bot.tree.sync()
    else:
        await bot.tree.sync()
    print(f"Logged in as {bot.user} - commands synced {synced_where}")
    if not refresh_war_status.is_running():
        refresh_war_status.start()


@bot.tree.command(name="wars", description="List synced ranked wars")
async def wars_command(interaction: discord.Interaction):
    if not await ensure_allowed(interaction):
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


@bot.tree.command(name="current_war", description="Post a live-updating status board for the current ranked war's enemy roster")
async def current_war_command(interaction: discord.Interaction):
    if not await ensure_allowed(interaction):
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

    embed, file = build_war_status_message(data)
    message = await interaction.channel.send(embed=embed, file=file)
    await api_post(
        "/api/settings/discord-war-status",
        {"war_id": data["war"]["id"], "channel_id": str(message.channel.id), "message_id": str(message.id)},
    )
    await interaction.followup.send(
        f"Posted - I'll refresh it every {WAR_STATUS_REFRESH_MINUTES} minutes while this war is active.",
        ephemeral=True,
    )


@bot.tree.command(name="paysheet", description="Show the paysheet for a war (defaults to most recent)")
@app_commands.describe(war_id="War ID from /wars - leave blank for the most recent")
async def paysheet_command(interaction: discord.Interaction, war_id: int | None = None):
    if not await ensure_allowed(interaction):
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
    if not await ensure_allowed(interaction):
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
    if not await ensure_allowed(interaction):
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
    if not await ensure_allowed(interaction):
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


@tasks.loop(minutes=WAR_STATUS_REFRESH_MINUTES)
async def refresh_war_status():
    ref = await api_get("/api/settings/discord-war-status")
    if not ref.get("message_id"):
        return

    channel_id = int(ref["channel_id"])
    message_id = int(ref["message_id"])
    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        message = await channel.fetch_message(message_id)
    except (discord.NotFound, discord.Forbidden):
        # Message or channel is gone - stop chasing it until /current_war is run again.
        await api_delete("/api/settings/discord-war-status")
        return

    try:
        data = await api_get("/api/wars/current")
    except Exception as e:
        print(f"current_war refresh: couldn't reach the app: {e}")
        return

    war = data["war"]
    if war is None or war["id"] != ref["war_id"]:
        await message.edit(content="*This war has ended - the status board is no longer being updated.*")
        await api_delete("/api/settings/discord-war-status")
        return

    embed, file = build_war_status_message(data)
    await message.edit(embed=embed, attachments=[file])


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
