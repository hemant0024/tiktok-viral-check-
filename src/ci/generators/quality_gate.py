"""Quality gate. Spec sections 27 and 28.

Rejections are stored, never silently dropped, with the check that fired and its score.
That log is the only way the thresholds ever get tuned honestly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ci.generators.originality import OriginalityVerdict
from ci.patterns.embed import normalize_text, tokenize


@dataclass
class GateVerdict:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    detail: str = ""


def check_hook(
    hook: dict[str, Any],
    hook_score: float,
    product_relevance: float,
    saturation: float,
    originality: OriginalityVerdict,
    cat_passes_deletion_test: bool,
    cfg: dict[str, Any],
    forbidden_claims: list[str],
) -> GateVerdict:
    reasons: list[str] = []
    details: list[str] = []

    text = hook.get("hook", "") or ""
    blob = normalize_text(" ".join(str(hook.get(k, "")) for k in
                                   ("hook", "spoken_dialogue", "on_screen_text", "payoff", "cta")))

    if not originality.original:
        reasons.append("copied wording")
        details.append(originality.reason())

    if hook_score < float(cfg.get("min_hook_score", 55)):
        reasons.append("weak hook")
        details.append(f"hook_score {hook_score:.1f} below {cfg.get('min_hook_score')}")

    if product_relevance < float(cfg.get("min_product_relevance", 50)):
        reasons.append("low product relevance")
        details.append(f"product_relevance {product_relevance:.1f}")

    if saturation > float(cfg.get("max_saturation", 80)):
        reasons.append("trend already saturated")
        details.append(f"saturation {saturation:.1f}")

    words = tokenize(normalize_text(text))
    if len(words) < int(cfg.get("min_hook_words", 3)):
        reasons.append("too generic")
        details.append(f"hook is {len(words)} words")
    if len(words) > int(cfg.get("max_hook_words", 30)):
        reasons.append("hook too long for three seconds")
        details.append(f"hook is {len(words)} words")

    if not (hook.get("first_frame_visual") or hook.get("first_3_second_action")):
        reasons.append("no clear visual")

    # Spec section 28. No prediction claims, ever.
    for phrase in cfg.get("banned_phrases", []):
        if normalize_text(phrase) in blob:
            reasons.append("unsafe or misleading claim")
            details.append(f"banned phrase: {phrase}")
            break

    for claim in forbidden_claims or []:
        if normalize_text(claim) in blob:
            reasons.append("unsafe or misleading claim")
            details.append(f"forbidden product claim: {claim}")
            break

    if not cat_passes_deletion_test:
        reasons.append("cat is decoration, not mechanism")

    return GateVerdict(approved=not reasons, reasons=sorted(set(reasons)), detail="; ".join(details))
