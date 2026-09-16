"""Map the clockworks actor shape onto NormalizedContent and run the radar."""
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
from ci.models import NormalizedContent, canonical_id
from ci.processors.snapshots import build_snapshots
from ci.stages import stage_radar

ci_logging.configure("ERROR")
s = get_settings()
now = datetime.now(timezone.utc)
repo = InMemoryRepository()
ugc = CompetitorUgcCollector(s)
brands = ugc.brand_handles()


def to_content(item: dict) -> NormalizedContent:
    author = item.get("authorMeta") or {}
    meta = item.get("videoMeta") or {}
    url = item.get("webVideoUrl", "")
    return NormalizedContent(
        content_id=canonical_id("tiktok", str(item.get("id") or ""), url),
        date_found=now.date().isoformat(), platform="tiktok",
        source="competitor_ugc:clockworks", url=url,
        creator=author.get("name", ""), creator_followers=int(author.get("fans") or 0),
        title=(item.get("text") or "")[:600], description=(item.get("text") or "")[:600],
        views=int(item.get("playCount") or 0), likes=int(item.get("diggCount") or 0),
        comments=int(item.get("commentCount") or 0), shares=int(item.get("shareCount") or 0),
        saves=int(item.get("collectCount") or 0),
        published_at=item.get("createTimeISO"), country="US",
        category=item.get("searchQuery", ""),
        duration_seconds=float(meta.get("duration") or 0), kind="organic_ugc",
    )


raw = json.loads((ROOT / sys.argv[1]).read_text())
videos, dropped_brand, dropped_attr = [], [], []
for item in raw:
    c = to_content(item)
    c.competitor = ugc.attribute(c)
    if not c.competitor:
        dropped_attr.append(c)
        continue
    if c.creator.strip().lower() in brands:
        dropped_brand.append(c)
        continue
    videos.append(c)

print(f"pulled {len(raw)} | kept {len(videos)} | brand-owned dropped {len(dropped_brand)} "
      f"| never named an app {len(dropped_attr)}")

repo.upsert("RAW_CONTENT", [v.model_dump() for v in videos])
repo.append("CONTENT_SNAPSHOTS", [x.model_dump() for x in build_snapshots(videos)])
stage_radar(repo, s, now)

rows = sorted(repo.read("RADAR"), key=lambda r: r["radar_score"], reverse=True)
print()
print(f"{'tier':14} {'score':>5} {'competitor':11} {'creator':22} {'views':>10} {'age':>5} "
      f"{'shr%':>6} {'lift':>8}")
print("-" * 96)
for r in rows:
    age = f"{int(r['age_hours'])}h" if r["age_hours"] < 48 else f"{int(r['age_hours']/24)}d"
    print(f"{r['takeoff_tier']:14} {r['radar_score']:>5.1f} {r['competitor'][:11]:11} "
          f"@{r['creator'][:21]:21} {r['views']:>10,} {age:>5} {r['share_rate']:>5.2%} "
          f"{r['creator_lift']:>7.1f}x")
