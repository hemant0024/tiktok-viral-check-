"""YouTube Data API v3.

The binding constraint is quota, not rate limits: 10,000 units a day, and
search.list costs 100 of them. That is 100 searches a day and nothing else, so
the budget below is enforced in code rather than left to hope.

Transcripts: captions.download only works for videos you own, so raw_transcript
is left empty here and filled later by the video analyser if that is enabled.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ci.config import Settings, get_settings
from ci.logging import get_logger, log_event
from ci.models import NormalizedContent, canonical_id

log = get_logger(__name__)
API = "https://www.googleapis.com/youtube/v3"

COST = {"search": 100, "videos": 1, "channels": 1, "playlistItems": 1}


def _parse_duration(iso: str) -> float:
    """PT1M30S -> 90.0. No dependency needed for a format this small."""
    if not iso.startswith("PT"):
        return 0.0
    total, number = 0.0, ""
    for ch in iso[2:]:
        if ch.isdigit():
            number += ch
        else:
            value = float(number or 0)
            total += value * {"H": 3600, "M": 60, "S": 1}.get(ch, 0)
            number = ""
    return total


class QuotaExhausted(RuntimeError):
    pass


class QuotaBudget:
    def __init__(self, daily: int, reserved: int) -> None:
        self.daily = daily
        self.reserved = reserved
        self.used = 0

    def spend(self, endpoint: str, calls: int = 1) -> None:
        cost = COST.get(endpoint, 1) * calls
        if self.used + cost > self.daily - self.reserved:
            raise QuotaExhausted(
                f"{endpoint} would take quota to {self.used + cost}, "
                f"budget is {self.daily - self.reserved}"
            )
        self.used += cost

    def remaining(self) -> int:
        return max(0, self.daily - self.reserved - self.used)


class YouTubeCollector:
    name = "youtube"

    def __init__(self, settings: Settings | None = None, http: Any = None) -> None:
        self.settings = settings or get_settings()
        self.cfg = self.settings.sources.get("youtube", {})
        self.categories = self.settings.sources.get("categories", [])
        self.enabled = bool(self.cfg.get("enabled", False))
        self.budget = QuotaBudget(
            int(self.cfg.get("daily_quota_units", 10000)),
            int(self.cfg.get("reserved_units", 1500)),
        )
        self._http = http or httpx

    def describe(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.enabled,
            "region": self.cfg.get("region_code"),
            "max_search_calls": self.cfg.get("max_search_calls"),
            "budget_units": self.budget.daily - self.budget.reserved,
            "key_present": bool(self.settings.youtube_api_key),
        }

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict:
        params = {**params, "key": self.settings.youtube_api_key}
        resp = self._http.get(f"{API}/{endpoint}", params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def queries(self, day_index: int | None = None) -> list[str]:
        templates = self.cfg.get("query_templates", ["{category}"])
        limit = int(self.cfg.get("max_search_calls", 60))
        idx = day_index if day_index is not None else datetime.now(timezone.utc).timetuple().tm_yday
        cats = self.categories or ["language learning"]
        rotated = cats[idx % len(cats):] + cats[: idx % len(cats)]
        out = []
        for category in rotated:
            for template in templates:
                out.append(template.format(category=category))
                if len(out) >= limit:
                    return out
        return out

    def search_ids(self, query: str) -> list[str]:
        self.budget.spend("search")
        published_after = (
            datetime.now(timezone.utc)
            - timedelta(days=int(self.cfg.get("published_within_days", 14)))
        ).isoformat()
        data = self._get("search", {
            "part": "id",
            "q": query,
            "type": "video",
            "order": "viewCount",
            "maxResults": int(self.cfg.get("results_per_search", 50)),
            "regionCode": self.cfg.get("region_code", "US"),
            "relevanceLanguage": self.cfg.get("relevance_language", "en"),
            "videoDuration": self.cfg.get("video_duration", "short"),
            "publishedAfter": published_after,
        })
        return [i["id"]["videoId"] for i in data.get("items", []) if i.get("id", {}).get("videoId")]

    def hydrate(self, video_ids: list[str], category: str = "") -> list[NormalizedContent]:
        out: list[NormalizedContent] = []
        for start in range(0, len(video_ids), 50):
            chunk = video_ids[start:start + 50]
            self.budget.spend("videos")
            data = self._get("videos", {
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(chunk),
                "maxResults": 50,
            })
            for item in data.get("items", []):
                out.append(self.normalize(item, category))
        return out

    def normalize(self, item: dict[str, Any], category: str = "") -> NormalizedContent:
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        details = item.get("contentDetails", {})
        vid = item.get("id", "")
        thumbs = snippet.get("thumbnails", {})
        thumb = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
        return NormalizedContent(
            content_id=canonical_id("youtube", vid, f"https://www.youtube.com/watch?v={vid}"),
            date_found=datetime.now(timezone.utc).date().isoformat(),
            platform="youtube",
            source="youtube:search",
            url=f"https://www.youtube.com/watch?v={vid}",
            creator=snippet.get("channelTitle", ""),
            title=snippet.get("title", ""),
            description=(snippet.get("description") or "")[:4000],
            views=int(stats.get("viewCount") or 0),
            likes=int(stats.get("likeCount") or 0),
            comments=int(stats.get("commentCount") or 0),
            published_at=snippet.get("publishedAt"),
            country=self.cfg.get("region_code", "US"),
            language=snippet.get("defaultAudioLanguage") or "en",
            category=category,
            transcript_source="none",
            thumbnail_url=thumb,
            duration_seconds=_parse_duration(details.get("duration", "")),
            hashtags=[t for t in (snippet.get("tags") or [])][:20],
            channel_id=snippet.get("channelId", ""),
        )

    def fetch(self) -> list[NormalizedContent]:
        if not self.enabled:
            return []
        if not self.settings.youtube_api_key:
            raise RuntimeError("YOUTUBE_API_KEY is not set")
        results: dict[str, NormalizedContent] = {}
        for query in self.queries():
            try:
                ids = self.search_ids(query)
            except QuotaExhausted as exc:
                log_event(log, logging.WARNING, "youtube quota budget reached",
                          query=query, used=self.budget.used, error=str(exc))
                break
            for content in self.hydrate(ids, category=query):
                results.setdefault(content.content_id, content)
        log_event(log, logging.INFO, "youtube fetch done",
                  unique=len(results), quota_used=self.budget.used,
                  quota_left=self.budget.remaining())
        return list(results.values())

    def refresh(self, content_ids: list[str]) -> list[NormalizedContent]:
        """Cheap re-read of tracked videos for snapshot history. 1 unit per 50."""
        native = [c.split(":", 1)[1] for c in content_ids if c.startswith("youtube:")]
        return self.hydrate(native)
