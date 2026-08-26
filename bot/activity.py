"""Builds per-poll activity observations for the enemy roster.

Every /current_war refresh (every 5 minutes), each enemy member's Torn
last_action.status ("Online"/"Idle"/"Offline") is sampled and logged against
the current UTC hour (Torn's own clock) via /api/activity-observations. Over
time this builds an empirical "percent of observed polls this member was
active at hour H" per member, shown as a heatmap table.

"Active" here means strictly last_action.status == "Online" - "Idle" (logged
in but away) is treated as not-active, since the practical question this
answers is "are they actually at the keyboard right now."

Unlike travel, there's no state to track here (no takeoff/landing) - just
log the raw observation every poll and let the backend aggregate it.
"""

import time

# Below this many observed polls for a member+hour, the heatmap shows "-"
# instead of a percentage - too few samples to mean much.
MIN_OBSERVED_SAMPLES = 5


def build_observations(members: list[dict], now: float | None = None) -> list[dict]:
    now = now if now is not None else time.time()
    hour_of_day = time.gmtime(now).tm_hour
    return [
        {
            "member_id": m["id"],
            "member_name": m.get("name"),
            "hour_of_day": hour_of_day,
            "is_active": m["last_action"]["status"] == "Online",
            "observed_at": int(now),
        }
        for m in members
    ]
