"""The local dashboard.

The part that matters most is the config editor. These YAML files carry the
reasoning behind every threshold, and that reasoning is worth more than the
numbers: it records which choices were tested against real data and why. A
parse-and-rewrite would delete all of it in one round trip.
"""
from __future__ import annotations

import shutil

import pytest
import yaml

from ci.dashboard import api
from ci.dashboard.yaml_edit import YamlEditError, apply, find_line, set_value

pytestmark = pytest.mark.unit


@pytest.fixture
def cfg(tmp_path):
    src = "\n".join([
        "# top comment that must survive",
        "radar:",
        "  # why the feed is capped at all",
        "  feed:",
        "    max_rows: 25          # a list nobody finishes is a list nobody reads",
        "    min_score_to_show: 30",
        "    tiers_to_show: [\"EXPLODING\", \"BREAKING OUT\"]",
        "  weights:",
        "    waves: 0.22           # the strongest tell",
        "    velocity: 0.05",
        "takeoff:",
        "  # views AND age, never either alone",
        "  tiers:",
        "    - {name: \"EXPLODING\", min_views: 200000, max_age_hours: 24}",
        "    - {name: \"BREAKING OUT\", min_views: 50000, max_age_hours: 24}",
        "  max_candidate_age_hours: 72",
        "",
    ])
    p = tmp_path / "scoring.yaml"
    p.write_text(src)
    return p


# --------------------------------------------------------------------------- #
# the comments are the point
# --------------------------------------------------------------------------- #
def test_editing_a_value_changes_exactly_one_line(cfg):
    before = cfg.read_text().splitlines()
    after = set_value(cfg, ["radar", "feed", "min_score_to_show"], 42).splitlines()
    differing = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(differing) == 1
    assert "min_score_to_show: 42" in after[differing[0]]


def test_every_comment_survives(cfg):
    before = cfg.read_text()
    after = set_value(cfg, ["radar", "weights", "waves"], 0.3)
    for comment in ("# top comment that must survive",
                    "# why the feed is capped at all",
                    "# a list nobody finishes is a list nobody reads",
                    "# views AND age, never either alone"):
        assert comment in after, f"lost: {comment}"
    assert before.count("#") == after.count("#")


def test_a_trailing_comment_stays_on_its_line(cfg):
    after = set_value(cfg, ["radar", "feed", "max_rows"], 40)
    line = next(l for l in after.splitlines() if "max_rows" in l)
    assert "40" in line
    assert "a list nobody finishes" in line, "the explanation was dropped"


def test_the_weight_comment_survives_a_weight_change(cfg):
    after = set_value(cfg, ["radar", "weights", "waves"], 0.4)
    line = next(l for l in after.splitlines() if "waves:" in l)
    assert "0.4" in line and "the strongest tell" in line


# --------------------------------------------------------------------------- #
# finding the right key
# --------------------------------------------------------------------------- #
def test_it_follows_indentation_rather_than_matching_text(cfg):
    """`weights` and `feed` both sit under `radar`, and a plain text search for
    a leaf key would find whichever appeared first in the file."""
    lines = cfg.read_text().splitlines()
    n = find_line(lines, ["radar", "weights", "velocity"])
    assert "velocity" in lines[n]


def test_a_missing_key_is_refused_by_name(cfg):
    with pytest.raises(YamlEditError, match="radar.feed.nonsense"):
        set_value(cfg, ["radar", "feed", "nonsense"], 1)


def test_a_list_value_round_trips(cfg):
    after = set_value(cfg, ["radar", "feed", "tiers_to_show"], ["INTERESTING"])
    assert yaml.safe_load(after)["radar"]["feed"]["tiers_to_show"] == ["INTERESTING"]


def test_the_result_still_parses_and_keeps_every_other_value(cfg):
    before = yaml.safe_load(cfg.read_text())
    after = yaml.safe_load(set_value(cfg, ["radar", "feed", "max_rows"], 11))
    before["radar"]["feed"]["max_rows"] = 11
    assert after == before, "something other than the edited key changed"


def test_several_edits_apply_together(cfg):
    out = apply(cfg, {"radar.feed.max_rows": 12, "radar.weights.velocity": 0.09})
    assert out["keys"] == 2
    data = yaml.safe_load(cfg.read_text())
    assert data["radar"]["feed"]["max_rows"] == 12
    assert data["radar"]["weights"]["velocity"] == 0.09
    assert "# top comment that must survive" in cfg.read_text()


# --------------------------------------------------------------------------- #
# the API
# --------------------------------------------------------------------------- #
def _seed(repo):
    repo.upsert("RADAR", [
        {"content_id": "a", "url": "https://tiktok.com/@x/video/a", "title": "praktika lesson",
         "creator": "small", "creator_followers": 500, "competitor": "Praktika AI",
         "views": 56000, "shares": 1200, "share_rate": 0.021, "save_rate": 0.004,
         "age_hours": 16, "radar_score": 88.0, "status": "EARLY SIGNAL",
         "takeoff_tier": "BREAKING OUT", "is_jackpot": True, "date": "2026-09-11",
         "kind": "organic_ugc"},
        {"content_id": "b", "url": "https://tiktok.com/@y/video/b", "title": "loora review",
         "creator": "big", "creator_followers": 400000, "competitor": "Loora AI",
         "views": 900, "shares": 1, "share_rate": 0.001, "save_rate": 0.0,
         "age_hours": 3, "radar_score": 31.0, "status": "EARLY SIGNAL",
         "takeoff_tier": "WATCH", "is_jackpot": False, "date": "2026-09-11",
         "kind": "organic_ugc"},
    ])


