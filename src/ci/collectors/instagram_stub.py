"""Instagram: there is no trend discovery API for content we do not own.

IG Hashtag Search exists but cannot do this job: 30 unique hashtags per rolling
7 days, recent_media covers only the last 24 hours, and username cannot be
requested, so there is no creator attribution at all.

This adapter satisfies the interface and returns nothing, so the pipeline runs
unchanged. Use the CSV importer to bring Instagram finds in by hand.
"""
from __future__ import annotations

from typing import Any

from ci.config import Settings, get_settings
from ci.models import NormalizedContent


class InstagramStubCollector:
    name = "instagram"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.cfg = self.settings.sources.get("instagram", {})
        self.enabled = bool(self.cfg.get("enabled", False))

    def describe(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.enabled,
            "status": "stub",
            "reason": "no trend discovery API exists for content we do not own",
            "workaround": "ci collect csv --path <file>",
        }

    def fetch(self) -> list[NormalizedContent]:
        return []
