"""Thin client for Torn's API v2 (https://www.torn.com/swagger/index.html)."""

import threading
import time
from collections import deque

import httpx

BASE_URL = "https://api.torn.com/v2"

# Torn's own limit is 100 requests/minute PER KEY; we cap each key we use below
# that so a single sync (which can fire dozens of calls) doesn't run it into
# Torn's own rate limit. Pooling multiple players' keys multiplies the app's
# effective budget, since each key's 100/min allowance is independent.
RATE_LIMIT_MAX_REQUESTS = 50
RATE_LIMIT_WINDOW_SECONDS = 60.0


class TornAPIError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(f"Torn API error [{code}]: {message}")


class TornRateLimitError(Exception):
    """Raised when every pooled key's own outgoing request budget (not Torn's
    account-level state) is exhausted."""

    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"Torn API request budget exhausted, retry after {retry_after:.0f}s")


class _RateLimiter:
    """Sliding-window limiter: at most `max_requests` calls in any `window_seconds`."""

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def try_acquire(self) -> tuple[bool, float]:
        """Returns (True, 0) and reserves a slot if one's available right now,
        else (False, seconds_until_one_frees_up) without reserving anything."""
        with self._lock:
            now = time.monotonic()
            while self._timestamps and now - self._timestamps[0] > self.window_seconds:
                self._timestamps.popleft()
            if self._timestamps and len(self._timestamps) >= self.max_requests:
                retry_after = self.window_seconds - (now - self._timestamps[0])
                return False, max(retry_after, 1.0)
            self._timestamps.append(now)
            return True, 0.0


# Per-key limiter state, keyed by the key string itself so it survives across
# the many short-lived TornClient instances this app creates (one per request),
# and a round-robin cursor so load spreads evenly across the pool over time -
# both need to be process-wide, not per-instance, to mean anything.
_key_limiters: dict[str, _RateLimiter] = {}
_key_limiters_lock = threading.Lock()
_pool_cursor = 0
_pool_cursor_lock = threading.Lock()


def _limiter_for_key(api_key: str) -> _RateLimiter:
    with _key_limiters_lock:
        if api_key not in _key_limiters:
            _key_limiters[api_key] = _RateLimiter(RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)
        return _key_limiters[api_key]


def _pick_key(api_keys: list[str]) -> str:
    """Round-robins through api_keys, returning the next one with budget to
    spare. Raises TornRateLimitError with the shortest wait if all are tapped."""
    global _pool_cursor
    with _pool_cursor_lock:
        start = _pool_cursor
        waits = []
        for i in range(len(api_keys)):
            idx = (start + i) % len(api_keys)
            ok, wait = _limiter_for_key(api_keys[idx]).try_acquire()
            if ok:
                _pool_cursor = (idx + 1) % len(api_keys)
                return api_keys[idx]
            waits.append(wait)
        raise TornRateLimitError(min(waits))


