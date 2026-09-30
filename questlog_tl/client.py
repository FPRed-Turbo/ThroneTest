"""Minimal, polite HTTP client for questlog.gg's Throne and Liberty tRPC API."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://questlog.gg/throne-and-liberty/api/trpc"
USER_AGENT = "ThroneTest-questlog-collector/0.1 (personal build research)"


class ApiError(RuntimeError):
    pass


class QuestlogClient:
    """Calls tRPC query procedures, e.g. ``call("database.getItems", {...})``.

    Requests are throttled globally (``min_interval`` seconds between request
    starts, across threads) and retried with exponential backoff.
    """

    def __init__(self, base_url: str = BASE_URL, min_interval: float = 0.25,
                 retries: int = 5, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.min_interval = min_interval
        self.retries = retries
        self.timeout = timeout
        self._lock = threading.Lock()
        self._next_slot = 0.0

    def _throttle(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + self.min_interval
        if wait > 0:
            time.sleep(wait)

    def call(self, procedure: str, params: dict | None = None):
        query = urllib.parse.urlencode({"input": json.dumps(params or {}, separators=(",", ":"))})
        url = f"{self.base_url}/{procedure}?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        delay = 2.0
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.load(resp)
                # tRPC omits "data" when a procedure returns nothing (e.g. an empty build).
                return payload.get("result", {}).get("data")
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")
                # 4xx other than 429 means bad input / unknown id: do not retry.
                if 400 <= e.code < 500 and e.code != 429:
                    raise ApiError(f"{procedure} {params}: HTTP {e.code}: {body[:300]}") from e
                err = e
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
                err = e
            if attempt < self.retries:
                time.sleep(delay)
                delay *= 2
        raise ApiError(f"{procedure} {params}: giving up after {self.retries + 1} attempts: {err}")
