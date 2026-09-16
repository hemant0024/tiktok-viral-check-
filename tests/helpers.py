from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ci.models import NormalizedContent  # noqa: E402

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def make_content(cid="tiktok:1", views=100000, hours_old=24, duration=30,
                 likes=None, saves=0, shares=0, comments=None, creator="c1",
                 category="language learning", platform="tiktok", is_ad=False):
    return NormalizedContent(
        content_id=cid,
        date_found=NOW.date().isoformat(),
        platform=platform,
        source="test",
        url=f"https://example.com/{cid}",
        creator=creator,
        title=f"title {cid}",
        views=views,
        likes=likes if likes is not None else int(views * 0.1),
        comments=comments if comments is not None else int(views * 0.01),
        shares=shares,
        saves=saves,
        published_at=(NOW - timedelta(hours=hours_old)).isoformat(),
        category=category,
        duration_seconds=duration,
        is_ad=is_ad,
    )


def snap(hours_ago, views, cid="tiktok:1"):
    return {
        "content_id": cid,
        "captured_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
        "views": views,
    }
