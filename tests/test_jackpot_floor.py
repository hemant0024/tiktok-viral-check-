"""The jackpot badge has to mean something.

Lift alone flagged 24 of the 52 videos collected on 11 Sep, including 348 views
from a 24-follower account. With no creator history, lift falls back to views
over followers, so any tiny account clears 5x on an ordinary day and the badge
stopped carrying information.
"""
from __future__ import annotations

from ci.scoring.viral_signals import takeoff_profile

CFG = {
    "expected_curve": {1: 300, 6: 1200, 24: 5000, 48: 9000},
    "tiers": [
        {"name": "EXPLODING", "min_views": 200000, "max_age_hours": 24},
        {"name": "BREAKING OUT", "min_views": 50000, "max_age_hours": 24},
        {"name": "INTERESTING", "min_views": 10000, "max_age_hours": 24},
        {"name": "WATCH", "min_views": 0, "max_age_hours": 24},
    ],
    "max_candidate_age_hours": 72,
    "jackpot": {"max_creator_followers": 50000, "min_lift": 5.0,
                "min_views": 5000, "bonus_multiplier": 1.25},
}


def test_a_tiny_account_beating_its_tiny_normal_is_not_a_jackpot():
    row = {"views": 348, "creator_followers": 24}
    assert takeoff_profile(row, 13, CFG, creator_lift=14.5).is_jackpot is False


def test_a_tiny_account_with_real_numbers_still_is():
    row = {"views": 137876, "creator_followers": 524}
    result = takeoff_profile(row, 41, CFG, creator_lift=263.0)
    assert result.is_jackpot is True
    assert result.penalty == 1.25
    assert "137,876 views" in result.notes[-1]


def test_the_floor_is_configurable():
    cfg = {**CFG, "jackpot": {**CFG["jackpot"], "min_views": 0}}
    row = {"views": 348, "creator_followers": 24}
    assert takeoff_profile(row, 13, cfg, creator_lift=14.5).is_jackpot is True


def test_a_big_account_never_qualifies_however_big_the_video():
    row = {"views": 900000, "creator_followers": 4000000}
    assert takeoff_profile(row, 10, CFG, creator_lift=9.0).is_jackpot is False


def test_the_floor_survives_an_unusable_publish_time():
    """Age under six minutes means we do not know when it was posted, so pace is
    refused. The jackpot check does not depend on age and must still run."""
    row = {"views": 60000, "creator_followers": 800}
    result = takeoff_profile(row, 0.0, CFG, creator_lift=75.0)
    assert result.is_jackpot is True
    assert result.tier == "UNKNOWN AGE"
