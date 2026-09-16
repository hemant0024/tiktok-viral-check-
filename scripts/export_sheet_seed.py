"""Seed CSV for the shared sheet, from the real clockworks pull."""
from __future__ import annotations

import csv
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

COLS = ["Date", "Status", "Score", "Competitor", "Creator", "Followers", "Title",
        "Views", "Likes", "Comments", "Shares", "Saves",
        "Shares %", "Saves %", "Comments %", "Likes %",
        "Age Hours", "Posted", "Pace vs Normal", "Creator Lift", "Waves",
        "Views/Hour", "Duration", "Link", "Why", "Content ID"]

rows_out = []
for item in json.loads((ROOT / "data/samples/clockworks_pull.json").read_text()):
    a, m = item.get("authorMeta") or {}, item.get("videoMeta") or {}
    url = item.get("webVideoUrl", "")
    c = NormalizedContent(
        content_id=canonical_id("tiktok", "", url), date_found=now.date().isoformat(),
        platform="tiktok", source="competitor_ugc", url=url,
        creator=a.get("name", ""), creator_followers=int(a.get("fans") or 0),
        title=(item.get("text") or "")[:300], views=int(item.get("playCount") or 0),
        likes=int(item.get("diggCount") or 0), comments=int(item.get("commentCount") or 0),
        shares=int(item.get("shareCount") or 0), saves=int(item.get("collectCount") or 0),
        published_at=item.get("createTimeISO"), country="US",
        category=item.get("searchQuery", ""), duration_seconds=float(m.get("duration") or 0),
        kind="organic_ugc",
    )
    c.competitor = ugc.attribute(c)
    if c.competitor and c.creator.strip().lower() not in brands:
        rows_out.append(c)

repo.upsert("RAW_CONTENT", [c.model_dump() for c in rows_out])
repo.append("CONTENT_SNAPSHOTS", [x.model_dump() for x in build_snapshots(rows_out)])
stage_radar(repo, s, now)

radar = sorted(repo.read("RADAR"), key=lambda r: r["radar_score"], reverse=True)
out = ROOT / "data/sheet_seed.csv"
with out.open("w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(COLS)
    for r in radar:
        w.writerow([
            r["date"], r["takeoff_tier"], round(r["radar_score"], 1), r["competitor"],
            "@" + r["creator"], r["creator_followers"], r["title"][:180],
            r["views"], r["likes"], r["comments"], r["shares"], r["saves"],
            f"{r['share_rate']:.2%}", f"{r['save_rate']:.2%}",
            f"{r['comment_rate']:.2%}", f"{r['like_rate']:.2%}",
            round(r["age_hours"]), (r.get("published_at") or "")[:10],
            f"{r['vs_expected']}x", f"{r['creator_lift']}x", r["wave_count"],
            round(r["views_per_hour"]), round(r["duration_seconds"]),
            r["url"], "; ".join(r["reasons"])[:400], r["content_id"],
        ])
print(f"{len(radar)} rows -> {out}")
