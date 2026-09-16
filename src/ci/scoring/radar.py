"""Viral radar. Per video, not per pattern.

The job: be first to know that a competitor's video is taking off, or about to.

Absolute views tell you what already happened, and by the time a video is at 2M
everyone has seen it. Three signals get there earlier, in order of how early:

  1. creator lift   this creator normally gets 12k and this one has 180k
  2. acceleration   views per day is rising, not just high
  3. velocity       raw speed right now

Creator lift is the earliest of the three because it fires while the absolute
numbers are still small. A 40k-view video from someone who normally gets 3k is
already breaking out; a 40k-view video from someone who normally gets 500k is dying.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from ci.scoring.scores import clamp, normalize
from ci.scoring.velocity import Velocity
from ci.scoring.viral_signals import Takeoff, ViralProfile

EXPLODING = "EXPLODING"
CLIMBING = "CLIMBING"
EARLY_SIGNAL = "EARLY SIGNAL"
STEADY = "STEADY"
COOLING = "COOLING"


@dataclass
class RadarVerdict:
    radar_score: float = 0.0
    status: str = STEADY
    creator_lift: float = 0.0
    creator_baseline_views: float = 0.0
    baseline_source: str = "none"      # history | followers | none
    components: dict[str, float | None] = field(default_factory=dict)
    measured: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    viral: ViralProfile | None = None
    takeoff: Takeoff | None = None

    @property
    def is_hot(self) -> bool:
        return self.status in {EXPLODING, CLIMBING, EARLY_SIGNAL}


def creator_baseline(creator_videos: list[dict], exclude_id: str, min_videos: int) -> float:
    """Median views of this creator's OTHER videos we have seen."""
    others = [
        int(v.get("views") or 0)
        for v in creator_videos
        if v.get("content_id") != exclude_id and int(v.get("views") or 0) > 0
    ]
    if len(others) < min_videos:
        return 0.0
    return float(median(others))


def compute_lift(content: dict[str, Any], creator_videos: list[dict],
                 cfg: dict[str, Any]) -> tuple[float, float, str]:
    """Returns (lift, baseline, source)."""
    views = int(content.get("views") or 0)
    min_videos = int(cfg.get("min_videos_for_baseline", 3))
    baseline = creator_baseline(creator_videos, content.get("content_id", ""), min_videos)
    if baseline > 0:
        return (views / baseline, baseline, "history")

    followers = int(content.get("creator_followers") or 0)
    if followers > 0:
        # Views per follower, expressed on the same scale so it can share a weight.
        return (views / followers, float(followers), "followers")
    return (0.0, 0.0, "none")


