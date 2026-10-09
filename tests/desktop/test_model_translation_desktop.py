"""
Desktop smoke test — the embedded server does model-to-model port
mapping exactly as the web platform does.

Device-model families are data and the mapping is server logic, so the
desktop platform needs no code of its own.  What it does need is for
the embedded ``ServerThread`` to load the families at startup, serve
them, compile an inventory and run a plan with both devices declared.
This proves all four, so a change that wires the feature into the web
app only (a lifespan step the desktop build skips, say) fails on the
desktop tier and not only on the web tier.

Complements ``tests/integration/test_migration_models_api.py``
(TestClient).
"""

from __future__ import annotations

import json
import logging
import shutil
import socket
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from netcanon.config import Settings
from netcanon.definitions import LIBRARY_DIR
from netcanon.main import create_app
from netcanon_desktop.server import ServerThread
from tests.conftest import FakeCollector

pytestmark = pytest.mark.desktop

REPO_ROOT = Path(__file__).resolve().parents[2]
CAPTURE_2930F = (
    REPO_ROOT / "tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1607_intervlan.cfg"
).read_text(encoding="utf-8")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _settings(tmp_path: Path) -> Settings:
    # The whole shipped library, as the MSI lays it out next to the
    # executable: device definitions, target profiles and model
    # families under one definitions directory.
    defs = tmp_path / "definitions"
    shutil.copytree(LIBRARY_DIR, defs)
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    return Settings(
        definitions_dir=defs, configs_dir=configs_dir, backup_concurrency=1,
    )


def _get(port: int, path: str) -> object:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as resp:
        assert resp.status == 200, path
        return json.loads(resp.read().decode("utf-8"))


def _post(port: int, path: str, body: dict) -> object:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as resp:
        assert resp.status == 200, path
        return json.loads(resp.read().decode("utf-8"))


class TestModelTranslationServedByEmbeddedServer:
    def test_families_inventory_and_a_declared_plan(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger="netcanon.migration.device_models")
        app = create_app(_settings(tmp_path))
        port = _free_port()
        target = {
            "mode": "stacked",
            "members": [{"model": "JL322A", "modules": {"A": "JL083A"}}],
        }
        with patch(
            "netcanon.api.routes.backups.get_collector",
            return_value=FakeCollector(output="! noop\n"),
        ):
            server = ServerThread(app, port=port, log_level="critical")
            server.start()
            try:
                server.wait_ready(timeout=10.0)
                families = _get(port, "/api/v1/migration/model-families")
                inventory = _post(port, "/api/v1/migration/inventory", {
                    "codec": "aruba_aoss", "deployment": target,
                })
                job = _post(port, "/api/v1/migration/plan", {
                    "source": "aruba_aoss",
                    "target": "aruba_aoss",
                    "raw_text": CAPTURE_2930F,
                    "source_deployment": {
                        "mode": "standalone", "members": [{"model": "JL260A"}],
                    },
                    "target_deployment": target,
                })
            finally:
                server.stop()
                server.join(timeout=5.0)

        # The shipped families are loaded.  The definitions directory
        # here IS a copy of the library, as on an installed desktop:
        # the copy must be recognised as the same families, not
        # refused as a conflicting second set -- which would show as
        # one warning per family at every start.
        keys = [f"{f['vendor']}/{f['family']}" for f in families]
        assert "aruba_aoss/2930F" in keys and "aruba_aoss/2930M" in keys
        loader_warnings = [
            record.getMessage() for record in caplog.records
            if record.name == "netcanon.migration.device_models"
        ]
        assert not loader_warnings, loader_warnings

        # An inventory is compiled on the server, by the naming rule.
        names = [p["name"] for p in inventory["ports"]]
        assert names[0] == "1/1" and names[-1] == "1/A4"

        # A plan with both devices declared pairs ports by position.
        assert job["status"] == "completed"
        assert job["port_renames"]["49"] == "1/A1"
        assert len(job["port_mapping_plan"]["pairings"]) == 52
        assert "untagged 1/48,1/A1,1/A2,1/A3,1/A4" in job["rendered"]
