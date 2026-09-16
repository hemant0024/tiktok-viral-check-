"""Hemant's own examples, run through the real radar."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ci import logging as ci_logging
from ci.config import get_settings
from ci.database import InMemoryRepository
from ci.models import ContentSnapshot, NormalizedContent
from ci.report.radar_render import render_feed
from ci.stages import stage_radar

ci_logging.configure("ERROR")
s = get_settings()
now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
repo = InMemoryRepository()

# (id, title, competitor, views, hours_old, followers, likes, shares, comments,
#  saves, hourly cumulative readings)
CASES = [
    ("A", "duolingo streak meme that went everywhere", "Duolingo", 2_000_000, 504, 900_000,
     140_000, 6_000, 3_000, 8_000, [(504, 1_900_000), (24, 1_980_000), (0, 2_000_000)]),
    ("B", "i cancelled my Babbel subscription, here is why", "Babbel", 800_000, 48, 200_000,
     60_000, 4_000, 2_000, 5_000, [(48, 500_000), (24, 700_000), (0, 800_000)]),
    ("C", "POV you understand Praktika but freeze in real life", "Praktika AI", 18_000, 4, 12_000,
     2_100, 320, 140, 260, [(4, 0), (3, 2_000), (2, 6_500), (1, 12_000), (0, 18_000)]),
    ("D", "day 1 using Loora and i already sound different", "Loora AI", 7_000, 1, 3_000,
     900, 150, 70, 130, [(1, 0), (0, 7_000)]),
    ("E", "my ELSA pronunciation score humbled me", "ELSA Speak", 102_500, 5, 4_000,
     10_000, 1_800, 600, 900,
     [(5, 0), (4, 1_000), (3, 3_500), (2, 10_500), (1, 32_500), (0, 102_500)]),
    ("F", "flat: 91k views but going nowhere", "Speak", 91_000, 4, 60_000,
     4_000, 200, 100, 150, [(4, 0), (3, 20_000), (2, 42_000), (1, 66_000), (0, 91_000)]),
]

content, snaps = [], []
for cid, title, comp, views, age, foll, likes, shares, comments, saves, readings in CASES:
    c = NormalizedContent(
        content_id=f"tiktok:{cid}", date_found=now.date().isoformat(), platform="tiktok",
        source="competitor_ugc:today", url=f"https://www.tiktok.com/@creator{cid}/video/{cid}",
        creator=f"creator{cid}", creator_followers=foll, title=title,
        views=views, likes=likes, comments=comments, shares=shares, saves=saves,
        published_at=(now - timedelta(hours=age)).isoformat(),
        duration_seconds=22, competitor=comp, kind="organic_ugc", hashtags=[comp.split()[0].lower()],
    )
    content.append(c)
    for hours_ago, v in readings:
        snaps.append(ContentSnapshot(content_id=c.content_id,
                                     captured_at=(now - timedelta(hours=hours_ago)).isoformat(),
                                     views=v, likes=likes, comments=comments,
                                     shares=shares, saves=saves))

repo.upsert("RAW_CONTENT", [c.model_dump() for c in content])
repo.append("CONTENT_SNAPSHOTS", [s.model_dump() for s in snaps])

result = stage_radar(repo, settings=s, now=now)
rows = sorted(repo.read("RADAR"), key=lambda r: r["radar_score"], reverse=True)

print(f"{'':3} {'tier':14} {'phase':13} {'score':>6} {'views':>10} {'age':>6} {'pace':>7} {'waves':>5} {'share%':>7}")
print("-" * 92)
for r in rows:
    cid = r["content_id"].split(":")[1]
    age = f"{int(r['age_hours'])}h" if r["age_hours"] < 48 else f"{int(r['age_hours']/24)}d"
    print(f"{cid:3} {r['takeoff_tier']:14} {r['viral_phase']:13} {r['radar_score']:>6.1f} "
          f"{r['views']:>10,} {age:>6} {r['vs_expected']:>6.1f}x {r['wave_count']:>5} "
          f"{r['share_rate']:>6.2%}")
print()
print("=" * 92)
print(render_feed(now.date().isoformat(), result["feed"], None, 3))
