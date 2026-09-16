"""The cheap filter. Spec section 26: 100 raw -> ~50 candidates, before LLM spend.

This does not only cut, it RANKS. The candidates that reach the model are the
hottest movers, and a share of the slate is reserved for young videos that are
climbing but have not accumulated views yet, so breakouts are never crowded out
by yesterday's already-big winners.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ci.models import NormalizedContent
from ci.scoring.velocity import Velocity, compute_velocity, heat_score, parse_dt


@dataclass
class FilterVerdict:
    content: NormalizedContent
    velocity: Velocity
    heat: float
    kept: bool
    reasons: list[str]
    slot: str = ""


def _hard_cuts(item: NormalizedContent, vel: Velocity, cfg: dict[str, Any],
               now: datetime) -> list[str]:
    reasons: list[str] = []
    duration = float(item.duration_seconds or 0)
    if duration and duration < float(cfg.get("min_duration_seconds", 3)):
        reasons.append("too short")
    if duration and duration > float(cfg.get("max_duration_seconds", 120)):
        reasons.append(f"longer than {cfg.get('max_duration_seconds')}s")
    published = parse_dt(item.published_at)
    if published:
        age_days = (now - published).total_seconds() / 86400
        if age_days > float(cfg.get("max_age_days", 30)):
            reasons.append("older than lookback window")
    if cfg.get("require_title_or_description", True) and not (item.title or item.description):
        reasons.append("no title or description")

    # Views threshold is velocity-aware on purpose. A video 6 hours old with
    # 3,000 views but on pace for 200k/day is exactly what we are hunting, and
    # a flat absolute floor would throw it away.
    min_views = int(cfg.get("min_views", 5000))
    if item.views < min_views and vel.views_per_day < min_views:
        reasons.append("below views floor and not on pace")

    if item.views > 0 and item.engagement_rate < float(cfg.get("min_engagement_rate", 0.02)):
        reasons.append("engagement rate too low")
    return reasons


def cheap_filter(
    items: list[NormalizedContent],
    snapshots_by_id: dict[str, list[dict]],
    scoring: dict[str, Any],
    now: datetime | None = None,
) -> tuple[list[NormalizedContent], list[FilterVerdict]]:
    now = now or datetime.now(timezone.utc)
    cfg = scoring.get("cheap_filter", {})
    cfg_vel = scoring.get("velocity", {})
    cfg_break = scoring.get("breakout", {})
    cfg_heat = cfg.get("heat", {})
    target = int(cfg.get("target_candidates", 50))

    verdicts: list[FilterVerdict] = []
    for item in items:
        payload = item.model_dump()
        vel = compute_velocity(payload, snapshots_by_id.get(item.content_id, []), cfg_vel, cfg_break, now)
        reasons = _hard_cuts(item, vel, cfg, now)
        verdicts.append(
            FilterVerdict(
                content=item,
                velocity=vel,
                heat=heat_score(payload, vel, cfg_heat),
                kept=not reasons,
                reasons=reasons,
            )
        )

    survivors = [v for v in verdicts if v.kept]
    if not cfg.get("rank_by_heat", True):
        for v in survivors[:target]:
            v.slot = "unranked"
        return [v.content for v in survivors[:target]], verdicts

    reserved_share = float(cfg_heat.get("breakout_reserved_share", 0.4))
    reserved = int(round(target * reserved_share))

    breakouts = sorted([v for v in survivors if v.velocity.is_breakout],
                       key=lambda v: v.heat, reverse=True)
    chosen: list[FilterVerdict] = []
    seen: set[str] = set()
    for v in breakouts[:reserved]:
        v.slot = "breakout"
        chosen.append(v)
        seen.add(v.content.content_id)

    rest = sorted([v for v in survivors if v.content.content_id not in seen],
                  key=lambda v: v.heat, reverse=True)
    for v in rest:
        if len(chosen) >= target:
            break
        v.slot = "proven" if not v.velocity.is_breakout else "breakout"
        chosen.append(v)

    for v in survivors:
        if not v.slot:
            v.kept = False
            v.reasons.append("cut at candidate cap")

    # Mark anything published outside the momentum window as reference material:
    # good for creative DNA, never counted towards momentum.
    lookback = float(cfg_vel.get("lookback_days", 30))
    for v in chosen:
        published = parse_dt(v.content.published_at)
        if published and (now - published).total_seconds() / 86400 > lookback:
            v.content.is_reference = True

    return [v.content for v in chosen], verdicts
