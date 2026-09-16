from __future__ import annotations

import json

import httpx

from ci.llm.providers.base import LlmResponse


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def complete(self, model: str, system: str, user: str, max_tokens: int, timeout: float) -> LlmResponse:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_completion_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        return LlmResponse(
            text=data["choices"][0]["message"]["content"],
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            model=model,
            provider=self.name,
            meta={"finish_reason": data["choices"][0].get("finish_reason")},
        )

    def embed(self, model: str, texts: list[str], timeout: float = 60.0) -> list[list[float]]:
        resp = httpx.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": model, "input": texts},
            timeout=timeout,
        )
        resp.raise_for_status()
        return [item["embedding"] for item in resp.json()["data"]]

    @staticmethod
    def parse_json(text: str) -> dict:
        return json.loads(text)
