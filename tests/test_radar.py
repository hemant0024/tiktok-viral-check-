"""Viral radar. The point is being EARLY, so these tests are mostly about
whether small numbers can still register."""
from __future__ import annotations

import pytest

from ci.scoring.radar import (
    COOLING, EARLY_SIGNAL, EXPLODING, LIKELY, NEW_WATCH, PROVEN, TEST_SIGNAL,
    apply_feed_caps, compute_lift, radar_score, winner_signal,
)
from datetime import datetime, timezone

from ci.scoring.velocity import compute_velocity
from tests.helpers import make_content, snap

pytestmark = pytest.mark.unit


def vel(content, snaps, scoring, now):
    return compute_velocity(content.model_dump(), snaps, scoring["velocity"],
                            scoring["breakout"], now)


def test_small_creator_breaking_out_beats_a_big_creator_flatlining(scoring, now):
    """The whole premise. 388 views can matter more than 1,557."""
    small = make_content(cid="small", views=388, hours_old=44, creator="tiny", saves=1, likes=49)
    big = make_content(cid="big", views=1557, hours_old=41, creator="huge", saves=4, likes=72)
    small_c, big_c = small.model_dump(), big.model_dump()
    small_c["creator_followers"], big_c["creator_followers"] = 92, 19756

    s = radar_score(small_c, vel(small, [snap(14, 213, "small"), snap(0, 388, "small")], scoring, now),
                    [], scoring["radar"])
    b = radar_score(big_c, vel(big, [snap(14, 856, "big"), snap(0, 1557, "big")], scoring, now),
                    [], scoring["radar"])
    assert s.radar_score > b.radar_score
    assert s.creator_lift > b.creator_lift


def test_acceleration_weight_is_redistributed_when_unmeasurable(scoring, now):
    """The bug this exists for: acceleration needs 3 snapshots, so scoring it as
    zero made 35% of the score dead on day one and nothing could ever reach
    EXPLODING until day three."""
    c = make_content(cid="c", views=50000, hours_old=20, saves=3000, shares=1500)
    payload = c.model_dump()
    payload["creator_followers"] = 5000

    two = radar_score(payload, vel(c, [snap(14, 27500, "c"), snap(0, 50000, "c")], scoring, now),
                      [], scoring["radar"])
    assert two.components["acceleration"] is None
    assert "acceleration" not in two.measured
    assert two.radar_score > 0

    three = radar_score(payload, vel(c, [snap(28, 4000, "c"), snap(14, 20000, "c"),
                                         snap(0, 50000, "c")], scoring, now), [], scoring["radar"])
    assert three.components["acceleration"] is not None
    assert "acceleration" in three.measured


def test_creator_history_beats_the_follower_fallback(scoring):
    history = [{"content_id": f"o{i}", "views": v} for i, v in enumerate([11000, 9000, 14000, 12000])]
    content = {"content_id": "x", "views": 180000, "creator_followers": 21000}
    lift, baseline, source = compute_lift(content, history, scoring["radar"])
    assert source == "history"
    assert baseline == 11500
    assert lift == pytest.approx(180000 / 11500)


def test_too_little_history_falls_back_to_followers(scoring):
    content = {"content_id": "x", "views": 400, "creator_followers": 100}
    lift, baseline, source = compute_lift(content, [{"content_id": "o1", "views": 50}],
                                          scoring["radar"])
    assert source == "followers"
    assert lift == pytest.approx(4.0)


def test_no_followers_and_no_history_is_not_a_crash(scoring):
    lift, baseline, source = compute_lift({"content_id": "x", "views": 100}, [], scoring["radar"])
    assert source == "none" and lift == 0.0


def test_decelerating_video_reads_as_cooling(scoring, now):
    c = make_content(cid="d", views=500000, hours_old=200)
    v = vel(c, [snap(60, 300000, "d"), snap(30, 460000, "d"), snap(0, 500000, "d")], scoring, now)
    result = radar_score(c.model_dump(), v, [], scoring["radar"])
    assert result.status == COOLING


def test_young_and_fast_reaches_exploding(scoring, now):
    c = make_content(cid="e", views=400000, hours_old=18, saves=30000, shares=18000, likes=60000)
    payload = c.model_dump()
    payload["creator_followers"] = 8000
    v = vel(c, [snap(36, 5000, "e"), snap(18, 90000, "e"), snap(0, 400000, "e")], scoring, now)
    assert radar_score(payload, v, [], scoring["radar"]).status == EXPLODING


# --------------------------------------------------------------------------- #
# Ads are scored on money over time, because the Ad Library exposes no views.
# --------------------------------------------------------------------------- #
def test_long_running_ad_with_many_variations_beats_a_new_single(scoring):
    """The spec's own Phase 4 case: 90 days with 8 variations vs 3 days with 1."""
    cfg = scoring["winner_signal"]
    strong = winner_signal({"days_running": 90, "variation_count": 8,
                            "publisher_platforms": ["FACEBOOK", "INSTAGRAM"]}, cfg)
    weak = winner_signal({"days_running": 3, "variation_count": 1,
                          "publisher_platforms": ["FACEBOOK"]}, cfg)
    assert strong.radar_score > weak.radar_score
    assert strong.status == PROVEN
    assert weak.status == TEST_SIGNAL


