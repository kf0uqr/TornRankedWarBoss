"""Thin client for Torn's API v2 (https://www.torn.com/swagger/index.html)."""

import threading
import time
from collections import deque

import httpx

BASE_URL = "https://api.torn.com/v2"

# Torn's own limit is 100 requests/minute; we cap ourselves below that so a single
# sync (which can fire dozens of calls) doesn't run the account into Torn's own
# rate limit. Shared across every TornClient instance, since a new client is
# created per request but the underlying account-wide budget is the same one.
RATE_LIMIT_MAX_REQUESTS = 75
RATE_LIMIT_WINDOW_SECONDS = 60.0


class TornAPIError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(f"Torn API error [{code}]: {message}")


class TornRateLimitError(Exception):
    """Raised when our own outgoing request budget (not Torn's) is exhausted."""

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

    def acquire(self):
        with self._lock:
            now = time.monotonic()
            while self._timestamps and now - self._timestamps[0] > self.window_seconds:
                self._timestamps.popleft()
            if self._timestamps and len(self._timestamps) >= self.max_requests:
                retry_after = self.window_seconds - (now - self._timestamps[0])
                raise TornRateLimitError(max(retry_after, 1.0))
            self._timestamps.append(now)


_rate_limiter = _RateLimiter(RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)


class TornClient:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("Torn API key is required")
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"ApiKey {api_key}"},
            timeout=15,
        )

    def get(self, path: str, params: dict | None = None) -> dict:
        _rate_limiter.acquire()
        response = self._client.get(path, params=params or {})
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise TornAPIError(data["error"]["code"], data["error"]["error"])
        return data

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

    # --- Torn endpoints ---

    def torn_items(self, category: str | None = None) -> list[dict]:
        params = {"cat": category} if category else {}
        data = self.get("/torn/items", params)
        return data["items"]
