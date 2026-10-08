"""
Desktop smoke test — the embedded server serves target-profile
provenance exactly as the web platform does.

Target profiles are pure data and the rename modal is a pure UI page, so
the desktop platform needs no code of its own to show a profile's
deployment state, evidence grade and caveat.  What it does need is for
the embedded ``ServerThread`` to put them on the wire and to serve
the page element that renders them — this test proves both, so a future
change that drops the fields from the response model (or the notice from
the template) fails on the desktop tier and not only on the web tier.

Complements ``tests/integration/test_migration_target_profiles_api.py``
(TestClient) and ``tests/e2e/test_migrate_rename_modal.py`` (browser).
"""

from __future__ import annotations

import json
import shutil
import socket
import urllib.request
from unittest.mock import patch

import pytest

from netcanon.config import Settings
from netcanon.definitions import LIBRARY_DIR
from netcanon.main import create_app
from netcanon_desktop.server import ServerThread
from tests.conftest import FakeCollector

pytestmark = pytest.mark.desktop


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _settings(tmp_path) -> Settings:
    # The whole shipped library, not just target_profiles/: the embedded
    # server's readiness probe requests the dashboard, which needs at
    # least one device definition to render.
    defs = tmp_path / "definitions"
    shutil.copytree(LIBRARY_DIR, defs)
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    return Settings(
        definitions_dir=defs, configs_dir=configs_dir, backup_concurrency=1,
    )


def _get(port: int, path: str) -> str:
    url = f"http://127.0.0.1:{port}{path}"
    with urllib.request.urlopen(url, timeout=5) as resp:
        assert resp.status == 200, path
        return resp.read().decode("utf-8")


class TestProfileProvenanceServedByEmbeddedServer:
    def test_provenance_reaches_the_wire_and_the_page(self, tmp_path):
        app = create_app(_settings(tmp_path))
        port = _free_port()
        with patch(
            "netcanon.api.routes.backups.get_collector",
            return_value=FakeCollector(output="! noop\n"),
        ):
            server = ServerThread(app, port=port, log_level="critical")
            server.start()
            try:
                server.wait_ready(timeout=10.0)
                profiles = json.loads(
                    _get(port, "/api/v1/migration/target-profiles")
                )
                migrate_html = _get(port, "/migrate")
                definitions_html = _get(port, "/definitions")
            finally:
                server.stop()
                server.join(timeout=5.0)

        by_key = {f"{p['vendor']}/{p['model']}": p for p in profiles}

        # Every profile serialises the provenance fields, graded or not.
        for key, profile in by_key.items():
            for field in ("deployment_state", "evidence", "evidence_ref", "caveat"):
                assert field in profile, (key, field)

        # A capture-backed profile carries its grade and its fixture.
        c9300 = by_key["cisco_iosxe/C9300-24UX"]
        assert c9300["evidence"] == "capture"
        assert c9300["evidence_ref"].startswith("tests/fixtures/real/")
        assert c9300["deployment_state"]

        # An unverified profile carries the caveat the operator must see.
        inferred = [p for p in profiles if p["evidence"] == "inferred"]
        assert inferred, "no profile is graded `inferred` any more"
        assert all(p["caveat"].strip() for p in inferred)

        # The rename modal ships the element that renders them, and the
        # definitions browser lists them.
        assert 'data-testid="migrate-rename-profile-notice"' in migrate_html
        assert "renderProfileNotice" in migrate_html
        assert 'data-testid="profile-evidence"' in definitions_html
        assert 'data-testid="profile-deployment-state"' in definitions_html
        assert 'data-testid="profile-caveat"' in definitions_html
