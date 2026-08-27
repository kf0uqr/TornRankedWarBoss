import httpx
from fastapi import APIRouter, Depends

from backend import db, ffscouter
from backend.deps import require_client, require_faction_id, require_leadership, torn_error_to_http
from backend.torn_api import TornAPIError, TornClient

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(require_leadership)])


def _exact_bars_and_stats_by_member() -> dict[int, dict]:
    """Bars/battlestats are only visible for the account whose own key is
    used - so this tries every pooled key individually (not round-robined,
    since we need to know specifically whose data came back) and keys the
    result by profile.id, which self-identifies whichever member that key
    belongs to. Members whose key isn't in the pool just won't appear here."""
    results: dict[int, dict] = {}
    for key in db.get_api_keys():
        try:
            data = TornClient([key]).user_bars_battlestats_profile()
        except (TornAPIError, httpx.HTTPError):
            continue
        profile = data["profile"]
        bs = data["battlestats"]
        results[profile["id"]] = {
            "name": profile.get("name"),
            "battle_stats_exact": sum(bs[stat]["value"] for stat in ("strength", "defense", "speed", "dexterity")),
            "energy": data["bars"]["energy"],
            "life": data["bars"]["life"],
        }
    return results


@router.get("")
def get_dashboard():
    faction_id = require_faction_id()
    client = require_client()
    try:
        members = client.faction_members(faction_id)
    except TornAPIError as exc:
        raise torn_error_to_http(exc)
    finally:
        client.close()

    ffscouter_key = db.get_ffscouter_api_key()
    ffscouter_error = None
    if ffscouter_key:
        try:
            estimates = ffscouter.get_stats(ffscouter_key, [m["id"] for m in members])
            for m in members:
                entry = estimates.get(m["id"])
                if entry:
                    m["bs_estimate_human"] = entry.get("bs_estimate_human")
        except (httpx.HTTPError, ffscouter.FFScouterError) as exc:
            ffscouter_error = str(exc)

    exact_by_member = _exact_bars_and_stats_by_member()
    for m in members:
        exact = exact_by_member.get(m["id"])
        if exact:
            m.update(exact)

    return {"members": members, "ffscouter_error": ffscouter_error}
