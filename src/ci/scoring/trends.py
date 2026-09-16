"""Day over day movement.

A single day's radar tells you what is hot this morning. It cannot tell you that a
video has been climbing for three days, that a competitor has quietly tripled its
output this week, or that a hook everyone was using has stopped working.

That only comes from keeping every day's rows and comparing them, which is why
RADAR is append-per-day and never overwritten.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

RISING = "RISING"
FALLING = "FALLING"
FLAT = "FLAT"
NEW = "NEW"
GONE = "GONE"


@dataclass
class VideoTrend:
    content_id: str
    competitor: str = ""
    creator: str = ""
    title: str = ""
    url: str = ""
    direction: str = NEW
    days_on_radar: int = 1
    first_seen: str = ""
    score_now: float = 0.0
    score_prev: float = 0.0
    score_delta: float = 0.0
    peak_score: float = 0.0
    views_now: int = 0
    views_prev: int = 0
    views_gained: int = 0
    views_gained_pct: float = 0.0
    rank_now: int = 0
    rank_prev: int = 0
    rank_change: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""


@dataclass
class CompetitorTrend:
    competitor: str
    videos_now: int = 0
    videos_prev: int = 0
    videos_delta: int = 0
    total_views_now: int = 0
    total_views_prev: int = 0
    avg_score_now: float = 0.0
    avg_score_prev: float = 0.0
    best_video_url: str = ""
    best_video_score: float = 0.0
    direction: str = FLAT
    note: str = ""


def _by_date(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        out[row.get("date", "")].append(row)
    return out


def _ranked(rows: list[dict]) -> dict[str, int]:
    ordered = sorted(rows, key=lambda r: float(r.get("radar_score", 0)), reverse=True)
    return {r.get("content_id", ""): i + 1 for i, r in enumerate(ordered)}


def video_trends(radar_rows: list[dict], today: str, lookback_days: int = 14,
                 min_delta: float = 3.0) -> list[VideoTrend]:
    by_date = _by_date(radar_rows)
    dates = sorted(by_date)
    if today not in by_date:
        return []
    prev_date = next((d for d in reversed(dates) if d < today), None)

    now_rows = by_date[today]
    prev_rows = by_date.get(prev_date, []) if prev_date else []
    now_rank = _ranked(now_rows)
    prev_rank = _ranked(prev_rows)
    prev_by_id = {r.get("content_id"): r for r in prev_rows}

    cutoff = (datetime.fromisoformat(today) - timedelta(days=lookback_days)).date().isoformat()
    seen_dates: dict[str, list[str]] = defaultdict(list)
    per_video_history: dict[str, list[dict]] = defaultdict(list)
    for date in dates:
        if date < cutoff:
            continue
        for row in by_date[date]:
            cid = row.get("content_id", "")
            seen_dates[cid].append(date)
            per_video_history[cid].append({
                "date": date,
                "score": round(float(row.get("radar_score", 0)), 1),
                "views": int(row.get("views") or 0),
            })

    out: list[VideoTrend] = []
    for row in now_rows:
        cid = row.get("content_id", "")
        prev = prev_by_id.get(cid)
        history = per_video_history.get(cid, [])
        trend = VideoTrend(
            content_id=cid,
            competitor=row.get("competitor", ""),
            creator=row.get("creator", ""),
            title=(row.get("title") or "")[:200],
            url=row.get("url", ""),
            days_on_radar=len(seen_dates.get(cid, [])),
            first_seen=(seen_dates.get(cid) or [today])[0],
            score_now=round(float(row.get("radar_score", 0)), 2),
            views_now=int(row.get("views") or 0),
            rank_now=now_rank.get(cid, 0),
            peak_score=round(max((h["score"] for h in history), default=0.0), 2),
            history=history[-lookback_days:],
        )
        if prev is None:
            trend.direction = NEW
            trend.note = "first time on the radar"
        else:
            trend.score_prev = round(float(prev.get("radar_score", 0)), 2)
            trend.score_delta = round(trend.score_now - trend.score_prev, 2)
            trend.views_prev = int(prev.get("views") or 0)
            trend.views_gained = trend.views_now - trend.views_prev
            if trend.views_prev > 0:
                trend.views_gained_pct = round(trend.views_gained / trend.views_prev * 100, 1)
            trend.rank_prev = prev_rank.get(cid, 0)
            # Rank 1 is best, so a smaller number is an improvement.
            trend.rank_change = trend.rank_prev - trend.rank_now if trend.rank_prev else 0
            if trend.score_delta >= min_delta:
                trend.direction = RISING
                trend.note = (f"up {trend.score_delta:.0f} points, "
                              f"+{trend.views_gained:,} views since yesterday")
            elif trend.score_delta <= -min_delta:
                trend.direction = FALLING
                trend.note = f"down {abs(trend.score_delta):.0f} points"
            else:
                trend.direction = FLAT
                trend.note = f"holding, +{trend.views_gained:,} views"
            if trend.days_on_radar >= 3 and trend.direction == RISING:
                trend.note += f", climbing {trend.days_on_radar} days straight"
        out.append(trend)

    out.sort(key=lambda t: (t.direction != RISING, -t.score_now))
    return out


def dropped_off(radar_rows: list[dict], today: str) -> list[dict]:
    """Videos that were on the radar yesterday and are not today. Usually means
    they cooled, and that is worth seeing."""
    by_date = _by_date(radar_rows)
    dates = sorted(by_date)
    prev_date = next((d for d in reversed(dates) if d < today), None)
    if not prev_date:
        return []
    now_ids = {r.get("content_id") for r in by_date.get(today, [])}
    return [
        {"content_id": r.get("content_id"), "creator": r.get("creator"),
         "competitor": r.get("competitor"), "url": r.get("url"),
         "last_score": r.get("radar_score"), "last_seen": prev_date}
        for r in by_date[prev_date] if r.get("content_id") not in now_ids
    ]


def competitor_trends(radar_rows: list[dict], today: str) -> list[CompetitorTrend]:
    by_date = _by_date(radar_rows)
    dates = sorted(by_date)
    prev_date = next((d for d in reversed(dates) if d < today), None)

    def group(rows: list[dict]) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            if row.get("competitor"):
                out[row["competitor"]].append(row)
        return out

    now = group(by_date.get(today, []))
    prev = group(by_date.get(prev_date, [])) if prev_date else {}

    out: list[CompetitorTrend] = []
    for name in sorted(set(now) | set(prev)):
        n, p = now.get(name, []), prev.get(name, [])
        trend = CompetitorTrend(
            competitor=name,
            videos_now=len(n), videos_prev=len(p), videos_delta=len(n) - len(p),
            total_views_now=sum(int(r.get("views") or 0) for r in n),
            total_views_prev=sum(int(r.get("views") or 0) for r in p),
            avg_score_now=round(sum(float(r.get("radar_score", 0)) for r in n) / len(n), 1) if n else 0.0,
            avg_score_prev=round(sum(float(r.get("radar_score", 0)) for r in p) / len(p), 1) if p else 0.0,
        )
        if n:
            best = max(n, key=lambda r: float(r.get("radar_score", 0)))
            trend.best_video_url = best.get("url", "")
            trend.best_video_score = round(float(best.get("radar_score", 0)), 1)
        # Direction has to weigh BOTH how many videos and how well they score.
        # Counting videos alone called a competitor FLAT while its average score
        # fell from 74 to 53, which is the opposite of flat.
        score_delta = round(trend.avg_score_now - trend.avg_score_prev, 1)
        notes = []
        if trend.videos_delta:
            notes.append(f"{abs(trend.videos_delta)} "
                         f"{'more' if trend.videos_delta > 0 else 'fewer'} videos than yesterday")
        if abs(score_delta) >= 5:
            notes.append(f"average score {'up' if score_delta > 0 else 'down'} {abs(score_delta):.0f}")

        if not p and n:
            trend.direction = NEW
            notes = ["first appearance"]
        elif not n and p:
            trend.direction = GONE
            notes = ["nothing on the radar today"]
        elif trend.videos_delta > 0 or score_delta >= 5:
            trend.direction = RISING
        elif trend.videos_delta < 0 or score_delta <= -5:
            trend.direction = FALLING
        else:
            trend.direction = FLAT
            notes = notes or ["no real change"]
        trend.note = ", ".join(notes)
        out.append(trend)

    out.sort(key=lambda t: (-t.videos_now, -t.avg_score_now))
    return out


def hashtag_trends(radar_rows: list[dict], today: str, top: int = 15) -> list[dict]:
    """Which tags are showing up more than they were. A cheap read on where the
    category's attention is moving."""
    by_date = _by_date(radar_rows)
    dates = sorted(by_date)
    prev_date = next((d for d in reversed(dates) if d < today), None)

    def counts(rows: list[dict]) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for row in rows:
            for tag in row.get("hashtags") or []:
                out[str(tag).lower()] += 1
        return out

    now = counts(by_date.get(today, []))
    prev = counts(by_date.get(prev_date, [])) if prev_date else {}
    rows = []
    for tag in set(now) | set(prev):
        n, p = now.get(tag, 0), prev.get(tag, 0)
        rows.append({"date": today, "hashtag": tag, "count_today": n,
                     "count_yesterday": p, "delta": n - p,
                     "direction": RISING if n > p else FALLING if n < p else FLAT})
    rows.sort(key=lambda r: (-r["delta"], -r["count_today"]))
    return rows[:top]
