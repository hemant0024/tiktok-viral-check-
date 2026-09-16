"""api.health tells apart the several different reasons a screen can be empty."""
from __future__ import annotations

from ci.dashboard import api


class FakeRepo:
    def __init__(self, tables):
        self.tables = tables

    def read(self, name):
        return self.tables.get(name, [])


def _diagnose(tables, settings, **overrides):
    # A copy, never the cached Settings object: mutating that one leaks into
    # every test that runs after this file.
    return api.health(settings.model_copy(update=overrides), FakeRepo(tables))["diagnosis"]


def test_nothing_collected_without_a_token_names_the_token(settings):
    d = _diagnose({}, settings, apify_token=None)
    assert "APIFY_TOKEN" in d["detail"]
    assert d["action"] == "", "there is nothing useful to click without a token"


def test_nothing_collected_with_a_token_offers_the_sweep(settings):
    d = _diagnose({}, settings, apify_token="tok")
    assert d["action"] == "collect_ugc"


def test_collected_but_never_scored_offers_the_free_fix(settings):
    d = _diagnose({"RAW_CONTENT": [{"content_id": "a"}]}, settings)
    assert d["action"] == "rescore"
    assert "1 videos" in d["detail"] or "1 video" in d["detail"]


def test_scores_with_no_collection_behind_them(settings):
    """Exactly the state a seeded demo leaves behind: re-scoring cannot help."""
    d = _diagnose({"RADAR": [{"date": "2026-09-11"}] * 52}, settings)
    assert d["action"] == "collect_ugc"
    assert "52" in d["headline"]


def test_a_healthy_store_says_nothing(settings):
    d = _diagnose({"RADAR": [{"date": "2026-09-11"}],
                   "RAW_CONTENT": [{"content_id": "a"}],
                   "CONTENT_SNAPSHOTS": [{"content_id": "a"}]}, settings)
    assert d["headline"] == ""


def test_one_measurement_each_is_called_out(settings):
    """With a single reading per video the two movement signals, 40% of the
    score between them, cannot be calculated at all."""
    d = _diagnose({"RADAR": [{"date": "2026-09-11"}],
                   "RAW_CONTENT": [{"content_id": "a"}]}, settings)
    assert d["action"] == "watch"