def test_the_real_linguza_ad_is_not_scored_zero(scoring):
    """It has no views because Meta publishes none. Scoring it on views put the
    strongest signal in the dataset at the bottom of the feed."""
    result = winner_signal({
        "days_running": 99, "variation_count": 5, "views": 0,
        "publisher_platforms": ["FACEBOOK", "INSTAGRAM", "MESSENGER", "THREADS"],
    }, scoring["winner_signal"])
    assert result.radar_score > 50
    assert result.status in {PROVEN, LIKELY}
    assert result.components["engagement"] is None
    assert any("99 days" in r for r in result.reasons)


def test_hook_reuse_across_competitors_lifts_an_ad(scoring):
    cfg = scoring["winner_signal"]
    alone = winner_signal({"days_running": 40, "variation_count": 3,
                           "publisher_platforms": ["FACEBOOK"]}, cfg, reused_by_competitors=0)
    shared = winner_signal({"days_running": 40, "variation_count": 3,
                            "publisher_platforms": ["FACEBOOK"]}, cfg, reused_by_competitors=4)
    assert shared.radar_score > alone.radar_score


# --------------------------------------------------------------------------- #
def test_variation_group_collapses_to_its_longest_running_ad(scoring):
    rows = [
        {"content_id": f"a{i}", "radar_score": 55.2, "creator": "Linguza",
         "competitor": "Linguza", "variation_group": "var_1", "days_running": d}
        for i, d in enumerate([65, 69, 70, 99, 20])
    ]
    feed = apply_feed_caps(rows, scoring["radar"])
    assert len(feed) == 1
    assert feed[0]["days_running"] == 99


def test_one_loud_creator_cannot_own_the_feed(scoring):
    rows = [{"content_id": f"x{i}", "radar_score": 90 - i, "creator": "spammer",
             "competitor": "", "variation_group": ""} for i in range(10)]
    feed = apply_feed_caps(rows, scoring["radar"])
    assert len(feed) <= scoring["radar"]["feed"]["max_per_creator"]


def test_below_threshold_rows_never_reach_the_feed(scoring):
    rows = [{"content_id": "x", "radar_score": 5, "creator": "c", "competitor": "",
             "variation_group": ""}]
    assert apply_feed_caps(rows, scoring["radar"]) == []


# --------------------------------------------------------------------------- #
# Day over day movement. Only computable because RADAR keeps history.
# --------------------------------------------------------------------------- #
def _radar_history():
    return [
        {"date": "2026-09-08", "content_id": "a", "radar_score": 30, "views": 5000,
         "competitor": "Praktika AI", "creator": "x", "url": "u1", "hashtags": ["praktika"]},
        {"date": "2026-09-09", "content_id": "a", "radar_score": 45, "views": 22000,
         "competitor": "Praktika AI", "creator": "x", "url": "u1", "hashtags": ["praktika"]},
        {"date": "2026-09-10", "content_id": "a", "radar_score": 68, "views": 90000,
         "competitor": "Praktika AI", "creator": "x", "url": "u1", "hashtags": ["praktika"]},
        {"date": "2026-09-09", "content_id": "b", "radar_score": 74, "views": 40000,
         "competitor": "Loora AI", "creator": "y", "url": "u2", "hashtags": ["loora"]},
        {"date": "2026-09-10", "content_id": "b", "radar_score": 53, "views": 46000,
         "competitor": "Loora AI", "creator": "y", "url": "u2", "hashtags": ["loora"]},
        {"date": "2026-09-09", "content_id": "d", "radar_score": 35, "views": 9000,
         "competitor": "Cambly", "creator": "w", "url": "u4", "hashtags": ["cambly"]},
    ]


def test_a_climbing_video_is_marked_rising_with_its_streak():
    from ci.scoring.trends import RISING, video_trends

    trends = {t.content_id: t for t in video_trends(_radar_history(), "2026-09-10")}
    a = trends["a"]
    assert a.direction == RISING
    assert a.score_delta == pytest.approx(23)
    assert a.days_on_radar == 3
    assert a.views_gained == 68000
    assert "3 days" in a.note


def test_a_cooling_video_is_marked_falling():
    from ci.scoring.trends import FALLING, video_trends

    trends = {t.content_id: t for t in video_trends(_radar_history(), "2026-09-10")}
    assert trends["b"].direction == FALLING
    assert trends["b"].rank_change < 0, "it lost rank"


def test_videos_that_left_the_radar_are_reported():
    from ci.scoring.trends import dropped_off

    gone = dropped_off(_radar_history(), "2026-09-10")
    assert [g["content_id"] for g in gone] == ["d"]


def test_competitor_direction_weighs_score_not_just_video_count():
    """Counting videos alone called Loora FLAT while its average score fell from
    74 to 53, which is the opposite of flat."""
    from ci.scoring.trends import FALLING, competitor_trends

    by_name = {c.competitor: c for c in competitor_trends(_radar_history(), "2026-09-10")}
    assert by_name["Loora AI"].videos_now == by_name["Loora AI"].videos_prev
    assert by_name["Loora AI"].direction == FALLING


def test_trends_need_two_days_before_they_mean_anything(repo, settings):
    from ci.stages import stage_trends

    repo.upsert("RADAR", [_radar_history()[-1]])
    result = stage_trends(repo, settings, datetime(2026, 9, 10, tzinfo=timezone.utc))
    assert result["videos"] == 0
    assert "one day" in result["note"]


def test_hashtag_movement_is_tracked():
    from ci.scoring.trends import hashtag_trends

    rows = {h["hashtag"]: h for h in hashtag_trends(_radar_history(), "2026-09-10")}
    assert rows["cambly"]["delta"] == -1
