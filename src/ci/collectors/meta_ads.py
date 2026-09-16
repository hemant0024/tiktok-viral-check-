"""Competitor ads from the US Meta Ad Library, via Apify.

The official Meta Ad Library API returns political ads worldwide plus anything
delivered to the UK or EU. It returns NO US commercial ads, and every competitor
we track is a US commercial advertiser, so the official API is useless here.

Field mapping below was verified against a live run on 2026-09-10. Three things
that run taught us, which are easy to get wrong from the docs:

  1. `totalActiveTime` is null on every US ad despite being advertised.
     Days running is endDate - startDate. startDate never changes.
  2. `collationCount` is NOT the variation count. It was null on half the ads and
     1 on the rest, while Linguza had five separate ad IDs all titled "Try free
     now!". Variation groups are derived from copy similarity instead.
  3. Dynamic creative ads come back with template placeholders like
     {{product.name}} and displayFormat DCO. They are dropped.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from ci.collectors.apify import ApifyClient
from ci.config import Settings, get_settings
from ci.logging import get_logger, log_event
from ci.models import NormalizedContent, canonical_id
from ci.patterns.embed import normalize_text, tokenize

log = get_logger(__name__)
_TEMPLATE = re.compile(r"\{\{.*?\}\}")


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _trigrams(text: str) -> set[tuple[str, ...]]:
    words = tokenize(normalize_text(text))
    return {tuple(words[i:i + 3]) for i in range(max(0, len(words) - 2))}


def copy_similarity(a: str, b: str) -> float:
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 1.0 if normalize_text(a) == normalize_text(b) else 0.0
    return len(ta & tb) / len(ta | tb)


def group_variations(ads: list[NormalizedContent], threshold: float = 0.75) -> list[NormalizedContent]:
    """A variation group is ads from the same page whose normalized copy is
    near-identical, or which share a non-null collationId.

    Linguza is the fixture for this: five ad IDs, one concept, collationCount
    reporting 1 on each.
    """
    by_page: dict[str, list[NormalizedContent]] = {}
    for ad in ads:
        by_page.setdefault(ad.creator, []).append(ad)

    for page, page_ads in by_page.items():
        groups: list[list[NormalizedContent]] = []
        for ad in page_ads:
            text = f"{ad.title} {ad.description}"
            collation = (ad.model_extra or {}).get("collation_id")
            placed = False
            for group in groups:
                head = group[0]
                head_collation = (head.model_extra or {}).get("collation_id")
                same_collation = bool(collation) and collation == head_collation
                if same_collation or copy_similarity(text, f"{head.title} {head.description}") >= threshold:
                    group.append(ad)
                    placed = True
                    break
            if not placed:
                groups.append([ad])

        for group in groups:
            gid = "var_" + hashlib.sha256(
                f"{page}|{normalize_text(group[0].title + group[0].description)}".encode()
            ).hexdigest()[:10]
            active = sum(1 for a in group if (a.model_extra or {}).get("is_active", True))
            for ad in group:
                ad.variation_group = gid
                ad.variation_count = max(active, len(group))
    return ads


class MetaAdsCollector:
    name = "meta_ads"

    def __init__(self, settings: Settings | None = None, client: ApifyClient | None = None,
                 last_run_date: str | None = None) -> None:
        self.settings = settings or get_settings()
        self.cfg = self.settings.sources.get("meta_ads", {})
        self.enabled = bool(self.cfg.get("enabled", False))
        self.last_run_date = last_run_date
        self._client = client

    def competitors(self) -> list[dict[str, Any]]:
        out = []
        for group in ("competitors", "adjacent"):
            out.extend(self.settings.competitors.get(group, []) or [])
        return out

    def describe(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.enabled,
            "actor": self.cfg.get("actor"),
            "country": self.cfg.get("country"),
            "pages_configured": len(self.page_urls()),
            "keyword_fallbacks": len(self.search_urls()),
            "mode": "full sweep" if self.is_full_sweep() else "new ads only",
            "since": self._since(),
            "token_present": bool(self.settings.apify_token),
        }

    def client(self) -> ApifyClient:
        if self._client is None:
            self._client = ApifyClient(self.settings.apify_token or "")
        return self._client

    def page_urls(self) -> list[str]:
        return [c["meta_page_url"] for c in self.competitors() if c.get("meta_page_url")]

    def search_urls(self) -> list[str]:
        """Competitors without a known page URL are found by keyword instead."""
        country = self.cfg.get("country", "US")
        out = []
        for comp in self.competitors():
            if comp.get("meta_page_url"):
                continue
            kws = comp.get("keywords", [])
            if not kws:
                continue
            q = kws[0].replace(" ", "%20")
            out.append(
                "https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
                f"&country={country}&q=%22{q}%22&search_type=keyword_unordered&media_type=video"
            )
        return out

    def is_full_sweep(self, today: datetime | None = None) -> bool:
        """startDate never changes, so a daily full sweep buys nothing. Daily runs
        find new ads; one weekly sweep catches the ones that died."""
        day = (today or datetime.now(timezone.utc)).weekday()
        return day == int(self.cfg.get("full_sweep_weekday", 0))

    def _since(self) -> str:
        if self.is_full_sweep():
            days = int(self.cfg.get("full_sweep_lookback_days", 120))
        elif self.last_run_date:
            return self.last_run_date
        else:
            days = int(self.cfg.get("first_run_lookback_days", 30))
        return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()

    @staticmethod
    def is_template_ad(item: dict[str, Any], snapshot: dict[str, Any]) -> bool:
        if str(snapshot.get("displayFormat", "")).upper() == "DCO":
            return True
        body = snapshot.get("body") or {}
        text = body.get("text", "") if isinstance(body, dict) else str(body)
        return bool(_TEMPLATE.search(f"{snapshot.get('title','')} {text}"))

    def normalize(self, item: dict[str, Any], now: datetime | None = None) -> NormalizedContent:
        now = now or datetime.now(timezone.utc)
        snapshot = item.get("snapshot") or {}
        body = snapshot.get("body") or {}
        body_text = body.get("text", "") if isinstance(body, dict) else str(body or "")
        ad_id = str(item.get("adArchiveID") or item.get("adArchiveId") or item.get("adId") or "")
        url = f"https://www.facebook.com/ads/library/?id={ad_id}"

        start = _ts(item.get("startDate"))
        end = _ts(item.get("endDate")) or now
        days_running = max(int((end - start).total_seconds() // 86400), 0) if start else 0

        videos = snapshot.get("videos") or []
        video = videos[0] if videos else {}
        images = snapshot.get("images") or []
        thumb = video.get("videoPreviewImageUrl") or (
            images[0].get("originalImageUrl") if images else ""
        )

        return NormalizedContent(
            content_id=canonical_id("meta_ads", ad_id, url),
            date_found=now.date().isoformat(),
            platform="meta_ads",
            source="meta_ads:apify",
            url=url,
            creator=item.get("pageName") or snapshot.get("pageName", ""),
            creator_followers=int(snapshot.get("pageLikeCount") or 0),
            title=str(snapshot.get("title") or "")[:500],
            description=str(body_text)[:4000],
            published_at=start.isoformat() if start else None,
            country=self.cfg.get("country", "US"),
            language="en",
            category="competitor ad",
            transcript_source="none",
            thumbnail_url=thumb or "",
            is_ad=True,
            kind="competitor_ad",
            ad_start_date=start.date().isoformat() if start else None,
            days_running=days_running,
            # Verified: real MP4 URLs come back here.
            video_url=video.get("videoHdUrl") or video.get("videoSdUrl") or "",
            # Kept for audit, deliberately NOT used as the variation count.
            collation_id=item.get("collationId"),
            collation_count=item.get("collationCount"),
            is_active=bool(item.get("isActive", True)),
            cta_text=snapshot.get("ctaText", ""),
            cta_type=snapshot.get("ctaType", ""),
            landing_page=snapshot.get("linkUrl", ""),
            publisher_platforms=item.get("publisherPlatform") or [],
            display_format=snapshot.get("displayFormat", ""),
        )

    def _run(self, urls: list[str]) -> list[dict]:
        if not urls:
            return []
        return self.client().run_actor(self.cfg["actor"], {
            "startUrls": [{"url": u} for u in urls],
            "resultsLimit": int(self.cfg.get("results_limit_per_page", 40)),
            "activeStatus": self.cfg.get("active_status", "active"),
            "onlyAdsNewerThan": self._since(),
            "isDetailsPerAd": True,
        })

    def fetch(self) -> list[NormalizedContent]:
        if not self.enabled:
            return []
        urls = self.page_urls() + self.search_urls()
        if not urls:
            log_event(log, logging.WARNING, "meta_ads has no page urls or keywords configured")
            return []

        items = self._run(urls)
        out: list[NormalizedContent] = []
        seen: set[str] = set()
        dropped_templates = 0
        for item in items:
            snapshot = item.get("snapshot") or {}
            if self.is_template_ad(item, snapshot):
                dropped_templates += 1
                continue
            try:
                ad = self.normalize(item)
            except Exception as exc:  # noqa: BLE001
                log_event(log, logging.WARNING, "meta ad skipped", error=str(exc))
                continue
            if ad.content_id in seen:
                continue
            seen.add(ad.content_id)
            out.append(ad)

        out = group_variations(out, float(self.cfg.get("variation_similarity", 0.75)))
        groups = len({a.variation_group for a in out})
        log_event(log, logging.INFO, "meta_ads fetch done",
                  urls=len(urls), ads=len(out), variation_groups=groups,
                  dropped_dco=dropped_templates, full_sweep=self.is_full_sweep())
        return out
