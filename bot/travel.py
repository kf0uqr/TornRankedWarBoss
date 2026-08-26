"""Estimates when a traveling enemy will land.

Torn's API doesn't give an exact arrival time for other players, but
/current_war refreshes every 5 minutes - so when a member's status flips
from something else to "Traveling" between two consecutive refreshes, that
tells us their takeoff time accurate to within that window. Estimated
arrival = takeoff + Torn's public standard (non-boosted) travel duration for
their destination. This can't account for a private jet, WLT, Business
Class, or the Airstrip faction perk, all of which shorten real travel time,
so treat it as an upper bound, not a guarantee - and anyone already
traveling when the bot starts (or before their first observed takeoff) has
no estimate at all, since we never saw them leave.
"""

import time

# One-way standard (non-boosted) travel durations, in minutes - the same for
# every player without a speed perk.
STANDARD_TRAVEL_MINUTES = {
    "Mexico": 26,
    "Cayman Islands": 35,
    "Canada": 41,
    "Hawaii": 134,
    "United Kingdom": 159,
    "Argentina": 167,
    "Switzerland": 175,
    "Japan": 225,
    "China": 220,
    "UAE": 271,
    "South Africa": 297,
}


def _parse_destination(description: str) -> str | None:
    """"Traveling from Torn to South Africa" / "Traveling to South Africa" -> "South Africa"."""
    if " to " in description:
        return description.rsplit(" to ", 1)[-1].strip()
    return None


class TravelTracker:
    """Per-war, in-memory only - like bot/decay.py's ScoreHistory, this just
    starts over on a bot restart rather than persisting anything."""

    def __init__(self):
        self.war_id: int | None = None
        self._takeoffs: dict[int, dict] = {}  # member_id -> {"t": epoch, "destination": str}
        self._last_description: dict[int, str] = {}

    def record(self, war_id: int, members: list[dict]) -> None:
        if war_id != self.war_id:
            self.war_id = war_id
            self._takeoffs = {}
            self._last_description = {}

        now = time.time()
        seen_ids = set()
        for m in members:
            mid = m["id"]
            seen_ids.add(mid)
            description = m["status"].get("description") or ""
            was_traveling = self._last_description.get(mid, "").startswith("Traveling")
            is_traveling = description.startswith("Traveling")

            if is_traveling and not was_traveling:
                destination = _parse_destination(description)
                if destination:
                    self._takeoffs[mid] = {"t": now, "destination": destination}
            elif not is_traveling and mid in self._takeoffs:
                del self._takeoffs[mid]

            self._last_description[mid] = description

        for mid in list(self._takeoffs):
            if mid not in seen_ids:
                del self._takeoffs[mid]

    def estimated_arrival(self, member_id: int) -> int | None:
        entry = self._takeoffs.get(member_id)
        if not entry:
            return None
        minutes = STANDARD_TRAVEL_MINUTES.get(entry["destination"])
        if minutes is None:
            return None
        return int(entry["t"] + minutes * 60)
