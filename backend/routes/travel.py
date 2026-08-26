from fastapi import APIRouter
from pydantic import BaseModel

from backend import db

router = APIRouter(prefix="/api/travel-observations", tags=["travel"])


class TravelObservationIn(BaseModel):
    member_id: int
    member_name: str | None = None
    destination: str
    has_private_island: bool = False
    takeoff_at: int
    landing_at: int


@router.post("")
def add_travel_observation(body: TravelObservationIn):
    db.add_travel_observation(
        body.member_id,
        body.member_name,
        body.destination,
        body.has_private_island,
        body.takeoff_at,
        body.landing_at,
    )
    return {"ok": True}


@router.get("")
def list_travel_observations(limit: int = 200):
    return db.list_travel_observations(limit)


@router.get("/estimates")
def get_travel_estimates():
    return db.get_travel_estimates()
