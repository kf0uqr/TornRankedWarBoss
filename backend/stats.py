"""Player Stats: ranks members on total hits, respect gained from inside hits, and
respect lost defending against inside hits, then sums the three ranks into an overall
rank - reconstructed from the `Player Stats` sheet's layout.

Ranking is dense (ties share a rank, the next distinct value is rank+1, no gaps) -
verified against the original sheet's numbers.
"""

from backend.torn_api import TornClient

LEADERSHIP_RANKS = {"Leader", "Co-Leader", "Chief Evasion Officer"}


def compute_respect_lost(client: TornClient, from_ts: int, to_ts: int) -> dict[int, float]:
    """Sum of respect lost per member from every incoming attack in the war window."""
    losses: dict[int, float] = {}
    for atk in client.faction_attacks("incoming", from_ts, to_ts):
        defender_id = atk.get("defender", {}).get("id")
        if defender_id is None:
            continue
        losses[defender_id] = losses.get(defender_id, 0.0) + (atk.get("respect_loss") or 0.0)
    return losses


def _dense_rank(items: list[tuple[int, float]], descending: bool) -> dict[int, int]:
    """items: (member_id, metric) pairs. Returns member_id -> rank, 1 = best."""
    distinct_values = sorted({value for _, value in items}, reverse=descending)
    rank_by_value = {value: i + 1 for i, value in enumerate(distinct_values)}
    return {member_id: rank_by_value[value] for member_id, value in items}


def rank_members(members: list[dict]) -> list[dict]:
    """members: dicts with member_id, name, inside_hits, outside_hits, assist_hits,
    respect (gained), respect_lost. Returns the same members enriched with per-category
    and overall dense ranks, sorted by overall rank."""
    enriched = [{**m, "total_hits": m["inside_hits"] + m["outside_hits"] + m["assist_hits"]} for m in members]

    hits_rank = _dense_rank([(m["member_id"], m["total_hits"]) for m in enriched], descending=True)
    respect_gained_rank = _dense_rank([(m["member_id"], m["respect"]) for m in enriched], descending=True)
    respect_lost_rank = _dense_rank([(m["member_id"], m["respect_lost"]) for m in enriched], descending=False)

    for m in enriched:
        m["hits_rank"] = hits_rank[m["member_id"]]
        m["respect_gained_rank"] = respect_gained_rank[m["member_id"]]
        m["respect_lost_rank"] = respect_lost_rank[m["member_id"]]
        m["score"] = m["hits_rank"] + m["respect_gained_rank"] + m["respect_lost_rank"]

    overall_rank = _dense_rank([(m["member_id"], m["score"]) for m in enriched], descending=False)
    for m in enriched:
        m["overall_rank"] = overall_rank[m["member_id"]]

    enriched.sort(key=lambda m: m["overall_rank"])
    return enriched


def compute_player_stats(members: list[dict]) -> dict:
    """Splits members into leadership (Leader/Co-Leader/Chief Evasion Officer) and
    everyone else, ranking each group independently."""
    leadership = [m for m in members if m["pay_rank"] in LEADERSHIP_RANKS]
    others = [m for m in members if m["pay_rank"] not in LEADERSHIP_RANKS]
    return {
        "leadership": rank_members(leadership),
        "others": rank_members(others),
    }
