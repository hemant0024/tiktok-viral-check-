"""Generation: adapt the mechanism, write hooks, give the cat a real job, score, gate."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ci.config import Settings, get_settings
from ci.generators.originality import check_batch_self_similarity, check_originality
from ci.generators.quality_gate import check_hook
from ci.llm.client import LlmClient
from ci.llm.prompts import load_prompt
from ci.logging import get_logger, log_event
from ci.models import Adaptation, CreativePattern
from ci.patterns.embed import Embedder
from ci.scoring.scores import hook_score as compute_hook_score
from ci.scoring.scores import opportunity_label

log = get_logger(__name__)


class Generator:
    def __init__(self, client: LlmClient, embedder: Embedder, settings: Settings | None = None) -> None:
        self.client = client
        self.embedder = embedder
        self.settings = settings or get_settings()
        self.scoring = self.settings.scoring
        self.p_adapt = load_prompt("adapt_to_product")
        self.p_hooks = load_prompt("generate_hooks")
        self.p_cat = load_prompt("generate_cat_execution")
        self.p_score = load_prompt("score_hooks")
        self._role_cursor = 0
        self._treatment_cursor = 0

    # Role rotation is enforced here, in Python, rather than asked for in a prompt.
    # Spec section 15 warns the cat must not be pasted onto everything, and a model
    # asked politely to vary will still drift to its favourite.
    def next_cat_role(self) -> str:
        roles = self.settings.cat_roles or ["cat reacts"]
        role = roles[self._role_cursor % len(roles)]
        self._role_cursor += 1
        return role

    def next_treatment(self) -> str:
        treatments = self.settings.product.get("mascot", {}).get("visual_treatments", ["2D flat animation"])
        t = treatments[self._treatment_cursor % len(treatments)]
        self._treatment_cursor += 1
        return t

    def _product_block(self) -> dict:
        return {
            "product": self.settings.product.get("product", {}),
            "market": self.settings.product.get("market", {}),
        }

    def generate_for_pattern(
        self,
        pattern: CreativePattern,
        trend: dict[str, Any],
        source_hooks: list[str],
        winners: list[dict],
        losers: list[dict],
        track: str = "proven",
    ) -> list[Adaptation]:
        today = datetime.now(timezone.utc).date().isoformat()
        gen_cfg = self.scoring.get("generation", {})
        gate_cfg = self.scoring.get("quality_gate", {})
        orig_cfg = self.scoring.get("originality", {})
        forbidden = self.settings.product.get("product", {}).get("forbidden_claims", [])
        saturation = float(trend.get("saturation_score", 0))

        pattern_block = {
            "name": pattern.name,
            "creative_mechanism": pattern.creative_mechanism,
            "hook_type": pattern.hook_type,
            "structure": pattern.structure,
            "emotion": pattern.emotion,
            "visual": pattern.visual,
        }

        adaptation = self.client.run_prompt(
            self.p_adapt, stage="generate_adapt",
            cache_content=f"{pattern.pattern_id}|{self.p_adapt.version}",
            pattern=pattern_block,
            product=self._product_block(),
            audience=self.settings.product.get("audience", {}),
        ).data

        hooks_per = int(gen_cfg.get("hooks_per_pattern", 5))
        raw = self.client.run_prompt(
            self.p_hooks, stage="generate_hooks",
            cache_content=f"{pattern.pattern_id}|{today}|{track}|{self.p_hooks.version}",
            hooks_per_pattern=hooks_per,
            pattern=pattern_block,
            adaptation=adaptation,
            product=self._product_block(),
            audience=self.settings.product.get("audience", {}),
            source_hooks=source_hooks[:15],
            winners=winners[:8] or "(no winners recorded yet)",
            losers=losers[:8] or "(no losers recorded yet)",
            market_country=self.settings.market_country,
            forbidden_claims=forbidden,
        ).data

        hooks = raw.get("hooks", [])[:hooks_per]
        texts = [h.get("hook", "") for h in hooks]
        self_flags = dict(check_batch_self_similarity(texts, orig_cfg))
        corpus_vecs = self.embedder.encode(source_hooks) if source_hooks else []

        out: list[Adaptation] = []
        for idx, hook in enumerate(hooks):
            role = self.next_cat_role()
            treatment = self.next_treatment()
            cat = self.client.run_prompt(
                self.p_cat, stage="generate_cat",
                cache_content=f"{pattern.pattern_id}|{idx}|{role}|{self.p_cat.version}|{hook.get('hook','')}",
                hook=hook, mechanism=pattern_block,
                mascot=self.settings.product.get("mascot", {}),
                cat_role=role, visual_treatment=treatment,
            ).data

            scores = self.client.run_prompt(
                self.p_score, stage="score_hooks",
                cache_content=f"{hook.get('hook','')}|{self.p_score.version}",
                hook=hook, product=self._product_block(),
                audience=self.settings.product.get("audience", {}),
                saturation_score=saturation,
            ).data

            total, breakdown = compute_hook_score(scores, self.scoring.get("hook_score", {}))

            originality = self_flags.get(idx)
            if originality is None:
                originality = check_originality(
                    hook.get("hook", ""), source_hooks, orig_cfg,
                    embedder=self.embedder, corpus_vecs=corpus_vecs,
                )

            verdict = check_hook(
                hook=hook, hook_score=total,
                product_relevance=float(scores.get("product_relevance", 0)),
                saturation=saturation, originality=originality,
                cat_passes_deletion_test=bool(cat.get("passes_deletion_test", True)),
                cfg=gate_cfg, forbidden_claims=forbidden,
            )

            out.append(Adaptation(
                adaptation_id=f"adp_{uuid.uuid4().hex[:12]}",
                pattern_id=pattern.pattern_id,
                date=today,
                hook=hook.get("hook", ""),
                first_frame_visual=hook.get("first_frame_visual", ""),
                first_3_second_action=hook.get("first_3_second_action", ""),
                spoken_dialogue=hook.get("spoken_dialogue", ""),
                on_screen_text=hook.get("on_screen_text", ""),
                creative_mechanism=hook.get("creative_mechanism", pattern.creative_mechanism),
                product_reveal=hook.get("product_reveal", ""),
                payoff=hook.get("payoff", ""),
                cta=hook.get("cta", ""),
                cat_role=cat.get("cat_role", role),
                cat_execution=cat.get("cat_execution", ""),
                visual_treatment=cat.get("visual_treatment", treatment),
                hook_score=total,
                score_breakdown=breakdown,
                strengths=scores.get("strengths", ""),
                weaknesses=scores.get("weaknesses", ""),
                risk=scores.get("risk", ""),
                recommended_test=scores.get("recommended_test", ""),
                opportunity_label=opportunity_label(total, gate_cfg),
                track=track,
                status="approved" if verdict.approved else "rejected",
                rejection_reasons=verdict.reasons,
                rejection_detail=verdict.detail,
                prompt_version=self.p_hooks.version,
            ))

        approved = sum(1 for a in out if a.status == "approved")
        log_event(log, logging.INFO, "generated for pattern",
                  pattern_id=pattern.pattern_id, hooks=len(out),
                  approved=approved, rejected=len(out) - approved)
        return out


def split_tracks(pattern_count: int, cfg: dict[str, Any], have_winners: bool) -> list[str]:
    """Spec section 21: about 70% proven, 30% experimental, once winners exist."""
    if not have_winners:
        return ["experimental"] * pattern_count
    proven_ratio = float(cfg.get("proven_ratio", 0.7))
    proven = int(round(pattern_count * proven_ratio))
    return ["proven"] * proven + ["experimental"] * (pattern_count - proven)