def test_filtering_by_tier(repo, settings):
    _seed(repo)
    out = api.rows(settings, repo, tiers=["BREAKING OUT"])
    assert out["matched"] == 1 and out["rows"][0]["content_id"] == "a"
    assert out["total"] == 2, "total must report everything stored, not the filtered count"


def test_filters_combine(repo, settings):
    _seed(repo)
    assert api.rows(settings, repo, min_score=50, max_followers=1000)["matched"] == 1
    assert api.rows(settings, repo, min_score=95)["matched"] == 0


def test_jackpot_and_search(repo, settings):
    _seed(repo)
    assert api.rows(settings, repo, jackpot_only=True)["matched"] == 1
    assert api.rows(settings, repo, q="loora")["matched"] == 1
    assert api.rows(settings, repo, q="nothing here")["matched"] == 0


def test_facets_only_offer_values_that_exist(repo, settings):
    _seed(repo)
    f = api.facets(settings, repo)
    assert f["competitors"] == ["Loora AI", "Praktika AI"]
    assert set(f["tiers"]) == {"BREAKING OUT", "WATCH"}


def test_rows_ignore_the_feed_caps(repo, settings):
    """The morning list is capped and tier-filtered. The dashboard is where you
    go to see what those caps hid, so it must read storage, not the feed."""
    settings.scoring["radar"]["feed"]["tiers_to_show"] = ["EXPLODING"]
    settings.scoring["radar"]["feed"]["min_score_to_show"] = 99
    _seed(repo)
    assert api.rows(settings, repo)["matched"] == 2


# --------------------------------------------------------------------------- #
# preview
# --------------------------------------------------------------------------- #
def test_preview_shows_what_a_threshold_change_would_do(repo, settings):
    """The question the dials cannot answer: move the bar and how many videos
    actually change tier? On real rows, not a guess."""
    _seed(repo)
    out = api.preview({"tier.breaking_views": 10000}, settings, repo)
    assert out["scored"] == 2
    assert out["moved_total"] >= 0
    assert "tiers" in out["before"] and "tiers" in out["after"]


def test_preview_changes_nothing_on_disk(repo, settings):
    from ci.config import CONFIG_DIR
    before = (CONFIG_DIR / "scoring.yaml").read_text()
    _seed(repo)
    api.preview({"tier.breaking_views": 1}, settings, repo)
    assert (CONFIG_DIR / "scoring.yaml").read_text() == before


def test_a_raised_bar_demotes_a_video(repo, settings):
    _seed(repo)
    out = api.preview({"tier.breaking_views": 500000}, settings, repo)
    moved = {m["creator"]: m["to"] for m in out["moved"]}
    assert moved.get("small") in {"INTERESTING", "WATCH", "DAY TWO"}


# --------------------------------------------------------------------------- #
# saving
# --------------------------------------------------------------------------- #
def test_only_allowlisted_fields_can_be_written():
    """An arbitrary dotted path from a request must never reach the YAML editor."""
    with pytest.raises(ValueError, match="not an editable field"):
        api.save({"radar.weights.anything": 1})


def test_values_are_bounds_checked():
    with pytest.raises(ValueError, match="at most"):
        api.save({"feed.min_score_to_show": 5000})
    with pytest.raises(ValueError, match="at least"):
        api.save({"feed.max_rows": -3})


def test_every_editable_field_points_at_a_real_config_key(settings):
    """A typo in a path would fail silently at read time, showing a blank control
    that writes to nothing."""
    blobs = {"scoring.yaml": settings.scoring, "sources.yaml": settings.sources}
    for key, spec in api.EDITABLE.items():
        value = api._dig(blobs[spec["file"]], spec["path"])
        assert value is not None, f"{key} -> {spec['file']}:{spec['path']} does not resolve"


def test_the_cost_readout_reflects_the_dials(settings):
    c = api.cost(settings)
    assert c["pulled_per_day"] == c["keywords"] * c["per_keyword"]
    assert len(c["actors"]) >= 2
    assert c["actors"][0]["per_day"] <= c["actors"][-1]["per_day"], "actors are not cheapest first"
    for a in c["actors"]:
        assert a["per_day"] == pytest.approx(a["sweep"] + a["recheck"], abs=0.02)


