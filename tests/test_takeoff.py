"""Takeoff detection. Views relative to AGE, not views.

Cases are Hemant's own worked examples.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone  # noqa: F401

import pytest

from ci.scoring.viral_signals import (
    BREAKING_OUT, FLAT, PEAKED, VIRAL, analyse_waves, engagement_ratios,
    expected_views_at, takeoff_profile, viral_profile,
)

pytestmark = pytest.mark.unit
NOW = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)


def snap_h(hours_ago, views):
    return {"captured_at": (NOW - timedelta(hours=hours_ago)).isoformat(), "views": views}


# --------------------------------------------------------------------------- #
# Views relative to age
# --------------------------------------------------------------------------- #
def test_two_million_views_three_weeks_old_is_already_viral(scoring):
    t = takeoff_profile({"views": 2_000_000, "creator_followers": 900_000}, 504,
                        scoring["takeoff"])
    assert t.is_already_viral is True
    assert t.penalty < 0.5, "already-viral must be downranked, we are late"


def test_eight_hundred_thousand_two_days_old_is_already_viral(scoring):
    t = takeoff_profile({"views": 800_000}, 48, scoring["takeoff"])
    assert t.is_already_viral is True


def test_eighteen_thousand_at_four_hours_is_a_live_candidate(scoring):
    t = takeoff_profile({"views": 18_000, "creator_followers": 12_000}, 4, scoring["takeoff"])
    assert t.is_already_viral is False
    assert t.tier == "INTERESTING"
    assert t.penalty == 1.0


def test_seven_thousand_at_one_hour_is_a_live_candidate(scoring):
    t = takeoff_profile({"views": 7_000, "creator_followers": 3_000}, 1, scoring["takeoff"])
    assert t.is_already_viral is False
    assert t.vs_expected > 1.0, "7K at 1h is above the normal curve"


def test_small_account_with_huge_numbers_is_the_jackpot(scoring):
    """80K in 6 hours from an account that normally gets 4K."""
    t = takeoff_profile({"views": 80_000, "creator_followers": 4_000}, 6,
                        scoring["takeoff"], creator_lift=20.0)
    assert t.is_jackpot is True
    assert t.penalty > 1.0


def test_big_creator_getting_big_numbers_is_not_the_jackpot(scoring):
    t = takeoff_profile({"views": 500_000, "creator_followers": 800_000}, 6,
                        scoring["takeoff"], creator_lift=0.6)
    assert t.is_jackpot is False


def test_viral_curve_holds_the_takeoff_benchmarks(scoring):
    """Hemant's original numbers describe a VIRAL trajectory, so they live in
    viral_curve. Using them as the 'normal' denominator made every real video
    read as below par and killed the pace signal."""
    curve = scoring["takeoff"]["viral_curve"]
    assert expected_views_at(1, curve) == pytest.approx(5000)
    assert expected_views_at(6, curve) == pytest.approx(60000)
    assert expected_views_at(24, curve) == pytest.approx(300000)


def test_expected_curve_is_calibrated_to_real_videos(scoring):
    """Measured on a real US pull: median competitor-keyword video was about
    8.5K views at 18 hours."""
    curve = scoring["takeoff"]["expected_curve"]
    at_18h = expected_views_at(18, curve)
    assert 2000 < at_18h < 20000, f"normal curve at 18h is {at_18h}, not realistic"
    # Interpolates between points rather than stepping.
    assert expected_views_at(3, curve) < expected_views_at(4, curve) < expected_views_at(6, curve)


def test_baseline_is_learned_from_our_own_data(scoring):
    """A hardcoded curve goes stale. Medians from what we have actually collected
    do not."""
    from datetime import timedelta

    from ci.scoring.viral_signals import learn_baseline_curve

    rows = []
    for views in [4000, 5000, 6000, 7000, 8000, 9000, 10000, 11000, 12000]:
        rows.append({"published_at": (NOW - timedelta(hours=20)).isoformat(), "views": views})
    curve = learn_baseline_curve(rows, scoring["takeoff"], NOW)
    assert 24.0 in curve
    assert curve[24.0] == pytest.approx(8000)


def test_learned_baseline_needs_enough_samples(scoring):
    from datetime import timedelta

    from ci.scoring.viral_signals import learn_baseline_curve

    rows = [{"published_at": (NOW - timedelta(hours=20)).isoformat(), "views": 5000}] * 3
    assert learn_baseline_curve(rows, scoring["takeoff"], NOW) == {}, "3 samples is not a baseline"


def test_a_video_nobody_shares_ranks_below_one_people_share(scoring):
    """Observed live: two Duolingo videos, same account, same day. One at 5.5x
    pace with a 0.09% share rate, one at 71x pace with 4.51%. Being watched is
    not the same as spreading."""
    from ci.scoring.radar import radar_score
    from ci.scoring.velocity import compute_velocity

    def build(views, shares, likes):
        content = {"content_id": f"v{shares}", "views": views, "shares": shares,
                   "likes": likes, "comments": 200, "saves": 100,
                   "creator_followers": 18_000_000,
                   "published_at": (NOW - timedelta(hours=17)).isoformat()}
        snaps = [{"captured_at": (NOW - timedelta(hours=h)).isoformat(),
                  "views": int(views * f)} for h, f in [(17, 0.0), (8, 0.6), (0, 1.0)]]
        vel = compute_velocity(content, snaps, scoring["velocity"], scoring["breakout"], NOW)
        vp = viral_profile(content, snaps, scoring["viral_signals"], vel.age_hours, NOW)
        tp = takeoff_profile(content, vel.age_hours, scoring["takeoff"])
        return radar_score(content, vel, [], scoring["radar"], viral=vp, takeoff=tp)

    shared = build(478_597, 21_575, 83_795)
    ignored = build(34_897, 30, 1_913)
    assert shared.radar_score > ignored.radar_score * 2


def test_beyond_the_window_is_not_a_candidate(scoring):
    t = takeoff_profile({"views": 40_000}, 200, scoring["takeoff"])
    assert t.tier == "TOO OLD"


# --------------------------------------------------------------------------- #
# Distribution waves
# --------------------------------------------------------------------------- #
def test_accelerating_video_shows_waves(scoring):
    """1,000 -> 2,500 -> 7,000 -> 22,000 -> 70,000 per hour."""
    cumulative = [0, 1000, 3500, 10500, 32500, 102500]
    snaps = [snap_h(5 - i, v) for i, v in enumerate(cumulative)]
    waves = analyse_waves(snaps, scoring["viral_signals"]["waves"], NOW)
    assert waves.wave_count >= 3
    assert waves.accelerating is True
    assert all(r > 1.5 for r in waves.ratios)


def test_flat_video_shows_no_waves(scoring):
    """20,000 -> 22,000 -> 24,000 -> 25,000 per hour. More views, no waves."""
    cumulative = [0, 20000, 42000, 66000, 91000]
    snaps = [snap_h(4 - i, v) for i, v in enumerate(cumulative)]
    waves = analyse_waves(snaps, scoring["viral_signals"]["waves"], NOW)
    assert waves.wave_count == 0
    assert waves.accelerating is False


def test_accelerating_beats_flat_even_with_fewer_views(scoring):
    cfg = scoring["viral_signals"]
    acc = viral_profile(
        {"views": 102500, "likes": 10000, "shares": 1800, "comments": 600, "saves": 900},
        [snap_h(5 - i, v) for i, v in enumerate([0, 1000, 3500, 10500, 32500, 102500])],
        cfg, age_hours=5, now=NOW)
    flat = viral_profile(
        {"views": 91000, "likes": 4000, "shares": 200, "comments": 100, "saves": 150},
        [snap_h(4 - i, v) for i, v in enumerate([0, 20000, 42000, 66000, 91000])],
        cfg, age_hours=4, now=NOW)
    assert acc.phase == VIRAL
    assert flat.phase == FLAT


def test_waves_need_three_readings(scoring):
    waves = analyse_waves([snap_h(1, 1000), snap_h(0, 5000)],
                          scoring["viral_signals"]["waves"], NOW)
    assert waves.readings == 2
    assert waves.wave_count == 0


def test_contracting_distribution_reads_as_peaked(scoring):
    cumulative = [0, 50000, 90000, 115000, 130000]
    snaps = [snap_h(4 - i, v) for i, v in enumerate(cumulative)]
    p = viral_profile({"views": 130000, "likes": 5000, "shares": 300,
                       "comments": 200, "saves": 300}, snaps,
                      scoring["viral_signals"], age_hours=4, now=NOW)
    assert p.phase == PEAKED


# --------------------------------------------------------------------------- #
# Engagement ratios
# --------------------------------------------------------------------------- #
def test_shares_are_weighted_above_likes(scoring):
    """A like says 'I enjoyed this'. A share says 'someone else needs to see this'."""
    cfg = scoring["viral_signals"]
    sharey, _ = engagement_ratios({"views": 100000, "shares": 3000, "likes": 3000,
                                   "comments": 200, "saves": 300}, cfg)
    likey, _ = engagement_ratios({"views": 100000, "shares": 200, "likes": 10000,
                                  "comments": 200, "saves": 300}, cfg)
    assert sharey > likey


def test_ratio_bands_match_the_benchmarks(scoring):
    _, ratios = engagement_ratios({"views": 100000, "shares": 1800, "saves": 1000,
                                   "comments": 800, "likes": 12000},
                                  scoring["viral_signals"])
    assert ratios["share_rate"].value == pytest.approx(0.018)
    assert ratios["share_rate"].band in {"elevated", "viral"}
    assert ratios["save_rate"].band == "viral"
    assert ratios["like_rate"].band in {"elevated", "viral"}


def test_normal_video_lands_in_the_normal_band(scoring):
    _, ratios = engagement_ratios({"views": 100000, "shares": 300, "saves": 200,
                                   "comments": 150, "likes": 4000},
                                  scoring["viral_signals"])
    assert all(r.band == "normal" for r in ratios.values())


def test_hemants_worked_example_reads_as_breaking_out(scoring):
    """20s UGC: 50K views, 55% completion, 12% likes, 1.8% shares, 0.8% comments,
    hourly 5K -> 15K -> 40K. Completion is unavailable to us, the rest is not."""
    snaps = [snap_h(4, 0), snap_h(3, 5000), snap_h(2, 20000), snap_h(1, 60000)]
    p = viral_profile({"views": 50000, "likes": 6000, "shares": 900,
                       "comments": 400, "saves": 500}, snaps,
                      scoring["viral_signals"], age_hours=4, now=NOW)
    assert p.phase == BREAKING_OUT
    assert p.engagement_score > 70
    assert p.waves.wave_count >= 2


def test_projection_does_not_explode(scoring):
    """An early version compounded a 2.7x wave ratio for 24 hours and projected
    686 billion views."""
    snaps = [snap_h(4, 0), snap_h(3, 5000), snap_h(2, 20000), snap_h(1, 60000)]
    p = viral_profile({"views": 50000, "likes": 6000, "shares": 900,
                       "comments": 400, "saves": 500}, snaps,
                      scoring["viral_signals"], age_hours=4, now=NOW)
    cap = 50000 * scoring["takeoff"].get("max_projection_multiple", 60)
    assert p.projection["in_24h"] < 50_000_000


def test_unobtainable_metrics_are_declared_not_faked(scoring):
    p = viral_profile({"views": 1000}, [], scoring["viral_signals"], age_hours=1, now=NOW)
    assert "completion rate" in p.missing
    assert "watch time" in p.missing
