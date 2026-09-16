"""Viral phase detection for TikTok.

Two ideas do most of the work here.

**Acceleration beats volume.** A video going 1,000 -> 2,500 -> 7,000 -> 22,000 ->
70,000 per hour is far more interesting than one going 20,000 -> 22,000 -> 24,000 ->
25,000, even though the second has more views for the first three hours. The first is
getting distribution waves: TikTok is finding progressively larger audiences and they
are responding well enough that it keeps expanding. The second has found its ceiling.

**Shares beat likes.** A like says "I enjoyed this". A share says "someone else needs
to see this". For finding a competitor ad concept worth rebuilding, that difference is
the whole game, so share_rate carries the heaviest weight of the four ratios.

What is deliberately NOT here: watch time, completion rate and rewatch rate. They are
excellent signals and they are creator-side analytics. No public API or scraper returns
them for a video you do not own. Pretending otherwise would put a number in the report
that nobody could stand behind.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ci.scoring.scores import clamp
from ci.scoring.velocity import parse_dt

PRE_VIRAL = "PRE-VIRAL"
BREAKING_OUT = "BREAKING OUT"
VIRAL = "VIRAL"
PEAKED = "PEAKED"
FLAT = "FLAT"

BAND_NORMAL = "normal"
BAND_ELEVATED = "elevated"
BAND_VIRAL = "viral"


@dataclass
class Ratio:
    name: str
    value: float
    band: str
    score: float
    benchmark: str = ""


@dataclass
class Waves:
    hourly: list[tuple[float, float]] = field(default_factory=list)   # (hours_ago, views/hour)
    ratios: list[float] = field(default_factory=list)
    wave_count: int = 0
    latest_ratio: float = 0.0
    peak_hourly: float = 0.0
    current_hourly: float = 0.0
    accelerating: bool = False
    readings: int = 0


@dataclass
class ViralProfile:
    engagement_score: float = 0.0
    ratios: dict[str, Ratio] = field(default_factory=dict)
    waves: Waves = field(default_factory=Waves)
    phase: str = FLAT
    projection: dict[str, Any] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
def _band_and_score(value: float, spec: dict[str, float]) -> tuple[str, float]:
    """0-100 within the band structure: normal floor, elevated, viral ceiling."""
    normal = float(spec.get("normal", 0))
    elevated = float(spec.get("elevated", normal * 2))
    viral = float(spec.get("viral", elevated * 3))
    if value >= viral:
        return BAND_VIRAL, 100.0
    if value >= elevated:
        span = viral - elevated or 1.0
        return BAND_VIRAL if value >= viral else BAND_ELEVATED, 65.0 + 35.0 * ((value - elevated) / span)
    if value >= normal:
        span = elevated - normal or 1.0
        return BAND_ELEVATED, 35.0 + 30.0 * ((value - normal) / span)
    span = normal or 1.0
    return BAND_NORMAL, 35.0 * (value / span)


def engagement_ratios(content: dict[str, Any], cfg: dict[str, Any]) -> tuple[float, dict[str, Ratio]]:
    views = max(int(content.get("views") or 0), 1)
    raw = {
        "share_rate": int(content.get("shares") or 0) / views,
        "save_rate": int(content.get("saves") or 0) / views,
        "comment_rate": int(content.get("comments") or 0) / views,
        "like_rate": int(content.get("likes") or 0) / views,
    }
    specs = cfg.get("ratios", {})
    out: dict[str, Ratio] = {}
    total, total_weight = 0.0, 0.0
    for name, value in raw.items():
        spec = specs.get(name, {})
        band, score = _band_and_score(value, spec)
        weight = float(spec.get("weight", 0.25))
        out[name] = Ratio(
            name=name, value=round(value, 5), band=band, score=round(score, 1),
            benchmark=f"normal <{spec.get('normal',0):.1%}, viral {spec.get('viral',0):.1%}+",
        )
        total += score * weight
        total_weight += weight
    return round(clamp(total / (total_weight or 1.0)), 2), out


# --------------------------------------------------------------------------- #
def analyse_waves(snapshots: list[dict], cfg: dict[str, Any],
                  now: datetime | None = None) -> Waves:
    """Hourly view rate between consecutive readings, and how each wave compares
    to the one before it."""
    waves = Waves()
    points: list[tuple[datetime, int]] = []
    for snap in snapshots:
        ts = parse_dt(snap.get("captured_at"))
        if ts is not None:
            points.append((ts, int(snap.get("views") or 0)))
    points.sort(key=lambda p: p[0])
    waves.readings = len(points)
    if len(points) < 2:
        return waves

    now = now or points[-1][0]
    min_hourly = float(cfg.get("min_hourly_views", 200))
    for (t1, v1), (t2, v2) in zip(points, points[1:]):
        hours = max((t2 - t1).total_seconds() / 3600, 1e-6)
        rate = max((v2 - v1) / hours, 0.0)
        waves.hourly.append((round((now - t2).total_seconds() / 3600, 2), round(rate, 1)))

    rates = [r for _, r in waves.hourly]
    waves.current_hourly = rates[-1] if rates else 0.0
    waves.peak_hourly = max(rates) if rates else 0.0

    threshold = float(cfg.get("wave_ratio_threshold", 1.5))
    for prev, current in zip(rates, rates[1:]):
        ratio = current / prev if prev > 0 else (float("inf") if current > 0 else 0.0)
        waves.ratios.append(round(ratio, 2) if ratio != float("inf") else 999.0)
        if ratio >= threshold and current >= min_hourly:
            waves.wave_count += 1
    waves.latest_ratio = waves.ratios[-1] if waves.ratios else 0.0
    waves.accelerating = waves.latest_ratio >= threshold and waves.current_hourly >= min_hourly
    return waves


# --------------------------------------------------------------------------- #
def project(waves: Waves, current_views: int, cfg: dict[str, Any]) -> dict[str, Any]:
    """Where this lands if the current wave holds. A range, never a promise."""
    if not waves.hourly or waves.current_hourly <= 0:
        return {}
    hours = cfg.get("project_hours", [6, 24])
    ratio = max(min(waves.latest_ratio, 3.0), 1.0)
    decay = float(cfg.get("ratio_decay_per_hour", 0.55))
    cap_multiple = float(cfg.get("max_projection_multiple", 60))

    def walk(target: float | None, max_hours: int) -> tuple[float, int]:
        """Step forward hour by hour with the wave ratio decaying toward 1.

        The decay is the whole point. An early version compounded a 2.7x ratio
        for 24 hours and projected 686 billion views, which is more than every
        video on the platform combined. Distribution waves flatten fast.
        """
        projected, rate, hrs = float(current_views), waves.current_hourly, 0
        ceiling = max(float(current_views), 1.0) * cap_multiple
        while hrs < max_hours:
            projected += rate
            if projected >= ceiling:
                projected = ceiling
                break
            # ratio -> 1.0 geometrically, so growth tails off instead of exploding
            step_ratio = 1.0 + (ratio - 1.0) * (decay ** hrs)
            rate *= step_ratio
            hrs += 1
            if target is not None and projected >= target:
                break
        return projected, hrs

    out: dict[str, Any] = {}
    for h in hours:
        projected, _ = walk(None, int(h))
        out[f"in_{h}h"] = int(projected)

    milestones = cfg.get("milestones", [10000, 100000, 1000000])
    next_milestone = next((m for m in milestones if m > current_views), None)
    if next_milestone and waves.current_hourly > 0:
        projected, hrs = walk(float(next_milestone), 168)
        if projected >= next_milestone:
            out["next_milestone"] = next_milestone
            out["hours_to_milestone"] = hrs
    out["basis"] = f"current {int(waves.current_hourly):,}/hr, wave ratio {ratio:.1f}x decaying"
    return out


# --------------------------------------------------------------------------- #
def viral_profile(content: dict[str, Any], snapshots: list[dict], cfg: dict[str, Any],
                  age_hours: float = 0.0, now: datetime | None = None) -> ViralProfile:
    profile = ViralProfile()
    profile.engagement_score, profile.ratios = engagement_ratios(content, cfg)
    profile.waves = analyse_waves(snapshots, cfg.get("waves", {}), now)
    waves_cfg = cfg.get("waves", {})
    phases = cfg.get("phases", {})

    combined = 0.6 * profile.engagement_score + 40.0 * min(profile.waves.wave_count, 3) / 3.0

    viral_spec = phases.get("viral", {})
    breaking = phases.get("breaking_out", {})
    pre = phases.get("pre_viral", {})
    peaked_below = float(phases.get("peaked", {}).get("wave_ratio_below", 1.0))

    if (combined >= float(viral_spec.get("min_score", 78))
            and profile.waves.wave_count >= int(viral_spec.get("requires_waves", 3))):
        profile.phase = VIRAL
    elif (combined >= float(breaking.get("min_score", 62))
          and profile.waves.wave_count >= int(breaking.get("requires_waves", 2))
          and age_hours <= float(breaking.get("max_age_hours", 96))):
        profile.phase = BREAKING_OUT
    elif (combined >= float(pre.get("min_score", 45))
          and profile.waves.wave_count >= int(pre.get("requires_waves", 1))
          and age_hours <= float(pre.get("max_age_hours", 48))):
        profile.phase = PRE_VIRAL
    elif (len(profile.waves.ratios) >= 2
          and profile.waves.latest_ratio < peaked_below
          and profile.waves.peak_hourly > 0):
        # Needs at least TWO ratios, so there is a previous wave to have fallen
        # from. With one reading pair the ratio is 0 and a one-hour-old video
        # was being called PEAKED, which is nonsense.
        profile.phase = PEAKED
    else:
        profile.phase = FLAT

    profile.projection = project(profile.waves, int(content.get("views") or 0),
                                 cfg.get("trajectory", {}))

    # Plain English, because a score nobody understands gets ignored.
    share = profile.ratios.get("share_rate")
    if share and share.band != BAND_NORMAL:
        profile.signals.append(
            f"share rate {share.value:.2%} ({share.band}), people are sending it to each other"
        )
    save = profile.ratios.get("save_rate")
    if save and save.band != BAND_NORMAL:
        profile.signals.append(f"save rate {save.value:.2%} ({save.band})")
    comment = profile.ratios.get("comment_rate")
    if comment and comment.band == BAND_VIRAL:
        profile.signals.append(f"comment rate {comment.value:.2%}, it is starting arguments")
    if profile.waves.wave_count:
        ratios = " -> ".join(f"{r:.1f}x" for r in profile.waves.ratios[-3:])
        profile.signals.append(
            f"{profile.waves.wave_count} distribution wave(s), last few {ratios}"
        )
    if profile.waves.current_hourly >= float(waves_cfg.get("min_hourly_views", 200)):
        profile.signals.append(f"{int(profile.waves.current_hourly):,} views/hour right now")
    if profile.phase == PEAKED:
        profile.signals.append("wave ratio has dropped below 1, distribution is contracting")
    if profile.waves.readings < int(waves_cfg.get("min_readings", 3)):
        profile.signals.append(
            f"only {profile.waves.readings} reading(s), waves need {waves_cfg.get('min_readings',3)}"
        )

    profile.missing = ["watch time", "completion rate", "rewatch rate"]
    return profile


# --------------------------------------------------------------------------- #
# Takeoff detection: views relative to AGE.
#
# A video with 2M views posted three weeks ago is not a lead, it is history.
# A video with 18K views posted four hours ago and climbing is the whole point.
# --------------------------------------------------------------------------- #
ALREADY_VIRAL = "ALREADY VIRAL"
TOO_OLD = "TOO OLD"
UNKNOWN_AGE = "UNKNOWN AGE"


@dataclass
class Takeoff:
    tier: str = TOO_OLD
    expected_views: float = 0.0
    vs_expected: float = 0.0
    vs_expected_score: float = 0.0
    is_already_viral: bool = False
    is_jackpot: bool = False
    penalty: float = 1.0
    baseline_source: str = "config"
    notes: list[str] = field(default_factory=list)


def expected_views_at(age_hours: float, curve: dict[Any, Any]) -> float:
    """Linear interpolation across the expected-views curve."""
    points = sorted((float(h), float(v)) for h, v in curve.items())
    if not points:
        return 0.0
    if age_hours <= points[0][0]:
        # Below the first point, scale down proportionally rather than flooring.
        return points[0][1] * max(age_hours, 0.1) / points[0][0]
    for (h1, v1), (h2, v2) in zip(points, points[1:]):
        if age_hours <= h2:
            span = h2 - h1 or 1.0
            return v1 + (v2 - v1) * ((age_hours - h1) / span)
    # Past the curve, extend at the last observed rate per hour.
    last_h, last_v = points[-1]
    return last_v + (last_v / last_h) * (age_hours - last_h)


def learn_baseline_curve(rows: list[dict[str, Any]], cfg: dict[str, Any],
                         now: datetime | None = None) -> dict[float, float]:
    """Build the expected-views curve from our OWN collected data.

    A hardcoded curve goes stale the moment the niche shifts, and a guessed one
    was never right to begin with. Median views per age bucket, from everything
    we have actually seen, is the only baseline that stays honest.
    """
    learn = cfg.get("learn_baseline", {})
    if not learn.get("enabled", True) or not rows:
        return {}
    now = now or datetime.now(timezone.utc)
    buckets = [float(b) for b in learn.get("buckets_hours", [1, 3, 6, 12, 24, 48, 72])]
    min_samples = int(learn.get("min_samples_per_bucket", 8))
    lookback_h = float(learn.get("lookback_days", 14)) * 24

    samples: dict[float, list[int]] = {b: [] for b in buckets}
    for row in rows:
        published = parse_dt(row.get("published_at"))
        if published is None:
            continue
        age = (now - published).total_seconds() / 3600
        if age <= 0 or age > lookback_h:
            continue
        # Assign to the nearest bucket at or above this age.
        bucket = next((b for b in buckets if age <= b), None)
        if bucket is not None:
            samples[bucket].append(int(row.get("views") or 0))

    curve: dict[float, float] = {}
    for bucket, views in samples.items():
        if len(views) >= min_samples:
            views.sort()
            curve[bucket] = float(views[len(views) // 2])
    return curve


def _apply_jackpot(result: "Takeoff", content: dict[str, Any], cfg: dict[str, Any],
                   creator_lift: float) -> None:
    """A small account suddenly getting huge views. Age-independent, and the
    cleanest evidence that the CONTENT did the work rather than the follower count."""
    jack = cfg.get("jackpot", {})
    followers = int(content.get("creator_followers") or 0)
    views = int(content.get("views") or 0)
    # The lift test alone is not enough. With no creator history, lift falls back
    # to views over followers, and a 24-follower account clears 5x at 120 views.
    # That flagged 24 of 52 videos on 11 Sep, which made the badge worthless.
    if (0 < followers <= int(jack.get("max_creator_followers", 50000))
            and creator_lift >= float(jack.get("min_lift", 5.0))
            and views >= int(jack.get("min_views", 0))):
        result.is_jackpot = True
        result.penalty = float(jack.get("bonus_multiplier", 1.25))
        result.notes.append(
            f"small account ({followers:,} followers) on {views:,} views, "
            f"{creator_lift:.1f}x its normal. This is the shape worth studying."
        )


def takeoff_profile(content: dict[str, Any], age_hours: float, cfg: dict[str, Any],
                    creator_lift: float = 0.0,
                    learned_curve: dict[float, float] | None = None) -> Takeoff:
    views = int(content.get("views") or 0)
    result = Takeoff()

    curve = learned_curve or cfg.get("expected_curve", {})
    result.baseline_source = "learned" if learned_curve else "config"
    # Age under six minutes means we do not know when this was posted, not that
    # it is six minutes old. Dividing by the curve there produces a pace figure
    # in the thousands that is pure artefact, so refuse to compute one.
    if age_hours < 0.1:
        result.expected_views = 0.0
        result.tier = UNKNOWN_AGE
        result.notes.append("no usable publish time, so pace and tier are not computed")
        _apply_jackpot(result, content, cfg, creator_lift)
        return result

    result.expected_views = round(expected_views_at(age_hours, curve), 0)
    if result.expected_views > 0:
        result.vs_expected = round(views / result.expected_views, 2)
    lo, hi = cfg.get("vs_expected_norm", [0.5, 4.0])
    result.vs_expected_score = round(100.0 * clamp(
        (result.vs_expected - float(lo)) / ((float(hi) - float(lo)) or 1.0), 0.0, 1.0
    ) * 100 / 100, 1)

    av = cfg.get("already_viral", {})
    if views >= int(av.get("min_views", 500000)) and age_hours >= float(av.get("older_than_hours", 48)):
        result.is_already_viral = True
        result.tier = av.get("label", ALREADY_VIRAL)
        result.penalty = float(av.get("penalty_multiplier", 0.25))
        result.notes.append(
            f"{views:,} views and {int(age_hours/24)}d old, this already went viral. "
            "The copies have started, so studying it now means arriving late."
        )
        return result

    if age_hours > float(cfg.get("max_candidate_age_hours", 72)):
        result.tier = TOO_OLD
        result.penalty = 0.5
        result.notes.append(f"{int(age_hours/24)}d old, past the takeoff window")
        return result

    for tier in cfg.get("tiers", []):
        if views >= int(tier.get("min_views", 0)) and age_hours <= float(tier.get("max_age_hours", 24)):
            result.tier = tier.get("name", "WATCH")
            break
    else:
        result.tier = "DAY TWO"

    if result.vs_expected >= 1.5:
        result.notes.append(
            f"{views:,} views at {int(age_hours)}h, about {result.vs_expected:.1f}x "
            f"what a normal video does by now"
        )
    elif result.vs_expected and result.vs_expected < 0.5:
        result.notes.append(f"below the normal curve for {int(age_hours)}h old")

    _apply_jackpot(result, content, cfg, creator_lift)
    return result
