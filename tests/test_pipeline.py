"""End to end, with the fake provider and the in memory repo. No network, no keys."""
from __future__ import annotations

import csv
from datetime import timedelta

import pytest

from ci.database import InMemoryRepository
from ci.llm.client import LlmClient
from ci.llm.providers.fake import FakeProvider
from ci.patterns.embed import HashingEmbedder
from ci.stages import (
    stage_analyze, stage_collect, stage_generate, stage_import_ads,
    stage_patterns_cluster, stage_patterns_score, stage_report,
)
from tests.helpers import NOW

pytestmark = pytest.mark.unit

ROWS = [
    ("tt1", "I probably shouldn't tell you this about English", 180000, 22000, 9000, 4200, 26),
    ("tt2", "POV: you understand the question but cannot answer", 240000, 31000, 12000, 5100, 34),
    ("tt3", "The mistake every English learner makes on day one", 90000, 11000, 3000, 900, 45),
    ("tt4", "Nobody tells you this about speaking a new language", 320000, 40000, 15000, 7000, 29),
    ("tt5", "Watch me correct her pronunciation in real time", 150000, 18000, 6000, 2200, 38),
]


@pytest.fixture
def csv_path(tmp_path):
    path = tmp_path / "seed.csv"
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "url", "creator", "title", "views", "likes",
                         "saves", "shares", "duration", "date", "category"])
        for i, (cid, title, views, likes, saves, shares, dur) in enumerate(ROWS):
            writer.writerow([
                cid, f"https://www.tiktok.com/@c{i}/video/{cid}", f"creator{i}", title,
                views, likes, saves, shares, dur,
                (NOW - timedelta(hours=10 + i * 3)).isoformat(), "language learning",
            ])
    return str(path)


@pytest.fixture
def client(settings):
    return LlmClient(settings, provider=FakeProvider(), video_provider=FakeProvider())


def test_collect_twice_writes_content_once_and_snapshots_twice(settings, csv_path):
    """Phase 2 acceptance, exactly as written in the brief."""
    repo = InMemoryRepository()
    first = stage_collect(repo, settings, ["csv"], path=csv_path)
    content_after_one = len(repo.read("RAW_CONTENT"))
    snaps_after_one = len(repo.read("CONTENT_SNAPSHOTS"))

    stage_collect(repo, settings, ["csv"], path=csv_path)
    content_after_two = len(repo.read("RAW_CONTENT"))
    snaps_after_two = len(repo.read("CONTENT_SNAPSHOTS"))

    assert content_after_one == len(ROWS)
    assert content_after_two == content_after_one, "re-running a day created duplicate content"
    assert snaps_after_two == snaps_after_one * 2, "snapshots must accumulate every run"

    ids = [r["content_id"] for r in repo.read("RAW_CONTENT")]
    assert len(ids) == len(set(ids))
    assert first["candidates"] > 0


def test_one_source_failing_does_not_end_the_run(settings):
    repo = InMemoryRepository()
    result = stage_collect(repo, settings, ["csv"], path="/nonexistent/file.csv")
    summary = result["summary"]
    assert summary["status"] in {"partial", "failed"}
    assert summary["failures"], "the failure must appear in the run summary"
    assert summary["failures"][0]["scope"] == "source"
    assert repo.read("RUN_LOG"), "the run summary must be persisted"


def test_full_pipeline_produces_a_report(settings, csv_path, client):
    repo = InMemoryRepository()
    embedder = HashingEmbedder()

    stage_collect(repo, settings, ["csv"], path=csv_path)
    analyzed = stage_analyze(repo, settings, client)
    assert analyzed["analysed"] > 0
    assert repo.read("HOOKS")

    clustered = stage_patterns_cluster(repo, settings, client, embedder)
    assert clustered["patterns"] > 0
    assert repo.read("PATTERN_MATCHES"), "every match decision must be auditable"

    scored = stage_patterns_score(repo, settings, client)
    assert scored["scored"] > 0
    trends = repo.read("TRENDS")
    assert all(0 <= t["opportunity_score"] <= 100 for t in trends)

    generated = stage_generate(repo, settings, client, embedder)
    assert generated["generated"] > 0
    adaptations = repo.read("ADAPTATIONS")
    rejected = [a for a in adaptations if a["status"] == "rejected"]
    for row in rejected:
        assert row["rejection_reasons"], "a rejection must always say why"

    report = stage_report(repo, settings)
    assert "DAILY CREATIVE RADAR" in report["concise"]
    stored = repo.read("DAILY_REPORTS")
    assert len(stored) == 1
    assert "top_patterns" in stored[0] and "top_hooks" in stored[0] and "top_ads" in stored[0]


def test_rerunning_analysis_hits_the_cache_and_makes_no_new_calls(settings, csv_path, client, tmp_path):
    """Phase 3 acceptance: re-run must cost nothing."""
    repo = InMemoryRepository()
    client.cache.dir = tmp_path / "cache"
    client.cache.dir.mkdir(parents=True, exist_ok=True)

    stage_collect(repo, settings, ["csv"], path=csv_path)
    stage_analyze(repo, settings, client)
    provider_calls_after_first = client._provider.calls
    assert provider_calls_after_first > 0

    # Wipe the HOOKS table so the stage re-analyses the same content.
    repo._tables["HOOKS"] = []
    stage_analyze(repo, settings, client)
    assert client._provider.calls == provider_calls_after_first, "cache did not prevent new calls"


def test_prompt_version_change_invalidates_the_cache(settings, client, tmp_path):
    from ci.llm.prompts import load_prompt

    client.cache.dir = tmp_path / "cache2"
    client.cache.dir.mkdir(parents=True, exist_ok=True)
    prompt = load_prompt("classify_hook")
    client.run_prompt(prompt, stage="t", cache_content="same", title="x")
    before = client._provider.calls

    prompt.version = "2"
    client.run_prompt(prompt, stage="t", cache_content="same", title="x")
    assert client._provider.calls == before + 1


def test_importing_ad_results_marks_winners_and_extracts_dna(settings, client, tmp_path):
    """Phase 8 acceptance."""
    repo = InMemoryRepository()
    path = tmp_path / "ads.csv"
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["creative_id", "hook_id", "spend", "impressions",
                         "3_sec_view_rate", "roas", "cac", "installs"])
        writer.writerow(["adp_win", "hook:tt1", "800", "400000", "0.34", "2.6", "9.5", "900"])
        writer.writerow(["adp_lose", "hook:tt2", "600", "300000", "0.08", "0.3", "70", "40"])

    result = stage_import_ads(repo, settings, client, str(path))
    assert result["imported"] == 2
    assert result["winners"] == 1
    winners = repo.read("WINNERS")
    assert len(winners) == 1
    assert winners[0]["reusable_pattern"], "a winner must yield a reusable pattern, not just a flag"


def test_llm_cost_is_logged_per_call(settings, csv_path, client):
    repo = InMemoryRepository()
    stage_collect(repo, settings, ["csv"], path=csv_path)
    stage_analyze(repo, settings, client)
    calls = repo.read("LLM_CALLS")
    assert calls
    assert all("input_tokens" in c and "cost_usd" in c for c in calls)
    assert all(c["prompt_version"] for c in calls)
