"""Thin Apify REST client. One place for auth, timeouts and item paging."""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from ci.logging import get_logger, log_event

log = get_logger(__name__)
BASE = "https://api.apify.com/v2"


class ApifyError(RuntimeError):
    pass


class ApifyThrottled(ApifyError):
    """The actor returned a no-results sentinel rather than failing.

    Verified 2026-09-10: the same keyword and input that returned 10 real videos
    returned `[{"noResults": true}]` eight minutes later. The free tier throttles
    after roughly five or six search calls and says nothing about it.

    This matters more than it sounds. Without detecting it, a throttled run
    quietly records "this competitor has no UGC today" as a fact, and that wrong
    zero then poisons the learned baseline and every trend line built on it.
    """


class ApifyClient:
    def __init__(self, token: str, timeout: float = 300.0,
                 throttle_after: int = 3, pace_seconds: float = 0.0) -> None:
        if not token:
            raise ApifyError("APIFY_TOKEN is not set")
        self.token = token
        self.timeout = timeout
        self.throttle_after = throttle_after
        self.pace_seconds = pace_seconds
        self.consecutive_empty = 0
        self._last_call = 0.0

    def run_actor(self, actor: str, run_input: dict[str, Any], max_items: int | None = None) -> list[dict]:
        """Run an actor to completion and return its dataset items."""
        actor_path = actor.replace("/", "~")
        params: dict[str, Any] = {"token": self.token}
        if max_items:
            params["maxItems"] = max_items
        if self.pace_seconds:
            elapsed = time.monotonic() - self._last_call
            if self._last_call and elapsed < self.pace_seconds:
                time.sleep(self.pace_seconds - elapsed)
        self._last_call = time.monotonic()
        log_event(log, logging.INFO, "apify run starting", actor=actor, max_items=max_items)
        resp = httpx.post(
            f"{BASE}/acts/{actor_path}/run-sync-get-dataset-items",
            params=params,
            json=run_input,
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise ApifyError(f"{actor} returned {resp.status_code}: {resp.text[:400]}")
        items = resp.json()
        if not isinstance(items, list):
            raise ApifyError(f"{actor} returned an unexpected payload: {type(items).__name__}")

        # Strip the sentinel rows and decide whether this was a real empty result
        # or a silent failure dressed up as success.
        real = [i for i in items if isinstance(i, dict) and not i.get("noResults")]
        sentinels = len(items) - len(real)

        # Two different shapes of nothing, both of which used to read as fact.
        #
        #   [{"noResults": true}]  the free-tier search throttle
        #   []                     an exhausted account balance
        #
        # Verified 2026-09-15 with $0.000923 of credit left: a pay-per-result
        # actor still reports status SUCCEEDED and "Scraped 3/3 search queries",
        # and simply returns an empty dataset. The same keyword had returned 15
        # videos four days earlier. Only the sentinel case was caught, so a run
        # with no money left recorded "this competitor has no UGC today" for every
        # keyword, and that wrong zero then poisons the learned baseline and every
        # trend line built on it.
        #
        # One empty result is ordinary. Several in a row is not a quiet niche.
        if not real:
            self.consecutive_empty += 1
            log_event(log, logging.WARNING,
                      "apify returned nothing",
                      actor=actor, shape="sentinel" if sentinels else "empty dataset",
                      consecutive_empty=self.consecutive_empty)
            if self.consecutive_empty >= self.throttle_after:
                cause = ("throttling" if sentinels
                         else "an exhausted account balance or a blocked actor")
                raise ApifyThrottled(
                    f"{actor} returned no results {self.consecutive_empty} times in a row. "
                    f"This is almost certainly {cause}, not an empty niche. "
                    "Treat these keywords as NOT CHECKED rather than as zero."
                )
        else:
            self.consecutive_empty = 0

        log_event(log, logging.INFO, "apify run finished", actor=actor,
                  items=len(real), sentinels=sentinels)
        return real
