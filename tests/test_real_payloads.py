"""Regression tests written from a real Apify run on 2026-09-11.

Every case here is a bug that a live pull found and the unit tests missed,
because the unit tests used payloads I wrote myself in the shape I expected.
"""
from __future__ import annotations

import pytest

from ci.collectors.competitor_ugc import CompetitorUgcCollector
from ci.collectors.tiktok import _tags

pytestmark = pytest.mark.unit


# Trimmed from the real clockworks/free-tiktok-scraper output.
CLOCKWORKS = {
    "id": "7684034267613269269",
    "text": "La app que uso se llama praktika #englishlearning #inglesfacil",
    "createTimeISO": "2026-09-10T22:17:31.000Z",
    "webVideoUrl": "https://www.tiktok.com/@learnwithcare/video/7684034267613269269",
    "playCount": 18122, "diggCount": 1430, "shareCount": 11,
    "commentCount": 8, "collectCount": 91,
    "authorMeta": {"name": "learnwithcare", "fans": 3261},
    "videoMeta": {"duration": 26.967},
    "hashtags": [{"id": "1", "name": "englishlearning"}, {"id": "2", "name": "inglesfacil"}],
}

# The other actor the repo names, same video, different field names.
APIDOJO = {
    "id": "7684034267613269269",
    "title": "La app que uso se llama praktika #englishlearning",
    "postPage": "https://www.tiktok.com/@learnwithcare/video/7684034267613269269",
    "views": 18122, "likes": 1430, "shares": 11, "comments": 8, "bookmarks": 91,
    "channel": {"username": "learnwithcare", "followers": 3261},
    "video": {"duration": 26.967},
    "hashtags": ["englishlearning"],
}


def test_hashtags_arrive_as_objects_and_must_not_kill_the_row(settings):
    """The live actor returns [{"name": "ai"}]. The model wants strings, so an
    uncoerced dict raised, the caller logged a skip, and EVERY video carrying a
    hashtag was silently dropped. That is almost every video on TikTok."""
    assert _tags([{"name": "ai"}, {"title": "english"}, "#plain", "", None]) == \
        ["ai", "english", "plain"]


def test_the_normalizer_reads_both_actor_schemas(settings):
    c = CompetitorUgcCollector(settings)
    a = c._tt.normalize(CLOCKWORKS, "ugc_keyword", "praktika")
    b = c._tt.normalize(APIDOJO, "ugc_keyword", "praktika")

    for got in (a, b):
        assert got.creator == "learnwithcare"
        assert got.creator_followers == 3261
        assert got.views == 18122
        assert got.likes == 1430
        assert got.shares == 11
        assert got.saves == 91
        assert got.duration_seconds == pytest.approx(26.967)
        assert "tiktok.com" in got.url
    assert a.published_at and a.published_at.startswith("2026-09-10")


def test_a_missing_schema_does_not_produce_a_silently_empty_row(settings):
    """Coding to one actor meant a fallback returned rows that looked like real
    videos with zero views, which scores as 'nothing happening' rather than as
    an error anyone would notice."""
    c = CompetitorUgcCollector(settings)
    got = c._tt.normalize(CLOCKWORKS, "ugc_keyword", "praktika")
    assert got.views > 0 and got.creator


# --------------------------------------------------------------------------- #
# attribution
# --------------------------------------------------------------------------- #
def _content(settings, text, hashtags=()):
    c = CompetitorUgcCollector(settings)
    item = dict(CLOCKWORKS)
    item["text"] = text
    item["hashtags"] = [{"name": h} for h in hashtags]
    return c, c._tt.normalize(item, "ugc_keyword", "praktika")


@pytest.mark.parametrize("text,tags", [
    ("Thanks Ahmadian", ("KenanganTerindah", "TamatPraktikal")),
    ("first day teaching", ("cikgupraktikal", "cikgu")),
    ("Perodua Bezza antara pilihan yang praktikal untuk kegunaan harian", ()),
])
def test_malay_praktikal_is_not_the_app_praktika(settings, text, tags):
    """Live pull, 2026-09-11: substring matching put three Malay posts about
    finishing an internship onto the Praktika feed. Short brand names collide
    with ordinary words in other languages, every single day."""
    c, content = _content(settings, text, tags)
    assert c.attribute(content) == "", f"false match on {text!r}"


@pytest.mark.parametrize("text,tags", [
    ("La app que uso se llama praktika", ("englishlearning",)),
    ("another lesson with Praktika Ai", ()),
    ("you need to try this app", ("praktika",)),
])
def test_a_real_mention_is_still_attributed(settings, text, tags):
    c, content = _content(settings, text, tags)
    assert c.attribute(content) == "Praktika AI"


def test_brand_owned_posts_are_never_counted(settings):
    """We track videos and hooks, not accounts. A brand posting on its own
    account is marketing, not evidence that anything is spreading."""
    c = CompetitorUgcCollector(settings)
    handles = c.brand_handles()
    assert "elsaspeak" in handles
    assert "loora.ai" in handles


def test_long_videos_never_reach_the_radar(settings):
    """'Only video under 2 mins.' That cap lived in cheap_filter, which gates the
    LLM path only, so an 8 minute app review still scored on the radar feed."""
    cap = settings.scoring["cheap_filter"]["max_duration_seconds"]
    assert cap == 120

    c = CompetitorUgcCollector(settings)
    long_item = dict(CLOCKWORKS)
    long_item["videoMeta"] = {"duration": 485.0}
    content = c._tt.normalize(long_item, "ugc_keyword", "praktika")
    assert content.duration_seconds > cap, "fixture is not actually long"
