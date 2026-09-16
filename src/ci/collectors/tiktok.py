"""TikTok via Apify.

There is no compliant official route: the TikTok Research API is restricted to
academic and non-profit applicants and we do not qualify. Spec section 3 permits
compliant third parties, so this uses apidojo/tiktok-scraper at $0.0003 per post.
Verified against a live run on 2026-09-10.

Two passes run every time, and the pairing is the point:
  proven   MOST_LIKED  -> what is already big
  breakout DATE_POSTED -> what is climbing right now
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ci.collectors.apify import ApifyClient
from ci.config import Settings, get_settings
from ci.logging import get_logger, log_event
from ci.models import NormalizedContent, canonical_id

log = get_logger(__name__)


def _iso(ts: Any) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return str(ts)


def _first(item: dict[str, Any], *paths: str, default: Any = None) -> Any:
    """Read the first path that is present, so one normalizer serves both actors.

    apidojo and clockworks return the same videos under different names
    (channel.username vs authorMeta.name, views vs playCount). Coding to one of
    them means a fallback actor returns rows that look empty rather than failing.
    """
    for path in paths:
        cur: Any = item
        for part in path.split("."):
            if not isinstance(cur, dict):
                cur = None
                break
            cur = cur.get(part)
        if cur not in (None, ""):
            return cur
    return default


def _tags(raw: Any) -> list[str]:
    """Hashtags arrive as ["ai"] from one actor and [{"name": "ai"}] from another.

    The model wants strings. Handed dicts it raises, and the caller logs a skip
    and moves on, so a single unexpected shape here silently drops every video
    that carries a hashtag, which is nearly all of them.
    """
    out: list[str] = []
    for tag in raw or []:
        if tag is None:
            continue
        if isinstance(tag, str):
            name = tag
        elif isinstance(tag, dict):
            name = str(tag.get("name") or tag.get("title") or "")
        else:
            name = str(tag)
        name = name.strip().lstrip("#")
        if name:
            out.append(name)
    return out



class TikTokCollector:
    name = "tiktok"

    def __init__(self, settings: Settings | None = None, client: ApifyClient | None = None) -> None:
        self.settings = settings or get_settings()
        self.cfg = self.settings.sources.get("tiktok", {})
        self.categories = self.settings.sources.get("categories", [])
        self.enabled = bool(self.cfg.get("enabled", False))
        self._client = client

    def describe(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.enabled,
            "actor": self.cfg.get("actor"),
            "location": self.cfg.get("location"),
            "passes": [p.get("name") for p in self.cfg.get("passes", [])],
            "token_present": bool(self.settings.apify_token),
        }

    def client(self) -> ApifyClient:
        if self._client is None:
            self._client = ApifyClient(self.settings.apify_token or "")
        return self._client

    def keywords(self, day_index: int | None = None) -> list[str]:
        """Rotate the category list so a week covers what one run cannot."""
        templates = self.cfg.get("keyword_templates", ["{category}"])
        per_run = int(self.cfg.get("keywords_per_run", 12))
        idx = day_index if day_index is not None else datetime.now(timezone.utc).timetuple().tm_yday
        cats = self.categories or ["language learning"]
        rotated = cats[idx % len(cats):] + cats[: idx % len(cats)]
        out: list[str] = []
        for i, category in enumerate(rotated):
            template = templates[i % len(templates)]
            out.append(template.format(category=category))
            if len(out) >= per_run:
                break
        return out

    def normalize(self, item: dict[str, Any], pass_name: str, keyword: str) -> NormalizedContent:
        channel = item.get("channel") or {}
        video = item.get("video") or {}
        song = item.get("song") or {}
        subs = item.get("subtitleInformation") or {}
        url = _first(item, "postPage", "webVideoUrl", default="")
        transcript_source = "none"
        # TikTok auto-captions come back in the same result at no extra cost.
        sub_url = _first(item, "subtitleInformation.url", "videoMeta.subtitleLinks.0.downloadLink",
                         default="")
        if sub_url:
            transcript_source = "platform_captions"
        title = str(_first(item, "title", "text", default=""))
        return NormalizedContent(
            content_id=canonical_id("tiktok", str(item.get("id") or ""), url),
            date_found=datetime.now(timezone.utc).date().isoformat(),
            platform="tiktok",
            source=f"tiktok:{pass_name}",
            url=url,
            creator=str(_first(item, "channel.username", "authorMeta.name",
                               "authorMeta.uniqueId", default="")),
            creator_followers=int(_first(item, "channel.followers", "authorMeta.fans",
                                         default=0) or 0),
            title=title[:2000],
            description=title[:2000],
            views=int(_first(item, "views", "playCount", default=0) or 0),
            likes=int(_first(item, "likes", "diggCount", default=0) or 0),
            comments=int(_first(item, "comments", "commentCount", default=0) or 0),
            shares=int(_first(item, "shares", "shareCount", default=0) or 0),
            saves=int(_first(item, "bookmarks", "collectCount", default=0) or 0),
            published_at=_iso(_first(item, "uploadedAt", "createTimeISO", "createTime"))
            or item.get("uploadedAtFormatted"),
            country=self.cfg.get("location", "US"),
            language=str(_first(item, "subtitleInformation.language_code", "textLanguage",
                                default="en") or "en"),
            category=keyword,
            raw_transcript="",
            transcript_source=transcript_source,
            thumbnail_url=str(_first(item, "video.cover", "video.thumbnail",
                                     "videoMeta.coverUrl", default="")),
            duration_seconds=float(_first(item, "video.duration", "videoMeta.duration",
                                          default=0.0) or 0.0),
            hashtags=_tags(item.get("hashtags")),
            sound_title=str(_first(item, "song.title", "musicMeta.musicName", default="")),
            collected_pass=pass_name,
            subtitle_url=sub_url,
            is_ad=bool(item.get("isAd") or item.get("isSponsored") or False),
        )

    def fetch(self) -> list[NormalizedContent]:
        if not self.enabled:
            return []
        keywords = self.keywords()
        client = self.client()
        results: list[NormalizedContent] = []
        seen: set[str] = set()
        for spec in self.cfg.get("passes", []):
            pass_name = spec.get("name", "default")
            max_items = int(spec.get("max_items_per_keyword", 25)) * len(keywords)
            run_input = {
                "keywords": keywords,
                "maxItems": max_items,
                "location": self.cfg.get("location", "US"),
                "sortType": spec.get("sort_type", "RELEVANCE"),
                "dateRange": spec.get("date_range", "THIS_WEEK"),
                "includeSearchKeywords": True,
            }
            items = client.run_actor(self.cfg["actor"], run_input, max_items=max_items)
            for item in items:
                try:
                    content = self.normalize(item, pass_name, item.get("keyword", ""))
                except Exception as exc:  # noqa: BLE001
                    log_event(log, logging.WARNING, "tiktok item skipped", error=str(exc))
                    continue
                if content.content_id in seen:
                    continue
                seen.add(content.content_id)
                results.append(content)
            log_event(log, logging.INFO, "tiktok pass done",
                      pass_name=pass_name, keywords=len(keywords), items=len(items))
        return results

    def fetch_by_urls(self, urls: list[str]) -> list[NormalizedContent]:
        """Re-check known posts to build snapshot history."""
        if not urls:
            return []
        items = self.client().run_actor(
            self.cfg["actor"],
            {"startUrls": urls, "maxItems": len(urls), "location": self.cfg.get("location", "US")},
            max_items=len(urls),
        )
        return [self.normalize(i, "snapshot", i.get("keyword", "")) for i in items]
