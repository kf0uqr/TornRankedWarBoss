"""Estimates when a traveling enemy will land, and logs each completed
flight it actually observes so the estimate can improve over time.

Torn's API doesn't give an exact arrival time for other players, but
/current_war refreshes regularly - so when a member's status flips from
something else to "Traveling" between two consecutive refreshes, that
tells us their takeoff time accurate to within one refresh interval. Estimated
arrival = takeoff + a travel duration for their destination: the standard
duration, or 70% of it if they own a Private Island (private jet access) -
backend/routes/wars.py looks that up via /user/{id}?selections=profile for
anyone currently traveling. This still can't account for WLT, Business
Class, or the Airstrip faction perk, which also shorten real travel time, so
treat it as an upper bound, not a guarantee - and anyone already traveling
when the bot starts (or before their first observed takeoff) has no
estimate at all, since we never saw them leave.

When a tracked member's status later flips back off "Traveling", that's a
completed flight - record() returns it (member/destination/PI/actual
duration) so the caller can POST it to /api/travel-observations. Once
enough observed flights pile up for a destination+PI combination, discord_bot.py
fetches the averages back from /api/travel-observations/estimates and passes
them into estimated_arrival() as overrides, so real observed durations
gradually replace the hardcoded standard-time table.
"""

import time

# One-way standard (non-boosted) travel durations, in minutes - the same for
# every player without a speed perk. Used until enough real observations
# exist for a destination (see MIN_OBSERVED_SAMPLES).
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

# Private Island grants private jet access, cutting travel time to 70% of standard.
PRIVATE_ISLAND_MULTIPLIER = 0.70

# Below this many observed flights for a destination+PI combo, the hardcoded
# standard time is still trusted more than the (noisy, small-sample) average.
MIN_OBSERVED_SAMPLES = 3


def _parse_travel_country(description: str) -> str | None:
    """Returns whichever leg of the trip is the foreign country, regardless of
    direction - travel duration is symmetric, so "Traveling from Torn to
    Mexico" and "Traveling from Mexico to Torn" (the return leg) both take
    Mexico's standard duration. Also handles "Traveling to X" (destination
    only, no explicit origin)."""
    if " to " not in description:
        return None
    origin, destination = description.split(" to ", 1)
    origin = origin.removeprefix("Traveling from ").strip()
    destination = destination.strip()
    if destination != "Torn":
        return destination
    return origin if origin and origin != "Torn" else None


def resolve_minutes(destination: str, has_private_island: bool, overrides: dict | None = None) -> float | None:
    """overrides: the shape returned by GET /api/travel-observations/estimates,
    e.g. {"South Africa": {"standard": {"avg_minutes": 289.4, "sample_count": 12}, ...}}"""
    if overrides:
        entry = overrides.get(destination, {}).get("private_island" if has_private_island else "standard")
        if entry and entry["sample_count"] >= MIN_OBSERVED_SAMPLES:
            return entry["avg_minutes"]

    minutes = STANDARD_TRAVEL_MINUTES.get(destination)
    if minutes is None:
        return None
    return minutes * PRIVATE_ISLAND_MULTIPLIER if has_private_island else minutes


class TravelTracker:
    """Per-war, in-memory only - like bot/decay.py's ScoreHistory, this just
    starts over on a bot restart rather than persisting anything itself
    (completed flights are persisted server-side as record() returns them)."""

    def __init__(self):
        self.war_id: int | None = None
        self._takeoffs: dict[int, dict] = {}  # member_id -> {"t", "name", "destination", "has_private_island"}
        self._last_description: dict[int, str] = {}

    def record(self, war_id: int, members: list[dict]) -> list[dict]:
        """members: each needs "id", "name", "status" (with "description"),
        and optionally "has_private_island" - only checked at the moment a
        takeoff is first observed, so a later property change won't
        retroactively affect an already-in-progress flight's estimate.

        Returns completed-flight observations (landings detected this call):
        [{"member_id", "member_name", "destination", "has_private_island",
          "takeoff_at", "landing_at"}, ...] - ready to POST as-is to
        /api/travel-observations."""
        if war_id != self.war_id:
            self.war_id = war_id
            self._takeoffs = {}
            self._last_description = {}

        now = time.time()
        completed = []
        seen_ids = set()
        for m in members:
            mid = m["id"]
            seen_ids.add(mid)
            description = m["status"].get("description") or ""
            previously_seen = mid in self._last_description
            was_traveling = self._last_description.get(mid, "").startswith("Traveling")
            is_traveling = description.startswith("Traveling")

            # Only counts as an observed takeoff if we'd already seen this
            # member NOT traveling on a prior poll - otherwise (e.g. right
            # after a bot restart, or their first appearance on the roster)
            # we don't actually know when they left, so no estimate at all
            # beats a confidently wrong one anchored to "just now".
            if is_traveling and previously_seen and not was_traveling:
                country = _parse_travel_country(description)
                if country:
                    self._takeoffs[mid] = {
                        "t": now,
                        "name": m.get("name"),
                        "destination": country,
                        "has_private_island": bool(m.get("has_private_island")),
                    }
            elif not is_traveling and mid in self._takeoffs:
                entry = self._takeoffs.pop(mid)
                completed.append(
                    {
                        "member_id": mid,
                        "member_name": entry["name"],
                        "destination": entry["destination"],
                        "has_private_island": entry["has_private_island"],
                        "takeoff_at": int(entry["t"]),
                        "landing_at": int(now),
                    }
                )

            self._last_description[mid] = description

        for mid in list(self._takeoffs):
            if mid not in seen_ids:
                del self._takeoffs[mid]

        return completed

    def estimated_arrival(self, member_id: int, overrides: dict | None = None) -> int | None:
        entry = self._takeoffs.get(member_id)
        if not entry:
            return None
        minutes = resolve_minutes(entry["destination"], entry["has_private_island"], overrides)
        if minutes is None:
            return None
        return int(entry["t"] + minutes * 60)

    def has_private_island(self, member_id: int) -> bool:
        entry = self._takeoffs.get(member_id)
        return bool(entry and entry["has_private_island"])