def radar_score(
    content: dict[str, Any],
    velocity: Velocity,
    creator_videos: list[dict],
    cfg: dict[str, Any],
    viral: ViralProfile | None = None,
    takeoff: Takeoff | None = None,
) -> RadarVerdict:
    weights = cfg.get("weights", {})
    verdict = RadarVerdict()

    lift, baseline, source = compute_lift(content, creator_videos, cfg)
    verdict.creator_lift = round(lift, 2)
    verdict.creator_baseline_views = baseline
    verdict.baseline_source = source

    vlo, vhi = cfg.get("velocity_norm_log10", [2.5, 6.0])
    velocity_c = 100.0 * normalize(math.log10(1 + max(velocity.views_per_day, 0.0)), vlo, vhi)

    alo, ahi = cfg.get("acceleration_norm_log10", [2.5, 6.0])
    accel_c = 100.0 * normalize(math.log10(1 + max(velocity.acceleration, 0.0)), alo, ahi)

    if source == "history":
        llo, lhi = cfg.get("creator_lift_norm", [1.0, 10.0])
    else:
        llo, lhi = cfg.get("fallback_views_per_follower_norm", [0.2, 5.0])
    lift_c = 100.0 * normalize(lift, float(llo), float(lhi))

    views = max(int(content.get("views") or 0), 1)
    weighted = (
        int(content.get("saves") or 0) * 3
        + int(content.get("shares") or 0) * 3
        + int(content.get("comments") or 0) * 2
        + int(content.get("likes") or 0)
    ) / views
    engagement_c = 100.0 * normalize(weighted, 0.0, 0.5)

    half_life = float(cfg.get("freshness_half_life_hours", 36))
    freshness_c = 100.0 * (0.5 ** (max(velocity.age_hours, 0.0) / half_life)) if half_life else 0.0

    # Only score components we can actually measure, then renormalize the weights
    # across those.
    #
    # This matters more than it sounds. Acceleration needs three snapshots, so on
    # day one and day two it is unmeasurable. Scoring it as zero meant 35% of the
    # score was dead weight and NOTHING could reach EXPLODING until day three,
    # which defeats the entire point of an early warning system. Redistributing
    # instead means a video is judged on what we know about it today.
    measurable: dict[str, tuple[float, float]] = {
        "velocity": (velocity_c, float(weights.get("velocity", 0.25))),
        "engagement": (engagement_c, float(weights.get("engagement", 0.10))),
        "freshness": (freshness_c, float(weights.get("freshness", 0.10))),
    }
    if velocity.snapshots_used >= int(cfg.get("min_snapshots_for_acceleration", 3)):
        measurable["acceleration"] = (accel_c, float(weights.get("acceleration", 0.35)))
        verdict.components["acceleration"] = round(accel_c, 1)
    else:
        verdict.components["acceleration"] = None
    if source != "none":
        measurable["creator_lift"] = (lift_c, float(weights.get("creator_lift", 0.20)))
        verdict.components["creator_lift"] = round(lift_c, 1)
    else:
        verdict.components["creator_lift"] = None

    verdict.components["velocity"] = round(velocity_c, 1)
    verdict.components["engagement"] = round(engagement_c, 1)
    verdict.components["freshness"] = round(freshness_c, 1)

    total_weight = sum(w for _, w in measurable.values()) or 1.0
    verdict.radar_score = round(clamp(
        sum(value * weight for value, weight in measurable.values()) / total_weight
    ), 2)
    verdict.measured = sorted(measurable)

    # Engagement quality from the viral profile replaces the crude blended one,
    # because share_rate carries different weight than likes and the bands are
    # calibrated per metric rather than lumped together.
    if viral is not None:
        verdict.viral = viral
        measurable["engagement"] = (viral.engagement_score,
                                    float(weights.get("engagement", 0.10)))
        verdict.components["engagement"] = round(viral.engagement_score, 1)
        if viral.waves.wave_count:
            wave_c = 100.0 * min(viral.waves.wave_count, 3) / 3.0
            measurable["waves"] = (wave_c, float(weights.get("waves", 0.20)))
            verdict.components["waves"] = round(wave_c, 1)
        else:
            verdict.components["waves"] = None
        total_weight = sum(w for _, w in measurable.values()) or 1.0
        verdict.radar_score = round(clamp(
            sum(value * weight for value, weight in measurable.values()) / total_weight
        ), 2)
        verdict.measured = sorted(measurable)

    # Views relative to AGE. A video doing 4x what a normal video does by this
    # point in its life is the signal; raw view count is not.
    if takeoff is not None:
        verdict.takeoff = takeoff
        measurable["vs_expected"] = (takeoff.vs_expected_score,
                                     float(weights.get("vs_expected", 0.20)))
        verdict.components["vs_expected"] = round(takeoff.vs_expected_score, 1)
        total_weight = sum(w for _, w in measurable.values()) or 1.0
        verdict.radar_score = round(clamp(
            sum(value * weight for value, weight in measurable.values()) / total_weight
        ), 2)
        verdict.measured = sorted(measurable)
        # Already-viral videos are downranked hard. We are not trying to find what
        # everyone has already seen.
        verdict.radar_score = round(clamp(verdict.radar_score * takeoff.penalty), 2)

    verdict.status = _status(verdict.radar_score, velocity, cfg)
    verdict.reasons = _reasons(verdict, velocity, content)
    if takeoff is not None:
        verdict.reasons = takeoff.notes + verdict.reasons
        if takeoff.is_already_viral or takeoff.tier == "TOO OLD":
            verdict.status = takeoff.tier
            return verdict
    if viral is not None:
        # Viral phase is a stronger statement than the generic status, so it wins.
        from ci.scoring.viral_signals import BAND_NORMAL, BREAKING_OUT, PRE_VIRAL, VIRAL
        if viral.phase == VIRAL:
            verdict.status = EXPLODING
        elif viral.phase == BREAKING_OUT:
            verdict.status = CLIMBING
        elif viral.phase == PRE_VIRAL and verdict.status == STEADY:
            verdict.status = EARLY_SIGNAL

        # A like says "I enjoyed this". A share says "someone else needs to see
        # this". For finding an ad concept worth rebuilding, that difference is
        # the whole game. So a video with a normal-band share rate AND no
        # distribution waves is getting views without spreading, and it cannot
        # outrank something people are actually passing around, however fast its
        # view count is climbing.
        share = viral.ratios.get("share_rate")
        if (share and share.band == BAND_NORMAL and viral.waves.wave_count == 0
                and content.get("views", 0) > 0):
            penalty = float(cfg.get("no_spread_penalty", 0.7))
            verdict.radar_score = round(clamp(verdict.radar_score * penalty), 2)
            verdict.reasons.append(
                f"views are climbing but share rate is only {share.value:.2%}, "
                "so it is being watched rather than passed on"
            )
        verdict.reasons = viral.signals + verdict.reasons
    return verdict


