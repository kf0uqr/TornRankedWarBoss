from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend import db
from backend.deps import require_leadership

router = APIRouter(prefix="/api/activity-observations", tags=["activity"], dependencies=[Depends(require_leadership)])


class ActivityObservationIn(BaseModel):
    member_id: int
    member_name: str | None = None
    hour_of_day: int
    is_active: bool
    observed_at: int


class ActivityObservationsIn(BaseModel):
    observations: list[ActivityObservationIn]


@router.post("")
def add_activity_observations(body: ActivityObservationsIn):
    db.add_activity_observations([o.model_dump() for o in body.observations])
    return {"ok": True, "count": len(body.observations)}


@router.get("/estimates")
def get_activity_estimates():
    return db.get_activity_estimates()
