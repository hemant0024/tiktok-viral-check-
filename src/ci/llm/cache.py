"""Content-addressed response cache. Key = content hash + prompt version + tier + model."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def cache_key(content: str, prompt_name: str, prompt_version: str, tier: str, model: str) -> str:
    raw = f"{prompt_name}|{prompt_version}|{tier}|{model}|{content}"
    return hashlib.sha256(raw.encode()).hexdigest()


class ResponseCache:
    def __init__(self, cache_dir: Path) -> None:
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    def _path(self, key: str) -> Path:
        return self.dir / f"{key[:2]}" / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if path.exists():
            self.hits += 1
            return json.loads(path.read_text())
        self.misses += 1
        return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, default=str))

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}
