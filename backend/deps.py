import time

from fastapi import Depends, HTTPException, Request

from backend import db
from backend.torn_api import TornClient, TornAPIError


def require_session(request: Request) -> dict:
    """Accepts either an Authorization: Bearer <token> header (used by the
    Tampermonkey script, which can't rely on cookie-jar behavior across
    contexts) or the twm_session cookie (used by the frontend). A token
    matching the app's own service_token is treated as a synthetic
    leadership session - that's how the Discord bot (a trusted local
    process, not a player) authenticates its own server-to-server calls."""
    token = None
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.cookies.get("twm_session")
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in.")

    service_token = db.get_service_token()
    if service_token and token == service_token:
        return {"is_leadership": True, "player_name": "bot", "torn_player_id": None, "position": None}

    session = db.get_session(token)
    if not session or session["expires_at"] < int(time.time()):
        raise HTTPException(status_code=401, detail="Session expired or invalid - log in again.")
    return session


def require_leadership(session: dict = Depends(require_session)) -> dict:
    if not session["is_leadership"]:
        raise HTTPException(status_code=403, detail="This is restricted to faction leadership.")
    return session


def require_client() -> TornClient:
    api_keys = db.get_api_keys()
    if not api_keys:
        raise HTTPException(status_code=400, detail="No Torn API key configured. Set one in Settings first.")
    return TornClient(api_keys)


def require_faction_id() -> int:
    faction_id = db.get_faction_id()
    if not faction_id:
        raise HTTPException(status_code=400, detail="No faction ID configured. Set one in Settings first.")
    return faction_id


def torn_error_to_http(exc: TornAPIError) -> HTTPException:
    return HTTPException(status_code=502, detail=exc.message)
