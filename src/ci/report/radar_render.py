"""The viral radar feed.

One block per video, with everything needed to go and look at it: the link, the
title, who made it, when, and the numbers that put it on the list.
"""
from __future__ import annotations

from datetime import datetime

ICON = {
    "EXPLODING": "[!!]",
    "BREAKING OUT": "[>>]",
    "INTERESTING": "[~ ]",
    "WATCH": "[. ]",
    "DAY TWO": "[d2]",
    "ALREADY VIRAL": "[xx]",
    "TOO OLD": "[--]",
    "PROVEN WINNER": "[$$]",
    "LIKELY WINNER": "[$ ]",
    "NEW, WATCH IT": "[??]",
    "TEST SIGNAL ONLY": "[. ]",
    "EXPLODING": "[!!]",
    "CLIMBING": "[^ ]",
    "EARLY SIGNAL": "[? ]",
    "STEADY": "[= ]",
    "COOLING": "[v ]",
}
ORDER = ["EXPLODING", "BREAKING OUT", "INTERESTING", "WATCH", "DAY TWO",
         "PROVEN WINNER", "LIKELY WINNER", "CLIMBING", "EARLY SIGNAL",
         "NEW, WATCH IT", "STEADY", "COOLING", "TEST SIGNAL ONLY"]


def human(n: float) -> str:
    n = float(n or 0)
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= limit:
            return f"{n / limit:.1f}".rstrip("0").rstrip(".") + suffix
    return str(int(n))


def age(hours: float) -> str:
    hours = float(hours or 0)
    if hours < 48:
        return f"{int(hours)}h old"
    return f"{int(hours / 24)}d old"


def short_date(value: str | None) -> str:
    if not value:
        return "unknown"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%d %b")
    except ValueError:
        return str(value)[:10]


