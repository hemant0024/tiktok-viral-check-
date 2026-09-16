"""Structured JSON logging. Every line carries run_id."""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

_RUN_ID = {"value": "-"}


def set_run_id(run_id: str) -> None:
    _RUN_ID["value"] = run_id


def get_run_id() -> str:
    return _RUN_ID["value"]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "run_id": _RUN_ID["value"],
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure(level: str | None = None) -> None:
    lvl = (level or os.getenv("CI_LOG_LEVEL", "INFO")).upper()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(lvl)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, level: int, msg: str, **fields) -> None:
    logger.log(level, msg, extra={"extra_fields": fields})
