"""Two actors, because the cheap one does not work on a free Apify plan.

Verified 2026-09-11: apidojo/tiktok-scraper costs $0.0003 per video against
clockworks' $0.0069, about 23x cheaper, and the config already pointed at it.
On the FREE plan it answers every call with {"noResults": true}, search and
direct URL alike, so it is effectively paid-only.

Without a fallback that means the configured system collects nothing, every day,
and correctly but uselessly reports all 57 keywords as NOT CHECKED.
"""
from __future__ import annotations

import pytest

from ci.collectors.apify import ApifyThrottled
from ci.collectors.competitor_ugc import CompetitorUgcCollector, build_actor_input

pytestmark = pytest.mark.unit


def test_the_two_actors_want_different_field_names(settings):
    """The reason this cannot be a one-line actor swap."""
    tk = settings.sources["tiktok"]
    cheap = build_actor_input(tk["actor_inputs"]["apidojo/tiktok-scraper"]["input"],
                              keywords=["praktika"], max_items=15, country="US")
    works = build_actor_input(tk["actor_inputs"]["clockworks/free-tiktok-scraper"]["input"],
                              keywords=["praktika"], max_items=15, country="US")

    assert cheap["keywords"] == ["praktika"] and cheap["maxItems"] == 15
    assert works["searchQueries"] == ["praktika"] and works["resultsPerPage"] == 15
    assert set(cheap) & set(works) == set(), "they share no field names at all"


def test_placeholders_are_all_substituted(settings):
    tk = settings.sources["tiktok"]
    for name, spec in tk["actor_inputs"].items():
        for shape in ("input", "by_url"):
            built = build_actor_input(spec.get(shape, {}), keywords=["k"],
                                      urls=["https://x/1"], max_items=9, country="US")
            leftover = [k for k, v in built.items()
                        if isinstance(v, str) and v.startswith("$")]
            assert not leftover, f"{name}.{shape} left {leftover} unsubstituted"


def test_it_falls_back_when_the_cheap_actor_throttles(settings, monkeypatch):
    c = CompetitorUgcCollector(settings)
    calls: list[str] = []

    class FakeClient:
        consecutive_empty = 0

        def run_actor(self, actor, run_input, max_items=None):
            calls.append(actor)
            if actor == "apidojo/tiktok-scraper":
                raise ApifyThrottled("noResults sentinel")
            return [{"id": "1"}]

    got = c._search(FakeClient(), ["praktika"], 15, {})
    assert calls == ["apidojo/tiktok-scraper", "clockworks/free-tiktok-scraper"]
    assert got == [{"id": "1"}]
    assert c.fell_back is True
    assert c.actor_used == "clockworks/free-tiktok-scraper"


def test_it_records_which_actor_ran(settings):
    """A run can silently cost 23x more than expected. That belongs on the record."""
    c = CompetitorUgcCollector(settings)

    class FakeClient:
        consecutive_empty = 0

        def run_actor(self, actor, run_input, max_items=None):
            return [{"id": "1"}]

    c._search(FakeClient(), ["praktika"], 15, {})
    assert c.actor_used == "apidojo/tiktok-scraper"
    assert c.fell_back is False


def test_it_does_not_fall_back_twice(settings):
    """One fallback per run. Ping-ponging between two throttled actors would
    burn the rate limit on both and still collect nothing."""
    c = CompetitorUgcCollector(settings)

    class FakeClient:
        consecutive_empty = 0

        def run_actor(self, actor, run_input, max_items=None):
            raise ApifyThrottled("everything is throttled")

    with pytest.raises(ApifyThrottled):
        c._search(FakeClient(), ["praktika"], 15, {})
    assert c.fell_back is True

    with pytest.raises(ApifyThrottled):
        c._search(FakeClient(), ["loora"], 15, {})


def test_per_pass_sorting_still_overrides_the_template(settings):
    """The two-pass design, proven vs breakout, has to survive the templating."""
    c = CompetitorUgcCollector(settings)
    seen: dict = {}

    class FakeClient:
        consecutive_empty = 0

        def run_actor(self, actor, run_input, max_items=None):
            seen.update(run_input)
            return []

    c._search(FakeClient(), ["praktika"], 25, {"sort_type": "MOST_LIKED"})
    assert seen["sortType"] == "MOST_LIKED"


def test_the_cheap_actor_is_the_primary(settings):
    """If these ever swap, the bill goes up 23x without anything failing."""
    tk = settings.sources["tiktok"]
    primary = tk["actor_inputs"][tk["actor"]]["cost_per_video_usd"]
    fallback = tk["actor_inputs"][tk["fallback_actor"]]["cost_per_video_usd"]
    assert primary < fallback, "the expensive actor is configured as primary"


def test_search_and_poll_are_priced_separately(settings):
    """A keyword search pays for the sorting, date and country add-ons. A direct
    URL poll pays for none of them. Using one number for both overstated the
    watch bill by about 2.3x, which is how I quoted $773/month instead of $436."""
    tk = settings.sources["tiktok"]
    works = tk["actor_inputs"]["clockworks/free-tiktok-scraper"]
    assert works["cost_per_video_by_url_usd"] < works["cost_per_video_usd"]

    cheap = tk["actor_inputs"]["apidojo/tiktok-scraper"]
    assert cheap["cost_per_video_usd"] == cheap["cost_per_video_by_url_usd"], \
        "apidojo is flat priced with no add-ons, that is the whole reason it is cheaper"


def test_the_by_url_shape_buys_no_add_ons(settings):
    """If a filter creeps into the poll shape the watch bill more than doubles
    and nothing fails to warn you."""
    tk = settings.sources["tiktok"]
    poll = tk["actor_inputs"]["clockworks/free-tiktok-scraper"]["by_url"]
    for charged in ("videoSearchSorting", "videoSearchDateFilter", "proxyCountryCode"):
        assert charged not in poll, f"{charged} is a charged add-on and is not needed to poll a known URL"
