"""Daily report.

Spec section 17 is the FULL output (top 10 patterns, top 20 hooks, top 5 ads) and it
is stored in DAILY_REPORTS. Spec section 18 is the concise message that gets sent, one
phone screen per concept. They are not in conflict once you split stored from sent.

The concise message is rendered in Python from the scored data, so it is deterministic
and testable. The model is used only to sharpen the "why today" line.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

SAT_BANDS = [(35, "Low"), (60, "Medium"), (80, "High"), (101, "Exhausted")]


def saturation_band(score: float) -> str:
    for threshold, label in SAT_BANDS:
        if score < threshold:
            return label
    return "Exhausted"


def stars(label: str) -> str:
    return {
        "High opportunity": "* * * * *  PRODUCE",
        "Medium opportunity": "* * * *    WORTH TESTING",
        "Experimental": "* * *      EXPERIMENT",
        "Low opportunity": "* *        SKIP",
    }.get(label, "* *        SKIP")


def format_date(date_str: str, fmt: str = "%B %-d, %Y") -> str:
    try:
        return datetime.fromisoformat(date_str).strftime(fmt)
    except (ValueError, TypeError):
        return date_str


def build_concepts(trends: list[dict], patterns_by_id: dict[str, dict],
                   adaptations: list[dict], limit: int) -> list[dict]:
    """Pair each top trend with its best approved hook."""
    approved = [a for a in adaptations if a.get("status") == "approved"]
    by_pattern: dict[str, list[dict]] = {}
    for a in approved:
        by_pattern.setdefault(a.get("pattern_id", ""), []).append(a)
    for hooks in by_pattern.values():
        hooks.sort(key=lambda h: h.get("hook_score", 0), reverse=True)

    concepts = []
    ranked = sorted(trends, key=lambda t: t.get("opportunity_score", 0), reverse=True)
    for trend in ranked:
        pid = trend.get("pattern_id", "")
        hooks = by_pattern.get(pid, [])
        if not hooks:
            continue
        pattern = patterns_by_id.get(pid, {})
        best = hooks[0]
        concepts.append({
            "pattern_id": pid,
            "name": (pattern.get("name") or pattern.get("creative_mechanism") or "Pattern").upper(),
            "mechanism": pattern.get("creative_mechanism", ""),
            "opportunity_score": trend.get("opportunity_score", 0),
            "momentum_score": trend.get("momentum_score", 0),
            "saturation_score": trend.get("saturation_score", 0),
            "saturation_band": saturation_band(float(trend.get("saturation_score", 0))),
            "cross_category": trend.get("distinct_categories", 1),
            "lifecycle_label": trend.get("lifecycle_label", ""),
            "opportunity_label": best.get("opportunity_label", "Experimental"),
            "is_breakout": trend.get("is_breakout", False),
            "velocity_confidence": trend.get("velocity_confidence", "low"),
            "why_it_matters": trend.get("why_it_matters", ""),
            "hook": best.get("hook", ""),
            "cat_execution": best.get("cat_execution", ""),
            "cat_role": best.get("cat_role", ""),
            "hook_score": best.get("hook_score", 0),
            "risk": best.get("risk", ""),
            "recommended_test": best.get("recommended_test", ""),
            "all_hooks": hooks,
        })
        if len(concepts) >= limit:
            break
    return concepts


def render_concise(date_str: str, concepts: list[dict], failures: list[str],
                   date_fmt: str = "%B %-d, %Y") -> str:
    """Spec section 18. One block per concept, each fitting one phone screen."""
    lines = ["DAILY CREATIVE RADAR", format_date(date_str, date_fmt), ""]
    for rank, c in enumerate(concepts, start=1):
        flag = "  [BREAKOUT]" if c.get("is_breakout") else ""
        lines += [
            f"#{rank} {c['name']}{flag}",
            "",
            f"Opportunity: {c['opportunity_score']:.0f} | Momentum: {c['momentum_score']:.0f} | "
            f"Saturation: {c['saturation_band']}",
            f"Cross-category: {c['cross_category']}",
            "",
            "Mechanism:",
            c["mechanism"] or "-",
            "",
            "Hook:",
            f'"{c["hook"]}"',
            "",
            "Cat execution:",
            c["cat_execution"] or "-",
            "",
            stars(c["opportunity_label"]),
        ]
        if c.get("why_it_matters"):
            lines.append(c["why_it_matters"])
        if c.get("velocity_confidence") == "low":
            lines.append("(early signal, one snapshot only)")
        lines += ["", "-" * 32, ""]

    if failures:
        lines.append("Missing from this report: " + "; ".join(failures))
    return "\n".join(lines).strip()


def build_full_report(concepts: list[dict], adaptations: list[dict], cfg: dict[str, Any]) -> dict:
    """Spec section 17. Stored in full, not sent."""
    gen = cfg.get("generation", {})
    approved = sorted(
        [a for a in adaptations if a.get("status") == "approved"],
        key=lambda a: a.get("hook_score", 0), reverse=True,
    )
    top_patterns = [
        {
            "rank": i,
            "trend": c["name"],
            "opportunity_score": c["opportunity_score"],
            "momentum_score": c["momentum_score"],
            "saturation_score": c["saturation_score"],
            "lifecycle": c["lifecycle_label"],
            "categories": c["cross_category"],
            "creative_mechanism": c["mechanism"],
            "why_it_matters": c["why_it_matters"],
        }
        for i, c in enumerate(concepts[: int(gen.get("report_top_patterns", 10))], start=1)
    ]
    top_hooks = [
        {
            "hook": a.get("hook", ""),
            "hook_type": a.get("creative_mechanism", ""),
            "creative_mechanism": a.get("creative_mechanism", ""),
            "product_adaptation": a.get("product_reveal", ""),
            "cat_version": a.get("cat_execution", ""),
            "hook_score": a.get("hook_score", 0),
            "recommended_visual": a.get("first_frame_visual", ""),
        }
        for a in approved[: int(gen.get("report_top_hooks", 20))]
    ]
    top_ads = [
        {
            "concept_name": c["name"].title(),
            "hook": c["hook"],
            "visual": (c["all_hooks"][0].get("first_frame_visual", "") if c["all_hooks"] else ""),
            "script": (c["all_hooks"][0].get("spoken_dialogue", "") if c["all_hooks"] else ""),
            "product_reveal": (c["all_hooks"][0].get("product_reveal", "") if c["all_hooks"] else ""),
            "cat_role": c["cat_role"],
            "cta": (c["all_hooks"][0].get("cta", "") if c["all_hooks"] else ""),
            "why_we_should_test_it": c["why_it_matters"] or c["mechanism"],
            "expected_risk": c["risk"],
            "priority": c["opportunity_label"],
        }
        for c in concepts[: int(gen.get("report_top_ads", 5))]
    ]
    return {"top_patterns": top_patterns, "top_hooks": top_hooks, "top_ads": top_ads}
