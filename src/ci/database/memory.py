"""In-memory adapter. Used by the unit suite. No network, no keys."""
from __future__ import annotations

import json
from typing import Any, Iterable

from ci.database.base import BaseRepository
from ci.models import TABLES


class InMemoryRepository(BaseRepository):
    name = "memory"

    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {t: [] for t in TABLES}

    def read(self, table: str) -> list[dict[str, Any]]:
        return [json.loads(json.dumps(r, default=str)) for r in self._tables.setdefault(table, [])]

    def upsert(self, table: str, rows: Iterable[dict[str, Any]]) -> int:
        current = self._tables.setdefault(table, [])
        merged, written = self._merge(table, current, rows)
        self._tables[table] = merged
        return written

    def append(self, table: str, rows: Iterable[dict[str, Any]]) -> int:
        current = self._tables.setdefault(table, [])
        rows = list(rows)
        current.extend(rows)
        return len(rows)

    def healthcheck(self) -> dict[str, Any]:
        return {"backend": "memory", "ok": True, "tables": len(self._tables)}
