"""Loads .env and config/*.yaml. Nothing else reads os.environ or the yaml files."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
PROMPTS_DIR = REPO_ROOT / "prompts"


class Settings(BaseModel):
    storage_backend: str = "local"
    local_data_dir: Path = REPO_ROOT / "data"
    google_service_account_json: str | None = None
    google_sheet_id: str | None = None

    llm_provider: str = "openai"
    llm_cheap_model: str = "gpt-5.6-luna"
    llm_strong_model: str = "gpt-5.6-sol"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"

    video_provider: str = "none"
    video_model: str = "gemini-3.8-flash"
    gemini_api_key: str | None = None

    youtube_api_key: str | None = None
    apify_token: str | None = None

    slack_bot_token: str | None = None
    slack_channel: str = "#creative-radar"
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    log_level: str = "INFO"
    dry_run: bool = False

    product: dict[str, Any] = Field(default_factory=dict)
    competitors: dict[str, Any] = Field(default_factory=dict)
    sources: dict[str, Any] = Field(default_factory=dict)
    scoring: dict[str, Any] = Field(default_factory=dict)

    # --- convenience accessors so callers never dig raw dicts for common things ---
    @property
    def market_country(self) -> str:
        return self.product.get("market", {}).get("country", "US")

    @property
    def timezone_name(self) -> str:
        return self.product.get("market", {}).get("timezone", "UTC")

    @property
    def cat_roles(self) -> list[str]:
        return list(self.product.get("mascot", {}).get("roles", []))

    def scoring_section(self, name: str) -> dict[str, Any]:
        return self.scoring.get(name, {})


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env", override=False)
    data_dir = Path(os.getenv("CI_LOCAL_DATA_DIR", str(REPO_ROOT / "data")))
    return Settings(
        storage_backend=os.getenv("CI_STORAGE_BACKEND", "local"),
        local_data_dir=data_dir if data_dir.is_absolute() else (REPO_ROOT / data_dir),
        google_service_account_json=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"),
        google_sheet_id=os.getenv("GOOGLE_SHEET_ID"),
        llm_provider=os.getenv("CI_LLM_PROVIDER", "openai"),
        llm_cheap_model=os.getenv("CI_LLM_CHEAP_MODEL", "gpt-5.6-luna"),
        llm_strong_model=os.getenv("CI_LLM_STRONG_MODEL", "gpt-5.6-sol"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        video_provider=os.getenv("CI_VIDEO_PROVIDER", "none"),
        video_model=os.getenv("CI_VIDEO_MODEL", "gemini-3.8-flash"),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        youtube_api_key=os.getenv("YOUTUBE_API_KEY"),
        apify_token=os.getenv("APIFY_TOKEN"),
        slack_bot_token=os.getenv("SLACK_BOT_TOKEN"),
        slack_channel=os.getenv("SLACK_CHANNEL", "#creative-radar"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        log_level=os.getenv("CI_LOG_LEVEL", "INFO"),
        dry_run=_as_bool(os.getenv("CI_DRY_RUN"), False),
        product=_load_yaml(CONFIG_DIR / "product.yaml"),
        competitors=_load_yaml(CONFIG_DIR / "competitors.yaml"),
        sources=_load_yaml(CONFIG_DIR / "sources.yaml"),
        scoring=_load_yaml(CONFIG_DIR / "scoring.yaml"),
    )


def reset_settings_cache() -> None:
    get_settings.cache_clear()
