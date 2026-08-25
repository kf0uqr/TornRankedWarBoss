"""Pulls raw war/chain/roster data from Torn and aggregates it into war_members rows.

Inside hits come straight from the ranked war report (Torn only counts attacks that
contributed to the war score there). Outside hits and assists are only visible in the
faction's chain reports, so every chain that fell inside the war's [start, end] window
is pulled and summed per attacker.
"""

import time

from backend import armory, stats
from backend.torn_api import TornClient


def _prior_war_end(client: TornClient, faction_id: int, current_war_start: int) -> int | None:
    """Latest end timestamp among ranked wars that finished before this one started."""
    wars = client.faction_rankedwars(faction_id, limit=100)
    prior_ends = [w["end"] for w in wars if w["end"] and w["end"] <= current_war_start]
    return max(prior_ends) if prior_ends else None


def sync_war(client: TornClient, conn, faction_id: int, ranked_war_id: int) -> int:
    report = client.faction_rankedwarreport(ranked_war_id)
    our_faction = next(f for f in report["factions"] if f["id"] == faction_id)
    opponent = next((f for f in report["factions"] if f["id"] != faction_id), None)
    start, end = report["start"], report["end"]
    opponent_name = opponent["name"] if opponent else None

    inside_hits: dict[int, int] = {}
    respect: dict[int, float] = {}
    names: dict[int, str] = {}
    levels: dict[int, int] = {}
    for m in our_faction["members"]:
        inside_hits[m["id"]] = m["attacks"]
        respect[m["id"]] = m["score"]
        names[m["id"]] = m["name"]
        levels[m["id"]] = m["level"]

    outside_hits: dict[int, int] = {}
    assist_hits: dict[int, int] = {}
    chains = client.faction_chains(faction_id, start, end)
    for chain in chains:
        chain_report = client.faction_chainreport(chain["id"])
        for attacker in chain_report["attackers"]:
            mid = attacker["id"]
            atk = attacker["attacks"]
            outside_hits[mid] = outside_hits.get(mid, 0) + (atk["total"] - atk["war"])
            assist_hits[mid] = assist_hits.get(mid, 0) + atk["assists"]

    positions: dict[int, str] = {}
    for member in client.faction_members(faction_id):
        positions[member["id"]] = member["position"]
        names.setdefault(member["id"], member["name"])
        levels.setdefault(member["id"], member["level"])

    # Xanax used is tracked from when the armory was last stocked (the previous war's
    # end) through this war's end, not just from this war's own start - restocking
    # happens between wars, and usage during that gap draws down the same stock.
    xanax_window_start = _prior_war_end(client, faction_id, start) or start
    xanax_used = armory.count_item_usage(client, "Xanax", xanax_window_start, end)

    # Respect lost is every incoming attack during the war itself (not the xanax window
    # above), up to whichever comes first: the war's own end, or the point it was termed
    # (is_termed/termed_at are manual settings, preserved across resyncs below). A war
    # marked termed with no specific time is treated as termed at its own start - i.e.
    # no respect lost counted at all.
    existing_war = conn.execute(
        "SELECT is_termed, termed_at FROM wars WHERE id = ?", (ranked_war_id,)
    ).fetchone()
    is_termed = bool(existing_war["is_termed"]) if existing_war else False
    termed_at = existing_war["termed_at"] if existing_war else None

    if is_termed:
        respect_lost_end = min(end, termed_at) if termed_at else start
    else:
        respect_lost_end = end
    respect_lost = stats.compute_respect_lost(client, start, respect_lost_end) if respect_lost_end > start else {}

    # Scoped to who was actually on the war roster (rankedwarreport lists every member
    # present during the war, even 0-hit ones, regardless of whether they've since left
    # the faction) or fought in one of its chains. Deliberately excludes `positions`
    # (current roster) and the xanax/respect_lost lookups, which are time-window based
    # and would otherwise pull in members who joined after the war was already over.
    member_ids = set(inside_hits) | set(outside_hits) | set(assist_hits)

    known_ranks = {r["rank_name"] for r in conn.execute("SELECT rank_name FROM rank_pay_rates")}

    # Prune anyone left over from a previous sync who's no longer on the war roster
    # (e.g. joined after the war and got swept in by an earlier version of this logic).
    if member_ids:
        placeholders = ",".join("?" * len(member_ids))
        conn.execute(
            f"DELETE FROM war_members WHERE war_id = ? AND member_id NOT IN ({placeholders})",
            (ranked_war_id, *member_ids),
        )
    else:
        conn.execute("DELETE FROM war_members WHERE war_id = ?", (ranked_war_id,))

    conn.execute(
        """
        INSERT INTO wars (id, opponent_name, start, end, synced_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            opponent_name = excluded.opponent_name,
            start = excluded.start,
            end = excluded.end,
            synced_at = excluded.synced_at
        """,
        (ranked_war_id, opponent_name, start, end, int(time.time())),
    )

    for mid in member_ids:
        existing = conn.execute(
            "SELECT fine_waived, pay_rank FROM war_members WHERE war_id = ? AND member_id = ?",
            (ranked_war_id, mid),
        ).fetchone()

        position = positions.get(mid)
        if existing:
            fine_waived = existing["fine_waived"]
            pay_rank = existing["pay_rank"]
        else:
            fine_waived = 0
            pay_rank = position if position in known_ranks else None

        conn.execute(
            """
            INSERT INTO war_members
                (war_id, member_id, name, position, level, inside_hits, outside_hits, assist_hits, respect, respect_lost, pay_rank, xanax_used, fine_waived)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(war_id, member_id) DO UPDATE SET
                name = excluded.name,
                position = excluded.position,
                level = excluded.level,
                inside_hits = excluded.inside_hits,
                outside_hits = excluded.outside_hits,
                assist_hits = excluded.assist_hits,
                respect = excluded.respect,
                respect_lost = excluded.respect_lost,
                pay_rank = excluded.pay_rank,
                xanax_used = excluded.xanax_used,
                fine_waived = excluded.fine_waived
            """,
            (
                ranked_war_id,
                mid,
                names.get(mid, str(mid)),
                position,
                levels.get(mid),
                inside_hits.get(mid, 0),
                outside_hits.get(mid, 0),
                assist_hits.get(mid, 0),
                respect.get(mid, 0.0),
                respect_lost.get(mid, 0.0),
                pay_rank,
                xanax_used.get(mid, 0),
                fine_waived,
            ),
        )

    conn.commit()
    return ranked_war_id
