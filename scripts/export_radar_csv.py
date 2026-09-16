"""Export the radar feed as CSV, the exact column order the Google Sheet uses."""
from __future__ import annotations

import csv
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
from ci.stages import stage_radar

COLUMNS = [
    "date", "status", "radar_score", "competitor", "kind", "platform",
    "title", "creator", "creator_followers", "published_at", "age_hours",
    "views", "likes", "comments", "shares", "saves", "engagement_rate",
    "views_per_day", "acceleration", "creator_lift", "baseline_source",
    "velocity_confidence", "duration_seconds", "days_running", "variation_count",
    "variation_group", "ad_start_date", "cta_text", "url", "video_url", "thumbnail_url",
    "landing_page", "sound_title", "hashtags", "why", "content_id",
]

ci_logging.configure("ERROR")
settings = get_settings()
repo = InMemoryRepository()
now = datetime.now(timezone.utc)

ugc = CompetitorUgcCollector(settings)
videos = []
for item in json.loads((ROOT / "data/samples/competitor_ugc_live.json").read_text()):
    v = ugc._tt.normalize(item, "ugc_fresh", item.get("keyword", ""))
    v.competitor = ugc.attribute(v)
    v.kind = "organic_ugc"
    if v.competitor:
        videos.append(v)

ads_c = MetaAdsCollector(settings)
ads = [
    ads_c.normalize({
        "adArchiveID": aid, "pageName": "Linguza: AI English Tutor", "isActive": True,
        "startDate": int(datetime(2026, m, d, tzinfo=timezone.utc).timestamp()),
        "endDate": int(now.timestamp()), "collationCount": 1,
        "snapshot": {"title": "Try free now!", "displayFormat": "VIDEO",
                     "body": {"text": "Learn Any Language 1-on-1 with AI - Speak Fluently in 30 Days!"},
                     "videos": [{"videoHdUrl": "https://video-phl2-1.xx.fbcdn.net/o1/v/t2/f2/m366/AQMXlX5PK4q5.mp4"}],
                     "ctaText": "Download",
                     "linkUrl": "https://play.google.com/store/apps/details?id=com.nxl.aienglishtutor",
                     "pageLikeCount": 27598}}, now)
    for aid, (m, d) in zip(
        ["2234892994031089", "1345857353551511", "2091062278152915", "981912097811285", "3662724713866656"],
        [(7, 7), (7, 3), (8, 21), (7, 2), (6, 3)])
]
group_variations(ads)
for a in ads:
    a.competitor = "Linguza"

allv = videos + ads
repo.upsert("RAW_CONTENT", [v.model_dump() for v in allv])
earlier = (now - timedelta(hours=14)).isoformat()
repo.append("CONTENT_SNAPSHOTS", [{**s.model_dump(), "captured_at": earlier,
                                   "views": int(s.views * 0.55)} for s in build_snapshots(allv)])
repo.append("CONTENT_SNAPSHOTS", [s.model_dump() for s in build_snapshots(allv)])

result = stage_radar(repo, settings, now)
rows = result["feed"]

out = ROOT / "data/radar_export.csv"
with out.open("w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow([c.replace("_", " ").title() for c in COLUMNS])
    for r in rows:
        w.writerow([
            "; ".join(r.get("reasons", [])) if c == "why"
            else " ".join(f"#{t}" for t in (r.get("hashtags") or [])) if c == "hashtags"
            else r.get(c, "")
            for c in COLUMNS
        ])
print(f"{len(rows)} rows -> {out}")
