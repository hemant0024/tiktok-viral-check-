"""Velocity, acceleration and breakout detection. Pure Python, unit tested.

Two snapshots give real growth. One snapshot gives a lifetime average, which
lies badly, so it is marked low confidence and discounted.

"Turning viral" is acceleration, not absolute views. A 50k-view video 12 hours
old that is speeding up matters more than a 5M-view video that has stopped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class Velocity:
    views_per_day: float = 0.0
    acceleration: float = 0.0          # change in views/day, per day
    confidence: str = "low"            # high | low
    confidence_factor: float = 0.7
    is_breakout: bool = False
    breakout_multiplier: float = 1.0
    age_hours: float = 0.0
    snapshots_used: int = 0
    notes: list[str] = field(default_factory=list)


def _ordered(snapshots: list[dict]) -> list[dict]:
    with_ts = [(parse_dt(s.get("captured_at")), s) for s in snapshots]
    return [s for ts, s in sorted((p for p in with_ts if p[0]), key=lambda p: p[0])]


def compute_velocity(
    content: dict[str, Any],
    snapshots: list[dict],
    cfg_velocity: dict[str, Any],
    cfg_breakout: dict[str, Any],
    now: datetime | None = None,
) -> Velocity:
    now = now or datetime.now(timezone.utc)
    published = parse_dt(content.get("published_at"))
    age_hours = (now - published).total_seconds() / 3600 if published else 0.0
    result = Velocity(age_hours=max(age_hours, 0.0))

    ordered = _ordered(snapshots)
    result.snapshots_used = len(ordered)
    min_gap_h = float(cfg_velocity.get("min_snapshot_gap_hours", 12))
    low_factor = float(cfg_velocity.get("single_snapshot_confidence", 0.7))
    high_factor = float(cfg_velocity.get("multi_snapshot_confidence", 1.0))

    usable: list[tuple[datetime, int]] = []
    for snap in ordered:
        ts = parse_dt(snap.get("captured_at"))
        if ts is None:
            continue
        if usable and (ts - usable[-1][0]).total_seconds() / 3600 < min_gap_h:
            continue
        usable.append((ts, int(snap.get("views") or 0)))

    if len(usable) >= 2:
        (t1, v1), (t2, v2) = usable[-2], usable[-1]
        days = max((t2 - t1).total_seconds() / 86400, 1e-6)
        result.views_per_day = max((v2 - v1) / days, 0.0)
        result.confidence = "high"
        result.confidence_factor = high_factor
    else:
        views = int(content.get("views") or 0)
        age_days = max(age_hours / 24, 0.5) if published else 1.0
        result.views_per_day = views / age_days
        result.confidence = "low"
        result.confidence_factor = low_factor
        result.notes.append("single snapshot, lifetime average used")

    # Acceleration needs three readings: two velocities to compare.
    min_snaps = int(cfg_breakout.get("min_snapshots_for_acceleration", 3))
    if len(usable) >= min_snaps:
        (t1, v1), (t2, v2), (t3, v3) = usable[-3], usable[-2], usable[-1]
        d1 = max((t2 - t1).total_seconds() / 86400, 1e-6)
        d2 = max((t3 - t2).total_seconds() / 86400, 1e-6)
        vel1 = (v2 - v1) / d1
        vel2 = (v3 - v2) / d2
        result.acceleration = (vel2 - vel1) / d2

    max_age = float(cfg_breakout.get("max_age_hours", 96))
    floor = float(cfg_breakout.get("min_velocity_floor", 2000))
    bonus_max = float(cfg_breakout.get("acceleration_bonus_max", 1.35))
    provisional = float(cfg_breakout.get("provisional_bonus", 1.15))

    young_enough = result.age_hours <= max_age
    fast_enough = result.views_per_day >= floor
    if young_enough and fast_enough:
        if result.acceleration > 0:
            result.is_breakout = True
            # Scale the bonus by how hard it is accelerating, capped.
            ratio = min(result.acceleration / max(result.views_per_day, 1.0), 1.0)
            result.breakout_multiplier = 1.0 + (bonus_max - 1.0) * ratio
            result.notes.append("accelerating")
        elif len(usable) < min_snaps:
            # Young and fast but not enough history to prove acceleration yet.
            result.is_breakout = True
            result.breakout_multiplier = provisional
            result.notes.append("provisional breakout, needs a third snapshot")
    return result


def heat_score(content: dict[str, Any], velocity: Velocity, cfg_heat: dict[str, Any]) -> float:
    """Ranking signal for the cheap filter. Not a report score, just triage."""
    import math

    vel_w = float(cfg_heat.get("velocity_weight", 0.55))
    acc_w = float(cfg_heat.get("acceleration_weight", 0.30))
    eng_w = float(cfg_heat.get("engagement_weight", 0.15))

    vel = math.log10(1 + max(velocity.views_per_day, 0.0))
    acc = math.log10(1 + max(velocity.acceleration, 0.0))
    views = max(int(content.get("views") or 0), 1)
    weighted_engagement = (
        int(content.get("saves") or 0) * 3
        + int(content.get("shares") or 0) * 3
        + int(content.get("comments") or 0) * 2
        + int(content.get("likes") or 0)
    ) / views

    score = vel_w * vel + acc_w * acc + eng_w * (weighted_engagement * 10)
    fresh_h = float(cfg_heat.get("freshness_bonus_hours", 48))
    if velocity.age_hours and velocity.age_hours <= fresh_h:
        score *= float(cfg_heat.get("freshness_bonus", 1.25))
    return round(score * velocity.confidence_factor * velocity.breakout_multiplier, 6)
