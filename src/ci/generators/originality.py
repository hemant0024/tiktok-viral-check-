"""Originality check.

The spec says "never copy the source video's exact wording" and rejects "copied
wording", but neither is implementable without a real similarity measure. This is it.

Four checks. Three against the source hook corpus, one against the batch itself so we
never ship five near duplicates of each other.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ci.patterns.embed import Embedder, cosine, normalize_text, tokenize


@dataclass
class OriginalityVerdict:
    original: bool
    checks: dict[str, float] = field(default_factory=dict)
    matched_source: str = ""
    failed_check: str = ""

    def reason(self) -> str:
        if self.original:
            return ""
        return (
            f"copied wording ({self.failed_check}="
            f"{self.checks.get(self.failed_check, 0):.2f}) against: "
            f"{self.matched_source[:120]}"
        )


def trigrams(text: str) -> set[tuple[str, str, str]]:
    words = tokenize(normalize_text(text))
    return {tuple(words[i:i + 3]) for i in range(max(0, len(words) - 2))}


def trigram_jaccard(a: str, b: str) -> float:
    ta, tb = trigrams(a), trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def longest_common_run(a: str, b: str) -> int:
    """Longest run of consecutive shared words. Catches a lifted phrase that
    trigram overlap dilutes away inside a longer sentence."""
    wa, wb = tokenize(normalize_text(a)), tokenize(normalize_text(b))
    if not wa or not wb:
        return 0
    best = 0
    prev = [0] * (len(wb) + 1)
    for i in range(1, len(wa) + 1):
        current = [0] * (len(wb) + 1)
        for j in range(1, len(wb) + 1):
            if wa[i - 1] == wb[j - 1]:
                current[j] = prev[j - 1] + 1
                best = max(best, current[j])
        prev = current
    return best


def check_originality(
    candidate: str,
    corpus: list[str],
    cfg: dict,
    embedder: Embedder | None = None,
    candidate_vec: list[float] | None = None,
    corpus_vecs: list[list[float]] | None = None,
) -> OriginalityVerdict:
    max_jaccard = float(cfg.get("trigram_jaccard_max", 0.60))
    max_run = int(cfg.get("longest_common_run_max_words", 7))
    max_cosine = float(cfg.get("embedding_cosine_max", 0.93))

    worst = OriginalityVerdict(original=True, checks={"trigram_jaccard": 0.0,
                                                      "longest_common_run": 0.0,
                                                      "embedding_cosine": 0.0})
    if not corpus:
        return worst

    if embedder is not None and candidate_vec is None:
        candidate_vec = embedder.encode([candidate])[0]
    if embedder is not None and corpus_vecs is None:
        corpus_vecs = embedder.encode(corpus)

    for idx, source in enumerate(corpus):
        jac = trigram_jaccard(candidate, source)
        run = float(longest_common_run(candidate, source))
        cos = 0.0
        if candidate_vec is not None and corpus_vecs is not None and idx < len(corpus_vecs):
            cos = cosine(candidate_vec, corpus_vecs[idx])

        failed = ""
        if jac >= max_jaccard:
            failed = "trigram_jaccard"
        elif run >= max_run:
            failed = "longest_common_run"
        elif cos >= max_cosine:
            failed = "embedding_cosine"

        if failed:
            return OriginalityVerdict(
                original=False,
                checks={"trigram_jaccard": jac, "longest_common_run": run, "embedding_cosine": cos},
                matched_source=source,
                failed_check=failed,
            )
        if jac > worst.checks["trigram_jaccard"]:
            worst.checks = {"trigram_jaccard": jac, "longest_common_run": run, "embedding_cosine": cos}
            worst.matched_source = source
    return worst


def check_batch_self_similarity(hooks: list[str], cfg: dict) -> list[tuple[int, OriginalityVerdict]]:
    """Check each hook against the others in its own batch."""
    out = []
    for i, hook in enumerate(hooks):
        others = [h for j, h in enumerate(hooks) if j != i]
        verdict = check_originality(hook, others, cfg)
        if not verdict.original:
            out.append((i, verdict))
    return out
