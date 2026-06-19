"""SEC-01: opt-in API-key gate + fail-closed non-loopback bind.

Two opt-in, fail-closed controls (audit finding SEC-01):

* ``require_api_key`` — when ``NETCANON_API_KEY`` is set, ``/api/v1``
  requires a matching ``Authorization: Bearer`` header; unset = no-op.
* ``bind_refusal_reason`` — ``netcanon serve`` refuses a non-loopback
  bind with no key and no explicit ``NETCANON_ALLOW_INSECURE_BIND`` opt-out.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from netcanon.api.auth import (
    bind_refusal_reason,
    is_loopback_host,
    require_api_key,
)
from netcanon.cli import main as cli_main
from netcanon.config import Settings

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# require_api_key dependency (tested in isolation on a minimal app)
# ---------------------------------------------------------------------------


def _client(api_key: str) -> TestClient:
    app = FastAPI()

    class _Settings:
        pass

    s = _Settings()
    s.api_key = api_key
    app.state.settings = s

    @app.get("/x", dependencies=[Depends(require_api_key)])
    def _x():
        return {"ok": True}

    return TestClient(app)


def test_no_key_configured_allows_unauthenticated():
    assert _client("").get("/x").status_code == 200


def test_key_configured_rejects_missing_header():
    r = _client("s3cret").get("/x")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_key_configured_accepts_valid_bearer():
    r = _client("s3cret").get("/x", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200


@pytest.mark.parametrize(
    "header",
    ["Bearer wrong", "s3cret", "Basic s3cret", "Bearer "],
)
def test_key_configured_rejects_bad_credentials(header):
    assert _client("s3cret").get("/x", headers={"Authorization": header}).status_code == 401


# ---------------------------------------------------------------------------
# bind-safety guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.5", "localhost", "::1"])
def test_loopback_hosts_recognised(host):
    assert is_loopback_host(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "10.0.0.5", "example.com"])
def test_non_loopback_hosts_recognised(host):
    assert not is_loopback_host(host)


def test_loopback_bind_never_refused():
    assert bind_refusal_reason("127.0.0.1", "", False) is None


def test_nonloopback_bind_no_key_refuses():
    reason = bind_refusal_reason("0.0.0.0", "", False)
    assert reason is not None and "NETCANON_API_KEY" in reason


def test_nonloopback_bind_with_key_allowed():
    assert bind_refusal_reason("0.0.0.0", "s3cret", False) is None


def test_nonloopback_bind_with_optout_allowed():
    assert bind_refusal_reason("0.0.0.0", "", True) is None


# ---------------------------------------------------------------------------
# Settings env wiring + `netcanon serve` refusal
# ---------------------------------------------------------------------------


def test_settings_reads_api_key_env(monkeypatch):
    monkeypatch.setenv("NETCANON_API_KEY", "k")
    assert Settings().api_key == "k"


def test_settings_reads_allow_insecure_bind_env(monkeypatch):
    monkeypatch.setenv("NETCANON_ALLOW_INSECURE_BIND", "1")
    assert Settings().allow_insecure_bind is True


def test_serve_refuses_insecure_bind(monkeypatch, capsys):
    # 0.0.0.0 + no key + no opt-out → refuse to start (exit 2), without
    # importing uvicorn or building the app.
    monkeypatch.setenv("NETCANON_HOST", "0.0.0.0")
    monkeypatch.delenv("NETCANON_API_KEY", raising=False)
    monkeypatch.delenv("NETCANON_ALLOW_INSECURE_BIND", raising=False)
    rc = cli_main(["serve"])
    assert rc == 2
    assert "Refusing to start" in capsys.readouterr().err
