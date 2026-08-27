import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from backend import db
from backend.deps import require_session
from backend.torn_api import TornAPIError, TornClient

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_COOKIE = "twm_session"


class LoginIn(BaseModel):
    api_key: str


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    """Identifies the player from their own Torn API key (same validation
    Torn call as the Discord bot's /add_api_key flow), looks up their live
    faction position to resolve leadership, and starts a session. Doesn't
    add the key to the shared pool - that's a separate, deliberate action
    in Settings, not an implicit side effect of logging in."""
    key = body.api_key.strip()
    try:
        info = TornClient([key]).get("/key/info")["info"]
    except TornAPIError as exc:
        raise HTTPException(status_code=400, detail=f"Torn rejected this key: {exc.message}")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Couldn't reach Torn's API: {exc}")

    faction_id = info["user"]["faction_id"]
    our_faction_id = db.get_faction_id()
    if our_faction_id and faction_id != our_faction_id:
        raise HTTPException(
            status_code=403,
            detail=f"This key belongs to a member of faction {faction_id}, not this faction ({our_faction_id}).",
        )

    torn_player_id = info["user"]["id"]
    position = None
    player_name = None
    try:
        for m in TornClient([key]).faction_members(faction_id):
            if m["id"] == torn_player_id:
                position = m.get("position")
                player_name = m.get("name")
                break
    except TornAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Couldn't look up your faction position: {exc.message}")

    # Torn's own faction API doesn't consistently match the casing of the
    # rank names configured in rank_pay_rates (e.g. it returns "Co-leader",
    # not "Co-Leader") - match case-insensitively so leadership detection
    # doesn't silently fail for a rank that's really configured as leadership.
    leadership_map = {name.lower(): is_lead for name, is_lead in db.get_rank_leadership_map().items()}
    is_leadership = leadership_map.get((position or "").lower(), False)

    db.prune_expired_sessions()
    token = secrets.token_hex(32)
    db.create_session(token, torn_player_id, player_name, position, is_leadership)

    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=db.SESSION_LIFETIME_SECONDS,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return {"token": token, "player_name": player_name, "position": position, "is_leadership": is_leadership}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    auth_header = request.headers.get("authorization")
    if not token and auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    if token:
        db.delete_session(token)
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
def me(session: dict = Depends(require_session)):
    return {
        "player_name": session["player_name"],
        "position": session["position"],
        "is_leadership": bool(session["is_leadership"]),
    }
