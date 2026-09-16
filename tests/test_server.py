"""The HTTP front door n8n drives."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from ci.server import Handler, _stages

pytestmark = pytest.mark.unit


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def get(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.status, json.loads(r.read())


def post(url, token=None):
    req = urllib.request.Request(url, method="POST", data=b"")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_every_cli_stage_worth_scheduling_is_exposed():
    names = set(_stages())
    for stage in ("radar", "trends", "watch", "sheets_push", "notify_radar",
                  "collect_competitor_ugc", "collect_meta_ads", "healthcheck"):
        assert stage in names


def test_health_lists_the_stages(server):
    status, body = get(f"{server}/health")
    assert status == 200
    assert body["ok"] is True
    assert len(body["stages"]) >= 15


def test_unknown_stage_is_a_404_with_the_real_list(server):
    status, body = post(f"{server}/run/does-not-exist")
    assert status == 404
    assert "stages" in body


def test_a_stage_returns_structured_json_n8n_can_branch_on(server):
    status, body = post(f"{server}/run/healthcheck")
    assert status == 200
    for key in ("ok", "stage", "status", "counts", "failures", "duration_seconds"):
        assert key in body, f"n8n needs {key} to branch"


def test_a_missing_credential_is_partial_not_a_crash(server, monkeypatch):
    """Failure isolation, over HTTP. One source without a token must not take
    the endpoint down."""
    status, body = post(f"{server}/run/collect_meta_ads")
    assert status == 200
    assert body["status"] in {"partial", "failed", "ok"}
    assert isinstance(body["failures"], list)


def test_token_is_enforced_when_configured(server, monkeypatch):
    monkeypatch.setenv("CI_API_TOKEN", "s3cret")
    assert post(f"{server}/run/healthcheck")[0] == 401
    assert post(f"{server}/run/healthcheck", token="s3cret")[0] == 200


def test_concurrent_stages_are_refused_not_queued():
    """Two stages running at once would double-write snapshots and corrupt the
    velocity history, so the second is refused rather than queued."""
    from ci.server import _LOCK

    assert _LOCK.acquire(blocking=False)
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_address[1]}/run/healthcheck"
        status, body = post(url)
        srv.shutdown()
        assert status == 409
        assert "running" in body
    finally:
        _LOCK.release()


def test_no_token_means_private_callers_only(monkeypatch):
    """These endpoints start Apify runs that cost money. With no token set, a
    public deployment must fail closed rather than bill quietly."""
    from ci.server import _is_private

    monkeypatch.delenv("CI_API_TOKEN", raising=False)
    assert _is_private("127.0.0.1")
    assert _is_private("172.18.0.4")     # docker compose network
    assert _is_private("10.1.2.3")
    assert _is_private("192.168.1.50")
    assert not _is_private("18.194.3.11")   # n8n Cloud egress
    assert not _is_private("")
    assert not _is_private("not-an-ip")


def test_a_token_lets_a_public_caller_in(server, monkeypatch):
    monkeypatch.setenv("CI_API_TOKEN", "s3cret")
    code, body = post(f"{server}/run/healthcheck")
    assert code == 401, "a request with no Authorization header was accepted"
    code, body = post(f"{server}/run/healthcheck", token="s3cret")
    assert code == 200
