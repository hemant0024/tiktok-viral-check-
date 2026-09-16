"""Organic UGC about our competitors.

Creator videos that mention or show a competitor app. These are where the next
competitor ad comes from: brands watch what performs organically, then pay to
boost it. Catching one on the way up means seeing their next ad weeks early.

Discovery is by brand KEYWORD, not by handle, because the people making these
videos do not follow the brand. They just name the app.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from ci.collectors.apify import ApifyClient, ApifyError, ApifyThrottled
from ci.collectors.tiktok import TikTokCollector
from ci.config import Settings, get_settings
from ci.logging import get_logger, log_event
from ci.models import NormalizedContent

log = get_logger(__name__)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())


def _mentions(blob: str, term: str) -> bool:
    """Whole-word match, not substring.

    Plain `in` made "praktika" match the Malay word "praktikal" (internship),
    so #TamatPraktikal and #cikgupraktikal landed on the Praktika feed. Short
    brand names collide with ordinary words in other languages constantly, and a
    keyword radar that cannot tell them apart reports noise as competitor signal.
    """
    term = _norm(term).strip()
    if not term:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", blob) is not None


def build_actor_input(spec: dict[str, Any], *, keywords: list[str] | None = None,
                      urls: list[str] | None = None, max_items: int = 15,
                      country: str = "US") -> dict[str, Any]:
    """Fill an actor's input template.

    The two TikTok actors want different field names for the same three ideas:
    which keywords, how many results, which country. Hardcoding one actor's
    names is what makes swapping actors a code change instead of a config change,
    and it is why the fallback could not exist before.
    """
    out: dict[str, Any] = {}
    for key, value in (spec or {}).items():
        if value == "$KEYWORDS":
            out[key] = keywords or []
        elif value == "$URLS":
            out[key] = urls or []
        elif value == "$MAX":
            out[key] = max_items
        elif value == "$COUNTRY":
            out[key] = country
        else:
            out[key] = value
    return out



class CompetitorUgcCollector:
    name = "competitor_ugc"

    def __init__(self, settings: Settings | None = None, client: ApifyClient | None = None) -> None:
        self.settings = settings or get_settings()
        self.cfg = self.settings.sources.get("competitor_ugc", {})
        self.tiktok_cfg = self.settings.sources.get("tiktok", {})
        self.enabled = bool(self.cfg.get("enabled", True))
        self._client = client
        self._tt = TikTokCollector(settings, client=client)
        # Keywords we could not check this run. NOT the same as keywords with no
        # results, and the report must never conflate the two.
        self.not_checked: list[str] = []
        self.brand_owned_dropped = 0
        self.too_long_dropped = 0
        # Which actor actually produced this run. The cheap one is paid-only, so
        # a run can silently cost 23x more than expected without this on the record.
        self.actor_used = ""
        self.fell_back = False

    def competitors(self) -> list[dict[str, Any]]:
        out = []
        for group in ("competitors", "adjacent"):
            out.extend(self.settings.competitors.get(group, []) or [])
        return out

    def brand_handles(self) -> set[str]:
        """Every handle owned by a competitor, lowercased.

        We track videos and hooks, not accounts. A brand posting on its own
        account is marketing; it is not a signal that anything is spreading.
        """
        handles = set()
        for comp in self.competitors():
            for key in ("tiktok", "instagram"):
                handle = (comp.get(key) or "").strip().lower().lstrip("@")
                if handle:
                    handles.add(handle)
            name = (comp.get("name") or "").lower().replace(" ", "")
            if name:
                handles.add(name)
        return handles

    def describe(self) -> dict[str, Any]:
        comps = self.competitors()
        return {
            "source": self.name,
            "brand_handles_excluded": len(self.brand_handles()),
            "enabled": self.enabled,
            "competitors": len(comps),
            "keywords": sum(len(c.get("keywords", [])) for c in comps),
            "keywords_per_run": self.cfg.get("keywords_per_run"),
            "actor": self.tiktok_cfg.get("actor"),
            "token_present": bool(self.settings.apify_token),
        }

    def client(self) -> ApifyClient:
        if self._client is None:
            self._client = ApifyClient(
                self.settings.apify_token or "",
                throttle_after=int(self.cfg.get("throttle_after", 3)),
                pace_seconds=float(self.cfg.get("pace_seconds", 3.0)),
            )
        return self._client

    def keyword_plan(self, day_index: int | None = None) -> list[tuple[str, str]]:
        """(keyword, competitor_name) pairs.

        `keywords_per_run: 0` means every keyword, every day, which is the only
        setting consistent with the point of this system. Rotating competitors
        across a week saves money and loses the thing being paid for: a video
        peaks inside 24 to 48 hours, so a competitor checked on Tuesday and next
        checked on Friday is a competitor whose breakout you read about after it
        is over. Worse, a competitor that was never checked looks exactly like a
        competitor that had nothing.

        A non-zero cap keeps the old rotation, for when the Apify plan is the
        binding constraint and partial coverage beats none.
        """
        per_run = int(self.cfg.get("keywords_per_run", 0) or 0)
        comps = self.competitors()
        if per_run <= 0:
            return [(kw, c.get("name", ""))
                    for c in comps for kw in c.get("keywords", [])]
        idx = day_index if day_index is not None else datetime.now(timezone.utc).timetuple().tm_yday
        rotated = comps[idx % len(comps):] + comps[: idx % len(comps)] if comps else []
        pairs: list[tuple[str, str]] = []
        # One keyword per competitor per pass, so every brand is covered before
        # any brand gets a second keyword.
        depth = 0
        while len(pairs) < per_run and rotated:
            added = False
            for comp in rotated:
                kws = comp.get("keywords", [])
                if depth < len(kws):
                    pairs.append((kws[depth], comp.get("name", "")))
                    added = True
                    if len(pairs) >= per_run:
                        break
            if not added:
                break
            depth += 1
        return pairs

    def attribute(self, content: NormalizedContent) -> str:
        """Which competitor is this video actually about?"""
        blob = _norm(f"{content.title} {content.description} {' '.join(content.hashtags)}")
        squashed = blob.replace(" ", "")
        best, best_len = "", 0
        for comp in self.competitors():
            for kw in comp.get("keywords", []):
                k = _norm(kw).strip()
                if k and _mentions(blob, k) and len(k) > best_len:
                    best, best_len = comp.get("name", ""), len(k)
            for tag in comp.get("hashtags", []):
                # Hashtags run words together, so match the squashed blob, but
                # still require a boundary so praktika does not catch praktikal.
                tag_n = _norm(tag).replace(" ", "")
                if tag_n and re.search(rf"(?<![a-z0-9]){re.escape(tag_n)}(?![a-z0-9])", squashed):
                    if len(tag_n) > best_len:
                        best, best_len = comp.get("name", ""), len(tag_n)
        return best

    def _actor_spec(self, actor: str) -> dict[str, Any]:
        return (self.tiktok_cfg.get("actor_inputs", {}) or {}).get(actor, {})

    def _search(self, client: ApifyClient, group: list[str], per_kw: int,
                spec: dict[str, Any]) -> list[dict]:
        """One search call, with a fallback to the second actor if the first throttles.

        The primary actor is the cheap one. On a free Apify plan it answers every
        call with the no-results sentinel, which would otherwise mean the whole
        system collects nothing and correctly but uselessly reports every keyword
        as NOT CHECKED. Falling back keeps the morning running, and records that
        it happened so the cost is never a surprise.
        """
        primary = self.tiktok_cfg.get("actor", "")
        fallback = self.tiktok_cfg.get("fallback_actor", "")
        country = self.tiktok_cfg.get("location", "US")

        def call(actor: str) -> list[dict]:
            conf = self._actor_spec(actor).get("input", {})
            if not conf:
                raise ApifyError(f"no input template configured for {actor}")
            run_input = build_actor_input(conf, keywords=group, max_items=per_kw,
                                          country=country)
            # Per-pass overrides still win, so the two-pass design survives.
            if "sortType" in run_input and spec.get("sort_type"):
                run_input["sortType"] = spec["sort_type"]
            if "dateRange" in run_input and spec.get("date_range"):
                run_input["dateRange"] = spec["date_range"]
            got = client.run_actor(actor, run_input, max_items=per_kw * len(group))
            self.actor_used = actor
            return got

        try:
            return call(primary)
        except ApifyThrottled:
            if not fallback or self.fell_back or fallback == primary:
                raise
            self.fell_back = True
            log_event(log, logging.WARNING,
                      "primary actor throttled, falling back",
                      primary=primary, fallback=fallback,
                      cost_multiple=round(
                          float(self._actor_spec(fallback).get("cost_per_video_usd", 0) or 0)
                          / float(self._actor_spec(primary).get("cost_per_video_usd", 1) or 1), 1))
            client.consecutive_empty = 0
            return call(fallback)

    def fetch(self) -> list[NormalizedContent]:
        if not self.enabled:
            return []
        plan = self.keyword_plan()
        if not plan:
            log_event(log, logging.WARNING, "no competitor keywords configured")
            return []
        keywords = [k for k, _ in plan]
        max_seconds = float(
            self.settings.scoring.get("cheap_filter", {}).get("max_duration_seconds", 120))
        brand_handles = self.brand_handles()
        client = self.client()
        results: list[NormalizedContent] = []
        seen: set[str] = set()

        # Batch size 1 by default, deliberately. Handing the actor six keywords at
        # once returned ten results that all came from the FIRST keyword, so five
        # competitors got silently skipped. Verified on a live run 2026-09-10.
        batch = max(1, int(self.cfg.get("keywords_per_call", 1)))
        batches = [keywords[i:i + batch] for i in range(0, len(keywords), batch)]

        for spec in self.cfg.get("passes", self.tiktok_cfg.get("passes", [])):
            pass_name = spec.get("name", "default")
            per_kw = int(spec.get("max_items_per_keyword", 15))
            items: list[dict] = []
            for group in batches:
                try:
                    items.extend(self._search(client, group, per_kw, spec))
                except ApifyThrottled as exc:

                    # Stop the sweep. Continuing would record every remaining
                    # competitor as having zero UGC, which is a lie that then
                    # poisons the learned baseline.
                    self.not_checked.extend(group)
                    self.not_checked.extend(
                        k for batch in batches[batches.index(group) + 1:] for k in batch
                    )
                    log_event(log, logging.ERROR, "throttled, sweep stopped early",
                              checked=len(keywords) - len(self.not_checked),
                              not_checked=len(self.not_checked), error=str(exc))
                    break
                except Exception as exc:  # noqa: BLE001 - one keyword must not kill the sweep
                    self.not_checked.extend(group)
                    log_event(log, logging.WARNING, "keyword batch failed",
                              keywords=group, error=str(exc))

            for item in items:
                try:
                    content = self._tt.normalize(item, f"ugc_{pass_name}", item.get("keyword", ""))
                except Exception as exc:  # noqa: BLE001
                    log_event(log, logging.WARNING, "ugc item skipped", error=str(exc))
                    continue
                if content.content_id in seen:
                    continue
                competitor = self.attribute(content)
                if not competitor and self.cfg.get("require_attribution", True):
                    # Keyword matched TikTok's fuzzy search but the video never
                    # names the app. Dropping these keeps the feed honest.
                    continue
                if (self.cfg.get("exclude_brand_owned", True)
                        and content.creator.strip().lower().lstrip("@") in brand_handles):
                    self.brand_owned_dropped += 1
                    continue
                # Short form only. The 2 minute cap lived in cheap_filter, which
                # gates the LLM path, so long videos were still reaching the
                # radar feed. An 8 minute app review is not short-form creative
                # and it is not what this system is for.
                if content.duration_seconds and content.duration_seconds > max_seconds:
                    self.too_long_dropped += 1
                    continue
                content.competitor = competitor
                content.kind = "organic_ugc"
                content.source = f"competitor_ugc:{pass_name}"
                seen.add(content.content_id)
                results.append(content)

        log_event(log, logging.INFO, "competitor ugc fetch done",
                  keywords=len(keywords), kept=len(results),
                  brand_owned_dropped=self.brand_owned_dropped,
                  too_long_dropped=self.too_long_dropped,
                  not_checked=sorted(set(self.not_checked)))
        return results
