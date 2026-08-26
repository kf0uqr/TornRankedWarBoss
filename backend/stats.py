"""Player Stats: ranks members on total hits, respect gained from inside hits, and
respect lost defending against inside hits, then sums the three ranks into an overall
rank - reconstructed from the `Player Stats` sheet's layout.

Ranking is dense (ties share a rank, the next distinct value is rank+1, no gaps) -
verified against the original sheet's numbers.
"""

from backend.torn_api import TornClient

LEADERSHIP_RANKS = {"Leader", "Co-Leader", "Chief Evasion Officer"}
_LEADERSHIP_RANKS_LOWER = {r.lower() for r in LEADERSHIP_RANKS}


def _is_leadership(rank_name: str | None) -> bool:
    """Case-insensitive check - Torn's own position string for Co-Leader is actually
    'Co-leader' (lowercase l), which would silently fail an exact-match comparison."""
    return bool(rank_name) and rank_name.strip().lower() in _LEADERSHIP_RANKS_LOWER


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
    respect (gained), respect_lost, best_hit, chain_respect_total, chain_hits_total,
    losses, escapes, draws, retaliation_hits, bonus_hits. Returns the same members
    enriched with per-category and overall dense ranks, sorted by overall rank.

    Overall rank/Score is still just hits + respect gained + respect lost, as
    verified against the original sheet - the newer quality/outcome metrics below
    are shown for reference only and aren't folded into it (yet)."""
    enriched = [{**m, "total_hits": m["inside_hits"] + m["outside_hits"] + m["assist_hits"]} for m in members]

    hits_rank = _dense_rank([(m["member_id"], m["total_hits"]) for m in enriched], descending=True)
    respect_gained_rank = _dense_rank([(m["member_id"], m["respect"]) for m in enriched], descending=True)
    respect_lost_rank = _dense_rank([(m["member_id"], m["respect_lost"]) for m in enriched], descending=False)

    for m in enriched:
        m["hits_rank"] = hits_rank[m["member_id"]]
        m["respect_gained_rank"] = respect_gained_rank[m["member_id"]]
        m["respect_lost_rank"] = respect_lost_rank[m["member_id"]]
        m["score"] = m["hits_rank"] + m["respect_gained_rank"] + m["respect_lost_rank"]

        m["avg_respect_per_hit"] = m["chain_respect_total"] / m["chain_hits_total"] if m["chain_hits_total"] else 0.0
        failed_attempts = m["losses"] + m["escapes"] + m["draws"]
        m["win_rate_pct"] = (
            (m["chain_hits_total"] - failed_attempts) / m["chain_hits_total"] * 100 if m["chain_hits_total"] else 0.0
        )

    for key, descending in (
        ("best_hit", True),
        ("avg_respect_per_hit", True),
        ("win_rate_pct", True),
        ("retaliation_hits", True),
        ("bonus_hits", True),
    ):
        rank = _dense_rank([(m["member_id"], m[key]) for m in enriched], descending=descending)
        for m in enriched:
            m[f"{key}_rank"] = rank[m["member_id"]]

    overall_rank = _dense_rank([(m["member_id"], m["score"]) for m in enriched], descending=False)
    for m in enriched:
        m["overall_rank"] = overall_rank[m["member_id"]]

    enriched.sort(key=lambda m: m["overall_rank"])
    return enriched


def compute_player_stats(members: list[dict]) -> dict:
    """Splits members into leadership (Leader/Co-Leader/Chief Evasion Officer) and
    everyone else, ranking each group independently."""
    leadership = [m for m in members if _is_leadership(m["pay_rank"])]
    others = [m for m in members if not _is_leadership(m["pay_rank"])]
    return {
        "leadership": rank_members(leadership),
        "others": rank_members(others),
    }


