"""Snapshot writing. Content rows are written once, snapshots every run."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from ci.models import ContentSnapshot, NormalizedContent


def build_snapshots(items: Iterable[NormalizedContent], captured_at: str | None = None) -> list[ContentSnapshot]:
    ts = captured_at or datetime.now(timezone.utc).isoformat()
    return [
        ContentSnapshot(
            content_id=item.content_id,
            captured_at=ts,
            views=item.views,
            likes=item.likes,
            comments=item.comments,
            shares=item.shares,
            saves=item.saves,
        )
        for item in items
    ]


def snapshots_by_content(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in rows:
        out.setdefault(row.get("content_id", ""), []).append(row)
    return out
