"""Viral radar on real competitor data.

The UGC rows and the Linguza ads are real, pulled live on 2026-09-10. The second
snapshot is simulated, because acceleration needs two readings 12+ hours apart and
I cannot wait 14 hours. In production the second reading is just tomorrow's run.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ci import logging as ci_logging
from ci.collectors.competitor_ugc import CompetitorUgcCollector
from ci.collectors.meta_ads import MetaAdsCollector, group_variations
from ci.config import get_settings
from ci.database import InMemoryRepository
from ci.processors.snapshots import build_snapshots
from ci.report.radar_render import render_feed
from ci.stages import stage_radar

ci_logging.configure("ERROR")
settings = get_settings()
repo = InMemoryRepository()
now = datetime.now(timezone.utc)

# ---- real organic UGC about competitors -----------------------------------
ugc_collector = CompetitorUgcCollector(settings)
raw = json.loads((ROOT / "data/samples/competitor_ugc_live.json").read_text())
videos = []
for item in raw:
    v = ugc_collector._tt.normalize(item, "ugc_fresh", item.get("keyword", ""))
    v.competitor = ugc_collector.attribute(v)
    v.kind = "organic_ugc"
    if v.competitor:
        videos.append(v)

# ---- real competitor ads (Linguza, live 2026-09-10) ------------------------
ads_collector = MetaAdsCollector(settings)
ads = [
    ads_collector.normalize({
        "adArchiveID": ad_id, "pageName": "Linguza: AI English Tutor", "isActive": True,
        "startDate": int(datetime(2026, m, d, tzinfo=timezone.utc).timestamp()),
        "endDate": int(now.timestamp()), "collationCount": 1, "collationId": None,
        "snapshot": {"title": "Try free now!", "displayFormat": "VIDEO",
                     "body": {"text": "Learn Any Language 1-on-1 with AI - Speak Fluently in 30 Days!"},
                     "videos": [{"videoHdUrl": "https://video-phl2-1.xx.fbcdn.net/o1/v/t2/f2/m366/AQMXlX5PK4q5ErS4.mp4"}],
                     "ctaText": "Download", "linkUrl": "https://play.google.com/store/apps/details?id=com.nxl.aienglishtutor",
                     "pageLikeCount": 27598},
    }, now)
    for ad_id, (m, d) in zip(
        ["2234892994031089", "1345857353551511", "2091062278152915", "981912097811285", "3662724713866656"],
        [(7, 7), (7, 3), (8, 21), (7, 2), (6, 3)])
]
group_variations(ads)
for ad in ads:
    ad.competitor = "Linguza"
    ad.views = 0  # the Ad Library exposes no view counts, by design

allv = videos + ads
repo.upsert("RAW_CONTENT", [v.model_dump() for v in allv])

# two snapshots so velocity and acceleration are real, not lifetime averages
earlier = (now - timedelta(hours=14)).isoformat()
repo.append("CONTENT_SNAPSHOTS", [
    {**s.model_dump(), "captured_at": earlier, "views": int(s.views * 0.55)}
    for s in build_snapshots(allv)
])
repo.append("CONTENT_SNAPSHOTS", [s.model_dump() for s in build_snapshots(allv)])

result = stage_radar(repo, settings, now)
print(render_feed(now.date().isoformat(), result["feed"]))
print()
print("counts:", result["summary"]["counts"])
