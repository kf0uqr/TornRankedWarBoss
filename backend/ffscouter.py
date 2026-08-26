"""Thin client for ffscouter.com's API (https://ffscouter.com/api-docs) - used
to enrich the enemy roster with Fair Fight / estimated battle stats, which
Torn's own API doesn't expose for players outside your faction.
"""

import httpx

BASE_URL = "https://ffscouter.com/api/v1"


class FFScouterError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(f"FFScouter API error [{code}]: {message}")


def get_stats(api_key: str, player_ids: list[int]) -> dict[int, dict]:
    """Fair Fight + estimated battle stats for up to 205 player IDs at a time,
    keyed by player_id. Callers with more than 205 IDs need to batch."""
    if not player_ids:
        return {}
    results: dict[int, dict] = {}
    with httpx.Client(base_url=BASE_URL, timeout=15) as client:
        for i in range(0, len(player_ids), 205):
            batch = player_ids[i : i + 205]
            resp = client.get("/get-stats", params={"key": api_key, "targets": ",".join(str(p) for p in batch)})
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and "code" in data:
                raise FFScouterError(data["code"], data.get("error", "unknown error"))
            for entry in data:
                results[entry["player_id"]] = entry
    return results
