"""What the dashboard reads and writes. No HTTP in here, so it is testable."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ci.config import CONFIG_DIR, get_settings
from ci.dashboard.yaml_edit import apply as apply_yaml
from ci.database import get_repository

# Every field the dashboard is allowed to write, and where it lives. An
# allowlist rather than a free-form path, so a stray request cannot rewrite an
# arbitrary part of the config, and so the UI can render the right control
# without guessing.
EDITABLE: dict[str, dict[str, Any]] = {
    # --- what reaches the morning list -----------------------------------
    "feed.min_score_to_show": {
        "file": "scoring.yaml", "path": "radar.feed.min_score_to_show",
        "type": "number", "min": 0, "max": 100, "group": "Morning list",
        "label": "Minimum score to appear",
        "help": "Below this a video still goes to the sheet, just not the list."},
    "feed.max_rows": {
        "file": "scoring.yaml", "path": "radar.feed.max_rows",
        "type": "number", "min": 1, "max": 200, "group": "Morning list",
        "label": "Maximum videos on the list",
        "help": "A list nobody finishes reading is a list nobody reads."},
    "feed.max_per_creator": {
        "file": "scoring.yaml", "path": "radar.feed.max_per_creator",
        "type": "number", "min": 1, "max": 25, "group": "Morning list",
        "label": "Max per creator",
        "help": "Stops one busy account owning the morning."},
    "feed.max_per_competitor": {
        "file": "scoring.yaml", "path": "radar.feed.max_per_competitor",
        "type": "number", "min": 1, "max": 50, "group": "Morning list",
        "label": "Max per competitor",
        "help": "Lingopanda had 17 videos on 11 Sep. Without this they fill the screen."},
    "feed.tiers_to_show": {
        "file": "scoring.yaml", "path": "radar.feed.tiers_to_show",
        "type": "tiers", "group": "Morning list",
        "label": "Tiers to show",
        "help": "Display only. Everything is still collected, scored and stored."},

    # --- what counts as big for its age ----------------------------------
    "tier.exploding_views": {
        "file": "scoring.yaml", "path": "takeoff.tiers.0.min_views",
        "type": "number", "min": 0, "max": 5000000, "step": 1000,
        "group": "Tier thresholds", "label": "EXPLODING, views in 24h"},
    "tier.breaking_views": {
        "file": "scoring.yaml", "path": "takeoff.tiers.1.min_views",
        "type": "number", "min": 0, "max": 1000000, "step": 500,
        "group": "Tier thresholds", "label": "BREAKING OUT, views in 24h",
        "help": "Only 1 of 36 videos cleared 50,000 on 11 Sep. Lower it and the tier fills up, but it stops meaning anything."},
    "tier.interesting_views": {
        "file": "scoring.yaml", "path": "takeoff.tiers.2.min_views",
        "type": "number", "min": 0, "max": 500000, "step": 500,
        "group": "Tier thresholds", "label": "INTERESTING, views in 24h"},
    "jackpot.min_views": {
        "file": "scoring.yaml", "path": "takeoff.jackpot.min_views",
        "type": "number", "min": 0, "max": 200000, "step": 500,
        "group": "Tier thresholds",
        "label": "Jackpot needs at least this many views",
        "help": "Without a floor the badge lands on 348 views from a 24-follower "
                "account, because a tiny account beats its own tiny normal every day."},
    "tier.max_candidate_age_hours": {
        "file": "scoring.yaml", "path": "takeoff.max_candidate_age_hours",
        "type": "number", "min": 12, "max": 336, "group": "Tier thresholds",
        "label": "Past this many hours, not a candidate"},

    # --- how the score is made up ----------------------------------------
    "w.waves": {"file": "scoring.yaml", "path": "radar.weights.waves",
                "type": "weight", "group": "Score weights",
                "label": "TikTok pushing it to new people",
                "help": "Needs several readings hours apart, so it is blank on a video's first morning."},
    "w.vs_expected": {"file": "scoring.yaml", "path": "radar.weights.vs_expected",
                      "type": "weight", "group": "Score weights", "label": "Big for its age"},
    "w.acceleration": {"file": "scoring.yaml", "path": "radar.weights.acceleration",
                       "type": "weight", "group": "Score weights", "label": "Speeding up"},
    "w.engagement": {"file": "scoring.yaml", "path": "radar.weights.engagement",
                     "type": "weight", "group": "Score weights", "label": "How people react"},
    "w.creator_lift": {"file": "scoring.yaml", "path": "radar.weights.creator_lift",
                       "type": "weight", "group": "Score weights", "label": "Big for this creator"},
    "w.velocity": {"file": "scoring.yaml", "path": "radar.weights.velocity",
                   "type": "weight", "group": "Score weights", "label": "Raw speed"},
    "w.freshness": {"file": "scoring.yaml", "path": "radar.weights.freshness",
                    "type": "weight", "group": "Score weights", "label": "Freshness"},

    # --- what counts as a good reaction ----------------------------------
    "band.share_elevated": {
        "file": "scoring.yaml", "path": "viral_signals.ratios.share_rate.elevated",
        "type": "rate", "group": "Reaction bars", "label": "Shares per view, good",
        "help": "0.01 means 1 in every 100 viewers shared it."},
    "band.share_viral": {
        "file": "scoring.yaml", "path": "viral_signals.ratios.share_rate.viral",
        "type": "rate", "group": "Reaction bars", "label": "Shares per view, exceptional"},
    "band.save_elevated": {
        "file": "scoring.yaml", "path": "viral_signals.ratios.save_rate.elevated",
        "type": "rate", "group": "Reaction bars", "label": "Saves per view, good"},

    # --- volume and cost --------------------------------------------------
    "vol.max_items_per_keyword": {
        "file": "sources.yaml", "path": "competitor_ugc.passes.0.max_items_per_keyword",
        "type": "number", "min": 1, "max": 200, "group": "Volume and cost",
        "label": "Videos per search",
        "help": "Searches are newest-first, so deeper results are older and more likely to age out."},
    "vol.keywords_per_run": {
        "file": "sources.yaml", "path": "competitor_ugc.keywords_per_run",
        "type": "number", "min": 0, "max": 500, "group": "Volume and cost",
        "label": "Keywords per run (0 means all)"},
    "vol.max_tracked": {
        "file": "scoring.yaml", "path": "viral_signals.watchlist.max_tracked",
        "type": "number", "min": 0, "max": 500, "group": "Volume and cost",
        "label": "Videos re-checked",
        "help": "The biggest single cost. Re-checking usually outspends the morning sweep."},
    "vol.poll_minutes": {
        "file": "scoring.yaml", "path": "viral_signals.watchlist.poll_minutes",
        "type": "number", "min": 5, "max": 720, "group": "Volume and cost",
        "label": "Re-check every N minutes"},
    "vol.max_duration_seconds": {
        "file": "scoring.yaml", "path": "cheap_filter.max_duration_seconds",
        "type": "number", "min": 5, "max": 900, "group": "Volume and cost",
        "label": "Longest video kept, seconds"},
}

NUMERIC_FILTERS = {
    "min_score": ("radar_score", "ge"), "max_score": ("radar_score", "le"),
    "min_views": ("views", "ge"), "max_views": ("views", "le"),
    "min_age": ("age_hours", "ge"), "max_age": ("age_hours", "le"),
    "min_share_rate": ("share_rate", "ge"),
    "max_followers": ("creator_followers", "le"),
}


def _num(row: dict, field: str) -> float:
    try:
        return float(row.get(field) or 0)
    except (TypeError, ValueError):
        return 0.0


def jackpot_rule(settings=None) -> dict[str, Any]:
    settings = settings or get_settings()
    cfg = (settings.scoring.get("takeoff") or {}).get("jackpot") or {}
    return {"max_creator_followers": int(cfg.get("max_creator_followers", 50000)),
            "min_lift": float(cfg.get("min_lift", 5.0)),
            "min_views": int(cfg.get("min_views", 0))}


def is_jackpot(row: dict, rule: dict[str, Any]) -> bool:
    followers = int(row.get("creator_followers") or 0)
    views = int(row.get("views") or 0)
    lift = float(row.get("creator_lift") or 0) or (views / followers if followers else 0)
    return bool(0 < followers <= rule["max_creator_followers"]
                and lift >= rule["min_lift"]
                and views >= rule["min_views"])


def rows(settings=None, repo=None, **f: Any) -> dict[str, Any]:
    """Every scored video, filtered. Reads storage, never the feed, so nothing
    the feed caps hid is hidden here too."""
    settings = settings or get_settings()
    data = (repo or get_repository(settings)).read("RADAR")

    tiers = {t.upper() for t in (f.get("tiers") or []) if t}
    comps = {c for c in (f.get("competitors") or []) if c}
    statuses = {s.upper() for s in (f.get("statuses") or []) if s}
    date = f.get("date") or ""
    query = (f.get("q") or "").lower().strip()
    rule = jackpot_rule(settings)

    out = []
    for r in data:
        r = {**r, "is_jackpot": is_jackpot(r, rule)}
        if tiers and str(r.get("takeoff_tier", "")).upper() not in tiers:
            continue
        if comps and r.get("competitor") not in comps:
            continue
        if statuses and str(r.get("status", "")).upper() not in statuses:
            continue
        if date and r.get("date") != date:
            continue
        if f.get("jackpot_only") and not r.get("is_jackpot"):
            continue
        if query and query not in " ".join(
                str(r.get(k, "")) for k in ("title", "creator", "competitor")).lower():
            continue
        ok = True
        for name, (field, op) in NUMERIC_FILTERS.items():
            raw = f.get(name)
            if raw in (None, ""):
                continue
            bound = float(raw)
            value = _num(r, field)
            if (op == "ge" and value < bound) or (op == "le" and value > bound):
                ok = False
                break
        if ok:
            out.append(r)

    sort_by = f.get("sort") or "radar_score"
    out.sort(key=lambda r: _num(r, sort_by), reverse=not f.get("ascending"))
    limit = int(f.get("limit") or 200)
    return {"total": len(data), "matched": len(out), "rows": out[:limit]}


def facets(settings=None, repo=None) -> dict[str, Any]:
    """The values actually present in the data, so filters only offer real options."""
    settings = settings or get_settings()
    data = (repo or get_repository(settings)).read("RADAR")
    def uniq(field: str) -> list[str]:
        return sorted({str(r.get(field) or "") for r in data} - {""})
    return {"competitors": uniq("competitor"), "tiers": uniq("takeoff_tier"),
            "statuses": uniq("status"), "dates": sorted(
                {str(r.get("date") or "") for r in data} - {""}, reverse=True),
            "count": len(data)}


def config(settings=None) -> dict[str, Any]:
    settings = settings or get_settings()
    blobs = {"scoring.yaml": settings.scoring, "sources.yaml": settings.sources}
    out = {}
    for key, spec in EDITABLE.items():
        out[key] = dict(spec, value=_dig(blobs[spec["file"]], spec["path"]), key=key)
    return {"fields": out, "groups": _groups()}


def _groups() -> list[str]:
    seen: list[str] = []
    for spec in EDITABLE.values():
        if spec["group"] not in seen:
            seen.append(spec["group"])
    return seen


def _dig(data: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if isinstance(data, list):
            try:
                data = data[int(part)]
                continue
            except (ValueError, IndexError):
                return None
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


def save(changes: dict[str, Any]) -> dict[str, Any]:
    """Write edits back, grouped per file so each file is written once."""
    per_file: dict[str, dict[str, Any]] = {}
    for key, value in changes.items():
        spec = EDITABLE.get(key)
        if not spec:
            raise ValueError(f"{key} is not an editable field")
        if spec["type"] in ("number", "weight", "rate"):
            value = float(value)
            if value == int(value) and spec["type"] == "number":
                value = int(value)
            lo, hi = spec.get("min"), spec.get("max")
            if lo is not None and value < lo:
                raise ValueError(f"{key} must be at least {lo}")
            if hi is not None and value > hi:
                raise ValueError(f"{key} must be at most {hi}")
        elif spec["type"] == "tiers":
            value = [str(v).upper() for v in (value or [])]
        per_file.setdefault(spec["file"], {})[spec["path"]] = value

    # Stage every file in memory first. An edit can span scoring.yaml and
    # sources.yaml, and writing the first before the second is validated would
    # leave the two config files disagreeing with each other.
    from ci.dashboard.yaml_edit import set_in_text

    staged: dict[str, str] = {}
    for name, edits in per_file.items():
        text = (CONFIG_DIR / name).read_text()
        for path, value in edits.items():
            text = set_in_text(text, [p for p in path.split(".") if p], value)
        staged[name] = text

    result = {}
    for name, edits in per_file.items():
        result[name] = apply_yaml(CONFIG_DIR / name, edits)
    get_settings.cache_clear()
    return {"files": result, "fields": len(changes)}


def cost(settings=None) -> dict[str, Any]:
    """What the current settings cost per day, per actor.

    Sitting next to the volume dials on purpose. The numbers move by a factor of
    twenty depending on which Apify plan is active, and that is not obvious from
    the dials themselves.
    """
    settings = settings or get_settings()
    tk = settings.sources.get("tiktok", {})
    ugc = settings.sources.get("competitor_ugc", {})
    wl = settings.scoring.get("viral_signals", {}).get("watchlist", {})
    comps = ((settings.competitors.get("competitors") or [])
             + (settings.competitors.get("adjacent") or []))

    configured = sum(len(c.get("keywords", []) or []) for c in comps)
    cap = int(ugc.get("keywords_per_run", 0) or 0)
    keywords = configured if cap <= 0 else min(cap, configured)
    passes = ugc.get("passes") or tk.get("passes") or [{}]
    per_kw = int((passes[0] or {}).get("max_items_per_keyword", 15))
    pulled = keywords * per_kw

    poll_minutes = max(1, int(wl.get("poll_minutes", 30) or 30))
    polls = int(24 * 60 / poll_minutes)
    tracked = int(wl.get("max_tracked", 0) or 0)
    if not wl.get("enabled", True):
        polls = tracked = 0

    actors = []
    for name, spec in (tk.get("actor_inputs") or {}).items():
        search = float(spec.get("cost_per_video_usd", 0) or 0)
        poll = float(spec.get("cost_per_video_by_url_usd", search) or search)
        sweep = pulled * search
        recheck = polls * tracked * poll
        actors.append({
            "actor": name, "sweep": round(sweep, 2), "recheck": round(recheck, 2),
            "per_day": round(sweep + recheck, 2),
            "per_month": round((sweep + recheck) * 30),
            "is_primary": name == tk.get("actor"),
        })
    actors.sort(key=lambda a: a["per_day"])
    return {"keywords": keywords, "configured_keywords": configured,
            "per_keyword": per_kw, "pulled_per_day": pulled,
            "polls_per_day": polls * tracked, "tracked": tracked,
            "actors": actors}


def _pending(settings, changes: dict[str, Any]) -> dict[str, Any]:
    """A copy of scoring with the pending edits applied, without writing anything."""
    import copy

    scoring = copy.deepcopy(settings.scoring)
    for key, value in (changes or {}).items():
        spec = EDITABLE.get(key)
        if not spec or spec["file"] != "scoring.yaml":
            continue
        parts = spec["path"].split(".")
        node: Any = scoring
        for part in parts[:-1]:
            node = node[int(part)] if isinstance(node, list) else node.setdefault(part, {})
        last = parts[-1]
        if spec["type"] == "tiers":
            value = [str(v).upper() for v in (value or [])]
        elif spec["type"] in ("number", "weight", "rate"):
            value = float(value)
            if spec["type"] == "number" and value == int(value):
                value = int(value)
        if isinstance(node, list):
            node[int(last)] = value
        else:
            node[last] = value
    return scoring


def _retier(row: dict, takeoff: dict[str, Any]) -> str:
    """Recompute the size-for-age label from stored views and age.

    Tier is only ever views and age, never anything learned, so it can be
    replayed exactly against new thresholds without re-scraping or re-scoring.
    """
    views = _num(row, "views")
    age = _num(row, "age_hours")
    av = takeoff.get("already_viral", {})
    if (views >= float(av.get("min_views", 500000))
            and age >= float(av.get("older_than_hours", 48))):
        return str(av.get("label", "ALREADY VIRAL"))
    if age > float(takeoff.get("max_candidate_age_hours", 72)):
        return "TOO OLD"
    for tier in takeoff.get("tiers", []) or []:
        if views >= float(tier.get("min_views", 0)) and age <= float(
                tier.get("max_age_hours", 24)):
            return str(tier.get("name", "WATCH"))
    return "DAY TWO"


def preview(changes: dict[str, Any], settings=None, repo=None) -> dict[str, Any]:
    """What the stored rows would look like under pending settings.

    Answers the question the dials cannot: drop BREAKING OUT to 20,000 and how
    many videos actually move? On real data, not a guess.
    """
    from collections import Counter

    from ci.scoring.radar import apply_feed_caps

    settings = settings or get_settings()
    data = (repo or get_repository(settings)).read("RADAR")
    now_cfg, new_cfg = settings.scoring, _pending(settings, changes)

    def snapshot(cfg: dict[str, Any], relabel: bool) -> dict[str, Any]:
        rows_ = []
        for r in data:
            row = dict(r)
            if relabel:
                row["takeoff_tier"] = _retier(row, cfg.get("takeoff", {}))
            rows_.append(row)
        feed = apply_feed_caps(rows_, cfg.get("radar", {}))
        return {"tiers": dict(Counter(r.get("takeoff_tier", "") for r in rows_)),
                "feed": len(feed),
                "feed_tiers": dict(Counter(r.get("takeoff_tier", "") for r in feed))}

    before = snapshot(now_cfg, relabel=False)
    after = snapshot(new_cfg, relabel=True)
    moved = [
        {"url": r.get("url", ""), "creator": r.get("creator", ""),
         "views": int(_num(r, "views")), "age_hours": round(_num(r, "age_hours")),
         "from": r.get("takeoff_tier", ""),
         "to": _retier(r, new_cfg.get("takeoff", {}))}
        for r in data
        if _retier(r, new_cfg.get("takeoff", {})) != r.get("takeoff_tier", "")
    ]
    return {"scored": len(data), "before": before, "after": after,
            "moved": moved[:40], "moved_total": len(moved)}


def transcript(content_id: str, settings=None) -> dict[str, Any]:
    """What is actually in the video, when tools/transcribe.py has been run on it.

    Absent for most videos, and that absence is the honest answer: without it the
    dashboard only has an idea we wrote, never the competitor's own script.
    """
    settings = settings or get_settings()
    safe = "".join(c for c in str(content_id) if c.isalnum() or c in "-_")
    path = Path(settings.local_data_dir) / "transcripts" / f"{safe}.json"
    if not safe or not path.exists():
        return {"found": False}
    try:
        import json
        return {"found": True, **json.loads(path.read_text())}
    except Exception as exc:  # noqa: BLE001
        return {"found": False, "error": str(exc)}


def transcribe_ready() -> dict[str, Any]:
    """Whether tools/transcribe.py has what it needs on this machine."""
    import importlib.util
    import shutil

    # yt-dlp and whisper are packages in the interpreter running this dashboard,
    # not commands on PATH. Looking for them with shutil.which greyed the job out
    # on a machine where both were installed and working, which is the same bug
    # that made transcribe.py claim yt-dlp was missing.
    missing = [name for name, module in (("yt-dlp", "yt_dlp"),
                                         ("faster-whisper", "faster_whisper"))
               if importlib.util.find_spec(module) is None]
    if shutil.which("ffmpeg") is None:
        missing.append("ffmpeg")
    return {"ready": not missing, "missing": missing,
            "ocr": shutil.which("tesseract") is not None}


def transcript_index(settings=None) -> dict[str, Any]:
    settings = settings or get_settings()
    folder = Path(settings.local_data_dir) / "transcripts"
    ids = sorted(f.stem for f in folder.glob("*.json")) if folder.exists() else []
    return {"ids": ids, "count": len(ids)}


def health(settings=None, repo=None) -> dict[str, Any]:
    """Where the data is, how much of it there is, and what is missing.

    An empty dashboard has several very different causes and they need very
    different answers: nothing has ever been collected, the last sweep came back
    empty, or the filters on screen exclude everything. Showing "no results" for
    all three sends someone hunting in the wrong place, so the page asks here
    and says which one it is.
    """
    settings = settings or get_settings()
    repo = repo or get_repository(settings)

    tables = {}
    for name in ("RADAR", "RAW_CONTENT", "CONTENT_SNAPSHOTS", "RUN_LOG"):
        try:
            tables[name] = len(repo.read(name))
        except Exception:  # noqa: BLE001  a missing table is a count of zero
            tables[name] = 0

    radar = repo.read("RADAR") if tables["RADAR"] else []
    dates = sorted({r.get("date") for r in radar if r.get("date")})
    runs = repo.read("RUN_LOG") if tables["RUN_LOG"] else []
    last_run = runs[-1] if runs else None

    env = Path(settings.local_data_dir).parent / ".env"
    state = {
        "data_dir": str(settings.local_data_dir),
        "storage_backend": settings.storage_backend,
        "tables": tables,
        "dates": dates,
        "latest_date": dates[-1] if dates else None,
        "last_run": {k: last_run.get(k) for k in ("stage", "status", "finished_at")}
                    if isinstance(last_run, dict) else None,
        "apify_token": bool(settings.apify_token),
        "env_file": env.exists(),
        "sheets_ready": bool(settings.google_sheet_id and settings.google_service_account_json),
        "transcripts": transcript_index(settings)["count"],
        "transcribe": transcribe_ready(),
    }
    state["diagnosis"] = _diagnose(state)
    return state


def _diagnose(state: dict[str, Any]) -> dict[str, str]:
    """One plain sentence about the state of the data, plus what fixes it."""
    tables = state["tables"]
    if tables["RADAR"] == 0 and tables["RAW_CONTENT"] == 0:
        if not state["apify_token"]:
            return {"headline": "Nothing has been collected yet",
                    "detail": "There is no APIFY_TOKEN, so no sweep can run. Put the "
                              "token in a .env file at the top of the project, then "
                              "run Collect creator videos.",
                    "action": ""}
        return {"headline": "Nothing has been collected yet",
                "detail": "The storage is empty. Run a sweep to fill it.",
                "action": "collect_ugc"}
    if tables["RADAR"] == 0:
        return {"headline": "Videos were collected but never scored",
                "detail": f"{tables['RAW_CONTENT']} videos are in storage with no scores "
                          "against them. Scoring is free and takes a second.",
                "action": "rescore"}
    if tables["RAW_CONTENT"] == 0:
        return {"headline": f"{tables['RADAR']} scored videos, no raw collection behind them",
                "detail": "The scores were loaded from a previous run, so re-scoring "
                          "cannot produce anything new. A fresh sweep can.",
                "action": "collect_ugc"}
    if tables["CONTENT_SNAPSHOTS"] == 0:
        return {"headline": "No repeat measurements yet",
                "detail": "Every video has been measured once, so the pushed-to-new-people "
                          "and speeding-up signals cannot be calculated. Re-check the "
                          "watchlist a few times through the day to fix that.",
                "action": "watch"}
    return {"headline": "", "detail": "", "action": ""}
