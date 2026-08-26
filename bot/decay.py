"""War decay / catch-up math for the /current_war board - ported from a
faction leader's own Tampermonkey script ("Torn WarDecay Timer"). Torn's
ranked-war target score starts decaying 1%/hour (of its original, pre-decay
value) 24 hours into the war; the catch-up-rate and max-payout numbers below
are community-observed rules, not documented by Torn, so treat them as
estimates rather than guaranteed thresholds.
"""

import time

DECAY_START_HOURS = 24
MIN_HISTORY_MINUTES = 15
HISTORY_MAX_AGE_SECONDS = 3 * 60 * 60


def compute_original_target(current_target: float, elapsed_hours: float) -> float:
    """Back-calculates the war's pre-decay target from the currently
    displayed (possibly already-decayed) target."""
    decayed_hours = max(0.0, elapsed_hours - DECAY_START_HOURS)
    if decayed_hours <= 0:
        return current_target
    if decayed_hours >= 100:
        return current_target if current_target > 0 else 1
    return current_target / (1 - decayed_hours / 100)


def compute_seconds_remaining(current_target: float, current_score: float, elapsed_hours: float) -> float | None:
    """Seconds until the decaying target falls to this side's current score -
    the point at which decay alone would end the war in their favor if
    neither side's score moves again."""
    original_target = compute_original_target(current_target, elapsed_hours)
    decay_rate_per_hour = original_target / 100
    if decay_rate_per_hour <= 0:
        return None

    remaining_gap = current_target - current_score
    if remaining_gap <= 0:
        return 0.0

    decayed_hours = max(0.0, elapsed_hours - DECAY_START_HOURS)
    if decayed_hours <= 0:
        hours_until_decay_starts = DECAY_START_HOURS - elapsed_hours
        hours_decaying_after_start = remaining_gap / decay_rate_per_hour
        hours_until_gap_closes = hours_until_decay_starts + hours_decaying_after_start
    else:
        hours_until_gap_closes = remaining_gap / decay_rate_per_hour

    return hours_until_gap_closes * 3600


class ScoreHistory:
    """Rolling per-war score samples for computing each side's observed
    score/hour pace. In-memory per bot process, keyed to the active war id -
    if the bot restarts mid-war, this just starts over and the catch-up rate
    shows "gathering data" again until enough samples build back up, same as
    the original script's cold-start behavior."""

    def __init__(self):
        self.war_id: int | None = None
        self.samples: list[dict] = []

    def record(self, war_id: int, own_score: float, opp_score: float) -> None:
        if war_id != self.war_id:
            self.war_id = war_id
            self.samples = []
        now = time.time()
        self.samples.append({"t": now, "own": own_score, "opp": opp_score})
        self.samples = [s for s in self.samples if now - s["t"] <= HISTORY_MAX_AGE_SECONDS]

    def observed_rate_per_hour(self, slot: str) -> float | None:
        if len(self.samples) < 2:
            return None
        now = time.time()
        newest = self.samples[-1]
        oldest = None
        for sample in self.samples:
            if (now - sample["t"]) / 60 >= MIN_HISTORY_MINUTES:
                oldest = sample
            else:
                break
        if oldest is None:
            return None
        hours_span = (newest["t"] - oldest["t"]) / 3600
        if hours_span <= 0:
            return None
        return (newest[slot] - oldest[slot]) / hours_span
