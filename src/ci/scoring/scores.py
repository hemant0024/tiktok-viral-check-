"""All scoring math. Pure Python, no prompts, no I/O, unit tested.

The spec's single Trend Score could not work: every component of its formula is a
good thing (velocity, cross category, novelty, relevance, applicability), yet the
label table called a high score Exhausted, and the sample report showed 91 with low
saturation as a five star produce.

The fix keeps the spec's weights exactly. The one change is novelty = 100 - saturation,
which makes the formula penalise crowding on its own, which is what the spec asked for
in words. The output is renamed opportunity_score, and momentum and saturation are
reported separately so the team can see why.
"""
from __future__ import annotations

import math
from typing import Any


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def normalize(value: float, low: float, high: float) -> float:
    """Map value from [low, high] onto [0, 1]."""
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


# --------------------------------------------------------------------------- #
def momentum_score(views_per_day: float, cfg: dict[str, Any],
                   confidence_factor: float = 1.0, breakout_multiplier: float = 1.0) -> float:
    """Log scaled, because view counts are skewed enough that one outlier would
    otherwise own the entire report."""
    floor = float(cfg.get("velocity_floor_log10", 2.0))
    ceiling = float(cfg.get("velocity_ceiling_log10", 6.0))
    raw = math.log10(1.0 + max(views_per_day, 0.0))
    base = 100.0 * normalize(raw, floor, ceiling)
    return round(clamp(base * confidence_factor * breakout_multiplier), 2)


def saturation_score(signals: dict[str, float], cfg: dict[str, Any]) -> float:
    """The eight signals the spec lists in section 11."""
    weights = cfg.get("weights", {})
    norms = cfg.get("norms", {})
    total = 0.0
    for key, weight in weights.items():
        low, high = norms.get(key, [0, 1])
        total += float(weight) * normalize(float(signals.get(key, 0) or 0), float(low), float(high))
    return round(clamp(total), 2)


def cross_category_score(distinct_categories: int, cfg: dict[str, Any]) -> float:
    low, high = cfg.get("norm", [1, 8])
    return round(100.0 * normalize(float(distinct_categories), float(low), float(high)), 2)


def opportunity_score(
    momentum: float,
    saturation: float,
    cross_category: float,
    audience_relevance: float,
    product_applicability: float,
    cfg: dict[str, Any],
) -> float:
    """Spec section 8 weights, unchanged. novelty = 100 - saturation."""
    w = cfg.get("weights", {})
    novelty = 100.0 - clamp(saturation)
    total = (
        float(w.get("momentum", 0.30)) * clamp(momentum)
        + float(w.get("cross_category", 0.20)) * clamp(cross_category)
        + float(w.get("novelty", 0.20)) * novelty
        + float(w.get("audience_relevance", 0.15)) * clamp(audience_relevance)
        + float(w.get("product_applicability", 0.15)) * clamp(product_applicability)
    )
    return round(clamp(total), 2)


def lifecycle_label(momentum: float, saturation: float, pattern_age_days: int,
                    momentum_falling_days: int, cfg: dict[str, Any]) -> str:
    """From momentum AND saturation together, which is what the spec asked for."""
    if saturation >= float(cfg.get("exhausted_saturation", 80)):
        return "Exhausted"
    if momentum_falling_days >= int(cfg.get("falling_days_for_exhausted", 3)):
        return "Exhausted"
    if saturation >= float(cfg.get("saturating_saturation", 60)):
        return "Saturating"
    if (saturation < float(cfg.get("emerging_saturation", 35))
            and pattern_age_days <= int(cfg.get("emerging_max_age_days", 7))):
        return "Emerging"
    if momentum >= float(cfg.get("rising_momentum", 60)):
        return "Rising"
    return "Saturating"


def opportunity_label(score: float, cfg: dict[str, Any]) -> str:
    """Spec section 28: never a prediction, only an opportunity band."""
    labels = cfg.get("opportunity_labels", {})
    if score >= float(labels.get("high", 75)):
        return "High opportunity"
    if score >= float(labels.get("medium", 55)):
        return "Medium opportunity"
    if score >= float(labels.get("experimental", 35)):
        return "Experimental"
    return "Low opportunity"


def hook_score(components: dict[str, float], cfg: dict[str, Any]) -> tuple[float, dict[str, float]]:
    """Spec section 16 weights."""
    weights = cfg.get("weights", {})
    breakdown: dict[str, float] = {}
    total = 0.0
    for key, weight in weights.items():
        value = clamp(float(components.get(key, 0) or 0))
        breakdown[key] = value
        total += float(weight) * value
    return round(clamp(total), 2), breakdown


def momentum_falling_days(history: list[float]) -> int:
    """How many consecutive days momentum has fallen, most recent last."""
    if len(history) < 2:
        return 0
    falling = 0
    for prev, current in zip(reversed(history[:-1]), reversed(history[1:])):
        if current < prev:
            falling += 1
        else:
            break
    return falling
