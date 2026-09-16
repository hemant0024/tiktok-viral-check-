"""We track videos and hooks, not accounts."""
from __future__ import annotations

import pytest

from ci.collectors.competitor_ugc import CompetitorUgcCollector
from ci.models import NormalizedContent

pytestmark = pytest.mark.unit


def video(title="", creator="someone", tags=None):
    return NormalizedContent(
        content_id=f"tiktok:{creator}", date_found="2026-09-10", platform="tiktok",
        source="test", url="https://example.com/x", creator=creator,
        title=title, hashtags=tags or [],
    )


def test_duolingo_is_off_the_list_for_good(settings):
    names = [c["name"] for c in settings.competitors["competitors"]]
    assert "Duolingo" not in names
    assert len(names) == 17


def test_a_video_mentioning_duolingo_is_no_longer_attributed(settings):
    c = CompetitorUgcCollector(settings)
    assert c.attribute(video("duolingo streak meme", tags=["duolingo"])) == ""


def test_real_competitors_still_attribute(settings):
    c = CompetitorUgcCollector(settings)
    assert c.attribute(video("i tried linguza for 30 days", tags=["linguza"])) == "Linguza"
    assert c.attribute(video("praktika ai review", tags=[])) == "Praktika AI"


def test_brand_owned_handles_are_known(settings):
    """A brand posting on its own account is marketing, not a signal that
    something is spreading."""
    c = CompetitorUgcCollector(settings)
    handles = c.brand_handles()
    assert "elsaspeak" in handles
    assert "cambly" in handles
    assert "preply" in handles


def test_a_random_creator_is_not_treated_as_a_brand(settings):
    c = CompetitorUgcCollector(settings)
    assert "averagejoeonair" not in c.brand_handles()


def test_keyword_plan_covers_every_competitor_before_repeating(settings):
    c = CompetitorUgcCollector(settings)
    plan = c.keyword_plan(1)
    covered = {name for _, name in plan}
    assert len(covered) == len(c.competitors()), "every brand gets a keyword before any gets two"
    assert not any("duolingo" in k.lower() for k, _ in plan)
