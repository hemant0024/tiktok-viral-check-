"""Two days of radar, then trends. Proves history is kept and movement computed."""
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
from ci.stages import stage_radar, stage_trends

ci_logging.configure("ERROR")
s = get_settings()
repo = InMemoryRepository()
day2 = datetime(2026, 9, 10, 9, tzinfo=timezone.utc)
day1 = day2 - timedelta(days=1)

# Real shapes: a climber, a fader, a newcomer.
CASES = [
    ("climber", "Praktika AI", "learn.with.shar", 2629, 22, [(day1, 9000), (day2, 78000)]),
    ("fader", "Loora AI", "somecreator", 41000, 18, [(day1, 120000), (day2, 131000)]),
    ("newcomer", "ELSA Speak", "freshface", 890, 16, [(None, 0), (day2, 14000)]),
]

for run_at in (day1, day2):
    content, snaps = [], []
    for cid, comp, creator, foll, dur, readings in CASES:
        reading = next((v for d, v in readings if d == run_at), None)
        if reading is None:
            continue
        published = run_at - timedelta(hours=20 if cid != "newcomer" else 5)
        c = NormalizedContent(
            content_id=f"tiktok:{cid}", date_found=run_at.date().isoformat(),
            platform="tiktok", source="competitor_ugc", url=f"https://tiktok.com/@{creator}/video/{cid}",
            creator=creator, creator_followers=foll, title=f"{comp} video by {creator}",
            views=reading, likes=int(reading * 0.09), comments=int(reading * 0.004),
            shares=int(reading * 0.022), saves=int(reading * 0.012),
            published_at=published.isoformat(), duration_seconds=dur,
            competitor=comp, kind="organic_ugc", hashtags=[comp.split()[0].lower()],
        )
        content.append(c)
        for d, v in readings:
            if d is not None and d <= run_at:
                snaps.append(ContentSnapshot(content_id=c.content_id,
                                             captured_at=d.isoformat(), views=v))
    repo.upsert("RAW_CONTENT", [c.model_dump() for c in content])
    repo.append("CONTENT_SNAPSHOTS", [x.model_dump() for x in snaps])
    stage_radar(repo, s, run_at)

print(f"RADAR rows kept: {len(repo.read('RADAR'))} across "
      f"{len({r['date'] for r in repo.read('RADAR')})} days  <- history, not overwritten")
print()
result = stage_trends(repo, s, day2)
print("counts:", result["summary"]["counts"])
print()
for row in sorted(repo.read("VIDEO_TRENDS"), key=lambda r: r["score_now"], reverse=True):
    print(f"{row['direction']:8} {row['creator']:16} score {row['score_prev']:>5.0f} -> "
          f"{row['score_now']:<5.0f} ({row['score_delta']:+.0f})  rank {row['rank_prev']}->{row['rank_now']}  "
          f"views +{row['views_gained']:,}  |  {row['note']}")
print()
for row in repo.read("COMPETITOR_TRENDS"):
    print(f"{row['direction']:8} {row['competitor']:14} videos {row['videos_prev']}->{row['videos_now']}  "
          f"avg {row['avg_score_prev']}->{row['avg_score_now']}  {row['note']}")
