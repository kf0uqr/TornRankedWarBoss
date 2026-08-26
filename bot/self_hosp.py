"""Self-hospitalize reminders for our own faction during an active war.

If a member has been offline 30+ minutes AND is in hospital with 5 minutes
or less left on the clock, they're about to walk out exposed with no chance
to protect their respect - self-hospitalizing (an item, a friendly hit, etc.)
resets the clock and denies the enemy free score. This flags them so a
teammate (or the member themself, if they check their phone) can catch it in
time.

Repeats up to MAX_ALERTS_PER_EPISODE times for the same hospitalization,
tracked by (member_id, the hospital's own "until" timestamp) so a fresh
hospitalization always starts its own count - stops once they come back
online, their hospital time changes (released, or a new stay), or the cap
is hit, whichever's first. In-memory only, like the other trackers here -
resets on a bot restart.
"""

import time

OFFLINE_THRESHOLD_SECONDS = 30 * 60
RELEASE_WARNING_SECONDS = 5 * 60
MAX_ALERTS_PER_EPISODE = 3


class SelfHospAlertTracker:
    def __init__(self):
        self._alert_counts: dict[tuple[int, int], int] = {}

    def check(self, members: list[dict], now: float | None = None) -> list[dict]:
        """Returns the members due an alert on this poll."""
        now = now if now is not None else time.time()
        due = []
        live_episodes = set()

        for m in members:
            status = m["status"]
            until = status.get("until")
            if status.get("state") != "Hospital" or not until:
                continue

            episode = (m["id"], until)
            live_episodes.add(episode)

            seconds_left = until - now
            if seconds_left <= 0 or seconds_left > RELEASE_WARNING_SECONDS:
                continue

            last_action = m["last_action"]
            offline_seconds = now - last_action["timestamp"]
            if last_action["status"] != "Offline" or offline_seconds < OFFLINE_THRESHOLD_SECONDS:
                continue

            count = self._alert_counts.get(episode, 0)
            if count >= MAX_ALERTS_PER_EPISODE:
                continue

            self._alert_counts[episode] = count + 1
            due.append(m)

        # Drop episodes no longer live (released, or re-hospitalized with a
        # different "until") so this doesn't grow unbounded over a long-running bot.
        for episode in list(self._alert_counts):
            if episode not in live_episodes:
                del self._alert_counts[episode]

        return due
