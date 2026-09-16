from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class LlmResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    provider: str = ""
    meta: dict = field(default_factory=dict)


class LlmProvider(Protocol):
    name: str

    def complete(self, model: str, system: str, user: str, max_tokens: int, timeout: float) -> LlmResponse: ...


class VideoProvider(Protocol):
    name: str

    def analyse_video(self, model: str, video_url: str, prompt: str, max_tokens: int, timeout: float) -> LlmResponse: ...
