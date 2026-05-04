"""
Smoke test confirming the embedded desktop server serves the Juniper
Junos definition.

The desktop platform creates its FastAPI app via the same
``netconfig.main.create_app`` factory the web platform uses, but
configures Settings with desktop-specific paths (APPDATA in frozen
mode, repo-relative in dev).  The risk a BD agent introduces: shipping
a YAML that validates standalone but breaks the desktop's definition
load (e.g. a path that only resolves when the cwd is the repo root).

This test runs the embedded server in-process via TestClient (the
same machinery `netconfig_desktop.server.ServerThread` wraps in
production) against a Settings tree containing the real Junos YAML,
then asserts:

* ``GET /api/v1/definitions/`` lists Juniper.
* ``GET /api/v1/definitions/Juniper`` returns the schema-validated
  shape with the netmiko driver and ``| display set | no-more``
  config command intact.

We use the in-process TestClient rather than ServerThread because
ServerThread spins a real socket — overkill for a smoke test that
just exercises the routing layer with the shipped definitions tree.
The desktop-specific seam is ``create_app(settings)``; that is what
this test pins.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from netconfig.collectors.base import BaseCollector
from netconfig.config import Settings
from netconfig.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[2]
JUNOS_DEF_PATH = REPO_ROOT / "definitions" / "juniper" / "junos" / "22.x.yaml"


class _NoopCollector(BaseCollector):
    """Returns a single line — collector is patched out for the smoke test."""

    def collect(self, device, definition):  # noqa: ARG002
        return "set system host-name junos-noop\n"


@pytest.fixture()
def junos_desktop_settings(tmp_path) -> Settings:
    """Settings as the desktop shell would build them, but with tmp dirs.

    The shipped Junos YAML is copied verbatim — same bytes the desktop
    embedded server would load from ``definitions/`` in dev mode or
    from ``<exe-dir>/definitions/`` in frozen mode.  Configs go to a
    tmp directory so the smoke test never writes inside the repo.
    """
    defs_dir = tmp_path / "definitions"
    (defs_dir / "juniper" / "junos").mkdir(parents=True)
    (defs_dir / "juniper" / "junos" / "22.x.yaml").write_text(
        JUNOS_DEF_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    return Settings(
        definitions_dir=defs_dir,
        configs_dir=configs_dir,
        backup_concurrency=1,
    )


@pytest.fixture()
def junos_desktop_client(junos_desktop_settings):
    app = create_app(junos_desktop_settings)
    with patch(
        "netconfig.api.routes.backups.get_collector",
        return_value=_NoopCollector(),
    ):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


class TestJunosDefinitionServedByDesktopServer:
    def test_list_definitions_includes_juniper(self, junos_desktop_client):
        resp = junos_desktop_client.get("/api/v1/definitions/")
        assert resp.status_code == 200
        keys = [d["type_key"] for d in resp.json()]
        assert "Juniper" in keys

    def test_get_juniper_definition_returns_200(self, junos_desktop_client):
        resp = junos_desktop_client.get("/api/v1/definitions/Juniper")
        assert resp.status_code == 200

    def test_juniper_definition_uses_netmiko_juniper_junos_driver(
        self, junos_desktop_client
    ):
        resp = junos_desktop_client.get("/api/v1/definitions/Juniper")
        body = resp.json()
        assert body["collector"]["strategy"] == "netmiko"
        assert body["collector"]["netmiko_device_type"] == "juniper_junos"

    def test_juniper_definition_uses_display_set_no_more(
        self, junos_desktop_client
    ):
        # Load-bearing: ``| display set`` produces the wire form the
        # juniper_junos codec parses; ``| no-more`` suppresses paging.
        resp = junos_desktop_client.get("/api/v1/definitions/Juniper")
        body = resp.json()
        assert "| display set" in body["commands"]["config"]
        assert "| no-more" in body["commands"]["config"]


class TestJunosBackupViaDesktopServer:
    """End-to-end smoke: post a backup against the embedded server."""

    def test_post_backup_for_juniper_returns_202(self, junos_desktop_client):
        resp = junos_desktop_client.post(
            "/api/v1/backups",
            json={
                "devices": [
                    {
                        "type_key": "Juniper",
                        "host": "10.0.0.1",
                        "credentials": {
                            "username": "admin",
                            "password": "fake-test-password",
                        },
                    }
                ]
            },
        )
        assert resp.status_code == 202

    def test_get_after_post_shows_completed(self, junos_desktop_client):
        post = junos_desktop_client.post(
            "/api/v1/backups",
            json={
                "devices": [
                    {
                        "type_key": "Juniper",
                        "host": "10.0.0.1",
                        "credentials": {
                            "username": "admin",
                            "password": "fake-test-password",
                        },
                    }
                ]
            },
        )
        # CLAUDE.md hard rule: GET, don't trust POST body for final state.
        job_id = post.json()["id"]
        job = junos_desktop_client.get(f"/api/v1/backups/{job_id}").json()
        assert job["status"] == "completed"
