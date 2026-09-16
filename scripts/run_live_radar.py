"""Run the radar on a live pull. First run means no waves yet, by definition."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ci import logging as ci_logging
from ci.collectors.competitor_ugc import CompetitorUgcCollector
from ci.config import get_settings
from ci.database import InMemoryRepository
from ci.processors.cheap_filter import cheap_filter
from ci.processors.dedup import dedup
from ci.processors.snapshots import build_snapshots
from ci.report.radar_render import render_feed
from ci.stages import stage_radar

ci_logging.configure("ERROR")
s = get_settings()
now = datetime.now(timezone.utc)
repo = InMemoryRepository()
ugc = CompetitorUgcCollector(s)

raw = json.loads((ROOT / sys.argv[1]).read_text())
videos, dropped = [], []
for item in raw:
    v = ugc._tt.normalize(item, "ugc_today", item.get("keyword", ""))
    v.competitor = ugc.attribute(v)
    v.kind = "organic_ugc"
    (videos if v.competitor else dropped).append(v)

print(f"pulled {len(raw)}  |  attributed to a competitor {len(videos)}  |  "
      f"dropped, never named the app {len(dropped)}")
for d in dropped:
    print(f"   dropped: @{d.creator} - {d.title[:58]}")

videos = dedup(videos)
kept, verdicts = cheap_filter(videos, {}, s.scoring, now)
cut = [v for v in verdicts if not v.kept]
if cut:
    print()
    for v in cut:
        print(f"   filtered: @{v.content.creator} - {'; '.join(v.reasons)}")

repo.upsert("RAW_CONTENT", [v.model_dump() for v in kept])
repo.append("CONTENT_SNAPSHOTS", [x.model_dump() for x in build_snapshots(kept)])
result = stage_radar(repo, s, now)

rows = sorted(repo.read("RADAR"), key=lambda r: r["radar_score"], reverse=True)
print()
print(f"{'tier':14} {'score':>6} {'competitor':12} {'creator':24} {'views':>9} {'age':>5} "
      f"{'pace':>6} {'shr%':>6} {'lift':>6}")
print("-" * 104)
for r in rows:
    age = f"{int(r['age_hours'])}h" if r["age_hours"] < 48 else f"{int(r['age_hours']/24)}d"
    print(f"{r['takeoff_tier']:14} {r['radar_score']:>6.1f} {r['competitor'][:12]:12} "
          f"@{r['creator'][:23]:23} {r['views']:>9,} {age:>5} {r['vs_expected']:>5.1f}x "
          f"{r['share_rate']:>5.2%} {r['creator_lift']:>5.1f}x")
print()
print("=" * 104)
print(render_feed(now.date().isoformat(), result["feed"], None, 3))
