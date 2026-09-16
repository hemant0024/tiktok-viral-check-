"""Phase 4 edge cases. These are the ones that silently corrupt a report."""
from __future__ import annotations

import pytest
from datetime import timedelta

from tests.helpers import make_content, snap

from ci.scoring.velocity import compute_velocity, heat_score

pytestmark = pytest.mark.unit


def test_single_snapshot_is_low_confidence(scoring, now):
    content = make_content(views=240000, hours_old=48).model_dump()
    v = compute_velocity(content, [snap(0, 240000)], scoring["velocity"], scoring["breakout"], now)
    assert v.confidence == "low"
    assert v.confidence_factor == pytest.approx(0.7)
    assert v.views_per_day == pytest.approx(120000, rel=0.01)


def test_two_snapshots_give_real_growth_at_high_confidence(scoring, now):
    content = make_content(views=200000, hours_old=72).model_dump()
    snaps = [snap(48, 50000), snap(0, 200000)]
    v = compute_velocity(content, snaps, scoring["velocity"], scoring["breakout"], now)
    assert v.confidence == "high"
    assert v.views_per_day == pytest.approx(75000, rel=0.01)


def test_readings_closer_than_the_gap_are_collapsed(scoring, now):
    """The gap is 0.5h now that `ci watch` polls every 30 minutes. Readings taken
    minutes apart are still noise and must not each count as a data point."""
    content = make_content(views=100000, hours_old=48).model_dump()
    snaps = [
        {"captured_at": (now - timedelta(minutes=m)).isoformat(), "views": v}
        for m, v in [(20, 96000), (12, 98000), (5, 99000), (0, 100000)]
    ]
    v = compute_velocity(content, snaps, scoring["velocity"], scoring["breakout"], now)
    assert v.snapshots_used == 4
    assert v.confidence == "low", "four readings inside 30 minutes is still one reading"


def test_hourly_readings_now_count_as_real_data(scoring, now):
    """The 12h gap threw away hourly polling and reported 'one snapshot only' on
    videos that had six readings."""
    content = make_content(views=100000, hours_old=6).model_dump()
    snaps = [snap(h, v) for h, v in [(5, 10000), (4, 25000), (3, 45000), (2, 70000), (0, 100000)]]
    v = compute_velocity(content, snaps, scoring["velocity"], scoring["breakout"], now)
    assert v.confidence == "high"


def test_zero_time_between_snapshots_does_not_divide_by_zero(scoring, now):
    content = make_content(views=100).model_dump()
    same = snap(0, 100)
    v = compute_velocity(content, [same, dict(same)], scoring["velocity"], scoring["breakout"], now)
    assert v.views_per_day >= 0


def test_no_snapshots_and_no_publish_date_survives(scoring, now):
    content = make_content(views=5000).model_dump()
    content["published_at"] = None
    v = compute_velocity(content, [], scoring["velocity"], scoring["breakout"], now)
    assert v.views_per_day == pytest.approx(5000)
    assert v.confidence == "low"


def test_old_viral_video_loses_to_fresh_fast_grower(scoring, now):
    """The whole point of the recency window. A 3 year old 10M view video
    computes to ~9k views a day and must not read as a rocket."""
    old = make_content(cid="old", views=10_000_000, hours_old=1095 * 24).model_dump()
    old_v = compute_velocity(old, [snap(0, 10_000_000, "old")], scoring["velocity"], scoring["breakout"], now)

    fresh = make_content(cid="fresh", views=50000, hours_old=18, saves=3000, shares=1500).model_dump()
    fresh_snaps = [snap(36, 0, "fresh"), snap(24, 4000, "fresh"),
                   snap(12, 18000, "fresh"), snap(0, 50000, "fresh")]
    fresh_v = compute_velocity(fresh, fresh_snaps, scoring["velocity"], scoring["breakout"], now)

    assert old_v.is_breakout is False
    assert fresh_v.is_breakout is True
    heat_cfg = scoring["cheap_filter"]["heat"]
    assert heat_score(fresh, fresh_v, heat_cfg) > heat_score(old, old_v, heat_cfg)


def test_acceleration_needs_three_readings(scoring, now):
    content = make_content(views=50000, hours_old=30).model_dump()
    two = compute_velocity(content, [snap(24, 10000), snap(0, 50000)],
                           scoring["velocity"], scoring["breakout"], now)
    assert two.acceleration == 0.0
    three = compute_velocity(content, [snap(48, 0), snap(24, 10000), snap(0, 50000)],
                             scoring["velocity"], scoring["breakout"], now)
    assert three.acceleration > 0


def test_decelerating_video_is_not_a_breakout(scoring, now):
    content = make_content(views=500000, hours_old=60).model_dump()
    snaps = [snap(48, 300000), snap(24, 460000), snap(0, 500000)]
    v = compute_velocity(content, snaps, scoring["velocity"], scoring["breakout"], now)
    assert v.acceleration < 0
    assert v.is_breakout is False


def test_young_and_fast_without_history_is_provisional(scoring, now):
    content = make_content(views=40000, hours_old=6).model_dump()
    v = compute_velocity(content, [snap(0, 40000)], scoring["velocity"], scoring["breakout"], now)
    assert v.is_breakout is True
    assert v.breakout_multiplier == pytest.approx(scoring["breakout"]["provisional_bonus"])
    assert "provisional" in " ".join(v.notes)
