"""Localhost dashboard. Stdlib only, same as the stage server.

Binds to 127.0.0.1 by default, deliberately. This one can rewrite config files,
so it must never be the thing that happens to be listening on 0.0.0.0.
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ci import logging as ci_logging
from ci.config import get_settings
from ci.dashboard import api, runner
from ci.logging import get_logger, log_event

log = get_logger(__name__)
PAGE = Path(__file__).with_name("page.html")

LIST_PARAMS = {"tiers", "competitors", "statuses"}
BOOL_PARAMS = {"jackpot_only", "ascending"}


class Handler(BaseHTTPRequestHandler):
    server_version = "creative-intelligence-dashboard/1.0"

    def log_message(self, fmt, *args):  # noqa: A003
        pass

    def _send(self, code: int, payload, content_type="application/json"):
        body = (payload if isinstance(payload, bytes)
                else json.dumps(payload, default=str).encode())
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if url.path == "/api/facets":
            return self._send(200, api.facets())
        if url.path == "/api/config":
            return self._send(200, api.config())
        if url.path == "/api/cost":
            return self._send(200, api.cost())
        if url.path == "/api/health":
            return self._send(200, api.health())
        if url.path == "/api/run":
            return self._send(200, runner.status())
        if url.path == "/api/rows":
            raw = parse_qs(url.query)
            filters = {}
            for key, values in raw.items():
                if key in LIST_PARAMS:
                    filters[key] = [v for v in values[0].split(",") if v]
                elif key in BOOL_PARAMS:
                    filters[key] = values[0] in ("1", "true", "yes")
                else:
                    filters[key] = values[0]
            try:
                return self._send(200, api.rows(**filters))
            except Exception as exc:  # noqa: BLE001
                return self._send(400, {"error": f"{type(exc).__name__}: {exc}"})
        return self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        url = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:  # noqa: BLE001
            return self._send(400, {"error": f"bad JSON body: {exc}"})

        if url.path == "/api/config":
            try:
                result = api.save(body.get("changes") or {})
            except Exception as exc:  # noqa: BLE001
                # A rejected edit must say why. "Saving failed" sends someone
                # hunting through YAML by hand.
                return self._send(400, {"error": str(exc)})
            log_event(log, logging.INFO, "config updated via dashboard",
                      fields=result["fields"])
            return self._send(200, {**result, "cost": api.cost()})

        if url.path.startswith("/api/run/"):
            # Stages run on their own thread and the page polls /api/run. A stage
            # can take four minutes; a request that blocks that long looks like a
            # hung dashboard and gets killed by whoever is watching it.
            key = url.path.rsplit("/", 1)[-1]
            try:
                result = runner.start(key)
            except KeyError:
                return self._send(404, {"error": f"unknown job: {key}",
                                        "jobs": [j["key"] for j in runner.catalogue()]})
            if not result.get("started"):
                return self._send(409, result)
            return self._send(200, result)

        if url.path == "/api/preview":
            # Score the stored rows against pending settings WITHOUT saving, so
            # you can see what moving a threshold would do before committing it.
            try:
                return self._send(200, api.preview(body.get("changes") or {}))
            except Exception as exc:  # noqa: BLE001
                return self._send(400, {"error": str(exc)})

        return self._send(404, {"error": "not found"})


def serve(host: str = "127.0.0.1", port: int = 8787) -> None:
    ci_logging.configure(get_settings().log_level)
    log_event(log, logging.INFO, "dashboard listening",
              url=f"http://{host}:{port}", editable=len(api.EDITABLE))
    print(f"\n  Radar dashboard  ->  http://{host}:{port}\n")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
