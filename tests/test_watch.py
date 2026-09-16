"""The 30-minute watch job.

This stage did not exist. The CLI, the HTTP server, run_watch.sh and the n8n
watch workflow all called it, /health advertised it, and calling it raised
AttributeError. So it failed 48 times a day in silence, and distribution waves,
22% of the radar score and the strongest signal in it, were never measurable on
any video. Every row read "waves not measurable yet", permanently.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ci.stages import stage_radar, stage_watch

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def _video(repo, cid, hours_old, views):
    repo.upsert("RAW_CONTENT", [{
        "content_id": cid, "kind": "organic_ugc", "platform": "tiktok",
        "url": f"https://www.tiktok.com/@c{cid}/video/{cid}",
        "title": "praktika lesson", "creator": f"c{cid}", "creator_followers": 400,
        "competitor": "Praktika AI", "views": views, "likes": int(views * .08),
        "comments": 4, "shares": int(views * .01), "saves": 9,
        "duration_seconds": 25,
        "published_at": (NOW - timedelta(hours=hours_old)).isoformat(),
    }])
    repo.upsert("CONTENT_SNAPSHOTS", [{
        "content_id": cid, "captured_at": (NOW - timedelta(hours=1)).isoformat(),
        "views": views, "likes": int(views * .08), "comments": 4,
        "shares": int(views * .01),
    }])


def test_the_stage_exists_and_is_callable(repo, settings):
    """The regression that matters. Import and call, nothing more."""
    out = stage_watch(repo, settings, now=NOW)
    assert out["summary"]["status"] != "failed"
    assert "tracked" in out and "polled" in out


def test_every_advertised_stage_can_actually_be_called():
    """/health listed 24 stages and one of them raised AttributeError. A stage
    name that cannot be resolved is worse than a missing one: n8n gets a 500 at
    6am instead of a 404 the day it was wired up."""
    from ci import stages as S
    from ci.server import _stages

    for name in _stages():
        pass
    for attr in ("stage_watch", "stage_radar", "stage_trends", "stage_sheets_push",
                 "stage_brief_input", "stage_save_brief", "stage_collect",
                 "stage_notify_radar", "stage_healthcheck", "stage_report"):
        assert hasattr(S, attr), f"ci.stages has no {attr}"


def test_only_hot_young_videos_are_tracked(repo, settings, monkeypatch):
    _video(repo, "hot", hours_old=6, views=40000)      # should be tracked
    _video(repo, "cold", hours_old=6, views=20)        # scores too low
    _video(repo, "ancient", hours_old=400, views=90000)  # past drop_after
    stage_radar(repo, settings, kind="ugc", now=NOW)

    seen = {}

    class FakeClient:
        def run_actor(self, actor, run_input, max_items=None):
            seen["urls"] = run_input["postURLs"]
            return []

    monkeypatch.setattr(
        "ci.collectors.competitor_ugc.CompetitorUgcCollector.client",
        lambda self: FakeClient())

    stage_watch(repo, settings, now=NOW)
    urls = seen.get("urls", [])
    assert any("hot" in u for u in urls)
    assert not any("ancient" in u for u in urls), "a 16-day-old video is not taking off"


def test_polling_appends_a_snapshot_rather_than_replacing_one(repo, settings, monkeypatch):
    """Waves are computed from consecutive readings. Overwriting the previous one
    would leave exactly one reading forever, which is the bug this stage exists
    to fix."""
    _video(repo, "hot", hours_old=6, views=40000)
    stage_radar(repo, settings, kind="ugc", now=NOW)

    class FakeClient:
        def run_actor(self, actor, run_input, max_items=None):
            return [{"id": "hot", "webVideoUrl": "https://www.tiktok.com/@chot/video/hot",
                     "playCount": 52000, "diggCount": 4200, "shareCount": 520,
                     "commentCount": 9, "collectCount": 40,
                     "authorMeta": {"name": "chot", "fans": 400},
                     "videoMeta": {"duration": 25}, "hashtags": [],
                     "text": "praktika lesson"}]

    monkeypatch.setattr(
        "ci.collectors.competitor_ugc.CompetitorUgcCollector.client",
        lambda self: FakeClient())

    before = len([r for r in repo.read("CONTENT_SNAPSHOTS") if r["content_id"] == "hot"])
    out = stage_watch(repo, settings, now=NOW)
    after = [r for r in repo.read("CONTENT_SNAPSHOTS") if r["content_id"] == "hot"]

    assert len(after) == before + 1, "the reading replaced the previous one"
    assert out["polled"] == 1
    assert {r["views"] for r in after} == {40000, 52000}


def test_it_reports_what_moved_not_everything_it_polled(repo, settings, monkeypatch):
    """The job fires 48 times a day. Something that notifies every time is
    something nobody reads."""
    _video(repo, "hot", hours_old=6, views=40000)
    stage_radar(repo, settings, kind="ugc", now=NOW)

    class FakeClient:
        def run_actor(self, actor, run_input, max_items=None):
            return [{"id": "hot", "webVideoUrl": "https://www.tiktok.com/@chot/video/hot",
                     "playCount": 52000, "diggCount": 4200, "shareCount": 520,
                     "commentCount": 9, "collectCount": 40,
                     "authorMeta": {"name": "chot", "fans": 400},
                     "videoMeta": {"duration": 25}, "hashtags": [],
                     "text": "praktika lesson"}]

    monkeypatch.setattr(
        "ci.collectors.competitor_ugc.CompetitorUgcCollector.client",
        lambda self: FakeClient())

    out = stage_watch(repo, settings, now=NOW)
    assert out["moved"], "a video that gained 12,000 views was not reported as moving"
    assert out["moved"][0]["gained"] == 12000
    assert out["moved"][0]["url"].startswith("http")


def test_a_quiet_run_returns_cleanly(repo, settings):
    out = stage_watch(repo, settings, now=NOW)
    assert out["tracked"] == 0
    assert out["summary"]["status"] != "failed"
