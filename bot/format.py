"""Table cell formatting for the Discord bot's images - mirrors
frontend/app.js's paysheetRowCells/statsRowCells etc. Kept in sync by hand,
same caveat as bot/render.py.
"""

import time

from bot.render import COLORS

PAYSHEET_HEADERS = [
    "Name", "Inside", "Outside", "Assists", "Xanax Used", "Rank",
    "Fine", "Paid Back", "Gross Pay", "Bonus", "Final Pay", "Paid",
]

STAT_HEADERS = [
    "Name", "Total Hits", "Respect Gained", "Respect Lost", "Best Hit",
    "Avg Respect/Hit", "Win Rate", "Retaliation Hits", "Bonus Hits", "Score", "Overall Rank",
]

CAREER_HEADERS = [
    "Name", "Position", "Wars Played", "Avg Hits", "Avg Respect Gained", "Avg Respect Lost",
    "Avg Best Hit", "Avg Respect/Hit", "Win Rate", "Avg Retaliation Hits", "Avg Bonus Hits",
    "Score", "Overall Rank",
]

ARMORY_HEADERS = ["Item", "Target Qty", "On Hand", "Needed", "Unit Price", "Cost"]

# Torn's own /faction/{id}/rankedwarreport doesn't expose battle stats for an
# enemy faction (that needs a spy report), so a real Fair Fight score isn't
# obtainable here - level/status/last-action are the closest useful proxy the
# public API gives us for "is this person worth hitting right now".
WAR_STATUS_HEADERS = ["Name", "Level", "Status", "Last Action", "Position", "On Wall", "Revivable"]

STATUS_COLOR_MAP = {
    "green": COLORS["good"],
    "red": COLORS["bad"],
    "yellow": COLORS["warn"],
    "blue": COLORS["accent"],
}


def _format_duration(seconds: int) -> str:
    seconds = max(seconds, 0)
    hours, rem = divmod(seconds, 3600)
    minutes, _ = divmod(rem, 60)
    return f"{hours}h{minutes}m" if hours else f"{minutes}m"


def money(n) -> str:
    n = round(n or 0)
    sign = "-" if n < 0 else ""
    return f"{sign}${abs(n):,}"


def num(n, digits: int = 0) -> str:
    n = n or 0
    return f"{n:,.{digits}f}" if digits else f"{round(n):,}"


def money_cell(n):
    n = n or 0
    return {"text": money(n), "color": COLORS["bad"] if n < 0 else COLORS["text"]}


def paysheet_row(m) -> list:
    bonus = m["flat_bonus"] + m["leadership_cut_share"]
    return [
        m["name"], num(m["inside_hits"]), num(m["outside_hits"]), num(m["assist_hits"]), num(m["xanax_used"]),
        m["pay_rank"] or "-", money(m["calculated_fine"]), "Yes" if m["fine_waived"] else "No",
        money(m["gross_pay"]), money(bonus), money_cell(m["final_pay"]), "Yes" if m["paid"] else "No",
    ]


def paysheet_totals_row(members: list) -> list:
    total_final = sum(m["final_pay"] for m in members)
    return [
        {"text": "Total", "color": COLORS["text"]},
        num(sum(m["inside_hits"] for m in members)),
        num(sum(m["outside_hits"] for m in members)),
        num(sum(m["assist_hits"] for m in members)),
        num(sum(m["xanax_used"] for m in members)),
        "",
        money(sum(m["calculated_fine"] for m in members)),
        "",
        money(sum(m["gross_pay"] for m in members)),
        money(sum(m["flat_bonus"] + m["leadership_cut_share"] for m in members)),
        money_cell(total_final),
        "",
    ]


def stats_row(m) -> list:
    return [
        m["name"],
        f"{num(m['total_hits'])} (#{m['hits_rank']})",
        f"{num(m['respect'], 2)} (#{m['respect_gained_rank']})",
        f"{num(m['respect_lost'], 2)} (#{m['respect_lost_rank']})",
        f"{num(m['best_hit'], 2)} (#{m['best_hit_rank']})",
        f"{num(m['avg_respect_per_hit'], 2)} (#{m['avg_respect_per_hit_rank']})",
        f"{num(m['win_rate_pct'], 1)}% (#{m['win_rate_pct_rank']})",
        f"{num(m['retaliation_hits'])} (#{m['retaliation_hits_rank']})",
        f"{num(m['bonus_hits'])} (#{m['bonus_hits_rank']})",
        str(m["score"]),
        f"#{m['overall_rank']}",
    ]


def career_row(m) -> list:
    return [
        m["name"], m["position"] or "-", num(m["wars_played"]),
        f"{num(m['avg_hits'], 1)} (#{m['avg_hits_rank']})",
        f"{num(m['avg_respect_gained'], 2)} (#{m['avg_respect_gained_rank']})",
        f"{num(m['avg_respect_lost'], 2)} (#{m['avg_respect_lost_rank']})",
        f"{num(m['avg_best_hit'], 2)} (#{m['avg_best_hit_rank']})",
        f"{num(m['avg_respect_per_hit'], 2)} (#{m['avg_respect_per_hit_rank']})",
        f"{num(m['win_rate_pct'], 1)}% (#{m['win_rate_pct_rank']})",
        f"{num(m['avg_retaliation_hits'], 2)} (#{m['avg_retaliation_hits_rank']})",
        f"{num(m['avg_bonus_hits'], 2)} (#{m['avg_bonus_hits_rank']})",
        str(m["score"]),
        f"#{m['overall_rank']}",
    ]


def armory_row(line) -> list:
    return [
        line["item_name"], num(line["target_qty"]), num(line["on_hand"]),
        num(line["needed"]), money(line["unit_price"]), money(line["cost"]),
    ]


def armory_totals_row(lines: list) -> list:
    return [
        {"text": "Total", "color": COLORS["text"]}, "", "", "",
        "", money(sum(l["cost"] for l in lines)),
    ]


def war_status_row(m) -> list:
    status = m["status"]
    status_text = status["description"] or status["state"]
    if status.get("until"):
        remaining = status["until"] - int(time.time())
        if remaining > 0:
            status_text += f" ({_format_duration(remaining)})"
    la = m["last_action"]
    return [
        m["name"],
        str(m["level"]),
        {"text": status_text, "color": STATUS_COLOR_MAP.get(status.get("color"), COLORS["text"])},
        la["relative"],
        m.get("position") or "-",
        "Yes" if m.get("is_on_wall") else "No",
        "Yes" if m.get("is_revivable") else "No",
    ]


def war_status_sort_key(m):
    """Okay (attackable) members first, then everyone else grouped by status,
    highest level first within each group - the people worth looking at first."""
    is_okay = m["status"].get("state") == "Okay"
    return (0 if is_okay else 1, -(m["level"] or 0))
