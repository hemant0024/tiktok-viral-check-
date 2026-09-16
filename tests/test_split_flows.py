"""Ads and UGC run as two independent flows, each ending in the Sheet.

The point of splitting them is failure isolation and readability: a throttled
TikTok actor must not stop the ads side from being scored and written, and the
two halves are scored on different signals so mixing them in one tab leaves every
column blank for half the rows.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ci.stages import KIND_GROUPS, stage_brief_input, stage_radar, stage_save_brief

pytestmark = pytest.mark.unit

WORKFLOWS = Path(__file__).resolve().parents[1] / "workflows" / "n8n"


def _content(repo, rows):
    repo.upsert("RAW_CONTENT", rows)


def _row(cid, kind, hours_old=8.0, **kw):
    """A fixture video, aged relative to now.

    These used to pin published_at to a literal date. The radar drops anything
    past 72 hours, so the whole file quietly started failing the moment the
    calendar moved past that date plus three days: the videos were not wrong,
    they had simply aged out. A test that passes only during one week is not
    testing what it claims to.
    """
    published = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    base = {"content_id": cid, "kind": kind, "platform": "tiktok",
            "published_at": published.isoformat(),
            "url": f"https://tiktok.com/@x/video/{cid}", "title": f"t{cid}",
            "creator": f"c{cid}", "competitor": "Loora", "views": 50000,
            "likes": 4000, "comments": 100, "shares": 900, "saves": 200,
            "duration_seconds": 30}
    base.update(kw)
    return base


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
def _ad(cid, **kw):
    """A durable ad. Meta gives no views for US commercial ads, so days running
    and variation count are the whole signal."""
    return _row(cid, "competitor_ad", views=0, likes=0, comments=0, shares=0, saves=0,
                days_running=45, variation_count=4, **kw)


def test_radar_kind_scores_only_that_half(repo, settings):
    _content(repo, [_row("u1", "organic_ugc"), _ad("a1")])

    ugc = stage_radar(repo, settings, kind="ugc")
    assert {r["content_id"] for r in ugc["feed"]} == {"u1"}

    ads = stage_radar(repo, settings, kind="ads")
    assert {r["content_id"] for r in ads["feed"]} == {"a1"}


def test_two_scoped_runs_coexist_in_one_radar_table(repo, settings):
    """The flows are independent but the table is shared. The second run must not
    wipe the first: they upsert per row, they do not replace the table."""
    _content(repo, [_row("u1", "organic_ugc"), _ad("a1")])
    stage_radar(repo, settings, kind="ugc")
    stage_radar(repo, settings, kind="ads")

    stored = {r["content_id"] for r in repo.read("RADAR")}
    assert stored == {"u1", "a1"}, "one flow overwrote the other's rows"


def test_ugc_flow_still_scores_when_the_ads_side_has_nothing(repo, settings):
    """The whole reason for splitting. A dead ads collector cannot stop UGC."""
    _content(repo, [_row("u1", "organic_ugc")])
    assert stage_radar(repo, settings, kind="ugc")["feed"]
    assert stage_radar(repo, settings, kind="ads")["feed"] == []
    assert {r["content_id"] for r in repo.read("RADAR")} == {"u1"}


def test_unknown_kind_is_refused_loudly(repo, settings):
    with pytest.raises(RuntimeError, match="unknown kind"):
        stage_radar(repo, settings, kind="videos")


# --------------------------------------------------------------------------- #
# the payload Claude reads
# --------------------------------------------------------------------------- #
def test_brief_input_is_scoped_and_small(repo, settings):
    _content(repo, [_row(f"u{i}", "organic_ugc", views=90000 - i * 1000) for i in range(20)])
    _content(repo, [_ad("a1")])
    stage_radar(repo, settings, kind="ugc")
    stage_radar(repo, settings, kind="ads")

    out = stage_brief_input(repo, settings, kind="ugc", limit=5)
    assert len(out["today"]) == 5, "limit ignored, Claude gets the whole dump"
    assert all(r.get("content_id", "").startswith("u") for r in out["today"])
    assert len(json.dumps(out)) < 20000, "payload is big enough to be worth trimming"


def test_brief_input_drops_empty_fields_rather_than_sending_zeroes(repo, settings):
    _content(repo, [_row("u1", "organic_ugc")])
    stage_radar(repo, settings, kind="ugc")
    row = stage_brief_input(repo, settings, kind="ugc")["today"][0]
    assert "content_id" in row and "url" in row
    assert not any(v in (0, 0.0, "", None, False) for v in row.values())


def test_ads_brief_is_told_there_are_no_view_counts(repo, settings):
    """Meta publishes no impressions for US commercial ads. If the note ever goes
    missing, Claude will confidently invent reach numbers."""
    out = stage_brief_input(repo, settings, kind="ads")
    assert "view counts" in out["note"] and "days running" in out["note"]


# --------------------------------------------------------------------------- #
# the brief comes back into the sheet
# --------------------------------------------------------------------------- #
def test_empty_brief_is_refused(repo, settings):
    with pytest.raises(RuntimeError, match="empty"):
        stage_save_brief(repo, settings, brief="   ")


def test_briefs_are_keyed_by_date_and_source(repo, settings, monkeypatch):
    import ci.stages as S

    class FakeSheets:
        instances: list = []

        def __init__(self, *a):
            FakeSheets.instances.append(self)

        def upsert_tab(self, tab, rows, key_fields=("date", "content_id")):
            self.tab, self.rows, self.keys = tab, rows, key_fields
            return len(rows)

    monkeypatch.setattr(S, "_settings_guard", None, raising=False)
    monkeypatch.setattr(settings, "google_service_account_json", "{}", raising=False)
    monkeypatch.setattr(settings, "google_sheet_id", "sheet123", raising=False)
    monkeypatch.setitem(__import__("sys").modules, "ci.database.sheets",
                        type("m", (), {"SheetsRepository": FakeSheets}))

    # Re-running the same flow replaces that flow's brief...
    stage_save_brief(repo, settings, brief="first read", source="claude/ugc")
    stage_save_brief(repo, settings, brief="second read", source="claude/ugc")
    rows = repo.read("DAILY_BRIEF")
    assert len(rows) == 1, "a rerun appended instead of replacing"
    assert rows[0]["brief"] == "second read"

    # ...but the other flow's brief on the same day is a separate row. Keyed on
    # date alone, the 6:30am ads run would silently wipe the 6am UGC read.
    stage_save_brief(repo, settings, brief="ads read", source="claude/ads")
    rows = repo.read("DAILY_BRIEF")
    assert len(rows) == 2, "one flow overwrote the other's brief"
    assert {r["source"] for r in rows} == {"claude/ugc", "claude/ads"}
    assert FakeSheets.instances[-1].keys == ("date", "source")


# --------------------------------------------------------------------------- #
# the n8n graphs themselves
# --------------------------------------------------------------------------- #
def _wf(name):
    return json.loads((WORKFLOWS / f"{name}.json").read_text())


def _urls(d):
    return " ".join(n["parameters"].get("url", "") for n in d["nodes"])


@pytest.mark.parametrize("name", ["ugc", "ads"])
def test_workflow_graph_is_connected(name):
    d = _wf(name)
    names = {n["name"] for n in d["nodes"]}
    targets = {t["node"] for v in d["connections"].values()
               for branches in v.values() for lst in branches for t in lst}
    assert targets <= names, f"connection points at a node that does not exist: {targets - names}"
    entry = names - targets
    assert all("Claude Sonnet" in n or "New York" in n for n in entry), \
        f"orphaned node, it will never run: {entry}"


@pytest.mark.parametrize("name", ["ugc", "ads"])
def test_the_sheet_is_the_endpoint(name):
    """'End point will be in sheet'. Every flow must reach a sheets push, and the
    brief must land there too rather than only in Slack."""
    urls = _urls(_wf(name))
    assert f"/run/sheets_push_{name}" in urls
    assert "/run/save_brief" in urls


@pytest.mark.parametrize("name", ["ugc", "ads"])
def test_each_flow_touches_only_its_own_half(name):
    other = "ads" if name == "ugc" else "ugc"
    blob = json.dumps(_wf(name))
    assert f"/run/radar_{name}" in blob
    assert f"radar_{other}" not in blob, "the flows are not actually independent"
    assert f"sheets_push_{other}" not in blob


@pytest.mark.parametrize("name", ["ugc", "ads"])
def test_collection_failure_does_not_halt_the_flow(name):
    d = _wf(name)
    collect = [n for n in d["nodes"] if "/run/collect" in n["parameters"].get("url", "")]
    assert collect, "no collector in the flow"
    assert all(n.get("onError") == "continueRegularOutput" for n in collect)


@pytest.mark.parametrize("name", ["ugc", "ads"])
def test_claude_node_is_wired_to_a_model(name):
    d = _wf(name)
    chains = [n for n in d["nodes"] if n["type"].endswith("chainLlm")]
    models = [n for n in d["nodes"] if n["type"].endswith("lmChatAnthropic")]
    assert len(chains) == 1 and len(models) == 1
    wired = d["connections"].get(models[0]["name"], {}).get("ai_languageModel")
    assert wired, "the model is not connected, the chain will fail at run time"
    assert wired[0][0]["node"] == chains[0]["name"]


@pytest.mark.parametrize("name", ["ugc", "ads"])
def test_the_model_field_is_a_resource_locator(name):
    """A plain string here is rejected by n8n as an invalid parameter, and the
    node only fails once the workflow actually runs."""
    model = next(n for n in _wf(name)["nodes"] if n["type"].endswith("lmChatAnthropic"))
    assert model["typeVersion"] >= 1.3
    assert model["parameters"]["model"]["__rl"] is True
    assert model["parameters"]["model"]["value"] == "claude-sonnet-4-5"


@pytest.mark.parametrize("name", ["ugc", "ads"])
def test_prompt_is_loaded_from_the_repo_not_pasted_into_the_json(name):
    """Prompts live in prompts/*.md. A prompt frozen inside exported JSON is a
    prompt nobody edits."""
    assert f"/prompt/daily_brief_{name}" in _urls(_wf(name))
    assert list((Path(__file__).resolve().parents[1] / "prompts").glob(f"*daily_brief_{name}.md"))


# --------------------------------------------------------------------------- #
# what running on n8n Cloud forces
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["ugc", "ads"])
def test_the_host_is_set_in_exactly_one_place(name):
    """Eight hardcoded hosts is eight chances to update seven of them."""
    d = _wf(name)
    config = [n for n in d["nodes"] if n["name"] == "Config"]
    assert len(config) == 1, "no single place to set the host"
    assert "REPLACE-ME" in json.dumps(config[0]), "the placeholder host is missing"
    for n in d["nodes"]:
        url = n["parameters"].get("url", "")
        if url:
            assert url.startswith("={{ $('Config')"), f"{n['name']} hardcodes its host"


@pytest.mark.parametrize("name", ["ugc", "ads"])
def test_no_secret_is_read_from_env(name):
    """n8n Cloud blocks $env outright. An expression reading it does not error,
    it silently resolves to empty, which is the worst of both."""
    blob = (WORKFLOWS / f"{name}.json").read_text()
    assert "$env" not in blob
    for marker in ("xoxb-", "sk-ant-", "apify_api_", "AIza"):
        assert marker not in blob, f"a real credential is committed in {name}.json"


@pytest.mark.parametrize("name", ["ugc", "ads"])
def test_every_service_call_carries_a_credential(name):
    """These endpoints start Apify runs that cost money. On a public host an
    unauthenticated call is someone else spending your budget."""
    for n in _wf(name)["nodes"]:
        if n["parameters"].get("url", "").startswith("={{ $('Config')"):
            assert n.get("credentials", {}).get("httpCustomAuth"), \
                f"{n['name']} calls the service with no credential"


@pytest.mark.parametrize("name", ["ugc", "ads"])
def test_a_broken_stage_fails_the_execution(name):
    """Every node continues on error so the sheet still gets written. That means
    nothing marks the run as failed unless the last node says so, and a run that
    reports success while three stages died is worse than no monitoring."""
    d = _wf(name)
    last = next(n for n in d["nodes"] if n["type"] == "n8n-nodes-base.code")
    assert "throw new Error" in last["parameters"]["jsCode"]
    assert d["connections"].get(last["name"]) is None, "the failure check is not the last step"


def test_the_flows_do_not_start_at_the_same_time():
    times = {}
    for name in ("ugc", "ads"):
        trig = next(n for n in _wf(name)["nodes"] if n["type"].endswith("scheduleTrigger"))
        expr = trig["parameters"]["rule"]["interval"][0]["expression"]
        times[name] = int(expr.split()[1]) * 60 + int(expr.split()[0])
    assert abs(times["ugc"] - times["ads"]) >= 30, \
        "overlapping runs double-write snapshots and corrupt velocity history"


@pytest.mark.parametrize("name", ["ugc", "ads"])
def test_the_schedule_is_pinned_to_a_timezone(name):
    """A cron with no timezone fires at 6am wherever the instance thinks it is."""
    assert _wf(name)["settings"].get("timezone") == "America/New_York"


# --------------------------------------------------------------------------- #
# the number most likely to make Claude write something false
# --------------------------------------------------------------------------- #
def test_no_publish_time_means_no_pace_figure(scoring):
    """A missing timestamp gives age 0. Dividing the curve by that produced
    '27,466x expected pace' on a real row — an artefact Claude would have
    reported as the finding of the day."""
    from ci.scoring.viral_signals import UNKNOWN_AGE, takeoff_profile

    out = takeoff_profile({"views": 412000, "creator_followers": 73}, 0.0,
                          scoring.get("takeoff", {}), creator_lift=900.0)
    assert out.vs_expected == 0.0
    assert out.expected_views == 0.0
    assert out.tier == UNKNOWN_AGE
    assert any("publish time" in n for n in out.notes)


def test_a_missing_timestamp_does_not_cost_us_the_jackpot(scoring):
    """Whether a 73-follower account is doing 900x its normal has nothing to do
    with knowing when it posted. That signal must survive."""
    from ci.scoring.viral_signals import takeoff_profile

    out = takeoff_profile({"views": 412000, "creator_followers": 73}, 0.0,
                          scoring.get("takeoff", {}), creator_lift=900.0)
    assert out.is_jackpot is True


def test_a_real_age_still_produces_a_sane_pace(scoring):
    from ci.scoring.viral_signals import takeoff_profile

    out = takeoff_profile({"views": 412000, "creator_followers": 73}, 9.0,
                          scoring.get("takeoff", {}), creator_lift=900.0)
    assert 50 < out.vs_expected < 500, f"pace off the scale again: {out.vs_expected}"


def test_brief_asks_for_a_field_that_actually_exists(repo, settings):
    """'posted_at' is in no model. The brief was asking for a field that could
    never be populated, so Claude never saw a date."""
    from ci.models import TABLES

    _content(repo, [_row("u1", "organic_ugc")])
    stage_radar(repo, settings, kind="ugc")
    radar_fields = set(TABLES["RADAR"].model_fields)
    row = stage_brief_input(repo, settings, kind="ugc")["today"][0]
    assert set(row) <= radar_fields
    assert "published_at" in radar_fields


# --------------------------------------------------------------------------- #
# the link is the deliverable
# --------------------------------------------------------------------------- #
def test_the_link_is_the_first_column(repo, settings):
    """The ask was 'the video link, name, creator name, date and all the data'.
    A username is not something you can open. Sheet columns follow model field
    order, so url has to be field one or it lands in column nine."""
    from ci.models import TABLES

    fields = list(TABLES["RADAR"].model_fields)
    assert fields[0] == "url", f"the sheet opens on {fields[0]!r}, not the link"
    assert fields[:4] == ["url", "title", "creator", "published_at"]


def test_the_brief_hands_claude_the_link_first(repo, settings):
    _content(repo, [_row("u1", "organic_ugc")])
    stage_radar(repo, settings, kind="ugc")
    row = stage_brief_input(repo, settings, kind="ugc")["today"][0]
    assert list(row)[0] == "url", "Claude reads an id before it reads the link"


def test_every_feed_row_carries_a_usable_link(repo, settings):
    """A row with no link is a row nobody can act on, whatever it scores."""
    _content(repo, [_row(f"u{i}", "organic_ugc", views=90000 - i * 900) for i in range(6)])
    feed = stage_radar(repo, settings, kind="ugc")["feed"]
    assert feed
    for r in feed:
        assert r.get("url", "").startswith("http"), f"{r['content_id']} has no link"


def test_the_rendered_feed_puts_the_link_above_the_creator():
    from ci.report.radar_render import render_feed

    out = render_feed("2026-09-11", [{
        "url": "https://www.tiktok.com/@someone/video/123",
        "title": "a caption", "creator": "someone", "creator_followers": 900,
        "radar_score": 61.0, "status": "EARLY SIGNAL", "competitor": "Praktika AI",
        "kind": "organic_ugc", "platform": "tiktok", "views": 18000, "shares": 40,
        "age_hours": 9.0,
    }])
    assert "https://www.tiktok.com/@someone/video/123" in out
    assert out.index("tiktok.com/@someone/video/123") < out.index("Creator"), \
        "the creator line comes before the link"


# --------------------------------------------------------------------------- #
# coverage: every competitor, every day
# --------------------------------------------------------------------------- #
def test_every_configured_keyword_runs_every_day(settings):
    """The plan rotated competitors across a week to save Apify credit. A video
    peaks inside 24 to 48 hours, so a competitor checked on Tuesday and next
    checked on Friday is one whose breakout you read about after it is over."""
    from ci.collectors.competitor_ugc import CompetitorUgcCollector

    c = CompetitorUgcCollector(settings)
    comps = c.competitors()
    configured = sum(len(x.get("keywords", [])) for x in comps)

    plan = c.keyword_plan()
    assert len(plan) == configured, \
        f"{configured} keywords configured, {len(plan)} planned"
    assert {name for _, name in plan} == {x["name"] for x in comps}


def test_coverage_does_not_drift_with_the_day_of_year(settings):
    """A rotation keyed on the day number means today's answer depends on the
    date, which makes 'nothing found' impossible to interpret."""
    from ci.collectors.competitor_ugc import CompetitorUgcCollector

    c = CompetitorUgcCollector(settings)
    assert c.keyword_plan(day_index=1) == c.keyword_plan(day_index=200)


def test_a_cap_still_rotates_for_a_smaller_apify_plan(settings):
    """Full coverage is the default, not the only option. On a plan that cannot
    afford it, partial coverage beats none."""
    from ci.collectors.competitor_ugc import CompetitorUgcCollector

    c = CompetitorUgcCollector(settings)
    c.cfg = dict(c.cfg, keywords_per_run=10)
    plan = c.keyword_plan(day_index=1)
    assert len(plan) == 10
    assert c.keyword_plan(day_index=1) != c.keyword_plan(day_index=2)


# --------------------------------------------------------------------------- #
# tier filter on the morning list
# --------------------------------------------------------------------------- #
def test_only_the_wanted_tiers_reach_the_feed(repo, settings):
    """WATCH is everything under 24h that has not done anything yet, and it is
    always the biggest group. Useful in the sheet, noise in a list you read in
    two minutes."""
    settings.scoring["radar"]["feed"]["tiers_to_show"] = ["BREAKING OUT", "INTERESTING"]
    _content(repo, [
        _row("big", "organic_ugc", hours_old=16, views=56000),   # BREAKING OUT
        _row("mid", "organic_ugc", hours_old=11, views=18000),   # INTERESTING
        _row("new", "organic_ugc", hours_old=3, views=900),      # WATCH
    ])
    feed = stage_radar(repo, settings, kind="ugc")["feed"]
    tiers = {r.get("takeoff_tier") for r in feed}
    assert tiers <= {"BREAKING OUT", "INTERESTING"}
    assert "WATCH" not in tiers


def test_the_filter_does_not_touch_what_gets_stored(repo, settings):
    """Display filter, not a collection filter. Everything still has to reach the
    sheet or tomorrow's trends and the learned baseline lose their history."""
    settings.scoring["radar"]["feed"]["tiers_to_show"] = ["BREAKING OUT"]
    _content(repo, [
        _row("big", "organic_ugc", hours_old=16, views=56000),
        _row("new", "organic_ugc", hours_old=3, views=900),
    ])
    out = stage_radar(repo, settings, kind="ugc")
    assert len(out["feed"]) < out["summary"]["counts"]["scored"]
    assert {r["content_id"] for r in repo.read("RADAR")} == {"big", "new"}


def test_ads_are_never_filtered_on_a_tier_they_cannot_have(repo, settings):
    """Tiers are views-for-age and Meta publishes no views for US commercial ads,
    so every ad carries an empty tier. Filtering on it would empty the ads feed."""
    settings.scoring["radar"]["feed"]["tiers_to_show"] = ["BREAKING OUT"]
    _content(repo, [_ad("a1")])
    feed = stage_radar(repo, settings, kind="ads")["feed"]
    assert [r["content_id"] for r in feed] == ["a1"]


def test_an_empty_tier_list_shows_everything(repo, settings):
    settings.scoring["radar"]["feed"]["tiers_to_show"] = []
    _content(repo, [_row("new", "organic_ugc", hours_old=3, views=900)])
    assert stage_radar(repo, settings, kind="ugc")["feed"]
