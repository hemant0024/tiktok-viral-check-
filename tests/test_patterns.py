from __future__ import annotations

import pytest

from ci.llm.client import LlmClient
from ci.llm.providers.fake import FakeProvider
from ci.patterns.embed import HashingEmbedder, cosine
from ci.patterns.match import PatternMatcher, attach_observation, canonical_text

pytestmark = pytest.mark.unit

INSIDER = {
    "creative_mechanism": "Perceived insider information",
    "hook_type": ["Confession", "Secret"],
    "structure": "Secret to reveal to demonstration",
    "emotion": "Curiosity",
}
TRANSFORM = {
    "creative_mechanism": "Before and after transformation",
    "hook_type": ["Transformation"],
    "structure": "State A to State B",
    "emotion": "Aspiration",
}


def matcher(scoring, client=None):
    return PatternMatcher(HashingEmbedder(), client, scoring["clustering"])


def test_first_sighting_creates_a_new_pattern(scoring):
    pattern, is_new = matcher(scoring).match(INSIDER, [])
    assert is_new is True
    assert pattern.pattern_id.startswith("pat_")
    assert pattern.embedding


def test_same_pattern_tomorrow_matches_rather_than_recreating(scoring):
    m = matcher(scoring)
    first, _ = m.match(INSIDER, [])
    second, is_new = m.match(dict(INSIDER), [first])
    assert is_new is False
    assert second.pattern_id == first.pattern_id


def test_a_different_mechanism_is_a_new_pattern(scoring):
    m = matcher(scoring)
    first, _ = m.match(INSIDER, [])
    other, is_new = m.match(TRANSFORM, [first])
    assert is_new is True
    assert other.pattern_id != first.pattern_id


def test_every_decision_is_logged_for_audit(scoring):
    m = matcher(scoring)
    first, _ = m.match(INSIDER, [])
    m.match(dict(INSIDER), [first])
    assert len(m.decisions) == 2
    assert {d.decider for d in m.decisions} == {"new", "vector"}
    assert m.decisions[1].similarity > scoring["clustering"]["auto_match_similarity"]


def test_ambiguous_band_asks_the_model(scoring, settings):
    """Between the two thresholds, a strong model adjudicates rather than guessing."""
    cfg = {**scoring["clustering"], "auto_match_similarity": 0.99, "adjudicate_similarity": 0.01}
    client = LlmClient(settings, provider=FakeProvider())
    m = PatternMatcher(HashingEmbedder(), client, cfg)
    first, _ = m.match(INSIDER, [])
    m.match(TRANSFORM, [first])
    assert m.decisions[-1].decider == "llm"


def test_adjudication_failure_falls_back_to_a_new_pattern(scoring, settings):
    class Broken(FakeProvider):
        def complete(self, *a, **kw):
            raise RuntimeError("provider down")

    cfg = {**scoring["clustering"], "auto_match_similarity": 0.99, "adjudicate_similarity": 0.01}
    client = LlmClient(settings, provider=Broken())
    client.limits = {**client.limits, "max_retries": 1, "retry_backoff_seconds": 0}
    m = PatternMatcher(HashingEmbedder(), client, cfg)
    first, _ = m.match(INSIDER, [])
    pattern, is_new = m.match(TRANSFORM, [first])
    assert is_new is True
    assert "failed" in m.decisions[-1].why


def test_observations_accumulate_without_duplicating(scoring):
    pattern, _ = matcher(scoring).match(INSIDER, [])
    content = {"content_id": "tiktok:1"}
    attach_observation(pattern, content, "hook one", "dating")
    attach_observation(pattern, content, "hook one", "dating")
    attach_observation(pattern, {"content_id": "tiktok:2"}, "hook two", "finance")
    assert pattern.example_content_ids == ["tiktok:1", "tiktok:2"]
    assert pattern.example_hooks == ["hook one", "hook two"]
    assert pattern.categories == ["dating", "finance"]


def test_canonical_text_is_stable():
    assert canonical_text(INSIDER) == canonical_text(dict(INSIDER))


def test_embeddings_are_normalized_and_comparable():
    e = HashingEmbedder()
    a, b = e.encode(["cat teaches english", "cat teaches english"])
    c = e.encode(["completely unrelated financial advice"])[0]
    assert cosine(a, b) == pytest.approx(1.0, abs=1e-6)
    assert cosine(a, c) < 0.5
