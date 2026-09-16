"""Manual CSV import. The fallback that keeps every unavailable source usable."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ci.config import Settings, get_settings
from ci.models import NormalizedContent, canonical_id

FIELD_ALIASES = {
    "link": "url", "post_url": "url", "video_url": "url",
    "author": "creator", "username": "creator", "channel": "creator",
    "caption": "description", "text": "description",
    "play_count": "views", "view_count": "views",
    "like_count": "likes", "digg_count": "likes",
    "comment_count": "comments", "share_count": "shares",
    "save_count": "saves", "bookmark_count": "saves",
    "duration": "duration_seconds", "date": "published_at",
}


class CsvCollector:
    name = "csv"

    def __init__(self, path: str | Path, settings: Settings | None = None,
                 platform: str = "csv") -> None:
        self.settings = settings or get_settings()
        self.path = Path(path)
        self.platform = platform
        self.enabled = True

    def describe(self) -> dict[str, Any]:
        return {"source": self.name, "enabled": True, "path": str(self.path),
                "exists": self.path.exists()}

    @staticmethod
    def _num(value: Any, cast=int) -> Any:
        try:
            return cast(str(value).replace(",", "").strip() or 0)
        except (TypeError, ValueError):
            return cast(0)

    def normalize(self, row: dict[str, Any]) -> NormalizedContent:
        clean = {}
        for key, value in row.items():
            k = (key or "").strip().lower().replace(" ", "_")
            clean[FIELD_ALIASES.get(k, k)] = value
        url = clean.get("url", "")
        return NormalizedContent(
            content_id=canonical_id(self.platform, clean.get("id") or None, url),
            date_found=datetime.now(timezone.utc).date().isoformat(),
            platform=self.platform if self.platform in
            {"youtube", "tiktok", "meta_ads", "instagram", "csv"} else "csv",
            source=f"csv:{self.path.name}",
            url=url,
            creator=clean.get("creator", ""),
            title=clean.get("title", ""),
            description=clean.get("description", ""),
            views=self._num(clean.get("views")),
            likes=self._num(clean.get("likes")),
            comments=self._num(clean.get("comments")),
            shares=self._num(clean.get("shares")),
            saves=self._num(clean.get("saves")),
            published_at=clean.get("published_at") or None,
            country=clean.get("country", self.settings.market_country),
            language=clean.get("language", "en"),
            category=clean.get("category", ""),
            raw_transcript=clean.get("raw_transcript", ""),
            transcript_source="manual" if clean.get("raw_transcript") else "none",
            duration_seconds=self._num(clean.get("duration_seconds"), float),
            hashtags=clean.get("hashtags", ""),
        )

    def fetch(self) -> list[NormalizedContent]:
        if not self.path.exists():
            raise FileNotFoundError(f"csv not found: {self.path}")
        with self.path.open(newline="") as fh:
            return [self.normalize(row) for row in csv.DictReader(fh)]
