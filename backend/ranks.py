"""Automatic pay_rank progression for the non-leadership member ladder.

The ladder, as specified:
  Audit Bait      - default for everyone else
  Petty Launderer - level 15+, linked a Discord account
  Ledger Keeper   - Petty Launderer requirements + 10+ hits in the war being
                     synced + we have a pooled API key for them
  Failed Audit    - was Ledger Keeper (their live Torn position) but didn't
                     make the 10-hit bar in the war being synced
  Kingpin         - the war's single best non-leadership performer, per the
                     same overall_rank stats.rank_members() already computes

Leadership (Leader/Co-Leader/Chief Evasion Officer) is never touched by this
- sync.py checks that via stats._is_leadership(position) before ever calling
compute_eligible_rank below.
"""

import httpx

from backend import db
from backend.torn_api import TornAPIError, TornClient


def get_member_ids_with_keys() -> set[int]:
    """Which members we currently hold a pooled API key for - checked one
    key at a time (each self-identifies via the personal-only /user
    endpoint, same rule as bars/battlestats/display), not round-robined."""
    ids: set[int] = set()
    for key in db.get_api_keys():
        try:
            ids.add(TornClient([key]).user_id())
        except (TornAPIError, httpx.HTTPError):
            continue
    return ids


def compute_eligible_rank(
    is_kingpin: bool,
    level: int | None,
    has_discord: bool,
    war_hits: int,
    has_key: bool,
    was_ledger_keeper: bool,
) -> str:
    if is_kingpin:
        return "Kingpin"

    petty_launderer_eligible = (level or 0) >= 15 and has_discord
    ledger_keeper_eligible = petty_launderer_eligible and war_hits >= 10 and has_key

    if ledger_keeper_eligible:
        return "Ledger Keeper"
    if was_ledger_keeper:
        return "Failed Audit"
    if petty_launderer_eligible:
        return "Petty Launderer"
    return "Audit Bait"
