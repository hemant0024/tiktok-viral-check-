"""Runs pipeline stages from the dashboard, in the background.

The stage server in ci.server runs a stage inside the request, which is right
for n8n: the caller is a machine that can wait four minutes for an answer.

A person cannot. So a stage started from the dashboard runs on its own thread
and the page polls for progress. Same reason as ci.server, only one runs at a
time: two collectors writing snapshots at once corrupts the velocity history,
which is the one thing in this pipeline that cannot be recomputed afterwards.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from typing import Any, Callable

from ci.config import Settings, get_settings
from ci.database import get_repository
from ci.logging import get_logger, log_event

log = get_logger(__name__)

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {
    "job": None,        # key of the job running right now, None when idle
    "label": None,
    "started": None,    # epoch seconds
    "steps": [],        # human-readable progress, appended as it goes
    "last": None,       # the finished record of the previous run
    "history": [],      # newest first, capped
}
HISTORY_LIMIT = 8


# Stages worth starting by hand. ci.server carries all twenty-four for n8n;
# this is the short list a person would actually click, in the order they would
# reach for them.
def catalogue() -> list[dict[str, Any]]:
    return [
        {"key": "rescore", "label": "Re-score what is stored",
         "blurb": "Applies the current settings to the videos already collected. "
                  "No scraping, no cost, a second or two.",
         "network": False, "needs": None, "cost": "free"},
        {"key": "watch", "label": "Re-check the watchlist",
         "blurb": "Re-measures the videos that look like they are taking off, so "
                  "the pushed-to-new-people signal can be calculated.",
         "network": True, "needs": "apify", "cost": "about $0.18 per run"},
        {"key": "collect_ugc", "label": "Collect creator videos, then score",
         "blurb": "A full sweep of every competitor keyword on TikTok, then scores "
                  "whatever comes back.",
         "network": True, "needs": "apify", "cost": "about $0.34 per sweep"},
        {"key": "collect_ads", "label": "Collect competitor ads, then score",
         "blurb": "Pulls the Meta ad library for the competitor pages, then scores them.",
         "network": True, "needs": "apify", "cost": "about $0.05 per sweep"},
        {"key": "sheets", "label": "Push to Google Sheet",
         "blurb": "Writes the current radar to the shared sheet.",
         "network": True, "needs": "google", "cost": "free"},
    ]


def _plan(key: str, settings: Settings) -> list[tuple[str, Callable[[], dict]]]:
    """Job key -> the named steps it runs, in order.

    Collection is always followed by scoring. Collecting without scoring leaves
    the dashboard looking exactly as empty as before, which reads as a failure
    even when the sweep worked.
    """
    from ci import stages as S

    repo = get_repository(settings)
    plans: dict[str, list[tuple[str, Callable[[], dict]]]] = {
        "rescore": [
            ("Scoring stored videos", lambda: S.stage_radar(repo, settings)),
        ],
        "watch": [
            ("Re-measuring the watchlist", lambda: S.stage_watch(repo, settings)),
            ("Scoring with the new measurements", lambda: S.stage_radar(repo, settings)),
        ],
        "collect_ugc": [
            ("Sweeping TikTok for competitor mentions",
             lambda: S.stage_collect(repo, settings, ["competitor_ugc"])),
            ("Scoring what came back", lambda: S.stage_radar(repo, settings, kind="ugc")),
        ],
        "collect_ads": [
            ("Pulling the Meta ad library",
             lambda: S.stage_collect(repo, settings, ["meta_ads"])),
            ("Scoring the ads", lambda: S.stage_radar(repo, settings, kind="ads")),
        ],
        "sheets": [
            ("Writing the Google Sheet", lambda: S.stage_sheets_push(repo, settings)),
        ],
    }
    if key not in plans:
        raise KeyError(key)
    return plans[key]


def _hint(key: str, results: list[dict], error: str | None) -> str:
    """One plain sentence about what to do next, or nothing.

    A sweep that collects zero is the failure people misread most often: the run
    says SUCCEEDED, the dashboard does not change, and the obvious conclusion is
    that the tool is broken. Usually it is an empty Apify balance.
    """
    blob = (error or "").lower()
    if "apify_token is not set" in blob:
        return ("Nothing was collected because APIFY_TOKEN is missing. Put it in a "
                ".env file at the top of the project.")
    if "402" in blob or "insufficient" in blob or "credit" in blob or "usage limit" in blob:
        return ("Apify has no credit left, so the scrape could not run. Top the "
                "account up and run this again.")
    if "throttl" in blob:
        return ("Apify throttled the search. Wait a few minutes and run it again, "
                "or switch to the paid actor in Settings.")
    if error:
        return ""
    scored = _count(results, "scored")
    if key.startswith("collect") or key == "watch":
        collected = _count(results, "collected") + _count(results, "new") + _count(results, "polled")
        if collected == 0:
            return ("The sweep ran but brought back nothing. That is almost always "
                    "an empty Apify balance: the scrape still reports success and "
                    "simply returns no videos. Check the balance before assuming "
                    "the competitors went quiet.")
    if key == "rescore" and scored == 0:
        return ("Nothing to score. Scoring only reads videos that were collected "
                "earlier, and the collection store is empty, so collect first.")
    return ""


def _count(results: list[dict], field: str) -> int:
    total = 0
    for r in results:
        value = r.get(field)
        summary = r.get("summary")
        if value is None and isinstance(summary, dict):
            value = (summary.get("counts") or {}).get(field)
        if isinstance(value, int):
            total += value
    return total


def _run(key: str, settings: Settings) -> None:
    started = _STATE["started"]
    results: list[dict] = []
    error: str | None = None
    try:
        for name, fn in _plan(key, settings):
            with _LOCK:
                _STATE["steps"] = _STATE["steps"] + [{"name": name, "state": "running"}]
            out = fn() or {}
            results.append(out if isinstance(out, dict) else {"result": out})
            with _LOCK:
                steps = [dict(s) for s in _STATE["steps"]]
                steps[-1] = {"name": name, "state": "done", "detail": _summarise(out)}
                _STATE["steps"] = steps
        log_event(log, logging.INFO, "dashboard job finished", job=key)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        log_event(log, logging.ERROR, "dashboard job failed", job=key, error=str(exc))
        log.debug(traceback.format_exc())
        with _LOCK:
            steps = [dict(s) for s in _STATE["steps"]]
            if steps and steps[-1].get("state") == "running":
                steps[-1] = {**steps[-1], "state": "failed", "detail": error}
                _STATE["steps"] = steps

    record = {
        "job": key,
        "label": next((j["label"] for j in catalogue() if j["key"] == key), key),
        "ok": error is None,
        "error": error,
        "hint": _hint(key, results, error),
        "results": results,
        "steps": _STATE["steps"],
        "started": started,
        "finished": time.time(),
        "seconds": round(time.time() - (started or time.time()), 1),
    }
    with _LOCK:
        _STATE["job"] = None
        _STATE["label"] = None
        _STATE["started"] = None
        _STATE["last"] = record
        _STATE["history"] = ([record] + _STATE["history"])[:HISTORY_LIMIT]


def _summarise(out: dict) -> str:
    """The two or three numbers from a stage result worth putting on screen.

    Stage results are not uniform: some carry counts at the top level, some bury
    them in summary.counts. Reading both is cheaper than making sixteen stages
    agree on a shape.
    """
    if not isinstance(out, dict):
        return ""
    counts: dict[str, Any] = {}
    summary = out.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("counts"), dict):
        counts.update(summary["counts"])
    counts.update({k: v for k, v in out.items() if isinstance(v, int)})
    order = ("collected", "new", "attributed", "scored", "on_feed", "hot", "kept",
             "dropped", "tracked", "polled", "checked", "rows", "pushed", "skipped")
    bits = [f"{k.replace('_', ' ')} {counts[k]}" for k in order if k in counts]
    bits += [f"{k.replace('_', ' ')} {v}" for k, v in counts.items()
             if k not in order and isinstance(v, int)]
    return " · ".join(bits[:4])


def start(key: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    if key not in {j["key"] for j in catalogue()}:
        raise KeyError(key)
    with _LOCK:
        if _STATE["job"]:
            return {"started": False, "reason": "busy", **_public()}
        _STATE["job"] = key
        _STATE["label"] = next(j["label"] for j in catalogue() if j["key"] == key)
        _STATE["started"] = time.time()
        _STATE["steps"] = []
    log_event(log, logging.INFO, "dashboard job starting", job=key)
    threading.Thread(target=_run, args=(key, settings), daemon=True,
                     name=f"dash-{key}").start()
    return {"started": True, **_public()}


def _public() -> dict[str, Any]:
    running = _STATE["job"]
    return {
        "running": running,
        "label": _STATE["label"],
        "elapsed": round(time.time() - _STATE["started"], 1) if _STATE["started"] else None,
        "steps": _STATE["steps"],
        "last": _STATE["last"],
        "history": _STATE["history"],
    }


def status() -> dict[str, Any]:
    with _LOCK:
        return {"jobs": catalogue(), **_public()}


def reset_for_tests() -> None:
    with _LOCK:
        _STATE.update({"job": None, "label": None, "started": None, "steps": [],
                       "last": None, "history": []})