def _status(score: float, velocity: Velocity, cfg: dict[str, Any]) -> str:
    s = cfg.get("status", {})
    accelerating = velocity.acceleration > 0
    decelerating = velocity.acceleration < float(s.get("cooling_acceleration_below", 0))

    exploding = s.get("exploding", {})
    if (score >= float(exploding.get("min_score", 70))
            and velocity.age_hours <= float(exploding.get("max_age_hours", 96))
            and (accelerating or not exploding.get("requires_positive_acceleration", True))):
        return EXPLODING

    climbing = s.get("climbing", {})
    if score >= float(climbing.get("min_score", 50)) and accelerating:
        return CLIMBING

    early = s.get("early_signal", {})
    if (score >= float(early.get("min_score", 35))
            and velocity.age_hours <= float(early.get("max_age_hours", 48))):
        return EARLY_SIGNAL

    if decelerating:
        return COOLING
    return STEADY


def _reasons(verdict: RadarVerdict, velocity: Velocity, content: dict[str, Any]) -> list[str]:
    """Plain English, because a score with no reason gets ignored."""
    out: list[str] = []
    if verdict.baseline_source == "history" and verdict.creator_lift >= 2:
        out.append(f"{verdict.creator_lift:.1f}x this creator's normal "
                   f"({int(verdict.creator_baseline_views):,} views)")
    elif verdict.baseline_source == "followers" and verdict.creator_lift >= 1:
        out.append(f"{verdict.creator_lift:.1f}x more views than followers, "
                   f"so it is reaching past their audience")
    if velocity.acceleration > 0:
        out.append(f"speeding up, +{int(velocity.acceleration):,} views/day per day")
    elif velocity.acceleration < 0:
        out.append("slowing down")
    if velocity.age_hours and velocity.age_hours <= 48:
        out.append(f"only {int(velocity.age_hours)}h old")
    if velocity.confidence == "low":
        out.append("one snapshot only, needs another run to confirm")
    if "acceleration" not in verdict.measured:
        out.append("acceleration not measurable yet, needs a third snapshot")
    saves = int(content.get("saves") or 0)
    views = max(int(content.get("views") or 0), 1)
    if saves / views > 0.04:
        out.append(f"unusually high saves ({saves:,}), people are keeping it")
    return out


def apply_feed_caps(rows: list[dict], cfg: dict[str, Any]) -> list[dict]:
    """Stop one loud creator or one brand from owning the whole feed."""
    feed = cfg.get("feed", {})
    max_rows = int(feed.get("max_rows", 25))
    min_score = float(feed.get("min_score_to_show", 30))
    per_creator = int(feed.get("max_per_creator", 3))
    per_competitor = int(feed.get("max_per_competitor", 6))

    wanted_tiers = {str(x).upper() for x in (feed.get("tiers_to_show") or [])}

    def tier_ok(row: dict) -> bool:
        # A row with no tier was never tier-scored, so the filter cannot speak to
        # it. Ads are the real case: tiers are views-for-age and Meta publishes no
        # views, so every ad would be filtered out on a tier it can never have.
        # Keying on the missing tier rather than on kind also covers anything
        # else that arrives without one.
        if not wanted_tiers or not row.get("takeoff_tier"):
            return True
        return str(row["takeoff_tier"]).upper() in wanted_tiers

    ranked = sorted(
        [r for r in rows
         if float(r.get("radar_score", 0)) >= min_score and tier_ok(r)],
        # Tie-break on days running, so a collapsed variation group is represented
        # by its LONGEST running ad rather than whichever happened to be first.
        key=lambda r: (float(r.get("radar_score", 0)), int(r.get("days_running", 0))),
        reverse=True,
    )

    # Collapse variation groups to their strongest member. Five ad IDs of the same
    # concept is ONE thing to look at, and the variation count already tells you
    # there are five. Showing all five is the raw-data dump the spec warns against.
    if feed.get("collapse_variation_groups", True):
        best_of_group: dict[str, dict] = {}
        collapsed: list[dict] = []
        for row in ranked:
            group = row.get("variation_group") or ""
            if not group:
                collapsed.append(row)
                continue
            if group not in best_of_group:
                best_of_group[group] = row
                collapsed.append(row)
        ranked = collapsed
    creator_seen: dict[str, int] = {}
    competitor_seen: dict[str, int] = {}
    out: list[dict] = []
    for row in ranked:
        creator = row.get("creator", "")
        competitor = row.get("competitor", "")
        if creator_seen.get(creator, 0) >= per_creator:
            continue
        if competitor and competitor_seen.get(competitor, 0) >= per_competitor:
            continue
        creator_seen[creator] = creator_seen.get(creator, 0) + 1
        if competitor:
            competitor_seen[competitor] = competitor_seen.get(competitor, 0) + 1
        out.append(row)
        if len(out) >= max_rows:
            break
    return out


