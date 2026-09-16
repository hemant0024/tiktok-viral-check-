"""A small HTTP front door for the stages, so n8n can drive them properly.

The first version had n8n shell out with `docker compose exec`. That cannot work:
the n8n image has no docker CLI, and mounting the socket to get one is both
fragile and a privilege escalation nobody wants on a box that runs scheduled jobs.

An HTTP endpoint is the boring correct answer. n8n makes an HTTP request, gets
structured JSON back, and can branch on it. It works identically on a laptop, a
VPS, or split across two machines.

Stdlib only, deliberately. This does not deserve a web framework.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from ci import logging as ci_logging
from ci.config import get_settings
from ci.database import get_repository
from ci.llm.client import LlmClient
from ci.logging import get_logger, log_event
from ci.patterns.embed import get_embedder

log = get_logger(__name__)


def _is_private(host: str) -> bool:
    """True for loopback, link-local, and RFC1918 style addresses."""
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (addr.is_loopback or addr.is_private or addr.is_link_local)

# One stage may take minutes. A second concurrent run would double-write
# snapshots and corrupt the velocity history, so stages are serialised.
_LOCK = threading.Lock()
_RUNNING: dict[str, Any] = {"stage": None, "started": None}


def _stages(body: dict[str, Any] | None = None) -> dict[str, Callable[[], dict]]:
    """Stage name -> callable. `body` is the POSTed JSON, for stages that take input.

    Ads and UGC get their own entries all the way down rather than a shared one
    with a flag, so each n8n workflow is a straight line of named steps and a
    failure on one side cannot take the other with it.
    """
    from ci import stages as S

    settings = get_settings()
    body = body or {}

    def repo():
        return get_repository(settings)

    def client():
        return LlmClient(settings)

    return {
        "healthcheck": lambda: S.stage_healthcheck(repo(), settings),
        "collect_competitor_ugc": lambda: S.stage_collect(repo(), settings, ["competitor_ugc"]),
        "collect_meta_ads": lambda: S.stage_collect(repo(), settings, ["meta_ads"]),
        "collect_tiktok": lambda: S.stage_collect(repo(), settings, ["tiktok"]),
        "collect_youtube": lambda: S.stage_collect(repo(), settings, ["youtube"]),
        "collect_all": lambda: S.stage_collect(
            repo(), settings, ["competitor_ugc", "meta_ads", "tiktok", "youtube"]),
        "radar": lambda: S.stage_radar(repo(), settings),
        "radar_ads": lambda: S.stage_radar(repo(), settings, kind="ads"),
        "radar_ugc": lambda: S.stage_radar(repo(), settings, kind="ugc"),
        "watch": lambda: S.stage_watch(repo(), settings),
        "trends": lambda: S.stage_trends(repo(), settings),
        "sheets_push": lambda: S.stage_sheets_push(repo(), settings),
        "sheets_push_ads": lambda: S.stage_sheets_push(repo(), settings, kind="ads"),
        "sheets_push_ugc": lambda: S.stage_sheets_push(repo(), settings, kind="ugc"),
        "brief_input_ads": lambda: S.stage_brief_input(repo(), settings, kind="ads",
                                                       limit=int(body.get("limit", 12))),
        "brief_input_ugc": lambda: S.stage_brief_input(repo(), settings, kind="ugc",
                                                       limit=int(body.get("limit", 12))),
        "save_brief": lambda: S.stage_save_brief(repo(), settings,
                                                 brief=str(body.get("brief", "")),
                                                 source=str(body.get("source", "claude"))),
        "notify_radar": lambda: S.stage_notify_radar(repo(), settings, "slack"),
        "analyze": lambda: S.stage_analyze(repo(), settings, client()),
        "patterns_cluster": lambda: S.stage_patterns_cluster(repo(), settings, client(), get_embedder()),
        "patterns_score": lambda: S.stage_patterns_score(repo(), settings, client()),
        "generate": lambda: S.stage_generate(repo(), settings, client(), get_embedder()),
        "report": lambda: S.stage_report(repo(), settings),
        "notify": lambda: S.stage_notify(repo(), settings, "slack"),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "creative-intelligence/1.0"

    def log_message(self, fmt, *args):  # noqa: A003 - silence stdlib access logs
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self) -> bool:
        token = os.getenv("CI_API_TOKEN", "")
        if token:
            return self.headers.get("Authorization", "") == f"Bearer {token}"

        # No token configured. That is fine on a laptop and dangerous on a public
        # host: these endpoints start Apify runs that cost real money. So with no
        # token, only private callers are accepted. Deploying publicly without
        # setting CI_API_TOKEN fails closed instead of billing quietly.
        return _is_private(self.client_address[0] if self.client_address else "")

    def do_GET(self):  # noqa: N802
        # Prompts are served from prompts/*.md rather than pasted into the n8n
        # JSON, so editing the file changes what Claude is told without anyone
        # re-importing a workflow.
        if self.path.startswith("/prompt/"):
            name = self.path[len("/prompt/"):].strip("/")
            if not name.replace("_", "").replace("-", "").isalnum():
                return self._send(400, {"error": "bad prompt name"})
            from ci.config import PROMPTS_DIR
            matches = sorted(PROMPTS_DIR.glob(f"*{name}.md"))
            if not matches:
                return self._send(404, {"error": f"no prompt matching {name!r}",
                                        "available": sorted(p.stem for p in PROMPTS_DIR.glob("*.md"))})
            return self._send(200, {"ok": True, "name": matches[0].stem,
                                    "prompt": matches[0].read_text()})
        if self.path in ("/health", "/"):
            return self._send(200, {
                "ok": True,
                "running": _RUNNING["stage"],
                "since": _RUNNING["started"],
                "stages": sorted(_stages()),
            })
        return self._send(404, {"error": "not found", "try": "/health or POST /run/<stage>"})

    def do_POST(self):  # noqa: N802
        if not self._authorised():
            return self._send(401, {"error": "bad or missing CI_API_TOKEN"})
        if not self.path.startswith("/run/"):
            return self._send(404, {"error": "not found", "try": "POST /run/<stage>"})

        name = self.path[len("/run/"):].strip("/")
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
        except Exception as exc:  # noqa: BLE001
            return self._send(400, {"error": f"bad JSON body: {exc}"})

        stages = _stages(body)
        if name not in stages:
            return self._send(404, {"error": f"unknown stage: {name}",
                                    "stages": sorted(stages)})

        # Refuse rather than queue. A stage that piles up behind another is a
        # stage nobody is watching, and double-writing snapshots corrupts velocity.
        if not _LOCK.acquire(blocking=False):
            return self._send(409, {"error": "another stage is running",
                                    "running": _RUNNING["stage"],
                                    "since": _RUNNING["started"]})
        started = time.time()
        _RUNNING.update({"stage": name, "started": time.strftime("%H:%M:%S")})
        try:
            log_event(log, logging.INFO, "stage requested", stage=name)
            result = stages[name]()
            summary = result.get("summary", {}) if isinstance(result, dict) else {}
            payload = {
                "ok": summary.get("status", "ok") != "failed",
                "stage": name,
                "duration_seconds": round(time.time() - started, 2),
                "status": summary.get("status", "ok"),
                "counts": summary.get("counts", {}),
                "failures": summary.get("failures", []),
                "result": {k: v for k, v in result.items() if k != "summary"}
                if isinstance(result, dict) else result,
            }
            return self._send(200, payload)
        except Exception as exc:  # noqa: BLE001 - the endpoint must always answer
            log_event(log, logging.ERROR, "stage failed", stage=name, error=str(exc))
            return self._send(500, {
                "ok": False, "stage": name, "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(limit=4),
                "duration_seconds": round(time.time() - started, 2),
            })
        finally:
            _RUNNING.update({"stage": None, "started": None})
            _LOCK.release()


def serve(host: str = "0.0.0.0", port: int = 8000) -> None:  # noqa: S104 - container-internal
    ci_logging.configure(get_settings().log_level)
    tokened = bool(os.getenv("CI_API_TOKEN", ""))
    log_event(log, logging.INFO, "server listening", host=host, port=port,
              stages=len(_stages()),
              auth="token" if tokened else "private callers only")
    if not tokened:
        log_event(log, logging.WARNING,
                  "CI_API_TOKEN is not set, so only private addresses are accepted. "
                  "Set it before putting this behind a public hostname.")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    serve(os.getenv("CI_HOST", "0.0.0.0"), int(os.getenv("CI_PORT", "8000")))  # noqa: S104
