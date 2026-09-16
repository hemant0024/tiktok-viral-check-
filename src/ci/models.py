"""One pydantic model per table. Nothing untyped crosses a module boundary."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Platform = Literal["youtube", "tiktok", "meta_ads", "instagram", "csv"]
Confidence = Literal["high", "low"]
Lifecycle = Literal["Emerging", "Rising", "Saturating", "Exhausted"]
OpportunityLabel = Literal["High opportunity", "Medium opportunity", "Experimental", "Low opportunity"]

HOOK_TYPES = [
    "Curiosity", "Confession", "Shock", "POV", "Reaction", "Challenge",
    "Transformation", "Comparison", "Contrarian", "Problem", "Demonstration",
    "Story", "Humor", "Social Proof", "Pattern Interrupt", "Before/After",
    "Question", "Mistake", "Secret", "Controversy",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def canonical_id(platform: str, native_id: str | None, url: str | None) -> str:
    """Platform ID where one exists, else a deterministic hash of the canonical URL."""
    if native_id:
        return f"{platform}:{native_id}"
    if not url:
        raise ValueError("need either a native id or a url to build a content_id")
    canon = url.split("?")[0].rstrip("/").lower()
    return f"{platform}:{hashlib.sha256(canon.encode()).hexdigest()[:16]}"


class BaseRow(BaseModel):
    model_config = {"extra": "allow"}


# --------------------------------------------------------------------------- #
# The normalized shape every source adapter must return. Spec section 3 and 5.
# --------------------------------------------------------------------------- #
class NormalizedContent(BaseRow):
    content_id: str
    date_found: str
    platform: Platform
    source: str
    url: str
    creator: str = ""
    creator_followers: int = 0
    title: str = ""
    description: str = ""
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    published_at: str | None = None
    country: str = "US"
    language: str = "en"
    category: str = ""
    subcategory: str = ""
    raw_transcript: str = ""
    transcript_source: Literal["owned_captions", "platform_captions", "video_model", "manual", "none"] = "none"
    thumbnail_url: str = ""
    duration_seconds: float = 0.0
    hashtags: list[str] = Field(default_factory=list)
    sound_title: str = ""
    is_ad: bool = False
    is_reference: bool = False
    collected_pass: str = ""
    # Competitor radar fields.
    competitor: str = ""
    kind: Literal["organic", "organic_ugc", "competitor_ad"] = "organic"
    ad_start_date: str | None = None
    days_running: int = 0
    variation_group: str = ""
    variation_count: int = 0
    video_url: str = ""

    @field_validator("hashtags", mode="before")
    @classmethod
    def _coerce_tags(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [t for t in v.split(",") if t]
        return list(v)

    @property
    def engagement_rate(self) -> float:
        if self.views <= 0:
            return 0.0
        return (self.likes + self.comments + self.shares + self.saves) / self.views


class ContentSnapshot(BaseRow):
    """Added in Phase 0. Velocity needs two readings of the same video."""
    content_id: str
    captured_at: str
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0

    @property
    def snapshot_key(self) -> str:
        return f"{self.content_id}|{self.captured_at}"


class Hook(BaseRow):
    hook_id: str
    content_id: str
    original_hook: str = ""
    first_3_second_description: str = ""
    visual_hook: str = ""
    spoken_hook: str = ""
    on_screen_text: str = ""
    hook_type: list[str] = Field(default_factory=list)
    creative_format: str = ""
    emotional_trigger: str = ""
    curiosity_mechanism: str = ""
    problem: str = ""
    payoff: str = ""
    cta: str = ""
    target_audience: str = ""
    product_category: str = ""
    analysis_source: str = "metadata"
    prompt_version: str = ""


class CreativePattern(BaseRow):
    """Persistent across days. Never recreated. Matched, not rebuilt."""
    pattern_id: str
    name: str
    creative_mechanism: str
    hook_type: list[str] = Field(default_factory=list)
    structure: str = ""
    emotion: str = ""
    visual: str = ""
    transferability: str = ""
    canonical_text: str = ""
    embedding: list[float] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    example_content_ids: list[str] = Field(default_factory=list)
    example_hooks: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)


class PatternMatchDecision(BaseRow):
    decision_id: str
    date: str
    candidate_text: str
    matched_pattern_id: str | None = None
    similarity: float = 0.0
    runner_up_pattern_id: str | None = None
    runner_up_similarity: float = 0.0
    decider: Literal["vector", "llm", "new"] = "new"
    why: str = ""


class Trend(BaseRow):
    """One row per pattern per day. This is what trends over time."""
    pattern_id: str
    date: str
    momentum_score: float = 0.0
    saturation_score: float = 0.0
    cross_category_score: float = 0.0
    audience_relevance_score: float = 0.0
    product_applicability_score: float = 0.0
    opportunity_score: float = 0.0
    lifecycle_label: Lifecycle = "Emerging"
    opportunity_label: OpportunityLabel = "Low opportunity"
    velocity_views_per_day: float = 0.0
    acceleration: float = 0.0
    is_breakout: bool = False
    velocity_confidence: Confidence = "low"
    distinct_categories: int = 1
    distinct_creators: int = 0
    content_count: int = 0
    pattern_age_days: int = 0
    why_it_matters: str = ""


class Adaptation(BaseRow):
    """A generated hook. Approved or rejected, both are stored."""
    adaptation_id: str
    pattern_id: str
    date: str
    hook: str
    first_frame_visual: str = ""
    first_3_second_action: str = ""
    spoken_dialogue: str = ""
    on_screen_text: str = ""
    creative_mechanism: str = ""
    product_reveal: str = ""
    payoff: str = ""
    cta: str = ""
    cat_role: str = ""
    cat_execution: str = ""
    visual_treatment: str = ""
    hook_score: float = 0.0
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    strengths: str = ""
    weaknesses: str = ""
    risk: str = ""
    recommended_test: str = ""
    opportunity_label: OpportunityLabel = "Experimental"
    track: Literal["proven", "experimental"] = "experimental"
    status: Literal["approved", "rejected"] = "approved"
    rejection_reasons: list[str] = Field(default_factory=list)
    rejection_detail: str = ""
    prompt_version: str = ""


class TestResult(BaseRow):
    """Spec section 19. CSV import first."""
    creative_id: str
    hook_id: str = ""
    trend_id: str = ""
    date_launched: str = ""
    spend: float = 0.0
    impressions: int = 0
    views: int = 0
    three_sec_view_rate: float = 0.0
    twentyfive_percent_view_rate: float = 0.0
    fifty_percent_view_rate: float = 0.0
    ninetyfive_percent_view_rate: float = 0.0
    ctr: float = 0.0
    cpc: float = 0.0
    installs: int = 0
    install_rate: float = 0.0
    purchases: int = 0
    conversion_rate: float = 0.0
    cac: float = 0.0
    roas: float = 0.0
    winner: bool = False


class Winner(BaseRow):
    """Spec section 20. Not just winner=true."""
    winner_id: str
    creative_id: str
    date_analyzed: str
    winning_hook_type: list[str] = Field(default_factory=list)
    winning_emotion: str = ""
    winning_visual: str = ""
    winning_structure: str = ""
    winning_problem: str = ""
    winning_payoff: str = ""
    winning_cta: str = ""
    winning_audience: str = ""
    reusable_pattern: str = ""
    roas: float = 0.0
    cac: float = 0.0


class RadarRow(BaseRow):
    """One video per day on the viral radar. This is the feed we want to be first to.

    Field order is the sheet's column order. The link is what you act on, so it
    is column one; a username is not something you can open.
    """
    url: str = ""
    title: str = ""
    creator: str = ""
    published_at: str | None = None
    competitor: str = ""
    radar_score: float = 0.0
    status: str = "STEADY"
    date: str = ""
    content_id: str = ""
    kind: str = "organic"
    platform: str = ""
    video_url: str = ""
    thumbnail_url: str = ""
    creator_followers: int = 0
    first_seen: str = ""
    age_hours: float = 0.0
    # Raw numbers.
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    engagement_rate: float = 0.0
    duration_seconds: float = 0.0
    hashtags: list[str] = Field(default_factory=list)
    sound_title: str = ""
    # Why it is on the radar.
    views_per_day: float = 0.0
    acceleration: float = 0.0
    creator_lift: float = 0.0
    creator_baseline_views: float = 0.0
    baseline_source: str = "none"
    velocity_confidence: str = "low"
    # None means "not measurable yet", which is different from zero and must stay
    # distinguishable. Acceleration is None until a video has three snapshots.
    components: dict[str, float | None] = Field(default_factory=dict)
    measured: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    # Viral phase detection.
    viral_phase: str = "FLAT"
    engagement_score: float = 0.0
    share_rate: float = 0.0
    save_rate: float = 0.0
    comment_rate: float = 0.0
    like_rate: float = 0.0
    share_rate_band: str = "normal"
    wave_count: int = 0
    wave_ratios: list[float] = Field(default_factory=list)
    views_per_hour: float = 0.0
    peak_views_per_hour: float = 0.0
    snapshot_readings: int = 0
    projection: dict[str, Any] = Field(default_factory=dict)
    on_watchlist: bool = False
    takeoff_tier: str = ""
    vs_expected: float = 0.0
    expected_views: float = 0.0
    is_jackpot: bool = False
    is_already_viral: bool = False
    # Ads only.
    days_running: int = 0
    variation_count: int = 0
    variation_group: str = ""
    ad_start_date: str | None = None
    cta_text: str = ""
    landing_page: str = ""


class VideoTrendRow(BaseRow):
    """One row per video per day, tracking how it moved."""
    date: str
    content_id: str
    direction: str = "NEW"
    competitor: str = ""
    creator: str = ""
    title: str = ""
    url: str = ""
    days_on_radar: int = 1
    first_seen: str = ""
    score_now: float = 0.0
    score_prev: float = 0.0
    score_delta: float = 0.0
    peak_score: float = 0.0
    views_now: int = 0
    views_prev: int = 0
    views_gained: int = 0
    views_gained_pct: float = 0.0
    rank_now: int = 0
    rank_prev: int = 0
    rank_change: int = 0
    note: str = ""
    history: list[dict[str, Any]] = Field(default_factory=list)


class CompetitorTrendRow(BaseRow):
    date: str
    competitor: str
    direction: str = "FLAT"
    videos_now: int = 0
    videos_prev: int = 0
    videos_delta: int = 0
    total_views_now: int = 0
    total_views_prev: int = 0
    avg_score_now: float = 0.0
    avg_score_prev: float = 0.0
    best_video_url: str = ""
    best_video_score: float = 0.0
    note: str = ""


class HashtagTrendRow(BaseRow):
    date: str
    hashtag: str
    count_today: int = 0
    count_yesterday: int = 0
    delta: int = 0
    direction: str = "FLAT"


class DailyBriefRow(BaseRow):
    """Claude's written read of the day, generated in the n8n graph."""
    date: str
    generated_at: str = ""
    source: str = "claude"
    brief: str = ""


