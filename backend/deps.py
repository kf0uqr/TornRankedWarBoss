from fastapi import HTTPException

from backend import db
from backend.torn_api import TornClient, TornAPIError


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
