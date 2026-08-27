"""Table cell formatting for the Discord bot's images - mirrors
frontend/app.js's paysheetRowCells/statsRowCells etc. Kept in sync by hand,
same caveat as bot/render.py.
"""

import re

from bot.activity import MIN_OBSERVED_SAMPLES as MIN_ACTIVITY_SAMPLES
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

# Torn's own API doesn't expose battle stats for an enemy faction (that needs
# a spy report), so estimated stats here come from ffscouter.com (see
# backend/ffscouter.py) when a key is configured in Settings - otherwise that
# column just shows "-". Fair Fight isn't shown: it's computed relative to the
# API key owner's own stats, so it's not a meaningful number to broadcast.
WAR_STATUS_HEADERS = ["Name", "Level", "Est. Stats", "Status", "Last Action", "Position", "On Wall", "Revivable"]

STATUS_COLOR_MAP = {
    "green": COLORS["good"],
    "red": COLORS["bad"],
    "yellow": COLORS["warn"],
    "blue": COLORS["accent"],
}

COUNTRY_ABBR = {
    "Torn": "Torn",
    "Mexico": "MEX",
    "Cayman Islands": "CAY",
    "Canada": "CAN",
    "Hawaii": "HAW",
    "United Kingdom": "UK",
    "Argentina": "ARG",
    "Switzerland": "SWI",
    "Japan": "JPN",
    "China": "CHN",
    "UAE": "UAE",
    "United Arab Emirates": "UAE",
    "South Africa": "SA",
}

_TRAVEL_RE = re.compile(r"^Traveling from (.+) to (.+)$")
_TRAVEL_TO_RE = re.compile(r"^Traveling to (.+)$")
_IN_COUNTRY_RE = re.compile(r"^In (.+)$")

_TIME_UNIT_ABBR = {
    "second": "s", "seconds": "s",
    "minute": "m", "minutes": "m",
    "hour": "h", "hours": "h",
    "day": "d", "days": "d",
    "week": "w", "weeks": "w",
    "month": "mo", "months": "mo",
    "year": "y", "years": "y",
}
_TIME_RE = re.compile(r"(\d+)\s+(seconds?|minutes?|hours?|days?|weeks?|months?|years?)")


def _abbr_country(name: str) -> str:
    return COUNTRY_ABBR.get(name.strip(), name.strip())


def abbreviate_status(text: str) -> str:
    """Shortens Torn's own travel wording - "Traveling from Torn to South
    Africa" -> "Torn -> SA" - so it fits the table without truncating."""
    m = _TRAVEL_RE.match(text)
    if m:
        return f"{_abbr_country(m.group(1))} → {_abbr_country(m.group(2))}"
    m = _TRAVEL_TO_RE.match(text)
    if m:
        return f"→ {_abbr_country(m.group(1))}"
    m = _IN_COUNTRY_RE.match(text)
    if m:
        return f"In {_abbr_country(m.group(1))}"
    return text


def abbreviate_relative(text: str) -> str:
    """"27 minutes ago" -> "27m ago", "1 day ago" -> "1d ago", etc."""
    return _TIME_RE.sub(lambda m: f"{m.group(1)}{_TIME_UNIT_ABBR[m.group(2)]}", text)


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
    # Torn's own description already reads e.g. "In hospital for 14 mins" -
    # no need to compute our own duration on top of it.
    status_text = abbreviate_status(status["description"] or status["state"])
    la = m["last_action"]
    return [
        m["name"],
        str(m["level"]),
        m.get("bs_estimate_human") or "-",
        {"text": status_text, "color": STATUS_COLOR_MAP.get(status.get("color"), COLORS["text"])},
        abbreviate_relative(la["relative"]),
        m.get("position") or "-",
        "Yes" if m.get("is_on_wall") else "No",
        "Yes" if m.get("is_revivable") else "No",
    ]


def war_status_sort_key(m):
    """Okay (attackable) members first, then everyone else grouped by status,
    highest level first within each group - the people worth looking at first."""
    is_okay = m["status"].get("state") == "Okay"
    return (0 if is_okay else 1, -(m["level"] or 0))


# war_hits/war_respect/war_respect_lost are computed live from the attack log
# (Torn's own rankedwarreport - used for the post-war paysheet - isn't
# available until the war ends), so treat these as an estimate rather than
# the official score.
OWN_WAR_HEADERS = ["Name", "Level", "Hits", "Respect Gained", "Respect Lost", "Status", "Last Action", "Position"]


