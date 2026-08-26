"""Reminds our own members with revives enabled to turn them off before a
ranked war starts.

First alert fires once we're within PRE_WAR_LEAD_SECONDS of the war's start
(Torn lists a declared-but-not-yet-started war the same way as an active one,
so this can trigger before the war actually begins), then repeats every
REPEAT_INTERVAL_SECONDS per member for as long as they still have revives
enabled - stopping the moment they turn it off. Keeps firing on the same
schedule after the war has started too; the message text is the caller's
job to vary based on whether `now >= war_start`.

In-memory only, like the other trackers here - resets on a bot restart.
"""

import time

PRE_WAR_LEAD_SECONDS = 5 * 3600
REPEAT_INTERVAL_SECONDS = 4 * 3600


class RevivesReminderTracker:
    def __init__(self):
        self._next_alert_at: dict[tuple[int, int], float] = {}  # (war_id, member_id) -> epoch

    def check(self, war_id: int, war_start: int, members: list[dict], now: float | None = None) -> list[dict]:
        now = now if now is not None else time.time()
        window_start = war_start - PRE_WAR_LEAD_SECONDS
        if now < window_start:
            return []

        due = []
        for m in members:
            key = (war_id, m["id"])
            if not m.get("is_revivable"):
                # Fixed it - drop any tracked state so re-enabling later starts fresh.
                self._next_alert_at.pop(key, None)
                continue

            next_at = self._next_alert_at.get(key, window_start)
            if now >= next_at:
                due.append(m)
                self._next_alert_at[key] = now + REPEAT_INTERVAL_SECONDS

        return due
