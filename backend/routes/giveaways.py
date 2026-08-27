from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend import db
from backend.deps import require_leadership

router = APIRouter(prefix="/api/giveaways", tags=["giveaways"], dependencies=[Depends(require_leadership)])


class GiveawayIn(BaseModel):
    channel_id: str
    name: str
    description: str | None = None
    item: str
    num_winners: int
    ends_at: int
    created_by: str | None = None


class GiveawayMessageIn(BaseModel):
    message_id: str


class GiveawayEntryIn(BaseModel):
    discord_user_id: str


class GiveawayFinalizeIn(BaseModel):
    winner_discord_user_ids: list[str]


def _get_or_404(giveaway_id: int) -> dict:
    giveaway = db.get_giveaway(giveaway_id)
    if giveaway is None:
        raise HTTPException(status_code=404, detail="Giveaway not found")
    return giveaway


@router.post("")
def create_giveaway(body: GiveawayIn):
    giveaway_id = db.create_giveaway(
        body.channel_id, body.name, body.description, body.item, body.num_winners, body.ends_at, body.created_by
    )
    return db.get_giveaway(giveaway_id)


@router.get("/active")
def list_active_giveaways():
    return db.list_active_giveaways()


@router.get("/{giveaway_id}")
def get_giveaway(giveaway_id: int):
    giveaway = _get_or_404(giveaway_id)
    giveaway["entry_count"] = db.count_giveaway_entries(giveaway_id)
    return giveaway


@router.post("/{giveaway_id}/message")
def set_giveaway_message(giveaway_id: int, body: GiveawayMessageIn):
    _get_or_404(giveaway_id)
    db.set_giveaway_message_id(giveaway_id, body.message_id)
    return db.get_giveaway(giveaway_id)


@router.post("/{giveaway_id}/enter")
def enter_giveaway(giveaway_id: int, body: GiveawayEntryIn):
    giveaway = _get_or_404(giveaway_id)
    if giveaway["status"] != "active":
        raise HTTPException(status_code=400, detail="This giveaway has already ended")
    entered = db.add_giveaway_entry(giveaway_id, body.discord_user_id)
    return {"entered": entered, "entry_count": db.count_giveaway_entries(giveaway_id)}


@router.get("/{giveaway_id}/entries")
def get_giveaway_entries(giveaway_id: int):
    _get_or_404(giveaway_id)
    return db.list_giveaway_entries(giveaway_id)


@router.post("/{giveaway_id}/finalize")
def finalize_giveaway(giveaway_id: int, body: GiveawayFinalizeIn):
    _get_or_404(giveaway_id)
    db.finalize_giveaway(giveaway_id, body.winner_discord_user_ids)
    return db.get_giveaway(giveaway_id)


@router.post("/{giveaway_id}/cancel")
def cancel_giveaway(giveaway_id: int):
    giveaway = _get_or_404(giveaway_id)
    if giveaway["status"] != "active":
        raise HTTPException(status_code=400, detail="This giveaway isn't running")
    db.cancel_giveaway(giveaway_id)
    return db.get_giveaway(giveaway_id)
