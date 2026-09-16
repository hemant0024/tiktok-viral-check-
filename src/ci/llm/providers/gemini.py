"""Gemini, used ONLY for video understanding on public YouTube URLs.

OpenAI has no native video input, and the spec requires first-frame, visual and
on-screen-text fields that cannot be derived from a title. The Gemini API accepts
a public YouTube URL directly, so nothing is downloaded and no terms are broken.
"""
from __future__ import annotations

import httpx

from ci.llm.providers.base import LlmResponse

BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def _generate(self, model: str, parts: list[dict], max_tokens: int, timeout: float) -> LlmResponse:
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        }
        resp = httpx.post(
            f"{BASE}/models/{model}:generateContent",
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usageMetadata", {})
        text = ""
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                text += part.get("text", "")
        return LlmResponse(
            text=text,
            input_tokens=usage.get("promptTokenCount", 0),
            output_tokens=usage.get("candidatesTokenCount", 0),
            model=model,
            provider=self.name,
        )

    def complete(self, model: str, system: str, user: str, max_tokens: int, timeout: float) -> LlmResponse:
        return self._generate(model, [{"text": f"{system}\n\n{user}"}], max_tokens, timeout)

    def analyse_video(self, model: str, video_url: str, prompt: str, max_tokens: int, timeout: float) -> LlmResponse:
        parts = [
            {"file_data": {"file_uri": video_url}},
            {"text": prompt},
        ]
        return self._generate(model, parts, max_tokens, timeout)
