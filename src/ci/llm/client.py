"""One LLM wrapper. Tiers, retries, timeouts, schema validation, cost log, cache."""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ci.config import CONFIG_DIR, Settings, get_settings
from ci.llm.cache import ResponseCache, cache_key
from ci.llm.prompts import Prompt, load_prompt, validate_against_schema
from ci.logging import get_logger, get_run_id, log_event
from ci.models import LlmCall

log = get_logger(__name__)
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class LlmBudgetExceeded(RuntimeError):
    pass


class LlmResult:
    def __init__(self, data: dict, call: LlmCall) -> None:
        self.data = data
        self.call = call

    def __getitem__(self, item):
        return self.data[item]

    def get(self, item, default=None):
        return self.data.get(item, default)


class LlmClient:
    def __init__(self, settings: Settings | None = None, provider=None, video_provider=None) -> None:
        self.settings = settings or get_settings()
        self.cfg = yaml.safe_load((CONFIG_DIR / "llm.yaml").read_text())
        self.pricing: dict[str, dict[str, float]] = self.cfg.get("pricing", {})
        self.limits: dict[str, Any] = self.cfg.get("limits", {})
        self.cache = ResponseCache(Path(self.settings.local_data_dir) / "llm_cache")
        self.calls: list[LlmCall] = []
        self.run_cost = 0.0
        self._provider = provider
        self._video_provider = video_provider

    # ------------------------------------------------------------------ #
    def _get_provider(self):
        if self._provider is not None:
            return self._provider
        name = self.settings.llm_provider.lower()
        if name == "openai":
            if not self.settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY is not set")
            from ci.llm.providers.openai import OpenAIProvider
            self._provider = OpenAIProvider(self.settings.openai_api_key, self.settings.openai_base_url)
        elif name == "gemini":
            if not self.settings.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY is not set")
            from ci.llm.providers.gemini import GeminiProvider
            self._provider = GeminiProvider(self.settings.gemini_api_key)
        elif name == "fake":
            from ci.llm.providers.fake import FakeProvider
            self._provider = FakeProvider()
        else:
            raise RuntimeError(f"unknown llm provider: {name}")
        return self._provider

    def _get_video_provider(self):
        if self._video_provider is not None:
            return self._video_provider
        name = self.settings.video_provider.lower()
        if name in {"none", ""}:
            return None
        if name == "gemini":
            if not self.settings.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY is not set but CI_VIDEO_PROVIDER=gemini")
            from ci.llm.providers.gemini import GeminiProvider
            self._video_provider = GeminiProvider(self.settings.gemini_api_key)
        elif name == "fake":
            from ci.llm.providers.fake import FakeProvider
            self._video_provider = FakeProvider()
        else:
            raise RuntimeError(f"unknown video provider: {name}")
        return self._video_provider

    def video_enabled(self) -> bool:
        return self.settings.video_provider.lower() not in {"none", ""}

    def model_for(self, tier: str) -> str:
        if tier == "cheap":
            return self.settings.llm_cheap_model
        if tier == "strong":
            return self.settings.llm_strong_model
        if tier == "video":
            return self.settings.video_model
        raise ValueError(f"unknown tier: {tier}")

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        price = self.pricing.get(model)
        if not price:
            return 0.0
        return (input_tokens / 1e6) * price.get("input", 0.0) + (
            output_tokens / 1e6
        ) * price.get("output", 0.0)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_json(text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n", "", text)
            text = re.sub(r"\n```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = _JSON_BLOCK.search(text)
            if not match:
                raise
            return json.loads(match.group(0))

    def _record(self, **kwargs) -> LlmCall:
        call = LlmCall(
            call_id=str(uuid.uuid4()),
            run_id=get_run_id(),
            created_at=datetime.now(timezone.utc).isoformat(),
            **kwargs,
        )
        self.calls.append(call)
        self.run_cost += call.cost_usd
        return call

    def run_prompt(
        self,
        prompt: Prompt | str,
        stage: str,
        cache_content: str,
        tier: str | None = None,
        video_url: str | None = None,
        **render_kwargs,
    ) -> LlmResult:
        """Render a prompt, call the model, validate against the prompt's schema."""
        prompt_obj = load_prompt(prompt) if isinstance(prompt, str) else prompt
        tier = tier or prompt_obj.tier
        model = self.model_for(tier)
        rendered = prompt_obj.render(**render_kwargs)

        key = cache_key(cache_content, prompt_obj.name, prompt_obj.version, tier, model)
        cached = self.cache.get(key)
        if cached is not None:
            call = self._record(
                stage=stage, prompt_name=prompt_obj.name, prompt_version=prompt_obj.version,
                tier=tier, model=model, provider="cache", cache_hit=True, ok=True,
            )
            return LlmResult(cached, call)

        budget = float(self.limits.get("max_cost_per_run_usd", 5.0))
        if self.run_cost >= budget:
            raise LlmBudgetExceeded(f"run cost {self.run_cost:.4f} hit the {budget} cap")

        timeout = float(self.limits.get("timeout_seconds", 90))
        max_tokens = int(self.limits.get("max_output_tokens", 4096))
        retries = int(self.limits.get("max_retries", 4))
        backoff = float(self.limits.get("retry_backoff_seconds", 2))

        provider = self._get_video_provider() if tier == "video" else self._get_provider()
        if provider is None:
            raise RuntimeError("video tier requested but CI_VIDEO_PROVIDER is none")
        if hasattr(provider, "set_schema"):
            provider.set_schema(prompt_obj.schema)

        last_error = ""
        for attempt in range(1, retries + 1):
            try:
                if tier == "video":
                    resp = provider.analyse_video(model, video_url or "", rendered, max_tokens, timeout)
                else:
                    resp = provider.complete(
                        model, "Reply with a single JSON object and nothing else.",
                        rendered, max_tokens, timeout,
                    )
                data = self._extract_json(resp.text)
                errors = validate_against_schema(data, prompt_obj.schema)
                if errors:
                    raise ValueError("schema validation failed: " + "; ".join(errors[:4]))
                call = self._record(
                    stage=stage, prompt_name=prompt_obj.name, prompt_version=prompt_obj.version,
                    tier=tier, model=model, provider=resp.provider,
                    input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
                    cost_usd=self.cost(model, resp.input_tokens, resp.output_tokens),
                    cache_hit=False, ok=True,
                )
                self.cache.set(key, data)
                return LlmResult(data, call)
            except Exception as exc:  # noqa: BLE001 - retried and logged
                last_error = f"{type(exc).__name__}: {exc}"
                log_event(log, logging.WARNING, "llm attempt failed",
                          stage=stage, prompt=prompt_obj.name, attempt=attempt, error=last_error)
                if attempt < retries:
                    time.sleep(backoff * attempt)

        call = self._record(
            stage=stage, prompt_name=prompt_obj.name, prompt_version=prompt_obj.version,
            tier=tier, model=model, provider=getattr(provider, "name", "?"),
            ok=False, error=last_error,
        )
        raise RuntimeError(f"llm call failed after {retries} attempts: {last_error}")

    def call_rows(self) -> list[dict]:
        return [c.model_dump() for c in self.calls]

    def stats(self) -> dict[str, Any]:
        return {
            "calls": len(self.calls),
            "cost_usd": round(self.run_cost, 6),
            **self.cache.stats(),
        }
