"""Every source implements this one interface. Swapping a source touches nothing downstream."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ci.models import NormalizedContent


@runtime_checkable
class SourceAdapter(Protocol):
    name: str
    enabled: bool

    def fetch(self) -> list[NormalizedContent]:
        """Return normalized content. Raising is allowed; the run isolates it."""
        ...

    def describe(self) -> dict[str, Any]:
        """Cheap, side-effect free summary used by healthcheck."""
        ...
