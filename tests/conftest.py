from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from ci.config import get_settings, reset_settings_cache  # noqa: E402
from ci.database import InMemoryRepository  # noqa: E402
from tests.helpers import NOW  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Every test gets its own data dir.

    Without this the LLM response cache persists into the repo's data/ folder
    between runs, and one test silently answers another. That actually happened.
    """
    monkeypatch.setenv("CI_LOCAL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CI_STORAGE_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def scoring(settings):
    return settings.scoring


@pytest.fixture
def repo():
    return InMemoryRepository()


@pytest.fixture
def now():
    return NOW
