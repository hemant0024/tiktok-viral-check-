"""Every stage: reads from storage, writes to storage. n8n only chains these."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ci.config import Settings, get_settings
from ci.database.base import Repository
from ci.generators.pipeline import Generator, split_tracks
from ci.llm.client import LlmClient
from ci.llm.prompts import load_prompt
from ci.logging import get_logger, log_event
from ci.models import (
    ContentSnapshot,
    CompetitorTrendRow, CreativePattern, DailyReport, HashtagTrendRow,
    RadarRow, Trend, VideoTrendRow,
)
from ci.patterns.embed import Embedder, get_embedder
from ci.patterns.match import PatternMatcher, attach_observation
from ci.processors.cheap_filter import cheap_filter
from ci.processors.dedup import dedup
from ci.processors.snapshots import build_snapshots, snapshots_by_content
from ci.report.radar_render import render_feed, render_slack
from ci.report.render import build_concepts, build_full_report, render_concise
from ci.run import RunContext
from ci.scoring.scores import (
    cross_category_score,
    lifecycle_label,
    momentum_falling_days,
    momentum_score,
    opportunity_label,
    opportunity_score,
    saturation_score,
)
from ci.scoring.radar import apply_feed_caps, radar_score, winner_signal
from ci.scoring.viral_signals import learn_baseline_curve, takeoff_profile, viral_profile
from ci.scoring.velocity import compute_velocity

log = get_logger(__name__)


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def get_collector(name: str, settings: Settings, repo: Repository, path: str | None = None):
    if name == "youtube":
        from ci.collectors.youtube import YouTubeCollector
        return YouTubeCollector(settings)
    if name == "tiktok":
        from ci.collectors.tiktok import TikTokCollector
        return TikTokCollector(settings)
    if name == "meta_ads":
        from ci.collectors.meta_ads import MetaAdsCollector
        runs = [r for r in repo.read("RUN_LOG") if r.get("stage", "").startswith("collect:meta_ads")]
        last = max((r.get("started_at", "") for r in runs), default="")[:10] or None
        return MetaAdsCollector(settings, last_run_date=last)
    if name == "competitor_ugc":
        from ci.collectors.competitor_ugc import CompetitorUgcCollector
        return CompetitorUgcCollector(settings)
    if name == "instagram":
        from ci.collectors.instagram_stub import InstagramStubCollector
        return InstagramStubCollector(settings)
    if name == "csv":
        from ci.collectors.csv_import import CsvCollector
        if not path:
            raise RuntimeError("csv collector needs --path")
        return CsvCollector(path, settings)
    raise RuntimeError(f"unknown source: {name}")


# --------------------------------------------------------------------------- #
def stage_collect(repo: Repository, settings: Settings, sources: list[str],
                  path: str | None = None) -> dict[str, Any]:
    ctx = RunContext(f"collect:{','.join(sources)}", repo)
    existing = repo.read("RAW_CONTENT")
    known_ids = {r.get("content_id") for r in existing}
    snaps = snapshots_by_content(repo.read("CONTENT_SNAPSHOTS"))

    collected = []
    for source in sources:
        with ctx.isolate("source", source):
            collector = get_collector(source, settings, repo, path)
            if not getattr(collector, "enabled", True):
                log_event(log, logging.INFO, "source disabled, skipped", source=source)
                continue
            items = collector.fetch()
            ctx.count(f"fetched_{source}", len(items))
            collected.extend(items)

    unique = dedup(collected)
    ctx.count("unique", len(unique))

    # Content rows are written ONCE. Snapshots are written EVERY run. That pairing
    # is what makes re-running a day idempotent while still building history.
    new_rows = [i.model_dump() for i in unique if i.content_id not in known_ids]
    if new_rows:
        repo.upsert("RAW_CONTENT", new_rows)
    ctx.count("new_content", len(new_rows))

    snapshots = build_snapshots(unique)
    repo.append("CONTENT_SNAPSHOTS", [s.model_dump() for s in snapshots])
    ctx.count("snapshots", len(snapshots))

    for item in unique:
        snaps.setdefault(item.content_id, []).append(
            {"captured_at": datetime.now(timezone.utc).isoformat(), "views": item.views}
        )
    candidates, verdicts = cheap_filter(unique, snaps, settings.scoring)
    ctx.count("candidates", len(candidates))
    ctx.count("filtered_out", len(verdicts) - len(candidates))

    verdict_by_id = {v.content.content_id: v for v in verdicts}
    updates = []
    for item in unique:
        v = verdict_by_id.get(item.content_id)
        row = item.model_dump()
        row["is_candidate"] = bool(v and v.kept and v.slot)
        row["filter_slot"] = v.slot if v else ""
        row["heat"] = v.heat if v else 0.0
        row["filter_reasons"] = v.reasons if v else []
        row["velocity_views_per_day"] = round(v.velocity.views_per_day, 2) if v else 0.0
        row["is_breakout"] = bool(v and v.velocity.is_breakout)
        row["velocity_confidence"] = v.velocity.confidence if v else "low"
        updates.append(row)
    repo.upsert("RAW_CONTENT", updates)

    breakouts = sum(1 for r in updates if r.get("is_breakout") and r.get("is_candidate"))
    ctx.count("breakout_candidates", breakouts)
    summary = ctx.finish()
    return {"summary": summary.model_dump(), "candidates": len(candidates), "breakouts": breakouts}


# --------------------------------------------------------------------------- #
def stage_analyze(repo: Repository, settings: Settings, client: LlmClient,
                  limit: int | None = None) -> dict[str, Any]:
    from ci.analyzers.creative_dna import DnaAnalyzer

    ctx = RunContext("analyze", repo)
    analyzer = DnaAnalyzer(client, settings)
    content = [r for r in repo.read("RAW_CONTENT") if r.get("is_candidate")]
    done = {h.get("content_id") for h in repo.read("HOOKS")}
    todo = [c for c in content if c.get("content_id") not in done]
    # Hottest first, so a budget stop still analyses the ones that matter.
    todo.sort(key=lambda c: c.get("heat", 0), reverse=True)
    if limit:
        todo = todo[:limit]

    hooks, count = [], 0
    for item in todo:
        with ctx.isolate("content", item.get("content_id", "")):
            dna, hook = analyzer.analyse(item)
            row = hook.model_dump()
            row["creative_dna"] = dna
            row["category"] = item.get("category", "")
            hooks.append(row)
            count += 1
    if hooks:
        repo.upsert("HOOKS", hooks)
    ctx.count("analysed", count)
    ctx.count("skipped_already_done", len(content) - len(todo))
    summary = ctx.finish(llm_cost=client.run_cost, llm_rows=client.call_rows())
    return {"summary": summary.model_dump(), "analysed": count, "llm": client.stats()}


# --------------------------------------------------------------------------- #
def stage_patterns_cluster(repo: Repository, settings: Settings, client: LlmClient,
                           embedder: Embedder | None = None) -> dict[str, Any]:
    ctx = RunContext("patterns:cluster", repo)
    embedder = embedder or get_embedder()
    matcher = PatternMatcher(embedder, client, settings.scoring.get("clustering", {}))
    patterns = [CreativePattern(**p) for p in repo.read("CREATIVE_PATTERNS")]
    by_id = {p.pattern_id: p for p in patterns}
    content_by_id = {c.get("content_id"): c for c in repo.read("RAW_CONTENT")}

    new_count = 0
    for hook in repo.read("HOOKS"):
        dna = hook.get("creative_dna") or {}
        if not dna.get("creative_mechanism"):
            continue
        with ctx.isolate("hook", hook.get("hook_id", "")):
            pattern, is_new = matcher.match(dna, list(by_id.values()))
            if is_new:
                new_count += 1
            content = content_by_id.get(hook.get("content_id"), {})
            pattern = attach_observation(
                pattern, content, hook.get("original_hook", ""), content.get("category", "")
            )
            by_id[pattern.pattern_id] = pattern

    repo.upsert("CREATIVE_PATTERNS", [p.model_dump() for p in by_id.values()])
    if matcher.decisions:
        repo.append("PATTERN_MATCHES", [d.model_dump() for d in matcher.decisions])
    ctx.count("patterns_total", len(by_id))
    ctx.count("patterns_new", new_count)
    ctx.count("patterns_matched", len(matcher.decisions) - new_count)
    summary = ctx.finish(llm_cost=client.run_cost, llm_rows=client.call_rows())
    return {"summary": summary.model_dump(), "patterns": len(by_id), "new": new_count}


# --------------------------------------------------------------------------- #
def stage_patterns_score(repo: Repository, settings: Settings, client: LlmClient) -> dict[str, Any]:
    ctx = RunContext("patterns:score", repo)
    scoring = settings.scoring
    patterns = [CreativePattern(**p) for p in repo.read("CREATIVE_PATTERNS")]
    content_by_id = {c.get("content_id"): c for c in repo.read("RAW_CONTENT")}
    snaps = snapshots_by_content(repo.read("CONTENT_SNAPSHOTS"))
    history: dict[str, list[float]] = {}
    for row in repo.read("TRENDS"):
        history.setdefault(row.get("pattern_id", ""), []).append(float(row.get("momentum_score", 0)))

    date = today()
    now = datetime.now(timezone.utc)
    trends: list[dict] = []

    for pattern in patterns:
        with ctx.isolate("pattern", pattern.pattern_id):
            items = [content_by_id[c] for c in pattern.example_content_ids if c in content_by_id]
            # Reference material feeds DNA but never momentum.
            scored_items = [i for i in items if not i.get("is_reference")]
            velocities = [
                compute_velocity(i, snaps.get(i.get("content_id", ""), []),
                                 scoring.get("velocity", {}), scoring.get("breakout", {}), now)
                for i in scored_items
            ]
            if velocities:
                ordered = sorted(v.views_per_day for v in velocities)
                median_vpd = ordered[len(ordered) // 2]
                confidence = "high" if any(v.confidence == "high" for v in velocities) else "low"
                factor = max((v.confidence_factor for v in velocities), default=0.7)
                breakout_mult = max((v.breakout_multiplier for v in velocities), default=1.0)
                is_breakout = any(v.is_breakout for v in velocities)
                acceleration = max((v.acceleration for v in velocities), default=0.0)
            else:
                median_vpd, confidence, factor = 0.0, "low", 0.7
                breakout_mult, is_breakout, acceleration = 1.0, False, 0.0

            momentum = momentum_score(median_vpd, scoring.get("momentum", {}), factor, breakout_mult)

            creators = {i.get("creator", "") for i in items if i.get("creator")}
            categories = set(pattern.categories) or {i.get("category", "") for i in items}
            categories.discard("")
            brands = {i.get("creator", "") for i in items if i.get("is_ad")}
            competitor_names = {
                c.get("name", "").lower()
                for group in ("competitors", "adjacent")
                for c in settings.competitors.get(group, []) or []
            }
            competitors = {c for c in creators if c.lower() in competitor_names}
            age_days = 0
            if pattern.first_seen:
                try:
                    age_days = (now.date() - datetime.fromisoformat(pattern.first_seen).date()).days
                except ValueError:
                    age_days = 0

            judged = {"exact_wording_repetition": 0.0, "visual_repetition": 0.0, "audio_repetition": 0.0}
            if len(pattern.example_hooks) > 1:
                try:
                    judged = client.run_prompt(
                        load_prompt("score_saturation"), stage="patterns_score",
                        cache_content=f"{pattern.pattern_id}|{len(pattern.example_hooks)}",
                        examples=pattern.example_hooks[:15],
                    ).data
                except Exception as exc:  # noqa: BLE001
                    ctx.fail("saturation_judgement", pattern.pattern_id, exc)

            saturation = saturation_score({
                "recent_occurrences": len(items),
                "distinct_brands": len(brands),
                "distinct_competitors": len(competitors),
                "trend_age_days": age_days,
                "exact_wording_repetition": float(judged.get("exact_wording_repetition", 0) or 0),
                "visual_repetition": float(judged.get("visual_repetition", 0) or 0),
                "audio_repetition": float(judged.get("audio_repetition", 0) or 0),
                "distinct_categories": len(categories),
            }, scoring.get("saturation", {}))

            cross = cross_category_score(max(len(categories), 1), scoring.get("cross_category", {}))
            audience_rel = float(pattern.model_extra.get("audience_relevance", 60)) if pattern.model_extra else 60.0
            product_app = float(pattern.model_extra.get("product_applicability", 60)) if pattern.model_extra else 60.0

            opportunity = opportunity_score(momentum, saturation, cross, audience_rel,
                                            product_app, scoring.get("opportunity", {}))
            falling = momentum_falling_days(history.get(pattern.pattern_id, []) + [momentum])
            lifecycle = lifecycle_label(momentum, saturation, age_days, falling, scoring.get("lifecycle", {}))

            trend = Trend(
                pattern_id=pattern.pattern_id, date=date,
                momentum_score=momentum, saturation_score=saturation,
                cross_category_score=cross, audience_relevance_score=audience_rel,
                product_applicability_score=product_app, opportunity_score=opportunity,
                lifecycle_label=lifecycle,
                opportunity_label=opportunity_label(opportunity, scoring.get("quality_gate", {})),
                velocity_views_per_day=round(median_vpd, 2), acceleration=round(acceleration, 2),
                is_breakout=is_breakout, velocity_confidence=confidence,
                distinct_categories=max(len(categories), 1), distinct_creators=len(creators),
                content_count=len(items), pattern_age_days=age_days,
            )

            try:
                narrative = client.run_prompt(
                    load_prompt("detect_trends"), stage="patterns_score",
                    cache_content=f"{pattern.pattern_id}|{date}|{int(opportunity)}",
                    pattern={"name": pattern.name, "creative_mechanism": pattern.creative_mechanism},
                    **{k: getattr(trend, k) for k in (
                        "momentum_score", "saturation_score", "distinct_categories",
                        "opportunity_score", "lifecycle_label", "velocity_views_per_day",
                        "velocity_confidence", "is_breakout", "content_count", "distinct_creators")},
                ).data
                trend.why_it_matters = narrative.get("why_it_matters", "")
            except Exception as exc:  # noqa: BLE001
                ctx.fail("narrative", pattern.pattern_id, exc)

            trends.append(trend.model_dump())

    if trends:
        repo.upsert("TRENDS", trends)
    ctx.count("scored", len(trends))
    ctx.count("breakouts", sum(1 for t in trends if t.get("is_breakout")))
    summary = ctx.finish(llm_cost=client.run_cost, llm_rows=client.call_rows())
    return {"summary": summary.model_dump(), "scored": len(trends)}


# --------------------------------------------------------------------------- #
def stage_generate(repo: Repository, settings: Settings, client: LlmClient,
                   embedder: Embedder | None = None) -> dict[str, Any]:
    ctx = RunContext("generate", repo)
    embedder = embedder or get_embedder()
    generator = Generator(client, embedder, settings)
    gen_cfg = settings.scoring.get("generation", {})
    gate_cfg = settings.scoring.get("quality_gate", {})
    date = today()

    trends = [t for t in repo.read("TRENDS") if t.get("date") == date]
    trends = [t for t in trends if float(t.get("saturation_score", 0)) <= float(gate_cfg.get("max_saturation", 80))]
    trends.sort(key=lambda t: t.get("opportunity_score", 0), reverse=True)
    trends = trends[: int(gen_cfg.get("patterns_per_day", 5))]

    patterns = {p.get("pattern_id"): CreativePattern(**p) for p in repo.read("CREATIVE_PATTERNS")}
    winners = repo.read("WINNERS")
    losers = [r for r in repo.read("TEST_RESULTS") if not r.get("winner")]
    tracks = split_tracks(len(trends), gen_cfg, bool(winners))

    all_rows: list[dict] = []
    for trend, track in zip(trends, tracks):
        pattern = patterns.get(trend.get("pattern_id"))
        if pattern is None:
            continue
        with ctx.isolate("pattern", pattern.pattern_id):
            adaptations = generator.generate_for_pattern(
                pattern, trend, pattern.example_hooks, winners, losers, track
            )
            all_rows.extend(a.model_dump() for a in adaptations)

    if all_rows:
        repo.upsert("ADAPTATIONS", all_rows)
    approved = sum(1 for a in all_rows if a.get("status") == "approved")
    ctx.count("generated", len(all_rows))
    ctx.count("approved", approved)
    ctx.count("rejected", len(all_rows) - approved)
    summary = ctx.finish(llm_cost=client.run_cost, llm_rows=client.call_rows())
    return {"summary": summary.model_dump(), "generated": len(all_rows), "approved": approved}


# --------------------------------------------------------------------------- #
def stage_report(repo: Repository, settings: Settings) -> dict[str, Any]:
    ctx = RunContext("report", repo)
    date = today()
    gen_cfg = settings.scoring.get("generation", {})
    trends = [t for t in repo.read("TRENDS") if t.get("date") == date]
    patterns = {p.get("pattern_id"): p for p in repo.read("CREATIVE_PATTERNS")}
    adaptations = [a for a in repo.read("ADAPTATIONS") if a.get("date") == date]

    failures: list[str] = []
    for row in repo.read("RUN_LOG"):
        if row.get("started_at", "")[:10] == date:
            for failure in row.get("failures", []):
                if failure.get("scope") == "source":
                    failures.append(f"{failure.get('item')}: {failure.get('error', '')[:80]}")

    concepts = build_concepts(trends, patterns, adaptations, int(gen_cfg.get("report_top_ads", 5)))
    full = build_full_report(concepts, adaptations, settings.scoring)
    concise = render_concise(
        date, concepts, sorted(set(failures)),
        settings.product.get("market", {}).get("date_format", "%B %-d, %Y"),
    )
    report = DailyReport(
        date=date, generated_at=datetime.now(timezone.utc).isoformat(),
        top_patterns=full["top_patterns"], top_hooks=full["top_hooks"],
        top_ads=full["top_ads"], concise_text=concise, run_id=ctx.run_id,
        stale_sources=sorted(set(failures)),
    )
    repo.upsert("DAILY_REPORTS", [report.model_dump()])
    ctx.count("concepts", len(concepts))
    ctx.count("hooks_in_report", len(full["top_hooks"]))
    summary = ctx.finish()
    return {"summary": summary.model_dump(), "concise": concise, "concepts": len(concepts)}


# --------------------------------------------------------------------------- #
def stage_notify(repo: Repository, settings: Settings, channel: str = "slack") -> dict[str, Any]:
    from ci.notifications import get_notifier

    ctx = RunContext(f"notify:{channel}", repo)
    date = today()
    reports = [r for r in repo.read("DAILY_REPORTS") if r.get("date") == date]
    if not reports:
        raise RuntimeError(f"no report stored for {date}. run `ci report` first")
    notifier = get_notifier(channel, settings)
    with ctx.isolate("notifier", channel):
        notifier.send(reports[-1].get("concise_text", ""))
        ctx.count("sent")
    summary = ctx.finish()
    return {"summary": summary.model_dump(), "sent": ctx.counts.get("sent", 0)}


# --------------------------------------------------------------------------- #
def stage_import_ads(repo: Repository, settings: Settings, client: LlmClient,
                     path: str) -> dict[str, Any]:
    from ci.analyzers.winners import WinnerAnalyzer, load_test_results, mark_winners

    ctx = RunContext("import:ads", repo)
    rules = settings.scoring.get("winner_rules", {})
    results = mark_winners(load_test_results(path), rules)
    repo.upsert("TEST_RESULTS", [r.model_dump() for r in results])
    ctx.count("imported", len(results))

    winners = [r for r in results if r.winner]
    ctx.count("winners", len(winners))
    adaptations = {a.get("adaptation_id"): a for a in repo.read("ADAPTATIONS")}
    hooks = {h.get("hook_id"): h for h in repo.read("HOOKS")}
    baseline = [r.model_dump() for r in results if not r.winner][:10]

    analyzer = WinnerAnalyzer(client, settings)
    rows = []
    for result in winners:
        with ctx.isolate("winner", result.creative_id):
            creative = adaptations.get(result.creative_id) or hooks.get(result.hook_id) or {
                "creative_id": result.creative_id
            }
            rows.append(analyzer.analyse(result, creative, baseline).model_dump())
    if rows:
        repo.upsert("WINNERS", rows)
    ctx.count("winner_dna_extracted", len(rows))
    summary = ctx.finish(llm_cost=client.run_cost, llm_rows=client.call_rows())
    return {"summary": summary.model_dump(), "imported": len(results), "winners": len(winners)}


# --------------------------------------------------------------------------- #
def stage_healthcheck(repo: Repository, settings: Settings) -> dict[str, Any]:
    from ci.collectors.instagram_stub import InstagramStubCollector
    from ci.collectors.meta_ads import MetaAdsCollector
    from ci.collectors.tiktok import TikTokCollector
    from ci.collectors.youtube import YouTubeCollector

    client = LlmClient(settings)
    checks: dict[str, Any] = {
        "storage": repo.healthcheck(),
        "config": {
            "product_loaded": bool(settings.product),
            "market": settings.market_country,
            "timezone": settings.timezone_name,
            "categories": len(settings.sources.get("categories", [])),
            "competitors": len(settings.competitors.get("competitors", [])),
            "cat_roles": len(settings.cat_roles),
            "max_duration_seconds": settings.scoring.get("cheap_filter", {}).get("max_duration_seconds"),
        },
        "llm": {
            "provider": settings.llm_provider,
            "cheap_model": settings.llm_cheap_model,
            "strong_model": settings.llm_strong_model,
            "openai_key": bool(settings.openai_api_key),
            "video_enabled": client.video_enabled(),
            "gemini_key": bool(settings.gemini_api_key),
            "priced_models": len(client.pricing),
        },
        "sources": [
            YouTubeCollector(settings).describe(),
            TikTokCollector(settings).describe(),
            MetaAdsCollector(settings).describe(),
            InstagramStubCollector(settings).describe(),
        ],
        "notifications": {
            "slack": bool(settings.slack_bot_token),
            "telegram": bool(settings.telegram_bot_token),
        },
    }
    missing = []
    if not settings.openai_api_key and settings.llm_provider == "openai":
        missing.append("OPENAI_API_KEY")
    if not settings.youtube_api_key and settings.sources.get("youtube", {}).get("enabled"):
        missing.append("YOUTUBE_API_KEY")
    if not settings.apify_token and (
        settings.sources.get("tiktok", {}).get("enabled")
        or settings.sources.get("meta_ads", {}).get("enabled")
    ):
        missing.append("APIFY_TOKEN")
    prompts_ok, prompt_errors = [], []
    for name in ("extract_creative_dna", "classify_hook", "cluster_patterns", "detect_trends",
                 "score_saturation", "adapt_to_product", "generate_hooks",
                 "generate_cat_execution", "score_hooks", "analyze_winners",
                 "generate_daily_report"):
        try:
            load_prompt(name)
            prompts_ok.append(name)
        except Exception as exc:  # noqa: BLE001
            prompt_errors.append(f"{name}: {exc}")
    checks["prompts"] = {"loaded": len(prompts_ok), "errors": prompt_errors}
    checks["missing_env"] = missing
    checks["ok"] = bool(checks["storage"].get("ok")) and not prompt_errors
    return checks


# --------------------------------------------------------------------------- #
KIND_GROUPS: dict[str, set[str]] = {
    "ads": {"competitor_ad"},
    "ugc": {"organic_ugc", "organic"},
}


def stage_radar(repo: Repository, settings: Settings, now: datetime | None = None,
                kind: str | None = None) -> dict[str, Any]:
    """The viral radar. Per video, not per pattern.

    Answers: which competitor video is taking off, or about to, right now.
    Pure Python. No LLM call, so it is cheap enough to run more than once a day
    if we ever want to shorten the loop.

    `kind` scores only ads or only UGC. The two flows run independently, so a
    dead Apify actor on the ads side must not stop UGC from being scored.
    RADAR is upserted per row, so two scoped runs coexist in one table.
    """
    ctx = RunContext(f"radar:{kind}" if kind else "radar", repo)
    now = now or datetime.now(timezone.utc)
    date = now.date().isoformat()
    scoring = settings.scoring
    cfg = scoring.get("radar", {})

    content = repo.read("RAW_CONTENT")
    if kind:
        wanted = KIND_GROUPS.get(kind)
        if not wanted:
            raise RuntimeError(f"unknown kind {kind!r}, expected one of {sorted(KIND_GROUPS)}")
        content = [r for r in content if r.get("kind") in wanted]
    snaps = snapshots_by_content(repo.read("CONTENT_SNAPSHOTS"))

    # Group by creator once, so creator baselines are a lookup not a scan.
    by_creator: dict[str, list[dict]] = {}
    for row in content:
        by_creator.setdefault(row.get("creator", ""), []).append(row)

    # Baseline learned from our own history, so pace stays honest as the niche
    # shifts. Falls back to the config curve until there is enough data.
    learned = learn_baseline_curve(content, scoring.get("takeoff", {}), now)
    if learned:
        log_event(log, logging.INFO, "using learned baseline curve", buckets=learned)

    rows: list[dict] = []
    for item in content:
        cid = item.get("content_id", "")
        with ctx.isolate("content", cid):
            vel = compute_velocity(item, snaps.get(cid, []), scoring.get("velocity", {}),
                                   scoring.get("breakout", {}), now)
            if item.get("kind") == "competitor_ad":
                # Ads have no views to measure, so they get the money-over-time signal.
                verdict = winner_signal(item, scoring.get("winner_signal", {}))
            else:
                history = by_creator.get(item.get("creator", ""), [])
                vp = viral_profile(item, snaps.get(cid, []),
                                   scoring.get("viral_signals", {}), vel.age_hours, now)
                from ci.scoring.radar import compute_lift
                lift, _, _ = compute_lift(item, history, cfg)
                tp = takeoff_profile(item, vel.age_hours, scoring.get("takeoff", {}), lift,
                                     learned_curve=learned or None)
                verdict = radar_score(item, vel, history, cfg, viral=vp, takeoff=tp)
            views = max(int(item.get("views") or 0), 1)
            engagement = (int(item.get("likes") or 0) + int(item.get("comments") or 0)
                          + int(item.get("shares") or 0) + int(item.get("saves") or 0)) / views
            first_seen = min(
                (s.get("captured_at", "") for s in snaps.get(cid, []) if s.get("captured_at")),
                default=item.get("date_found", ""),
            )
            rows.append(RadarRow(
                date=date, content_id=cid,
                radar_score=verdict.radar_score, status=verdict.status,
                competitor=item.get("competitor", ""), kind=item.get("kind", "organic"),
                platform=item.get("platform", ""),
                url=item.get("url", ""), video_url=item.get("video_url", ""),
                thumbnail_url=item.get("thumbnail_url", ""),
                title=item.get("title", ""), creator=item.get("creator", ""),
                creator_followers=int(item.get("creator_followers") or 0),
                published_at=item.get("published_at"), first_seen=first_seen,
                age_hours=round(vel.age_hours, 1),
                views=int(item.get("views") or 0), likes=int(item.get("likes") or 0),
                comments=int(item.get("comments") or 0), shares=int(item.get("shares") or 0),
                saves=int(item.get("saves") or 0), engagement_rate=round(engagement, 5),
                duration_seconds=float(item.get("duration_seconds") or 0),
                hashtags=item.get("hashtags") or [], sound_title=item.get("sound_title", ""),
                views_per_day=round(vel.views_per_day, 1),
                acceleration=round(vel.acceleration, 1),
                creator_lift=verdict.creator_lift,
                creator_baseline_views=verdict.creator_baseline_views,
                baseline_source=verdict.baseline_source,
                velocity_confidence=vel.confidence,
                components=verdict.components, measured=verdict.measured,
                reasons=verdict.reasons,
                viral_phase=verdict.viral.phase if verdict.viral else "FLAT",
                engagement_score=verdict.viral.engagement_score if verdict.viral else 0.0,
                share_rate=verdict.viral.ratios["share_rate"].value if verdict.viral else 0.0,
                save_rate=verdict.viral.ratios["save_rate"].value if verdict.viral else 0.0,
                comment_rate=verdict.viral.ratios["comment_rate"].value if verdict.viral else 0.0,
                like_rate=verdict.viral.ratios["like_rate"].value if verdict.viral else 0.0,
                share_rate_band=verdict.viral.ratios["share_rate"].band if verdict.viral else "normal",
                wave_count=verdict.viral.waves.wave_count if verdict.viral else 0,
                wave_ratios=verdict.viral.waves.ratios if verdict.viral else [],
                views_per_hour=round(verdict.viral.waves.current_hourly, 1) if verdict.viral else 0.0,
                peak_views_per_hour=round(verdict.viral.waves.peak_hourly, 1) if verdict.viral else 0.0,
                snapshot_readings=verdict.viral.waves.readings if verdict.viral else 0,
                projection=verdict.viral.projection if verdict.viral else {},
                takeoff_tier=verdict.takeoff.tier if verdict.takeoff else "",
                vs_expected=verdict.takeoff.vs_expected if verdict.takeoff else 0.0,
                expected_views=verdict.takeoff.expected_views if verdict.takeoff else 0.0,
                is_jackpot=verdict.takeoff.is_jackpot if verdict.takeoff else False,
                is_already_viral=verdict.takeoff.is_already_viral if verdict.takeoff else False,
                days_running=int(item.get("days_running") or 0),
                variation_count=int(item.get("variation_count") or 0),
                variation_group=item.get("variation_group", ""),
                ad_start_date=item.get("ad_start_date"),
                cta_text=item.get("cta_text", ""), landing_page=item.get("landing_page", ""),
            ).model_dump())

    feed = apply_feed_caps(rows, cfg)
    if rows:
        repo.upsert("RADAR", rows)

    hot = [r for r in feed if r["status"] in {"EXPLODING", "CLIMBING", "EARLY SIGNAL"}]
    ctx.count("scored", len(rows))
    ctx.count("on_feed", len(feed))
    for status in ("EXPLODING", "CLIMBING", "EARLY SIGNAL", "STEADY", "COOLING"):
        n = sum(1 for r in rows if r["status"] == status)
        if n:
            ctx.count(status.lower().replace(" ", "_"), n)

    failures = []
    for row in repo.read("RUN_LOG"):
        if row.get("started_at", "")[:10] == date:
            for failure in row.get("failures", []):
                if failure.get("scope") == "source":
                    failures.append(f"{failure.get('item')}: {failure.get('error','')[:60]}")

    summary = ctx.finish()
    return {
        "summary": summary.model_dump(),
        "kind": kind or "all",
        "feed": feed,
        "hot": len(hot),
        "text": render_feed(date, feed, sorted(set(failures))),
        "slack": render_slack(date, feed),
    }


def stage_notify_radar(repo: Repository, settings: Settings, channel: str = "slack") -> dict[str, Any]:
    from ci.notifications import get_notifier

    ctx = RunContext(f"notify_radar:{channel}", repo)
    date = today()
    rows = [r for r in repo.read("RADAR") if r.get("date") == date]
    if not rows:
        raise RuntimeError(f"no radar rows for {date}. run `ci radar` first")
    feed = apply_feed_caps(rows, settings.scoring.get("radar", {}))
    with ctx.isolate("notifier", channel):
        get_notifier(channel, settings).send(render_slack(date, feed))
        ctx.count("sent")
    summary = ctx.finish()
    return {"summary": summary.model_dump(), "sent": ctx.counts.get("sent", 0)}


# --------------------------------------------------------------------------- #
def stage_sheets_push(repo: Repository, settings: Settings,
                      kind: str | None = None,
                      tables: list[str] | None = None) -> dict[str, Any]:
    """Push into the shared Google Sheet. The sheet is where every flow ends.

    `kind` splits ads from UGC into their own tabs. They are different things
    scored on different signals (ads on days running and variations, UGC on
    waves and share rate), so mixing them in one tab means every column is blank
    for half the rows and neither reads cleanly.

    TODAY tabs are replaced each morning. HISTORY tabs ACCUMULATE, because trends
    are only computable from kept history.
    """
    from ci.database.sheets import SheetsRepository

    label = kind or "all"
    ctx = RunContext(f"sheets:push:{label}", repo)
    if not settings.google_service_account_json or not settings.google_sheet_id:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_SHEET_ID must be set in .env"
        )
    target = SheetsRepository(settings.google_service_account_json, settings.google_sheet_id)
    cfg = settings.scoring.get("sheet", {})
    keep_days = int(cfg.get("history_days", 180))
    date = today()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).date().isoformat()

    def radar_rows(kinds: set[str] | None) -> tuple[list[dict], list[dict]]:
        rows = repo.read("RADAR")
        if kinds:
            rows = [r for r in rows if r.get("kind") in kinds]
        todays = sorted([r for r in rows if r.get("date") == date],
                        key=lambda r: float(r.get("radar_score", 0)), reverse=True)
        history = sorted([r for r in rows if r.get("date", "") >= cutoff],
                         key=lambda r: (r.get("date", ""), -float(r.get("radar_score", 0))),
                         reverse=True)
        return todays, history

    plan: list[tuple[str, list[dict], bool]] = []

    if kind in (None, "ads"):
        todays, history = radar_rows({"competitor_ad"})
        plan += [("ADS_TODAY", todays, True), ("ADS_HISTORY", history, False)]
    if kind in (None, "ugc"):
        todays, history = radar_rows({"organic_ugc", "organic"})
        plan += [("UGC_TODAY", todays, True), ("UGC_HISTORY", history, False)]
    if kind is None:
        plan += [
            ("VIDEO_TRENDS", [r for r in repo.read("VIDEO_TRENDS") if r.get("date", "") >= cutoff], False),
            ("COMPETITOR_TRENDS", [r for r in repo.read("COMPETITOR_TRENDS") if r.get("date", "") >= cutoff], False),
            ("HASHTAG_TRENDS", [r for r in repo.read("HASHTAG_TRENDS") if r.get("date", "") >= cutoff], False),
            ("RUN_LOG", repo.read("RUN_LOG")[-500:], False),
        ]
    if tables:
        plan = [p for p in plan if p[0] in tables]

    for tab, rows, replace in plan:
        with ctx.isolate("tab", tab):
            if not rows:
                continue
            if replace:
                target.replace_tab(tab, rows)
            else:
                target.upsert_tab(tab, rows)
            ctx.count(f"pushed_{tab}", len(rows))

    summary = ctx.finish()
    return {"summary": summary.model_dump(), "kind": label,
            "tabs": [p[0] for p in plan],
            "sheet_url": f"https://docs.google.com/spreadsheets/d/{settings.google_sheet_id}/edit"}


def stage_brief_input(repo: Repository, settings: Settings,
                      kind: str = "ugc", limit: int = 12) -> dict[str, Any]:
    """The compact payload the Claude node reads.

    The full radar feed is tens of thousands of tokens of numbers Claude does not
    need. This hands it the day's top rows with only the fields a written read
    actually turns on, plus what yesterday looked like so it can say what changed
    rather than re-describing today from scratch.
    """
    wanted = KIND_GROUPS.get(kind)
    if not wanted:
        raise RuntimeError(f"unknown kind {kind!r}, expected one of {sorted(KIND_GROUPS)}")
    date = today()
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    rows = [r for r in repo.read("RADAR") if r.get("kind") in wanted]

    keep = ("url", "title", "creator", "published_at", "competitor", "age_hours",
            "views", "shares", "radar_score", "status", "creator_followers",
            "phase", "takeoff_tier", "share_rate", "lift", "vs_expected",
            "is_jackpot", "days_running", "variation_count", "hook_text", "content_id")

    def slim(r: dict) -> dict:
        return {k: r[k] for k in keep if r.get(k) not in (None, "", 0, 0.0, False)}

    todays = sorted([r for r in rows if r.get("date") == date],
                    key=lambda r: float(r.get("radar_score", 0)), reverse=True)[:limit]
    prior = sorted([r for r in rows if r.get("date") == yesterday],
                   key=lambda r: float(r.get("radar_score", 0)), reverse=True)[:limit]

    trends_tab = "COMPETITOR_TRENDS"
    trends = [r for r in repo.read(trends_tab) if r.get("date") == date][:15]

    return {
        "kind": kind, "date": date,
        "counts": {"scored_today": sum(1 for r in rows if r.get("date") == date),
                   "on_brief": len(todays)},
        "today": [slim(r) for r in todays],
        "yesterday": [slim(r) for r in prior],
        "competitor_trends": [{k: v for k, v in r.items() if k != "date"} for r in trends],
        "note": ("Ads carry no view counts — Meta does not publish them for US commercial "
                 "ads — so judge these on days running and variation count."
                 if kind == "ads" else
                 "Judge these on views relative to age, share rate, and wave ratios. "
                 "An already-huge video is not a finding."),
    }


def stage_save_brief(repo: Repository, settings: Settings,
                     brief: str, source: str = "claude") -> dict[str, Any]:
    """Write Claude's written read of the day into the sheet.

    The brief is generated by a Claude node inside the n8n graph rather than
    inside Python, so the prompt is visible and editable by whoever owns the
    workflow instead of buried in a Python file.
    """
    from ci.database.sheets import SheetsRepository

    ctx = RunContext("sheets:brief", repo)
    if not brief or not brief.strip():
        raise RuntimeError("brief is empty, nothing to save")
    if not settings.google_service_account_json or not settings.google_sheet_id:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_SHEET_ID must be set")

    row = {
        "date": today(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "brief": brief.strip()[:45000],
    }
    repo.upsert("DAILY_BRIEF", [row])
    target = SheetsRepository(settings.google_service_account_json, settings.google_sheet_id)
    with ctx.isolate("tab", "DAILY_BRIEF"):
        target.upsert_tab("DAILY_BRIEF", repo.read("DAILY_BRIEF"),
                          key_fields=("date", "source"))
        ctx.count("saved", 1)
    summary = ctx.finish()
    return {"summary": summary.model_dump(), "date": row["date"],
            "chars": len(row["brief"])}


# --------------------------------------------------------------------------- #
def stage_watch(repo: Repository, settings: Settings,
                now: datetime | None = None) -> dict[str, Any]:
    """Re-poll the videos that look like they are taking off.

    This stage was referenced by the CLI, the HTTP server, run_watch.sh and the
    n8n watch workflow, and never existed. `/health` advertised it and calling it
    raised AttributeError, so the job failed 48 times a day in silence.

    That matters more than a missing function usually would. Distribution waves
    are 22% of the radar score and the single strongest signal in it, and a wave
    is this hour's view rate against last hour's. A once-daily snapshot can never
    produce one. Without this stage every video read "waves not measurable yet",
    permanently, and the strongest component was dead weight on every row.
    """
    from ci.collectors.apify import ApifyThrottled
    from ci.collectors.competitor_ugc import CompetitorUgcCollector

    ctx = RunContext("watch", repo)
    now = now or datetime.now(timezone.utc)
    cfg = settings.scoring.get("viral_signals", {}).get("watchlist", {})
    if not cfg.get("enabled", True):
        summary = ctx.finish(notes="watchlist disabled in config")
        return {"summary": summary.model_dump(), "tracked": 0, "polled": 0}

    min_score = float(cfg.get("add_above_score", 35))
    max_age = float(cfg.get("add_if_age_hours_below", 72))
    max_tracked = int(cfg.get("max_tracked", 60))
    drop_after = float(cfg.get("drop_after_hours", 168))

    # Latest radar row per video, so a video is judged on its most recent score
    # rather than whatever it scored the first morning it appeared.
    latest: dict[str, dict] = {}
    for row in repo.read("RADAR"):
        cid = row.get("content_id", "")
        if not cid:
            continue
        if cid not in latest or row.get("date", "") >= latest[cid].get("date", ""):
            latest[cid] = row

    by_id = {r.get("content_id", ""): r for r in repo.read("RAW_CONTENT")}
    candidates: list[dict] = []
    for cid, row in latest.items():
        age = float(row.get("age_hours") or 0.0)
        if float(row.get("radar_score") or 0) < min_score:
            continue
        if age >= drop_after:
            continue
        # Young enough to still be climbing, OR already showing waves and so
        # worth following past the usual cutoff.
        waves = int(row.get("wave_count") or 0)
        if age > max_age and waves < 1:
            continue
        content = by_id.get(cid)
        if not content or not content.get("url"):
            continue
        candidates.append({"content_id": cid, "url": content["url"],
                           "score": float(row.get("radar_score") or 0)})

    candidates.sort(key=lambda c: -c["score"])
    watchlist = candidates[:max_tracked]
    ctx.count("tracked", len(watchlist))
    if not watchlist:
        summary = ctx.finish(notes="nothing above the watchlist threshold yet")
        return {"summary": summary.model_dump(), "tracked": 0, "polled": 0, "moved": []}

    from ci.collectors.competitor_ugc import build_actor_input

    collector = CompetitorUgcCollector(settings)
    client = collector.client()
    urls = [c["url"] for c in watchlist]

    # Direct URLs, not a search, so no date or sorting add-on is charged. This is
    # the cheapest call the system makes per video, which matters because the
    # watch job polls far more videos per day than the morning sweep collects.
    #
    # Same two-actor fallback as collection: the cheap actor is paid-only, and a
    # watch job that silently does nothing would leave waves permanently blank,
    # which is exactly the failure this stage exists to fix.
    items: list[dict] = []
    tried: list[str] = []
    for actor in (collector.tiktok_cfg.get("actor", ""),
                  collector.tiktok_cfg.get("fallback_actor", "")):
        if not actor or actor in tried:
            continue
        tried.append(actor)
        shape = collector._actor_spec(actor).get("by_url", {})
        if not shape:
            continue
        with ctx.isolate("source", f"watch:{actor}"):
            try:
                items = client.run_actor(
                    actor,
                    build_actor_input(shape, urls=urls, max_items=len(urls),
                                      country=collector.tiktok_cfg.get("location", "US")),
                    max_items=len(urls))
                ctx.count("actor_used", 1)
                log_event(log, logging.INFO, "watch polled", actor=actor, items=len(items))
                break
            except ApifyThrottled as exc:
                log_event(log, logging.WARNING, "watch actor throttled, trying next",
                          actor=actor, error=str(exc))
                client.consecutive_empty = 0
                ctx.count("throttled", 1)

    captured = now.isoformat(timespec="seconds")
    snapshots: list[dict] = []
    by_url = {c["url"].rstrip("/"): c["content_id"] for c in watchlist}
    for item in items:
        with ctx.isolate("item", str(item.get("id", ""))):
            try:
                content = collector._tt.normalize(item, "watch", "")
            except Exception as exc:  # noqa: BLE001 - one bad row must not stop the poll
                log_event(log, logging.WARNING, "watch item skipped", error=str(exc))
                continue
            cid = by_url.get((content.url or "").rstrip("/")) or content.content_id
            if not cid:
                continue
            snapshots.append(ContentSnapshot(
                content_id=cid, captured_at=captured,
                views=content.views, likes=content.likes,
                comments=content.comments, shares=content.shares,
                saves=content.saves,
            ).model_dump())

    if snapshots:
        repo.upsert("CONTENT_SNAPSHOTS", snapshots)
    ctx.count("polled", len(snapshots))

    # What actually changed since the previous reading, which is the only reason
    # to send a notification at all.
    previous = snapshots_by_content(repo.read("CONTENT_SNAPSHOTS"))
    moved: list[dict] = []
    for snap in snapshots:
        cid = snap["content_id"]
        history = sorted(previous.get(cid, []), key=lambda r: r.get("captured_at", ""))
        if len(history) < 2:
            continue
        before, after = history[-2], history[-1]
        gained = int(after.get("views") or 0) - int(before.get("views") or 0)
        if gained <= 0:
            continue
        row = latest.get(cid, {})
        moved.append({
            "content_id": cid,
            "url": by_id.get(cid, {}).get("url", ""),
            "creator": row.get("creator", ""),
            "competitor": row.get("competitor", ""),
            "views": int(after.get("views") or 0),
            "gained": gained,
            "readings": len(history),
        })
    moved.sort(key=lambda m: -m["gained"])
    ctx.count("moved", len(moved))

    summary = ctx.finish()
    return {"summary": summary.model_dump(), "tracked": len(watchlist),
            "polled": len(snapshots), "moved": moved[:10]}


# --------------------------------------------------------------------------- #
def stage_trends(repo: Repository, settings: Settings, now: datetime | None = None) -> dict[str, Any]:
    """Day over day movement. Needs RADAR history, which is why nothing is ever
    overwritten there."""
    from ci.scoring.trends import (
        competitor_trends, dropped_off, hashtag_trends, video_trends,
    )

    ctx = RunContext("trends", repo)
    now = now or datetime.now(timezone.utc)
    date = now.date().isoformat()
    cfg = settings.scoring.get("trends", {})
    radar = repo.read("RADAR")

    days = len({r.get("date") for r in radar})
    if days < 2:
        ctx.count("days_of_history", days)
        summary = ctx.finish(notes="needs a second day before trends mean anything")
        return {"summary": summary.model_dump(), "videos": 0, "competitors": 0,
                "note": "only one day of history so far, trends start tomorrow"}

    vt = video_trends(radar, date, int(cfg.get("lookback_days", 14)),
                      float(cfg.get("min_score_delta", 3.0)))
    ct = competitor_trends(radar, date)
    ht = hashtag_trends(radar, date, int(cfg.get("top_hashtags", 15)))
    gone = dropped_off(radar, date)

    if vt:
        repo.upsert("VIDEO_TRENDS", [VideoTrendRow(date=date, **{
            k: v for k, v in t.__dict__.items()}).model_dump() for t in vt])
    if ct:
        repo.upsert("COMPETITOR_TRENDS", [CompetitorTrendRow(date=date, **{
            k: v for k, v in c.__dict__.items()}).model_dump() for c in ct])
    if ht:
        repo.upsert("HASHTAG_TRENDS", [HashtagTrendRow(**h).model_dump() for h in ht])

    rising = [t for t in vt if t.direction == "RISING"]
    ctx.count("days_of_history", days)
    ctx.count("videos_tracked", len(vt))
    ctx.count("rising", len(rising))
    ctx.count("falling", sum(1 for t in vt if t.direction == "FALLING"))
    ctx.count("new", sum(1 for t in vt if t.direction == "NEW"))
    ctx.count("dropped_off", len(gone))
    summary = ctx.finish()
    return {
        "summary": summary.model_dump(),
        "videos": len(vt), "competitors": len(ct),
        "rising": [{"creator": t.creator, "competitor": t.competitor,
                    "score": t.score_now, "delta": t.score_delta,
                    "days": t.days_on_radar, "url": t.url, "note": t.note}
                   for t in rising[:10]],
        "dropped_off": gone[:10],
    }
