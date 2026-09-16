"""The dashboard's run control and its answer to "why is this empty"."""
from __future__ import annotations

import time

import pytest

from ci.dashboard import api, runner


@pytest.fixture(autouse=True)
def _clean():
    runner.reset_for_tests()
    yield
    runner.reset_for_tests()


def _wait(limit: float = 10.0) -> dict:
    deadline = time.time() + limit
    while time.time() < deadline:
        state = runner.status()
        if not state["running"]:
            return state
        time.sleep(0.05)
    raise AssertionError("job never finished")


def test_catalogue_declares_what_each_job_needs():
    jobs = {j["key"]: j for j in runner.catalogue()}
    assert jobs["rescore"]["needs"] is None, "scoring stored rows needs no credential"
    assert jobs["collect_ugc"]["needs"] == "apify"
    # Naming Apify on the Google Sheets job sent someone hunting for the wrong
    # credential, which is the whole reason this field exists.
    assert jobs["sheets"]["needs"] == "google"


def test_unknown_job_is_refused():
    with pytest.raises(KeyError):
        runner.start("drop_everything")


def test_one_job_at_a_time(monkeypatch):
    """Two collectors writing snapshots at once corrupts the velocity history,
    and that is the one thing in this pipeline that cannot be recomputed."""
    monkeypatch.setattr(runner, "_plan",
                        lambda key, settings: [("slow", lambda: time.sleep(0.4) or {})])
    first = runner.start("rescore")
    assert first["started"] is True
    second = runner.start("rescore")
    assert second["started"] is False and second["reason"] == "busy"
    _wait()


def test_a_failing_stage_is_reported_not_swallowed(monkeypatch):
    def boom():
        raise RuntimeError("actor returned 402: insufficient credit")
    monkeypatch.setattr(runner, "_plan", lambda key, settings: [("sweep", boom)])
    runner.start("collect_ugc")
    last = _wait()["last"]
    assert last["ok"] is False
    assert "402" in last["error"]
    assert "credit" in last["hint"].lower(), "an empty balance must say so in words"
    assert last["steps"][-1]["state"] == "failed"


def test_a_sweep_that_collects_nothing_explains_itself(monkeypatch):
    """Out of credit, Apify reports SUCCEEDED and returns an empty dataset. The
    run looks fine and the dashboard does not move, which reads as a broken tool."""
    monkeypatch.setattr(runner, "_plan",
                        lambda key, settings: [("sweep", lambda: {"collected": 0})])
    runner.start("collect_ugc")
    last = _wait()["last"]
    assert last["ok"] is True
    assert "balance" in last["hint"].lower()


def test_steps_carry_the_numbers_from_the_stage(monkeypatch):
    monkeypatch.setattr(runner, "_plan", lambda key, settings: [
        ("one", lambda: {"summary": {"counts": {"scored": 12, "on_feed": 3}}})])
    runner.start("rescore")
    last = _wait()["last"]
    assert "scored 12" in last["steps"][0]["detail"]


def test_collection_is_always_followed_by_scoring(monkeypatch):
    """Collecting without scoring leaves the screen exactly as empty as before."""
    from ci.config import get_settings
    names = [name for name, _ in runner._plan("collect_ugc", get_settings())]
    assert len(names) == 2 and "Scoring" in names[1]


def test_history_keeps_the_last_runs(monkeypatch):
    monkeypatch.setattr(runner, "_plan", lambda key, settings: [("x", lambda: {})])
    for _ in range(3):
        runner.start("rescore")
        _wait()
    assert len(runner.status()["history"]) == 3
    assert runner.status()["history"][0]["job"] == "rescore"