def compute_career_stats(current_members: list[dict], war_member_rows: list[dict]) -> list[dict]:
    """Per-war averages for every currently-in-faction member, across all synced wars
    they appear in. current_members: dicts with member_id, name, position.
    war_member_rows: every war_members row across every synced war.

    Leadership (Leader/Co-Leader/Chief Evasion Officer) is excluded entirely - this
    board is for ranking regular players against each other."""
    current_members = [m for m in current_members if not _is_leadership(m["position"])]

    rows_by_member: dict[int, list[dict]] = {}
    for row in war_member_rows:
        rows_by_member.setdefault(row["member_id"], []).append(row)

    results = []
    for m in current_members:
        rows = rows_by_member.get(m["member_id"], [])
        wars_played = len(rows)
        if wars_played:
            avg_hits = sum(r["inside_hits"] + r["outside_hits"] + r["assist_hits"] for r in rows) / wars_played
            avg_respect_gained = sum(r["respect"] for r in rows) / wars_played
            avg_respect_lost = sum(r["respect_lost"] for r in rows) / wars_played
            avg_best_hit = sum(r["best_hit"] for r in rows) / wars_played
            avg_retaliation_hits = sum(r["retaliation_hits"] for r in rows) / wars_played
            avg_bonus_hits = sum(r["bonus_hits"] for r in rows) / wars_played
            # Weighted across wars (sum of totals / sum of totals), not an average of
            # per-war percentages/rates, so a single small-sample war doesn't skew it.
            total_chain_hits = sum(r["chain_hits_total"] for r in rows)
            avg_respect_per_hit = sum(r["chain_respect_total"] for r in rows) / total_chain_hits if total_chain_hits else 0.0
            failed_attempts = sum(r["losses"] + r["escapes"] + r["draws"] for r in rows)
            win_rate_pct = (total_chain_hits - failed_attempts) / total_chain_hits * 100 if total_chain_hits else 0.0
        else:
            avg_hits = avg_respect_gained = avg_respect_lost = 0.0
            avg_best_hit = avg_respect_per_hit = win_rate_pct = 0.0
            avg_retaliation_hits = avg_bonus_hits = 0.0
        results.append(
            {
                "member_id": m["member_id"],
                "name": m["name"],
                "position": m["position"],
                "wars_played": wars_played,
                "avg_hits": avg_hits,
                "avg_respect_gained": avg_respect_gained,
                "avg_respect_lost": avg_respect_lost,
                "avg_best_hit": avg_best_hit,
                "avg_respect_per_hit": avg_respect_per_hit,
                "win_rate_pct": win_rate_pct,
                "avg_retaliation_hits": avg_retaliation_hits,
                "avg_bonus_hits": avg_bonus_hits,
            }
        )

    avg_hits_rank = _dense_rank([(r["member_id"], r["avg_hits"]) for r in results], descending=True)
    avg_respect_gained_rank = _dense_rank(
        [(r["member_id"], r["avg_respect_gained"]) for r in results], descending=True
    )
    avg_respect_lost_rank = _dense_rank(
        [(r["member_id"], r["avg_respect_lost"]) for r in results], descending=False
    )
    for r in results:
        r["avg_hits_rank"] = avg_hits_rank[r["member_id"]]
        r["avg_respect_gained_rank"] = avg_respect_gained_rank[r["member_id"]]
        r["avg_respect_lost_rank"] = avg_respect_lost_rank[r["member_id"]]
        r["score"] = r["avg_hits_rank"] + r["avg_respect_gained_rank"] + r["avg_respect_lost_rank"]

    # Reference-only metrics, same as the per-war Player Stats page - not part of Score.
    for key, descending in (
        ("avg_best_hit", True),
        ("avg_respect_per_hit", True),
        ("win_rate_pct", True),
        ("avg_retaliation_hits", True),
        ("avg_bonus_hits", True),
    ):
        rank = _dense_rank([(r["member_id"], r[key]) for r in results], descending=descending)
        for r in results:
            r[f"{key}_rank"] = rank[r["member_id"]]

    overall_rank = _dense_rank([(r["member_id"], r["score"]) for r in results], descending=False)
    for r in results:
        r["overall_rank"] = overall_rank[r["member_id"]]

    results.sort(key=lambda r: r["overall_rank"])
    return results
