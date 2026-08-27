from fastapi import APIRouter, Depends

from backend import db, stats
from backend.deps import require_client, require_faction_id, require_leadership, torn_error_to_http
from backend.torn_api import TornAPIError, TornClient

router = APIRouter(prefix="/api/stats", tags=["stats"], dependencies=[Depends(require_leadership)])


@router.get("/career")
def get_career_stats(client: TornClient = Depends(require_client)):
    faction_id = require_faction_id()
    try:
        current_members = client.faction_members(faction_id)
    except TornAPIError as exc:
        raise torn_error_to_http(exc)
    finally:
        client.close()

    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT member_id, inside_hits, outside_hits, assist_hits, respect, respect_lost, "
            "best_hit, chain_respect_total, chain_hits_total, losses, escapes, draws, retaliation_hits, bonus_hits "
            "FROM war_members"
        ).fetchall()
        war_member_rows = [dict(r) for r in rows]
    finally:
        conn.close()

    members = [{"member_id": m["id"], "name": m["name"], "position": m["position"]} for m in current_members]
    return stats.compute_career_stats(members, war_member_rows)