class TornClient:
    def __init__(self, api_keys: list[str]):
        if not api_keys:
            raise ValueError("At least one Torn API key is required")
        self._api_keys = api_keys
        self._client = httpx.Client(base_url=BASE_URL, timeout=15)

    def get(self, path: str, params: dict | None = None) -> dict:
        last_error = None
        # Retries with the next pooled key on ANY Torn API error, bounded to
        # the pool size. Torn reuses error codes inconsistently across
        # endpoints - e.g. a key missing a selection can come back as
        # "Incorrect ID-entity relation" (code 7), which reads like a bad
        # request rather than a key problem - so a curated "these codes are
        # key-specific" list turned out to be unreliable in practice. Worst
        # case for a genuinely request-level error (bad ID, wrong fields):
        # every key reproduces the same error and this still raises it
        # correctly, just after a few wasted calls instead of one.
        for _ in range(len(self._api_keys)):
            key = _pick_key(self._api_keys)
            response = self._client.get(path, params=params or {}, headers={"Authorization": f"ApiKey {key}"})
            response.raise_for_status()
            data = response.json()
            if "error" not in data:
                return data

            error = TornAPIError(data["error"]["code"], data["error"]["error"])
            print(f"Torn API error for {path} ({error}) - retrying with another pooled key.")
            last_error = error
        raise last_error

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- Faction endpoints ---

    def faction_rankedwars(self, faction_id: int, limit: int = 20, offset: int = 0) -> list[dict]:
        data = self.get(f"/faction/{faction_id}/rankedwars", {"limit": limit, "offset": offset})
        return data["rankedwars"]

    def faction_rankedwarreport(self, ranked_war_id: int) -> dict:
        data = self.get(f"/faction/{ranked_war_id}/rankedwarreport")
        return data["rankedwarreport"]

    def faction_chains(self, faction_id: int, from_ts: int, to_ts: int, limit: int = 100) -> list[dict]:
        data = self.get(f"/faction/{faction_id}/chains", {"from": from_ts, "to": to_ts, "limit": limit})
        return data["chains"]

    def faction_chainreport(self, chain_id: int) -> dict:
        data = self.get(f"/faction/{chain_id}/chainreport")
        return data["chainreport"]

    def faction_members(self, faction_id: int) -> list[dict]:
        data = self.get(f"/faction/{faction_id}/members")
        return data["members"]

    def faction_inventory(self, category: str) -> list[dict]:
        data = self.get("/faction/inventory", {"cat": category})
        return data["inventory"]

    def faction_news(self, category: str, from_ts: int, to_ts: int) -> list[dict]:
        """Fetches every news entry in [from_ts, to_ts] for the given category, paginating as needed."""
        results = []
        seen_ids = set()
        cursor_from = from_ts
        while True:
            data = self.get(
                "/faction/news",
                {
                    "cat": category,
                    "from": cursor_from,
                    "to": to_ts,
                    "sort": "ASC",
                    "limit": 100,
                    "striptags": "false",
                },
            )
            items = data["news"]
            new_items = [i for i in items if i["id"] not in seen_ids]
            if not new_items:
                break
            seen_ids.update(i["id"] for i in new_items)
            results.extend(new_items)
            if len(items) < 100:
                break
            cursor_from = max(i["timestamp"] for i in items)
        return results

    def faction_attacks(self, direction: str, from_ts: int, to_ts: int) -> list[dict]:
        """Fetches every attack in [from_ts, to_ts] in the given direction (incoming/outgoing), paginating as needed."""
        results = []
        seen_ids = set()
        cursor_from = from_ts
        while True:
            data = self.get(
                "/faction/attacks",
                {
                    "filters": direction,
                    "from": cursor_from,
                    "to": to_ts,
                    "sort": "ASC",
                    "limit": 100,
                },
            )
            items = data["attacks"]
            new_items = [i for i in items if i["id"] not in seen_ids]
            if not new_items:
                break
            seen_ids.update(i["id"] for i in new_items)
            results.extend(new_items)
            if len(items) < 100:
                break
            cursor_from = max(i["started"] for i in items)
        return results

    # --- User endpoints ---

    def user_profile(self, user_id: int) -> dict:
        return self.get(f"/user/{user_id}", {"selections": "profile"})["profile"]

    def user_bars_battlestats_profile(self) -> dict:
        """bars/battlestats are only ever the calling key's own account, no
        matter whose ID you pass (Torn won't return another player's) - so
        this is meant to be called on a single-key TornClient([key]) built
        from a specific member's own contributed key, one member at a time.
        Returns {"bars": {...}, "battlestats": {...}, "profile": {...}}."""
        return self.get("/user", {"selections": "bars,battlestats,profile"})

    # --- Torn endpoints ---

    def torn_items(self, category: str | None = None) -> list[dict]:
        params = {"cat": category} if category else {}
        data = self.get("/torn/items", params)
        return data["items"]