# --------------------------------------------------------------------------- #
# Ads are scored differently, on purpose.
#
# The Meta Ad Library exposes no views, likes or spend for US commercial ads, so
# every views-based signal is zero for them. Ranking ads by a views-based score
# put a Linguza ad that had been running 99 days with 5 variations at the bottom
# of the feed, which is exactly backwards: that is the strongest evidence in the
# whole dataset. Money spent over time is the signal.
# --------------------------------------------------------------------------- #
PROVEN = "PROVEN WINNER"
LIKELY = "LIKELY WINNER"
NEW_WATCH = "NEW, WATCH IT"
TEST_SIGNAL = "TEST SIGNAL ONLY"


def winner_signal(content: dict[str, Any], cfg: dict[str, Any],
                  reused_by_competitors: int = 0, relaunched: bool = False) -> RadarVerdict:
    weights = cfg.get("weights", {})
    verdict = RadarVerdict()

    days = int(content.get("days_running") or 0)
    variations = int(content.get("variation_count") or 0)
    platforms = len(content.get("publisher_platforms") or []) or 1

    dlo, dhi = cfg.get("days_running_norm", [3, 60])
    vlo, vhi = cfg.get("variations_norm", [1, 8])
    plo, phi = cfg.get("platforms_norm", [1, 4])

    days_c = 100.0 * normalize(days, float(dlo), float(dhi))
    var_c = 100.0 * normalize(variations, float(vlo), float(vhi))
    plat_c = 100.0 * normalize(platforms, float(plo), float(phi))
    reuse_c = 100.0 * normalize(reused_by_competitors, 1.0, 4.0)
    relaunch_c = 100.0 if relaunched else 0.0

    views = int(content.get("views") or 0)
    if views > 0:
        weighted = (int(content.get("saves") or 0) * 3 + int(content.get("shares") or 0) * 3
                    + int(content.get("comments") or 0) * 2 + int(content.get("likes") or 0)) / views
        engagement_c = 100.0 * normalize(weighted, 0.0, 0.5)
        measurable_engagement = True
    else:
        engagement_c, measurable_engagement = 0.0, False

    measurable = {
        "days_running": (days_c, float(weights.get("days_running", 0.30))),
        "variations": (var_c, float(weights.get("variations", 0.20))),
        "relaunched_or_scaled": (relaunch_c, float(weights.get("relaunched_or_scaled", 0.15))),
        "platforms": (plat_c, float(weights.get("platforms", 0.10))),
    }
    verdict.components = {"days_running": round(days_c, 1), "variations": round(var_c, 1),
                          "relaunched_or_scaled": round(relaunch_c, 1),
                          "platforms": round(plat_c, 1)}
    if reused_by_competitors:
        measurable["hook_reused_by_others"] = (reuse_c, float(weights.get("hook_reused_by_others", 0.15)))
        verdict.components["hook_reused_by_others"] = round(reuse_c, 1)
    else:
        verdict.components["hook_reused_by_others"] = None
    if measurable_engagement:
        measurable["engagement"] = (engagement_c, float(weights.get("engagement", 0.10)))
        verdict.components["engagement"] = round(engagement_c, 1)
    else:
        verdict.components["engagement"] = None

    total = sum(w for _, w in measurable.values()) or 1.0
    verdict.radar_score = round(clamp(sum(v * w for v, w in measurable.values()) / total), 2)
    verdict.measured = sorted(measurable)

    s = cfg.get("status", {})
    if verdict.radar_score >= float(s.get("proven_winner", 70)):
        verdict.status = PROVEN
    elif verdict.radar_score >= float(s.get("likely_winner", 50)):
        verdict.status = LIKELY
    elif verdict.radar_score >= float(s.get("new_watch_it", 30)):
        verdict.status = NEW_WATCH
    else:
        verdict.status = TEST_SIGNAL

    reasons = []
    if days >= 60:
        reasons.append(f"running {days} days, which is a strong winner signal")
    elif days >= 30:
        reasons.append(f"running {days} days, usually means it is converting")
    elif days > 0:
        reasons.append(f"only {days} days old, too early to call")
    if variations >= 3:
        reasons.append(f"{variations} variations, brands only duplicate ads that work")
    if relaunched:
        reasons.append("relaunched after a gap, so they came back to it")
    if reused_by_competitors >= 2:
        reasons.append(f"{reused_by_competitors} other competitors run this hook style")
    if platforms >= 2:
        reasons.append(f"live on {platforms} placements, so it survived more than one auction")
    if not measurable_engagement:
        reasons.append("no public engagement data, the Ad Library does not expose it")
    verdict.reasons = reasons
    return verdict
