"""Dedup on content_id. Re-running a day must never create duplicates."""
from __future__ import annotations

from typing import Iterable

from ci.models import NormalizedContent


def dedup(items: Iterable[NormalizedContent]) -> list[NormalizedContent]:
    """First win, but a later item with more views replaces an earlier one.

    Two passes over the same query can return the same video with slightly
    different counts. Keep the richer reading.
    """
    best: dict[str, NormalizedContent] = {}
    for item in items:
        current = best.get(item.content_id)
        if current is None or item.views > current.views:
            if current is not None:
                item.collected_pass = current.collected_pass or item.collected_pass
            best[item.content_id] = item
    return list(best.values())


def split_new_and_known(items: list[NormalizedContent], known_ids: set[str]):
    new = [i for i in items if i.content_id not in known_ids]
    known = [i for i in items if i.content_id in known_ids]
    return new, known
