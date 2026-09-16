"""Cross day pattern matching.

Without this, CREATIVE_PATTERNS gets rebuilt every morning and momentum, saturation,
trend age and cross category all become impossible. Patterns must be MATCHED, not
recreated.

Three bands, cheap first:
  >= auto_match      attach to the existing pattern, no LLM call
  >= adjudicate      ask the strong model, comparing against the nearest few
  <  adjudicate      genuinely new pattern
Every decision is logged with its similarity and decider so a bad merge is auditable.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ci.llm.client import LlmClient
from ci.llm.prompts import load_prompt
from ci.logging import get_logger, log_event
from ci.models import CreativePattern, PatternMatchDecision
from ci.patterns.embed import Embedder, cosine

log = get_logger(__name__)


def canonical_text(dna: dict[str, Any]) -> str:
    return " | ".join(
        str(dna.get(k, "") or "")
        for k in ("creative_mechanism", "hook_type", "structure", "emotion")
    ).strip(" |")


def pattern_id_for(text: str) -> str:
    return "pat_" + hashlib.sha256(text.encode()).hexdigest()[:12]


class PatternMatcher:
    def __init__(self, embedder: Embedder, client: LlmClient | None = None,
                 cfg: dict[str, Any] | None = None) -> None:
        self.embedder = embedder
        self.client = client
        self.cfg = cfg or {}
        self.auto = float(self.cfg.get("auto_match_similarity", 0.86))
        self.adjudicate = float(self.cfg.get("adjudicate_similarity", 0.72))
        self.max_to_llm = int(self.cfg.get("max_candidates_to_llm", 3))
        self.decisions: list[PatternMatchDecision] = []

    def _rank(self, vec: list[float], existing: list[CreativePattern]) -> list[tuple[float, CreativePattern]]:
        scored = [(cosine(vec, p.embedding), p) for p in existing if p.embedding]
        return sorted(scored, key=lambda pair: pair[0], reverse=True)

    def _log_decision(self, text: str, matched: str | None, sim: float,
                      runner: tuple[float, CreativePattern] | None, decider: str, why: str) -> None:
        self.decisions.append(
            PatternMatchDecision(
                decision_id=str(uuid.uuid4()),
                date=datetime.now(timezone.utc).date().isoformat(),
                candidate_text=text[:500],
                matched_pattern_id=matched,
                similarity=round(sim, 4),
                runner_up_pattern_id=runner[1].pattern_id if runner else None,
                runner_up_similarity=round(runner[0], 4) if runner else 0.0,
                decider=decider,
                why=why[:400],
            )
        )

    def match(self, dna: dict[str, Any], existing: list[CreativePattern]) -> tuple[CreativePattern, bool]:
        """Returns (pattern, is_new)."""
        text = canonical_text(dna)
        vec = self.embedder.encode([text])[0]
        ranked = self._rank(vec, existing)
        best = ranked[0] if ranked else None
        runner = ranked[1] if len(ranked) > 1 else None

        if best and best[0] >= self.auto:
            self._log_decision(text, best[1].pattern_id, best[0], runner, "vector", "above auto-match threshold")
            return best[1], False

        if best and best[0] >= self.adjudicate and self.client is not None:
            candidates = ranked[: self.max_to_llm]
            payload = [
                {"pattern_id": p.pattern_id, "name": p.name,
                 "creative_mechanism": p.creative_mechanism,
                 "structure": p.structure, "similarity": round(sim, 3)}
                for sim, p in candidates
            ]
            try:
                verdict = self.client.run_prompt(
                    load_prompt("cluster_patterns"), stage="patterns_cluster",
                    cache_content=text + "|" + ",".join(p["pattern_id"] for p in payload),
                    candidate=text, existing=payload,
                ).data
                if verdict.get("match") and verdict.get("pattern_id"):
                    for sim, pattern in candidates:
                        if pattern.pattern_id == verdict["pattern_id"]:
                            self._log_decision(text, pattern.pattern_id, sim, runner, "llm",
                                               verdict.get("why", ""))
                            return pattern, False
                self._log_decision(text, None, best[0], runner, "llm", verdict.get("why", "no match"))
            except Exception as exc:  # noqa: BLE001 - fall back to a new pattern
                log_event(log, logging.WARNING, "pattern adjudication failed", error=str(exc))
                self._log_decision(text, None, best[0], runner, "llm", f"adjudication failed: {exc}")

        elif best:
            self._log_decision(text, None, best[0], runner, "new", "below adjudication threshold")
        else:
            self._log_decision(text, None, 0.0, None, "new", "no existing patterns")

        now = datetime.now(timezone.utc).date().isoformat()
        pattern = CreativePattern(
            pattern_id=pattern_id_for(text),
            name=str(dna.get("creative_mechanism", "Unnamed pattern"))[:120],
            creative_mechanism=str(dna.get("creative_mechanism", "")),
            hook_type=dna.get("hook_type", []) or [],
            structure=str(dna.get("structure", "")),
            emotion=str(dna.get("emotion", "")),
            visual=str(dna.get("visual", "")),
            transferability=str(dna.get("transferability", "")),
            canonical_text=text,
            embedding=vec,
            first_seen=now,
            last_seen=now,
        )
        return pattern, True


def attach_observation(pattern: CreativePattern, content: dict[str, Any],
                       hook_text: str, category: str) -> CreativePattern:
    today = datetime.now(timezone.utc).date().isoformat()
    pattern.last_seen = today
    cid = content.get("content_id", "")
    if cid and cid not in pattern.example_content_ids:
        pattern.example_content_ids = (pattern.example_content_ids + [cid])[-40:]
    if hook_text and hook_text not in pattern.example_hooks:
        pattern.example_hooks = (pattern.example_hooks + [hook_text])[-40:]
    if category and category not in pattern.categories:
        pattern.categories = pattern.categories + [category]
    return pattern
