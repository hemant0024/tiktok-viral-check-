"""Replay a saved Apify TikTok payload through the real collector and filter.

Used to show Phase 2 output without needing an APIFY_TOKEN on this machine.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ci.collectors.tiktok import TikTokCollector
from ci.config import get_settings
from ci.processors.cheap_filter import cheap_filter
from ci.processors.dedup import dedup

settings = get_settings()
items = json.loads(Path(sys.argv[1]).read_text())
collector = TikTokCollector(settings)
normalized = dedup([collector.normalize(i, "breakout", i.get("keyword", "")) for i in items])
now = datetime.now(timezone.utc)

# Simulate a second snapshot 14 hours later so velocity has two real readings,
# which is what the second daily run would produce.
snaps = {}
for item in normalized:
    snaps[item.content_id] = [
        {"captured_at": (now - timedelta(hours=14)).isoformat(), "views": int(item.views * 0.72)},
        {"captured_at": now.isoformat(), "views": item.views},
    ]

kept, verdicts = cheap_filter(normalized, snaps, settings.scoring, now)
kept_ids = {c.content_id for c in kept}

print(f"collected {len(normalized)} real US TikToks, {len(kept)} passed the cheap filter\n")
head = f"{'creator':22} {'views':>8} {'saves':>6} {'dur':>6} {'v/day':>9} {'heat':>6} {'slot':9} verdict"
print(head); print("-" * len(head))
for v in sorted(verdicts, key=lambda v: v.heat, reverse=True):
    c = v.content
    status = "KEPT" if c.content_id in kept_ids else "cut: " + (v.reasons[0] if v.reasons else "cap")
    print(f"{c.creator[:22]:22} {c.views:>8} {c.saves:>6} {c.duration_seconds:>6.0f} "
          f"{v.velocity.views_per_day:>9.0f} {v.heat:>6.2f} {v.slot or '-':9} {status}")

print()
breakouts = [v for v in verdicts if v.velocity.is_breakout and v.content.content_id in kept_ids]
print(f"breakout candidates: {len(breakouts)}")
for v in breakouts:
    print(f"  {v.content.creator} | {v.content.views:,} views | accelerating | "
          f"{', '.join(v.velocity.notes) or 'confirmed'}")
