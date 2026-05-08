"""
Desktop smoke test — confirm the embedded server serves the shipped
Aruba AOS-S 16.x device definition over HTTP exactly as the web
platform does.

This complements ``tests/integration/test_backups_aruba.py``: the
integration tier uses ``TestClient`` against a synthetically-built
app, while this desktop tier wires the *real* embedded ASGI server
(``ServerThread``) up to the same FastAPI factory and confirms the
definition reaches the wire.

No real SSH ever runs — the backup collector is replaced with a
``FakeCollector`` returning canned AOS-S output, so the test
demonstrates end-to-end serving without device dependence.
"""

from __future__ import annotations

import shutil
import socket
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from netcanon.config import Settings
from netcanon.main import create_app
from netcanon_desktop.server import ServerThread
from tests.conftest import FakeCollector

pytestmark = pytest.mark.desktop


REPO_ROOT = Path(__file__).resolve().parents[2]
ARUBA_DEF_SRC = REPO_ROOT / "definitions" / "aruba" / "aos-s" / "16.x.yaml"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_settings_with_aruba(tmp_path) -> Settings:
    """Build a Settings whose definitions tree contains a copy of the
    real Aruba YAML alongside the rest of the shipped definitions."""
    defs = tmp_path / "definitions"
    defs.mkdir()
    # Mirror just the Aruba subtree; that's the file under test.
    aruba_dst = defs / "aruba" / "aos-s"
    aruba_dst.mkdir(parents=True)
    shutil.copy(ARUBA_DEF_SRC, aruba_dst / "16.x.yaml")
    # We also copy in target_profiles so create_app's migration wiring
    # finds the directory at startup (parity with the production tree).
    src_profiles = REPO_ROOT / "definitions" / "target_profiles"
    if src_profiles.is_dir():
        shutil.copytree(src_profiles, defs / "target_profiles")

    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    return Settings(
        definitions_dir=defs,
        configs_dir=configs_dir,
        backup_concurrency=1,
    )


class TestArubaDefinitionServedByEmbeddedServer:
    """Embedded server serves the Aruba definition over real HTTP."""

    def test_definition_listed_via_embedded_server(self, tmp_path):
        settings = _build_settings_with_aruba(tmp_path)
        app = create_app(settings)
        port = _free_port()

        # Patch the collector factory so any inadvertent backup attempt
        # is harmless (no SSH).  The smoke check below only hits GET
        # endpoints, but defence-in-depth is cheap.
        with patch(
            "netcanon.api.routes.backups.get_collector",
            return_value=FakeCollector(output="! noop\n"),
        ):
            server = ServerThread(app, port=port, log_level="critical")
            server.start()
            try:
                server.wait_ready(timeout=10.0)
                url = f"http://127.0.0.1:{port}/api/v1/definitions/Aruba"
                with urllib.request.urlopen(url, timeout=3) as resp:
                    assert resp.status == 200
                    body = resp.read().decode("utf-8")
                # Smoke-level fields — full schema validation is in
                # tests/unit/test_aruba_aoss_definition.py.
                assert '"type_key":"Aruba"' in body or \
                       '"type_key": "Aruba"' in body
                assert '"netmiko_device_type":"aruba_osswitch"' in body or \
                       '"netmiko_device_type": "aruba_osswitch"' in body
            finally:
                server.stop()
                server.join(timeout=5.0)
