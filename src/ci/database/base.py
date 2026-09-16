"""Repository interface. Intelligence code NEVER talks to Sheets directly."""
from __future__ import annotations

from typing import Any, Iterable, Protocol, runtime_checkable

from ci.models import PRIMARY_KEYS


def row_key(table: str, row: dict[str, Any]) -> str:
    pk = PRIMARY_KEYS[table]
    if isinstance(pk, tuple):
        return "|".join(str(row.get(k, "")) for k in pk)
    return str(row.get(pk, ""))


@runtime_checkable
class Repository(Protocol):
    def read(self, table: str) -> list[dict[str, Any]]: ...
    def upsert(self, table: str, rows: Iterable[dict[str, Any]]) -> int:
        """Insert or replace by primary key. Idempotent by contract."""
        ...
    def append(self, table: str, rows: Iterable[dict[str, Any]]) -> int:
        """Append-only. Used for snapshots and logs where history is the point."""
        ...
    def healthcheck(self) -> dict[str, Any]: ...


class BaseRepository:
    """Shared upsert semantics so every adapter behaves identically."""

    name = "base"

    def _merge(self, table: str, existing: list[dict], rows: Iterable[dict]) -> tuple[list[dict], int]:
        index = {row_key(table, r): i for i, r in enumerate(existing)}
        written = 0
        for row in rows:
            key = row_key(table, row)
            if key in index:
                existing[index[key]] = row
            else:
                index[key] = len(existing)
                existing.append(row)
            written += 1
        return existing, written