def own_war_row(m) -> list:
    status = m["status"]
    status_text = abbreviate_status(status["description"] or status["state"])
    la = m["last_action"]
    return [
        m["name"],
        str(m["level"]),
        num(m.get("war_hits", 0)),
        num(m.get("war_respect", 0), 2),
        num(m.get("war_respect_lost", 0), 2),
        {"text": status_text, "color": STATUS_COLOR_MAP.get(status.get("color"), COLORS["text"])},
        abbreviate_relative(la["relative"]),
        m.get("position") or "-",
    ]


def own_war_sort_key(m):
    """Highest respect gained this war first, hits as the tiebreaker."""
    return (-(m.get("war_respect") or 0), -(m.get("war_hits") or 0))


# Hours are UTC (Torn's own clock). Estimates come from
# /api/activity-observations/estimates - percent of observed refresh polls
# a member was Online at that hour, keyed by string member_id/hour since
# that's how it comes back over JSON.
ACTIVITY_HEATMAP_HEADERS = ["Name"] + [f"{h:02d}" for h in range(24)]


def activity_heatmap_row(member_id: int, name: str, estimates: dict) -> list:
    by_hour = estimates.get(str(member_id), {})
    row = [name]
    for hour in range(24):
        entry = by_hour.get(str(hour))
        if not entry or entry["total_count"] < MIN_ACTIVITY_SAMPLES:
            row.append({"text": "-", "color": COLORS["text_dim"]})
            continue
        pct = entry["pct"]
        if pct >= 50:
            color = COLORS["good"]
        elif pct >= 20:
            color = COLORS["warn"]
        else:
            color = COLORS["text_dim"]
        row.append({"text": f"{pct:.0f}%", "color": color})
    return row


# Torn only ever returns bars/battlestats for the account whose own key made
# the request, never an arbitrary target - so "exact" here only covers
# members who've contributed their own key via /add_api_key or Settings.
# Everyone else falls back to the same FFScouter estimate used for the enemy
# roster (or "-" if neither is available).
DASHBOARD_HEADERS = ["Name", "Level", "Status", "Last Action", "Position", "Battle Stats", "Energy", "Health"]


def _format_stat_total(n: float) -> str:
    sign = "-" if n < 0 else ""
    n = abs(n)
    for suffix, div in (("t", 1e12), ("b", 1e9), ("m", 1e6), ("k", 1e3)):
        if n >= div:
            return f"{sign}{n / div:.2f}{suffix}"
    return f"{sign}{n:.0f}"


def _bar_cell(bar: dict | None) -> str:
    if not bar:
        return "-"
    return f"{bar['current']:,}/{bar['maximum']:,}"


def dashboard_row(m) -> list:
    status = m["status"]
    status_text = abbreviate_status(status["description"] or status["state"])

    if "battle_stats_exact" in m:
        stats_cell = {"text": _format_stat_total(m["battle_stats_exact"]), "color": COLORS["good"]}
    elif m.get("bs_estimate_human"):
        stats_cell = m["bs_estimate_human"]
    else:
        stats_cell = "-"

    return [
        m["name"],
        str(m["level"]),
        {"text": status_text, "color": STATUS_COLOR_MAP.get(status.get("color"), COLORS["text"])},
        abbreviate_relative(m["last_action"]["relative"]),
        m.get("position") or "-",
        stats_cell,
        _bar_cell(m.get("energy")),
        _bar_cell(m.get("life")),
    ]


def dashboard_sort_key(m):
    return m["name"].lower()


# Only covers members with a key in the pool (exact stats are required to
# measure a real gain - FFScouter's estimate is too noisy day-to-day to
# track trends against). A gain of 0 usually just means only one snapshot
# has been taken in the requested window so far, not that they've stalled.
GAINS_HEADERS = ["Name", "Then", "Now", "Gain"]


def gains_row(g) -> list:
    gain = g["gain"]
    color = COLORS["good"] if gain > 0 else COLORS["bad"] if gain < 0 else COLORS["text_dim"]
    gain_text = f"+{_format_stat_total(gain)}" if gain > 0 else _format_stat_total(gain)
    return [
        g["member_name"] or f"#{g['member_id']}",
        _format_stat_total(g["baseline_total"]),
        _format_stat_total(g["latest_total"]),
        {"text": gain_text, "color": color},
    ]


def gains_sort_key(g):
    return -g["gain"]