# --------------------------------------------------------------------------- #
# list items, and not writing half an edit
# --------------------------------------------------------------------------- #
def test_a_flow_style_list_item_keeps_its_column_alignment(cfg):
    """The tier table is written as aligned inline maps and reads as a table.
    An edit that collapses the spacing makes it unreadable."""
    after = set_value(cfg, ["takeoff", "tiers", "1", "min_views"], 40000)
    line = next(l for l in after.splitlines()
                if "BREAKING OUT" in l and l.lstrip().startswith("- {"))
    assert "min_views: 40000" in line
    assert "max_age_hours: 24}" in line
    assert yaml.safe_load(after)["takeoff"]["tiers"][1]["min_views"] == 40000
    assert yaml.safe_load(after)["takeoff"]["tiers"][0]["min_views"] == 200000, \
        "editing item 1 changed item 0"


def test_a_block_style_list_item_is_found_on_a_later_line(tmp_path):
    """The collection passes are block style, so the key sits several lines
    below the `-`. Looking only at the `-` line misses it entirely."""
    p = tmp_path / "sources.yaml"
    p.write_text("\n".join([
        "competitor_ugc:",
        "  passes:",
        "    - name: today",
        "      sort_type: \"DATE_POSTED\"",
        "      max_items_per_keyword: 20    # how deep to go",
        "    - name: this_week",
        "      max_items_per_keyword: 40",
        "",
    ]))
    after = set_value(p, ["competitor_ugc", "passes", "0", "max_items_per_keyword"], 30)
    data = yaml.safe_load(after)
    assert data["competitor_ugc"]["passes"][0]["max_items_per_keyword"] == 30
    assert data["competitor_ugc"]["passes"][1]["max_items_per_keyword"] == 40, \
        "the edit leaked into the next list item"
    assert "# how deep to go" in after


def test_a_failed_edit_leaves_the_file_untouched(cfg):
    """An edit can be rejected half way through a batch. If the earlier ones are
    already on disk the config is left in a state nobody chose, and the 6am run
    is the thing that finds out."""
    before = cfg.read_text()
    with pytest.raises(YamlEditError):
        apply(cfg, {"radar.feed.max_rows": 40, "radar.feed.does_not_exist": 1})
    assert cfg.read_text() == before


def test_a_rejected_value_never_reaches_disk():
    from ci.config import CONFIG_DIR

    before = (CONFIG_DIR / "scoring.yaml").read_text()
    with pytest.raises(ValueError):
        api.save({"feed.max_rows": 40, "tier.breaking_views": 10 ** 12})
    assert (CONFIG_DIR / "scoring.yaml").read_text() == before, \
        "the valid half of a rejected batch was written anyway"


def test_an_edit_spanning_two_files_is_all_or_nothing():
    """Changes can touch scoring.yaml and sources.yaml together. Writing the
    first before validating the second leaves the two disagreeing."""
    from ci.config import CONFIG_DIR

    scoring = (CONFIG_DIR / "scoring.yaml").read_text()
    sources = (CONFIG_DIR / "sources.yaml").read_text()
    with pytest.raises(ValueError):
        api.save({"feed.max_rows": 44, "vol.keywords_per_run": 10 ** 6})
    assert (CONFIG_DIR / "scoring.yaml").read_text() == scoring
    assert (CONFIG_DIR / "sources.yaml").read_text() == sources


def test_a_real_save_round_trips_to_the_same_bytes():
    """The strongest check there is: change it, change it back, and the file
    should be indistinguishable from the original."""
    from ci.config import CONFIG_DIR, get_settings

    path = CONFIG_DIR / "scoring.yaml"
    original = path.read_text()
    try:
        api.save({"feed.min_score_to_show": 37, "tier.breaking_views": 41000})
        changed = path.read_text()
        assert changed != original
        assert changed.count("#") == original.count("#")
    finally:
        api.save({"feed.min_score_to_show": 30, "tier.breaking_views": 50000})
        get_settings.cache_clear()
    assert path.read_text() == original


# --------------------------------------------------------------------------- #
# the page itself
# --------------------------------------------------------------------------- #
def test_the_page_fetches_nothing_from_the_internet():
    """This runs on a laptop, sometimes with no network. A local tool that blocks
    on fonts.googleapis.com is a local tool that hangs on a train."""
    from ci.dashboard.server import PAGE

    html = PAGE.read_text()
    for host in ("fonts.googleapis.com", "fonts.gstatic.com", "cdnjs", "unpkg", "jsdelivr"):
        assert host not in html, f"the page reaches out to {host}"


def test_the_page_defines_both_themes():
    """It follows the machine's own setting until the person picks one, and the
    choice is applied in <head> so nobody sees a white flash on a dark desk."""
    from ci.dashboard.server import PAGE

    html = PAGE.read_text()
    assert "prefers-color-scheme: light" in html, "no default from the machine"
    assert '[data-theme="light"]' in html, "no light palette"
    assert html.index("prefers-color-scheme: light") < html.index("</head>")


def test_the_server_binds_to_localhost_by_default():
    """This one can rewrite config files. It must never be the thing left
    listening on 0.0.0.0."""
    import inspect

    from ci.dashboard.server import serve

    assert inspect.signature(serve).parameters["host"].default == "127.0.0.1"
