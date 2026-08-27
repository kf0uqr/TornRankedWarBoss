"""Duration parsing for /new_giveaway - "1h30m", "2d", "45s", "1d 2h" etc."""

import re

_UNIT_SECONDS = {"d": 86400, "h": 3600, "m": 60, "s": 1}
_PART_RE = re.compile(r"(\d+)\s*([dhms])", re.IGNORECASE)

MIN_SECONDS = 10
MAX_SECONDS = 30 * 86400


def parse_duration(text: str) -> int | None:
    """"1h30m" -> 5400. Returns None if the text doesn't parse to at least
    one recognized part, or the total is outside [MIN_SECONDS, MAX_SECONDS]."""
    text = text.strip()
    if not text:
        return None
    parts = _PART_RE.findall(text)
    if not parts:
        return None
    # Reject leftover text the regex didn't consume (e.g. "1x", "soon") -
    # rebuilding from the matches and comparing length catches that cheaply.
    consumed = sum(len(n) + len(u) for n, u in parts)
    if consumed < len(text.replace(" ", "")):
        return None

    total = sum(int(n) * _UNIT_SECONDS[u.lower()] for n, u in parts)
    if total < MIN_SECONDS or total > MAX_SECONDS:
        return None
    return total
