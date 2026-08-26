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

import sys
from pathlib import Path

import discord
import httpx
from discord import app_commands
from discord.ext import commands

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import db  # noqa: E402

APP_BASE_URL = "http://localhost:8787"
MAX_TABLE_ROWS = 20

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


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


async def most_recent_war_id() -> int | None:
    wars = await api_get("/api/wars")
    return wars[0]["id"] if wars else None


def table_block(rows: list[str], header: str | None = None) -> str:
    lines = ([header] if header else []) + rows
    text = "```\n" + "\n".join(lines) + "\n```"
    return text[:1024]


@bot.event
async def on_ready():
    guild_id = db.get_setting("discord_guild_id")
    if guild_id:
        guild = discord.Object(id=int(guild_id))
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    else:
        await bot.tree.sync()
    print(f"Logged in as {bot.user} - commands synced" + (f" to guild {guild_id}" if guild_id else " globally"))


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

    rows = [f"{('paid' if m['paid'] else '-'):<5}{m['name']:<15}{money(m['final_pay'])}" for m in members[:MAX_TABLE_ROWS]]
    embed.add_field(name=f"Final Pay (top {min(len(members), MAX_TABLE_ROWS)})", value=table_block(rows), inline=False)
    if len(members) > MAX_TABLE_ROWS:
        embed.set_footer(text=f"+{len(members) - MAX_TABLE_ROWS} more not shown - see the app for the full list")
    await interaction.followup.send(embed=embed)


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
    for section_name, key in (("Leadership", "leadership"), ("Everyone Else", "others")):
        members = sorted(data[key], key=lambda m: m["overall_rank"])[:MAX_TABLE_ROWS]
        if not members:
            continue
        rows = [f"#{m['overall_rank']:<4}{m['name']:<15}{int(m['total_hits'])} hits" for m in members]
        embed.add_field(name=section_name, value=table_block(rows), inline=False)
    await interaction.followup.send(embed=embed)


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

    members = sorted(members, key=lambda m: m["overall_rank"])[:MAX_TABLE_ROWS]
    if not members:
        await interaction.followup.send("No stats yet - sync a war first.")
        return
    rows = [f"#{m['overall_rank']:<4}{m['name']:<15}{m['wars_played']}w {m['avg_hits']:.1f} avg hits" for m in members]
    embed = discord.Embed(title="Career Leaderboard", color=0x5DA9FF)
    embed.add_field(name="Overall Rank", value=table_block(rows), inline=False)
    await interaction.followup.send(embed=embed)


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
    if needed:
        rows = [f"{l['item_name']:<20}{l['needed']:>6} x {money(l['unit_price'])}" for l in needed[:MAX_TABLE_ROWS]]
        embed.add_field(name="Items Needing Restock", value=table_block(rows), inline=False)
    else:
        embed.add_field(name="Items Needing Restock", value="Fully stocked.", inline=False)
    await interaction.followup.send(embed=embed)


def main():
    token = db.get_discord_bot_token()
    if not token:
        print("No Discord bot token configured. Add one in the app's Settings tab first.")
        raise SystemExit(1)
    bot.run(token)


if __name__ == "__main__":
    main()
