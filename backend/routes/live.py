import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.deps import require_leadership, require_session

router = APIRouter(prefix="/api/live", tags=["live"])

# Ephemeral, in-memory only - published by the Discord bot every
# WAR_STATUS_REFRESH_MINUTES while /current_war's boards are running, and
# cleared when they stop or the war ends. Not persisted: there's no value in
# remembering a stale snapshot across an app restart, same reasoning as
# bot/travel.py's TravelTracker being in-memory-only.
_snapshot: dict = {"war_id": None, "updated_at": None, "members": []}


class LiveMemberIn(BaseModel):
    id: int
    name: str
    level: int | None = None
    position: str | None = None
    status: dict
    last_action: dict
    is_on_wall: bool = False
    is_revivable: bool = False
    bs_estimate_human: str | None = None
    online_probability_now: float | None = None
    estimated_landing_at: int | None = None


class WarSnapshotIn(BaseModel):
    war_id: int
    members: list[LiveMemberIn]


@router.post("/war-snapshot", dependencies=[Depends(require_leadership)])
def publish_war_snapshot(body: WarSnapshotIn):
    global _snapshot
    _snapshot = {
        "war_id": body.war_id,
        "updated_at": int(time.time()),
        "members": [m.model_dump() for m in body.members],
    }
    return {"ok": True}


@router.delete("/war-snapshot", dependencies=[Depends(require_leadership)])
def clear_war_snapshot():
    global _snapshot
    _snapshot = {"war_id": None, "updated_at": None, "members": []}
    return {"ok": True}


@router.get("/war-snapshot", dependencies=[Depends(require_session)])
def get_war_snapshot():
    return _snapshot
