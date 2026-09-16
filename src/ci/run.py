"""Run context. Failure isolation and the run summary live here (spec section 25)."""
from __future__ import annotations

import logging
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from ci.database.base import Repository
from ci.logging import get_logger, log_event, set_run_id
from ci.models import RunLog

log = get_logger(__name__)


class RunContext:
    def __init__(self, stage: str, repo: Repository, run_id: str | None = None) -> None:
        self.run_id = run_id or f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
        self.stage = stage
        self.repo = repo
        self.started = time.time()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.counts: dict[str, int] = {}
        self.failures: list[dict[str, Any]] = []
        set_run_id(self.run_id)

    def count(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def fail(self, scope: str, item: str, exc: BaseException) -> None:
        """One item or one source failing must never end the run."""
        entry = {
            "scope": scope,
            "item": item,
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc(limit=3),
        }
        self.failures.append(entry)
        self.count(f"failed_{scope}")
        log_event(log, logging.ERROR, "isolated failure", scope=scope, item=item, error=entry["error"])

    @contextmanager
    def isolate(self, scope: str, item: str):
        try:
            yield
        except Exception as exc:  # noqa: BLE001 - the whole point of this helper
            self.fail(scope, item, exc)

    def summary(self, llm_cost: float = 0.0, notes: str = "") -> RunLog:
        status = "ok" if not self.failures else ("failed" if not self.counts else "partial")
        return RunLog(
            run_id=self.run_id,
            stage=self.stage,
            started_at=self.started_at,
            finished_at=datetime.now(timezone.utc).isoformat(),
            status=status,
            counts=self.counts,
            failures=self.failures,
            duration_seconds=round(time.time() - self.started, 3),
            llm_cost_usd=round(llm_cost, 6),
            notes=notes,
        )

    def finish(self, llm_cost: float = 0.0, notes: str = "", llm_rows: list[dict] | None = None) -> RunLog:
        summary = self.summary(llm_cost, notes)
        self.repo.append("RUN_LOG", [summary.model_dump()])
        if llm_rows:
            self.repo.append("LLM_CALLS", llm_rows)
        log_event(log, logging.INFO, "run finished", stage=self.stage,
                  status=summary.status, counts=self.counts,
                  failures=len(self.failures), cost_usd=summary.llm_cost_usd)
        return summary
