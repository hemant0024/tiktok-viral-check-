"""Local JSONL adapter. Lets the whole pipeline run today with zero credentials.

Not in the spec's list, but it satisfies the same interface, so it costs nothing
architecturally and it is what makes the unit and smoke tests real.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ci.database.base import BaseRepository
from ci.models import TABLES


class LocalJsonRepository(BaseRepository):
    name = "local"

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, table: str) -> Path:
        return self.data_dir / f"{table}.jsonl"

    def read(self, table: str) -> list[dict[str, Any]]:
        path = self._path(table)
        if not path.exists():
            return []
        out = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def _write_all(self, table: str, rows: list[dict[str, Any]]) -> None:
        tmp = self._path(table).with_suffix(".tmp")
        with tmp.open("w") as fh:
            for row in rows:
                fh.write(json.dumps(row, default=str) + "\n")
        tmp.replace(self._path(table))

    def upsert(self, table: str, rows: Iterable[dict[str, Any]]) -> int:
        merged, written = self._merge(table, self.read(table), rows)
        self._write_all(table, merged)
        return written

    def append(self, table: str, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        with self._path(table).open("a") as fh:
            for row in rows:
                fh.write(json.dumps(row, default=str) + "\n")
        return len(rows)

    def healthcheck(self) -> dict[str, Any]:
        """Write and read back. Deliberately does NOT require delete.

        Some mounts allow writes but refuse unlink, and a store we can write to and
        read from is healthy whether or not we are allowed to tidy up after ourselves.
        """
        probe = self.data_dir / ".probe"
        writable = False
        note = ""
        try:
            probe.write_text("ok")
            writable = probe.read_text() == "ok"
        except OSError as exc:
            note = f"write failed: {exc}"
        else:
            try:
                probe.unlink()
            except OSError:
                note = "writable, but this filesystem does not permit deletes"
        return {
            "backend": "local",
            "ok": writable,
            "data_dir": str(self.data_dir),
            "tables_present": sum(1 for t in TABLES if self._path(t).exists()),
            "note": note,
        }
