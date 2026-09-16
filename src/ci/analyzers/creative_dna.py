"""Creative DNA extraction and hook classification. Cheap tier, cached, validated."""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from ci.analyzers.video import fetch_platform_captions, visual_notes
from ci.config import Settings, get_settings
from ci.llm.client import LlmClient
from ci.llm.prompts import load_prompt
from ci.logging import get_logger, log_event
from ci.models import Hook

log = get_logger(__name__)


def content_fingerprint(content: dict[str, Any]) -> str:
    """Cache key input. Re-analysing an unchanged video must cost nothing."""
    parts = [
        content.get("content_id", ""),
        content.get("title", ""),
        content.get("description", "")[:2000],
        content.get("raw_transcript", "")[:2000],
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _render_args(content: dict[str, Any], notes: dict[str, Any], settings: Settings) -> dict:
    return {
        "market_country": settings.market_country,
        "platform": content.get("platform", ""),
        "creator": content.get("creator", ""),
        "creator_followers": content.get("creator_followers", 0),
        "title": content.get("title", ""),
        "description": content.get("description", ""),
        "hashtags": content.get("hashtags", []),
        "sound_title": content.get("sound_title", ""),
        "duration_seconds": content.get("duration_seconds", 0),
        "views": content.get("views", 0),
        "likes": content.get("likes", 0),
        "comments": content.get("comments", 0),
        "shares": content.get("shares", 0),
        "saves": content.get("saves", 0),
        "transcript": (content.get("raw_transcript") or "")[:6000] or "(none available)",
        "visual_notes": notes or "(no video analysis available)",
    }


class DnaAnalyzer:
    def __init__(self, client: LlmClient, settings: Settings | None = None) -> None:
        self.client = client
        self.settings = settings or get_settings()
        self.dna_prompt = load_prompt("extract_creative_dna")
        self.hook_prompt = load_prompt("classify_hook")

    def enrich_transcript(self, content: dict[str, Any]) -> dict[str, Any]:
        """Free wins first: TikTok ships caption urls with the post."""
        if content.get("raw_transcript"):
            return content
        sub_url = content.get("subtitle_url") or ""
        if sub_url:
            text = fetch_platform_captions(sub_url)
            if text:
                content["raw_transcript"] = text
                content["transcript_source"] = "platform_captions"
        return content

    def analyse(self, content: dict[str, Any]) -> tuple[dict, Hook]:
        content = self.enrich_transcript(content)
        notes = visual_notes(self.client, content)
        if notes and not content.get("raw_transcript"):
            content["transcript_source"] = "video_model"
        fingerprint = content_fingerprint(content) + ("|v" if notes else "")
        args = _render_args(content, notes, self.settings)

        dna = self.client.run_prompt(
            self.dna_prompt, stage="analyze_dna", cache_content=fingerprint, **args
        ).data
        hook_data = self.client.run_prompt(
            self.hook_prompt, stage="analyze_hooks", cache_content=fingerprint, **args
        ).data

        hook = Hook(
            hook_id=f"hook:{content.get('content_id','')}",
            content_id=content.get("content_id", ""),
            original_hook=hook_data.get("original_hook", ""),
            first_3_second_description=notes.get("first_3_second_description")
            or hook_data.get("first_3_second_description", ""),
            visual_hook=notes.get("visual_hook") or hook_data.get("visual_hook", ""),
            spoken_hook=notes.get("spoken_hook") or hook_data.get("spoken_hook", ""),
            on_screen_text=notes.get("on_screen_text") or hook_data.get("on_screen_text", ""),
            hook_type=hook_data.get("hook_type", []),
            creative_format=hook_data.get("creative_format", ""),
            emotional_trigger=hook_data.get("emotional_trigger", ""),
            curiosity_mechanism=hook_data.get("curiosity_mechanism", ""),
            problem=hook_data.get("problem", ""),
            payoff=hook_data.get("payoff", ""),
            cta=hook_data.get("cta", ""),
            target_audience=hook_data.get("target_audience", ""),
            product_category=hook_data.get("product_category", ""),
            analysis_source="video" if notes else hook_data.get("evidence", "metadata_only"),
            prompt_version=f"{self.dna_prompt.version}/{self.hook_prompt.version}",
        )
        dna["content_id"] = content.get("content_id", "")
        log_event(log, logging.INFO, "analysed",
                  content_id=content.get("content_id"),
                  mechanism=dna.get("creative_mechanism", "")[:60],
                  evidence=hook.analysis_source)
        return dna, hook
