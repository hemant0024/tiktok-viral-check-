"""Video understanding for the first three seconds.

The spec requires first_3_second_description, visual_hook and on_screen_text. None of
those can come from a title. OpenAI has no native video input, so this uses Gemini,
which accepts a public YouTube URL directly. Nothing is downloaded and no terms broken.

TikTok is different: the collector already returns auto-caption URLs in the same
result, so TikTok transcripts cost nothing extra.
"""
from __future__ import annotations

import logging

import httpx

from ci.llm.client import LlmClient
from ci.logging import get_logger, log_event

log = get_logger(__name__)

VIDEO_PROMPT = (
    "Watch the first 10 seconds of this video and describe only what happens.\n"
    "Return JSON with keys: first_3_second_description, visual_hook, on_screen_text,\n"
    "spoken_hook, audio_device. Describe what you can see and hear. Do not interpret,\n"
    "do not judge quality, and leave a field as an empty string if it is not present."
)

VIDEO_SCHEMA = {
    "type": "object",
    "required": ["first_3_second_description", "visual_hook", "on_screen_text"],
    "properties": {
        "first_3_second_description": {"type": "string"},
        "visual_hook": {"type": "string"},
        "on_screen_text": {"type": "string"},
        "spoken_hook": {"type": "string"},
        "audio_device": {"type": "string"},
    },
}


def fetch_platform_captions(url: str, timeout: float = 20.0, max_chars: int = 6000) -> str:
    """TikTok auto-captions arrive as a WebVTT url in the collector result."""
    if not url:
        return ""
    try:
        resp = httpx.get(url, timeout=timeout)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log_event(log, logging.WARNING, "caption fetch failed", url=url[:80], error=str(exc))
        return ""
    lines = []
    for line in resp.text.splitlines():
        line = line.strip()
        if not line or line.startswith(("WEBVTT", "NOTE")) or "-->" in line or line.isdigit():
            continue
        lines.append(line)
    return " ".join(lines)[:max_chars]


def visual_notes(client: LlmClient, content: dict, stage: str = "analyze_dna") -> dict:
    """Returns {} when video analysis is off, so every caller degrades cleanly."""
    if not client.video_enabled():
        return {}
    if content.get("platform") != "youtube":
        # Only YouTube URLs are accepted directly by the video model.
        return {}
    from ci.llm.prompts import Prompt

    prompt = Prompt(
        name="video_first_seconds", version="1", tier="video",
        description="first seconds of a public video",
        template=VIDEO_PROMPT, schema=VIDEO_SCHEMA,
    )
    try:
        result = client.run_prompt(
            prompt, stage=stage, cache_content=content.get("content_id", ""),
            tier="video", video_url=content.get("url", ""),
        )
        return result.data
    except Exception as exc:  # noqa: BLE001
        log_event(log, logging.WARNING, "video analysis failed",
                  content_id=content.get("content_id"), error=str(exc))
        return {}
