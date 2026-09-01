"""Automatic pay_rank progression for the non-leadership member ladder.

The ladder, as specified:
  Audit Bait      - default for everyone else; also where anyone missing
                     Discord (or level) lands regardless of past rank
  Petty Launderer - level 15+, linked a Discord account; also where anyone
                     missing an API key lands regardless of past rank
  Ledger Keeper   - Petty Launderer requirements + 10+ hits in the war being
                     synced + we have a pooled API key for them
  Failed Audit    - specifically "would still be Ledger Keeper except for
                     the hit count" - was Ledger Keeper (their live Torn
                     position), still has Discord + a key, just didn't make
                     the 10-hit bar this war. Missing Discord or a key is
                     NOT a Failed Audit - it drops straight through to
                     Audit Bait/Petty Launderer instead, on purpose: the
                     whole point is to push them toward fixing whichever's
                     actually missing (mostly the key - only about half the
                     faction has contributed one) rather than resting on a
                     rank they no longer fully qualify for.
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
    if not petty_launderer_eligible:
        return "Audit Bait"

    if war_hits >= 10 and has_key:
        return "Ledger Keeper"

    # Reaches here with level+Discord satisfied but not (hits + key) both -
    # Failed Audit only if the ONE thing missing is the hit count (they do
    # have a key) and they currently hold Ledger Keeper. Missing the key
    # itself skips straight to Petty Launderer, no matter what rank they
    # held before.
    if has_key and war_hits < 10 and was_ledger_keeper:
        return "Failed Audit"

    return "Petty Launderer"
