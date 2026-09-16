"""Full pipeline on real US TikTok data, with a stubbed Apify client and a fake LLM.

Proves the whole chain works on real payloads without needing an APIFY_TOKEN or an
OPENAI_API_KEY on this machine. Swap the two stubs for real credentials and the same
code path runs for real.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ci import logging as ci_logging
from ci.config import get_settings
from ci.database import InMemoryRepository
from ci.llm.client import LlmClient
from ci.llm.providers.fake import FakeProvider
from ci.patterns.embed import HashingEmbedder
from ci.stages import (
    stage_analyze, stage_collect, stage_generate,
    stage_patterns_cluster, stage_patterns_score, stage_report,
)

ci_logging.configure("ERROR")
settings = get_settings()
payload = json.loads((ROOT / "data/samples/tiktok_live_us.json").read_text())


class StubApify:
    def run_actor(self, actor, run_input, max_items=None):
        return payload


import ci.stages as stages  # noqa: E402
from ci.collectors.tiktok import TikTokCollector  # noqa: E402

_real = stages.get_collector


def patched(name, s, repo, path=None):
    if name == "tiktok":
        return TikTokCollector(s, client=StubApify())
    return _real(name, s, repo, path)


stages.get_collector = patched

repo = InMemoryRepository()
client = LlmClient(settings, provider=FakeProvider(), video_provider=FakeProvider())
embedder = HashingEmbedder()

print("=" * 70)
r = stage_collect(repo, settings, ["tiktok"])
print(f"COLLECT      {r['summary']['counts']}")
r2 = stage_collect(repo, settings, ["tiktok"])
print(f"COLLECT x2   content rows: {len(repo.read('RAW_CONTENT'))} "
      f"(unchanged) | snapshots: {len(repo.read('CONTENT_SNAPSHOTS'))} (doubled)")
print(f"ANALYZE      {stage_analyze(repo, settings, client)['summary']['counts']}")
print(f"CLUSTER      {stage_patterns_cluster(repo, settings, client, embedder)['summary']['counts']}")
print(f"SCORE        {stage_patterns_score(repo, settings, client)['summary']['counts']}")
print(f"GENERATE     {stage_generate(repo, settings, client, embedder)['summary']['counts']}")
report = stage_report(repo, settings)
print(f"REPORT       {report['summary']['counts']}")
print(f"LLM          {client.stats()}")
print("=" * 70)

rejected = [a for a in repo.read("ADAPTATIONS") if a["status"] == "rejected"]
print(f"\nrejections logged with reasons: {len(rejected)}")
for row in rejected[:4]:
    print(f"  - {row['rejection_reasons']} :: {row['rejection_detail'][:70]}")

print("\nrun log (every stage persisted):")
for row in repo.read("RUN_LOG"):
    print(f"  {row['stage']:20} {row['status']:8} {row['duration_seconds']:>6.2f}s "
          f"failures={len(row['failures'])}")
