from __future__ import annotations

import pytest

from ci.generators.originality import (
    check_batch_self_similarity, check_originality, longest_common_run, trigram_jaccard,
)
from ci.generators.quality_gate import check_hook
from ci.patterns.embed import HashingEmbedder, normalize_text

pytestmark = pytest.mark.unit

SOURCE = ["I probably shouldn't tell you this, but you don't need to memorize thousands of words."]
GOOD_HOOK = {
    "hook": "You understand every word and still freeze when someone asks you a question",
    "first_frame_visual": "cat mid-sentence, eyes wide",
    "cta": "Try a conversation",
}


def test_apostrophes_do_not_hide_a_copy():
    """The bug this test exists for: 'shouldn't' and 'shouldnt' normalizing
    differently made a near-verbatim copy read as original."""
    assert normalize_text("I shouldn't") == normalize_text("I shouldnt")
    assert normalize_text("you don't") == normalize_text("you dont")


def test_near_verbatim_copy_is_rejected(scoring):
    candidate = "I probably shouldnt tell you this but you dont need to memorize thousands of words"
    verdict = check_originality(candidate, SOURCE, scoring["originality"], embedder=HashingEmbedder())
    assert verdict.original is False
    assert verdict.reason()


def test_lifted_opening_phrase_is_rejected(scoring):
    candidate = "I probably shouldn't tell you this, but your English teacher was wrong"
    verdict = check_originality(candidate, SOURCE, scoring["originality"], embedder=HashingEmbedder())
    assert verdict.original is False
    assert verdict.failed_check == "longest_common_run"


def test_genuinely_original_hook_passes(scoring):
    candidate = "Nobody warned me that understanding English and speaking it are different skills"
    verdict = check_originality(candidate, SOURCE, scoring["originality"], embedder=HashingEmbedder())
    assert verdict.original is True


def test_empty_corpus_is_original(scoring):
    assert check_originality("anything at all here", [], scoring["originality"]).original is True


def test_batch_self_similarity_catches_five_rewrites_of_one_idea(scoring):
    batch = [
        "You freeze when you try to speak",
        "You freeze when you try to speak English",
        "Your accent is not the problem",
    ]
    flagged = dict(check_batch_self_similarity(batch, scoring["originality"]))
    assert 0 in flagged and 1 in flagged
    assert 2 not in flagged


def test_similarity_helpers():
    assert trigram_jaccard("a b c d", "a b c d") == pytest.approx(1.0)
    assert trigram_jaccard("a b c", "x y z") == 0.0
    assert longest_common_run("one two three four", "zero one two three") == 3


def _gate(hook, scoring, **kw):
    from ci.generators.originality import OriginalityVerdict
    defaults = dict(hook_score=72, product_relevance=80, saturation=25,
                    originality=OriginalityVerdict(original=True),
                    cat_passes_deletion_test=True)
    defaults.update(kw)
    return check_hook(hook=hook, cfg=scoring["quality_gate"],
                      forbidden_claims=["fluent in 7 days", "guaranteed fluency"], **defaults)


def test_good_hook_is_approved(scoring):
    assert _gate(GOOD_HOOK, scoring).approved is True


def test_virality_prediction_is_rejected(scoring):
    hook = {**GOOD_HOOK, "payoff": "This will go viral, trust me"}
    assert "unsafe or misleading claim" in _gate(hook, scoring).reasons


def test_forbidden_product_claim_is_rejected(scoring):
    hook = {**GOOD_HOOK, "payoff": "You will be fluent in 7 days"}
    assert "unsafe or misleading claim" in _gate(hook, scoring).reasons


def test_cat_as_decoration_is_rejected(scoring):
    assert "cat is decoration, not mechanism" in _gate(
        GOOD_HOOK, scoring, cat_passes_deletion_test=False).reasons


def test_saturated_pattern_is_rejected(scoring):
    assert "trend already saturated" in _gate(GOOD_HOOK, scoring, saturation=88).reasons


def test_hook_with_no_visual_is_rejected(scoring):
    hook = {"hook": GOOD_HOOK["hook"]}
    assert "no clear visual" in _gate(hook, scoring).reasons


def test_weak_score_is_rejected(scoring):
    assert "weak hook" in _gate(GOOD_HOOK, scoring, hook_score=30).reasons
