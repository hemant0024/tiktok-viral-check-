from __future__ import annotations

import pytest

from ci.scoring.scores import (
    cross_category_score, hook_score, lifecycle_label, momentum_falling_days,
    momentum_score, opportunity_label, opportunity_score,
)

pytestmark = pytest.mark.unit


def test_spec_sample_report_resolves_correctly(scoring):
    """Spec 18 shows Trend Score 91, saturation Low, five stars PRODUCE.
    The spec's own label table would have called 91 Exhausted."""
    cross = cross_category_score(6, scoring["cross_category"])
    opp = opportunity_score(91, 20, cross, 85, 88, scoring["opportunity"])
    assert opp > 75
    assert lifecycle_label(91, 20, 5, 0, scoring["lifecycle"]) == "Emerging"
    assert opportunity_label(opp, scoring["quality_gate"]) == "High opportunity"


def test_crowding_reduces_opportunity_at_identical_momentum(scoring):
    cross = cross_category_score(6, scoring["cross_category"])
    fresh = opportunity_score(91, 20, cross, 85, 88, scoring["opportunity"])
    crowded = opportunity_score(91, 85, cross, 85, 88, scoring["opportunity"])
    assert crowded < fresh


def test_saturation_over_80_is_exhausted_whatever_the_momentum(scoring):
    assert lifecycle_label(99, 85, 3, 0, scoring["lifecycle"]) == "Exhausted"


def test_momentum_falling_three_days_is_exhausted(scoring):
    assert momentum_falling_days([80, 70, 60, 50]) == 3
    assert lifecycle_label(70, 30, 20, 3, scoring["lifecycle"]) == "Exhausted"


def test_momentum_falling_resets_on_an_up_day(scoring):
    assert momentum_falling_days([80, 70, 60, 65]) == 0


def test_single_category_pattern_scores_zero_cross_category(scoring):
    assert cross_category_score(1, scoring["cross_category"]) == 0.0


def test_zero_adopters_does_not_crash_saturation(scoring):
    from ci.scoring.scores import saturation_score
    result = saturation_score({}, scoring["saturation"])
    assert result == 0.0


def test_low_confidence_velocity_caps_momentum(scoring):
    confident = momentum_score(100000, scoring["momentum"], 1.0, 1.0)
    unconfident = momentum_score(100000, scoring["momentum"], 0.7, 1.0)
    assert unconfident < confident


def test_scores_stay_inside_zero_to_one_hundred(scoring):
    assert momentum_score(10**12, scoring["momentum"], 1.0, 1.35) <= 100
    assert momentum_score(0, scoring["momentum"]) >= 0
    assert opportunity_score(200, -50, 200, 200, 200, scoring["opportunity"]) <= 100


def test_hook_score_uses_spec_weights(scoring):
    total, breakdown = hook_score({
        "attention_potential": 100, "curiosity": 100, "novelty": 100,
        "product_relevance": 100, "audience_relevance": 100,
        "visual_potential": 100, "production_simplicity": 100,
    }, scoring["hook_score"])
    assert total == pytest.approx(100)
    assert len(breakdown) == 7