class DailyReport(BaseRow):
    date: str
    generated_at: str
    top_patterns: list[dict[str, Any]] = Field(default_factory=list)
    top_hooks: list[dict[str, Any]] = Field(default_factory=list)
    top_ads: list[dict[str, Any]] = Field(default_factory=list)
    concise_text: str = ""
    run_id: str = ""
    stale_sources: list[str] = Field(default_factory=list)


class RunLog(BaseRow):
    run_id: str
    stage: str
    started_at: str
    finished_at: str = ""
    status: Literal["running", "ok", "partial", "failed"] = "running"
    counts: dict[str, int] = Field(default_factory=dict)
    failures: list[dict[str, Any]] = Field(default_factory=list)
    duration_seconds: float = 0.0
    llm_cost_usd: float = 0.0
    notes: str = ""


class LlmCall(BaseRow):
    call_id: str
    run_id: str
    created_at: str
    stage: str
    prompt_name: str
    prompt_version: str
    tier: Literal["cheap", "strong", "video"]
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cache_hit: bool = False
    ok: bool = True
    error: str = ""


TABLES: dict[str, type[BaseRow]] = {
    "RAW_CONTENT": NormalizedContent,
    "CONTENT_SNAPSHOTS": ContentSnapshot,
    "HOOKS": Hook,
    "CREATIVE_PATTERNS": CreativePattern,
    "PATTERN_MATCHES": PatternMatchDecision,
    "TRENDS": Trend,
    "ADAPTATIONS": Adaptation,
    "TEST_RESULTS": TestResult,
    "WINNERS": Winner,
    "RADAR": RadarRow,
    "VIDEO_TRENDS": VideoTrendRow,
    "COMPETITOR_TRENDS": CompetitorTrendRow,
    "HASHTAG_TRENDS": HashtagTrendRow,
    "DAILY_BRIEF": DailyBriefRow,
    "DAILY_REPORTS": DailyReport,
    "RUN_LOG": RunLog,
    "LLM_CALLS": LlmCall,
}

PRIMARY_KEYS: dict[str, str | tuple[str, ...]] = {
    "RAW_CONTENT": "content_id",
    "CONTENT_SNAPSHOTS": ("content_id", "captured_at"),
    "HOOKS": "hook_id",
    "CREATIVE_PATTERNS": "pattern_id",
    "PATTERN_MATCHES": "decision_id",
    "TRENDS": ("pattern_id", "date"),
    "ADAPTATIONS": "adaptation_id",
    "TEST_RESULTS": "creative_id",
    "WINNERS": "winner_id",
    "RADAR": ("date", "content_id"),
    "VIDEO_TRENDS": ("date", "content_id"),
    "COMPETITOR_TRENDS": ("date", "competitor"),
    "HASHTAG_TRENDS": ("date", "hashtag"),
    "DAILY_BRIEF": ("date", "source"),
    "DAILY_REPORTS": "date",
    "RUN_LOG": "run_id",
    "LLM_CALLS": "call_id",
}