def render_feed(date_str: str, rows: list[dict], failures: list[str] | None = None,
                limit: int | None = None) -> str:
    if not rows:
        return f"COMPETITOR VIRAL RADAR\n{date_str}\n\nNothing crossed the threshold today."

    shown = rows[:limit] if limit else rows
    by_status: dict[str, int] = {}
    for row in rows:
        by_status[row.get("status", "STEADY")] = by_status.get(row.get("status", "STEADY"), 0) + 1

    counts = "  ".join(
        f"{ICON.get(s, '')} {by_status[s]} {s.lower()}" for s in ORDER if by_status.get(s)
    )
    lines = ["COMPETITOR VIRAL RADAR", date_str, "", counts, "", "=" * 64, ""]

    for rank, r in enumerate(shown, start=1):
        status = r.get("status", "STEADY")
        kind = "AD" if r.get("kind") == "competitor_ad" else "UGC"
        competitor = r.get("competitor") or "unattributed"
        lines += [
            f"{ICON.get(status,'')} #{rank}  {status}   score {r.get('radar_score',0):.0f}"
            f"   ·  {competitor}  ·  {kind}",
            f"     {r.get('url','')}",
            "",
            f"     {r.get('title','') or '(no caption)'}",
            "",
            f"     Creator   @{r.get('creator','')}"
            + (f"  ({human(r.get('creator_followers'))} followers)"
               if r.get("creator_followers") else ""),
            f"     Posted    {short_date(r.get('published_at'))}  ·  {age(r.get('age_hours'))}"
            + (f"  ·  {int(r.get('duration_seconds') or 0)}s" if r.get("duration_seconds") else ""),
        ]
        if r.get("video_url"):
            lines.append(f"     Video     {r['video_url'][:78]}")

        lines += [
            "",
            f"     {human(r.get('views')):>7} views    {human(r.get('likes')):>7} likes    "
            f"{human(r.get('comments')):>6} comments",
            f"     {human(r.get('shares')):>7} shares   {human(r.get('saves')):>7} saves",
        ]
        # Ratios first, share rate first among them. A like says "I enjoyed this",
        # a share says "someone else needs to see this".
        if r.get("share_rate") is not None and r.get("kind") != "competitor_ad":
            band = r.get("share_rate_band", "normal")
            flag = "  <-- " + band.upper() if band != "normal" else ""
            lines += [
                "",
                f"     shares/views   {float(r.get('share_rate') or 0):>6.2%}{flag}",
                f"     saves/views    {float(r.get('save_rate') or 0):>6.2%}",
                f"     comments/views {float(r.get('comment_rate') or 0):>6.2%}",
                f"     likes/views    {float(r.get('like_rate') or 0):>6.2%}",
            ]
        if r.get("expected_views"):
            lines.append(
                f"\n     Pace      {human(r.get('views'))} views at {age(r.get('age_hours'))}, "
                f"vs {human(r.get('expected_views'))} normal  ->  "
                f"{float(r.get('vs_expected') or 0):.1f}x pace"
            )
        if r.get("wave_count"):
            ratios = " -> ".join(f"{x:.1f}x" for x in (r.get("wave_ratios") or [])[-4:])
            lines.append(
                f"     Waves     {r['wave_count']} distribution wave(s)   {ratios}"
                f"   now {human(r.get('views_per_hour'))}/hr"
            )
        elif r.get("snapshot_readings", 0) < 3 and r.get("kind") != "competitor_ad":
            lines.append(
                f"     Waves     not measurable yet, {r.get('snapshot_readings',0)} reading(s) of 3"
            )
        proj = r.get("projection") or {}
        if proj.get("next_milestone"):
            lines.append(
                f"     Trajectory on pace for {human(proj['next_milestone'])} in about "
                f"{proj['hours_to_milestone']}h   (rough, {proj.get('basis','')})"
            )
        if r.get("is_jackpot"):
            lines.append("     ** JACKPOT: small account, abnormal numbers **")
        if r.get("kind") == "competitor_ad":
            lines.append(
                f"     Running   {r.get('days_running',0)} days since "
                f"{short_date(r.get('ad_start_date'))}  ·  {r.get('variation_count',0)} variations"
            )
            if r.get("cta_text"):
                lines.append(f"     CTA       {r['cta_text']}  ->  {(r.get('landing_page') or '')[:50]}")
        if r.get("hashtags"):
            lines.append("     Tags      " + " ".join(f"#{t}" for t in r["hashtags"][:6]))
        if r.get("reasons"):
            lines += ["", "     Why it is here:"]
            lines += [f"       - {reason}" for reason in r["reasons"]]
        lines += ["", "-" * 64, ""]

    if failures:
        lines.append("Missing from this radar: " + "; ".join(failures))
    return "\n".join(lines).strip()


def render_slack(date_str: str, rows: list[dict], limit: int = 8) -> str:
    """Tighter version for a phone. Same information, less of it."""
    if not rows:
        return f"*COMPETITOR VIRAL RADAR*  {date_str}\nNothing crossed the threshold today."
    lines = [f"*COMPETITOR VIRAL RADAR*  {date_str}", ""]
    for rank, r in enumerate(rows[:limit], start=1):
        kind = "ad" if r.get("kind") == "competitor_ad" else "ugc"
        head = (f"{ICON.get(r.get('status',''),'')} *{rank}. {r.get('competitor') or 'unattributed'}*"
                f"  {r.get('status','')}  ·  {r.get('radar_score',0):.0f}")
        detail = (f"{human(r.get('views'))} views · {human(r.get('views_per_day'))}/day"
                  f" · {age(r.get('age_hours'))} · {kind}")
        if r.get("kind") == "competitor_ad":
            detail += f" · {r.get('days_running',0)}d running · {r.get('variation_count',0)} vars"
        elif float(r.get("creator_lift") or 0) >= 2:
            detail += f" · {float(r['creator_lift']):.1f}x normal"
        lines += [head, f"@{r.get('creator','')} — {(r.get('title') or '')[:90]}", detail,
                  r.get("url", ""), ""]
    return "\n".join(lines).strip()
