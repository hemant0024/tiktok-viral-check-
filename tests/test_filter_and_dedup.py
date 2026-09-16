from __future__ import annotations

import pytest

from pathlib import Path

from ci.processors.cheap_filter import cheap_filter
from ci.processors.dedup import dedup
from ci.processors.snapshots import build_snapshots
from tests.helpers import make_content, snap

pytestmark = pytest.mark.unit


def test_videos_over_two_minutes_are_cut(scoring, now):
    long_video = make_content(cid="long", views=500000, hours_old=20, duration=900)
    _, verdicts = cheap_filter([long_video], {}, scoring, now)
    assert verdicts[0].kept is False
    assert any("longer than" in r for r in verdicts[0].reasons)


def test_two_minute_boundary_is_inclusive(scoring, now):
    ok = make_content(cid="ok", views=500000, hours_old=20, duration=120)
    over = make_content(cid="over", views=500000, hours_old=20, duration=121)
    _, verdicts = cheap_filter([ok, over], {}, scoring, now)
    by_id = {v.content.content_id: v for v in verdicts}
    assert by_id["ok"].kept is True
    assert by_id["over"].kept is False


def test_young_video_below_views_floor_survives_if_on_pace(scoring, now):
    """A 4 hour old video with 3,000 views is on pace for 18,000 a day.
    A flat views floor would throw away exactly what we are hunting."""
    climbing = make_content(cid="climbing", views=3000, hours_old=4, duration=25,
                            saves=300, shares=150)
    _, verdicts = cheap_filter([climbing], {}, scoring, now)
    assert verdicts[0].kept is True


def test_flat_low_view_video_is_cut(scoring, now):
    flat = make_content(cid="flat", views=300, hours_old=240, duration=25)
    _, verdicts = cheap_filter([flat], {}, scoring, now)
    assert verdicts[0].kept is False


def test_breakouts_get_reserved_slots_over_bigger_older_videos(scoring, now):
    """Without a reserved share, yesterday's winners crowd out today's climbers."""
    cfg = {**scoring}
    cfg["cheap_filter"] = {**scoring["cheap_filter"], "target_candidates": 5}
    proven = [make_content(cid=f"big{i}", views=3_000_000, hours_old=200, duration=40)
              for i in range(10)]
    climbers = [make_content(cid=f"new{i}", views=40000, hours_old=8, duration=30,
                             saves=2000, shares=900) for i in range(4)]
    kept, _ = cheap_filter(proven + climbers, {}, cfg, now)
    kept_ids = {c.content_id for c in kept}
    assert any(cid.startswith("new") for cid in kept_ids)


def test_old_content_inside_lookback_is_marked_reference(scoring, now):
    cfg = {**scoring}
    cfg["velocity"] = {**scoring["velocity"], "lookback_days": 1}
    item = make_content(cid="ref", views=800000, hours_old=72, duration=30)
    kept, _ = cheap_filter([item], {}, cfg, now)
    assert kept and kept[0].is_reference is True


def test_dedup_keeps_the_richer_reading(now):
    a = make_content(cid="tiktok:1", views=1000)
    b = make_content(cid="tiktok:1", views=5000)
    result = dedup([a, b])
    assert len(result) == 1
    assert result[0].views == 5000


def test_snapshots_are_built_for_every_item():
    items = [make_content(cid=f"c{i}") for i in range(3)]
    snaps = build_snapshots(items, captured_at="2026-09-10T00:00:00+00:00")
    assert len(snaps) == 3
    assert len({s.snapshot_key for s in snaps}) == 3


def test_local_storage_is_healthy_even_when_deletes_are_forbidden(tmp_path, monkeypatch):
    """A mount that allows writes but refuses unlink is still a healthy store.
    The first version of this check called unlink and reported FAIL on a folder
    that was working perfectly."""
    import os

    from ci.database.localjson import LocalJsonRepository

    repo = LocalJsonRepository(tmp_path / "d")
    real_unlink = os.unlink

    def no_unlink(path, *a, **kw):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(os, "unlink", no_unlink)
    monkeypatch.setattr(Path, "unlink", lambda self, **kw: no_unlink(self))
    health = repo.healthcheck()
    monkeypatch.setattr(os, "unlink", real_unlink)
    assert health["ok"] is True
    assert "delete" in health["note"]


def test_silent_throttle_is_detected_not_recorded_as_zero(monkeypatch):
    """The free Apify tier returns {"noResults": true} instead of an error when
    throttled. Verified live: the same keyword returned 10 videos, then nothing,
    8 minutes later. Recording that as "this competitor has no UGC" is a lie that
    poisons the learned baseline."""
    import httpx

    from ci.collectors.apify import ApifyClient, ApifyThrottled

    class Resp:
        status_code = 200

        @staticmethod
        def json():
            return [{"noResults": True}] * 10

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp())
    client = ApifyClient("token", throttle_after=3)

    assert client.run_actor("x/y", {}) == []
    assert client.run_actor("x/y", {}) == []
    with pytest.raises(ApifyThrottled):
        client.run_actor("x/y", {})


def test_real_results_reset_the_throttle_counter(monkeypatch):
    import httpx

    from ci.collectors.apify import ApifyClient

    state = {"empty": True}

    class Resp:
        status_code = 200

        @staticmethod
        def json():
            return [{"noResults": True}] if state["empty"] else [{"id": "1", "views": 10}]

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp())
    client = ApifyClient("token", throttle_after=3)
    client.run_actor("x/y", {})
    assert client.consecutive_empty == 1
    state["empty"] = False
    assert len(client.run_actor("x/y", {})) == 1
    assert client.consecutive_empty == 0


def test_sentinel_rows_never_reach_the_pipeline(monkeypatch):
    import httpx

    from ci.collectors.apify import ApifyClient

    class Resp:
        status_code = 200

        @staticmethod
        def json():
            return [{"id": "1", "views": 100}, {"noResults": True}]

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp())
    out = ApifyClient("token").run_actor("x/y", {})
    assert out == [{"id": "1", "views": 100}]
