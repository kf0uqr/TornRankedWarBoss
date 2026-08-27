import time

from fastapi import APIRouter, Depends

from backend import db
from backend.deps import require_leadership
from backend.routes.dashboard import _exact_bars_and_stats_by_member

router = APIRouter(prefix="/api/stat-snapshots", tags=["stat-snapshots"], dependencies=[Depends(require_leadership)])


@router.post("/capture")
def capture_snapshot():
    """Records today's (UTC) battle-stat total for every member whose own key
    is in the pool - a no-op if already captured today. Meant to be called
    periodically (e.g. hourly) rather than on a precise midnight schedule;
    it just captures whenever it's next asked after the UTC date rolls over."""
    snapshot_date = time.strftime("%Y-%m-%d", time.gmtime())
    if db.has_stat_snapshot_today(snapshot_date):
        return {"captured": False, "reason": "already captured today"}

    exact = _exact_bars_and_stats_by_member()
    entries = [
        {"member_id": member_id, "member_name": v.get("name"), "battle_stats_total": v["battle_stats_exact"]}
        for member_id, v in exact.items()
    ]
    db.add_stat_snapshots(snapshot_date, entries)
    return {"captured": True, "count": len(entries)}


@router.get("/gains")
def get_gains(since: int):
    latest = {r["member_id"]: r for r in db.get_latest_stat_snapshots()}
    baseline = {r["member_id"]: r for r in db.get_earliest_stat_snapshots_since(since)}

    results = []
    for member_id, latest_row in latest.items():
        base_row = baseline.get(member_id)
        if base_row is None:
            continue
        results.append(
            {
                "member_id": member_id,
                "member_name": latest_row["member_name"],
                "baseline_total": base_row["battle_stats_total"],
                "baseline_at": base_row["recorded_at"],
                "latest_total": latest_row["battle_stats_total"],
                "latest_at": latest_row["recorded_at"],
                "gain": latest_row["battle_stats_total"] - base_row["battle_stats_total"],
            }
        )
    results.sort(key=lambda r: r["gain"], reverse=True)
    return results
