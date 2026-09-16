"""Deterministic provider for the unit suite. No network, no keys.

Returns a schema-shaped stub built from the prompt's own JSON schema, so tests
exercise the real validation path rather than a hand-written happy answer.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ci.llm.providers.base import LlmResponse


def _stub_for(spec: dict[str, Any], seed: str) -> Any:
    kind = spec.get("type", "string")
    if "enum" in spec:
        options = spec["enum"]
        idx = int(hashlib.sha256(seed.encode()).hexdigest(), 16) % len(options)
        return options[idx]
    if kind == "string":
        return f"stub:{seed[:24]}"
    if kind == "integer":
        return int(hashlib.sha256(seed.encode()).hexdigest()[:4], 16) % 100
    if kind == "number":
        return round((int(hashlib.sha256(seed.encode()).hexdigest()[:4], 16) % 1000) / 10.0, 2)
    if kind == "boolean":
        return int(hashlib.sha256(seed.encode()).hexdigest()[:2], 16) % 2 == 0
    if kind == "array":
        item_spec = spec.get("items", {"type": "string"})
        return [_stub_for(item_spec, seed + str(i)) for i in range(2)]
    if kind == "object":
        return {k: _stub_for(v, seed + k) for k, v in spec.get("properties", {}).items()}
    return None


class FakeProvider:
    name = "fake"

    def __init__(self, schema: dict | None = None) -> None:
        self.schema = schema or {}
        self.calls = 0

    def set_schema(self, schema: dict) -> None:
        self.schema = schema

    def complete(self, model: str, system: str, user: str, max_tokens: int, timeout: float) -> LlmResponse:
        self.calls += 1
        seed = hashlib.sha256(user.encode()).hexdigest()
        props = self.schema.get("properties", {})
        payload = {k: _stub_for(v, seed + k) for k, v in props.items()}
        text = json.dumps(payload)
        return LlmResponse(
            text=text,
            input_tokens=max(1, len(user) // 4),
            output_tokens=max(1, len(text) // 4),
            model=model,
            provider=self.name,
        )

    def analyse_video(self, model: str, video_url: str, prompt: str, max_tokens: int, timeout: float) -> LlmResponse:
        return self.complete(model, "", prompt + video_url, max_tokens, timeout)
