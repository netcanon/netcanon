"""
Desktop smoke test confirming the embedded server serves the shipped
Arista EOS 4.32 device definition.

The embedded server is the same FastAPI app the web platform runs —
this test wires the definition tree from the repo root into a fresh
``Settings`` and verifies that:

* the Arista YAML loads cleanly through the production
  ``DefinitionLoader``
* the embedded ASGI server (``ServerThread``) starts, becomes ready,
  and responds 200 to ``GET /api/v1/definitions/Arista``

No real SSH happens — backup execution is exercised in the
integration tier.  This tier locks in the desktop-specific contract
that *the same server code* the desktop ships will surface the new
device definition.
"""

from __future__ import annotations

import socket
import urllib.request
from pathlib import Path

from netconfig.config import Settings
from netconfig.definitions.loader import DefinitionLoader
from netconfig.main import create_app
from netconfig_desktop.server import ServerThread

# Note: desktop tests share the test directory without a dedicated
# pytest marker — the suite is gated on the testpath ``tests/desktop``
# rather than a marker (matches existing convention in this dir).


REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED_DEFINITIONS_DIR = REPO_ROOT / "definitions"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestAristaDefinitionLoadsForDesktop:
    """The shipped YAML must validate through the production loader so
    the desktop's embedded server can serve it.  This guards against a
    schema-incompatible edit slipping in unnoticed."""

    def test_arista_appears_in_loaded_definitions(self):
        loader = DefinitionLoader(SHIPPED_DEFINITIONS_DIR)
        defs = loader.load_all()
        assert "Arista" in defs, (
            "Arista type_key not loaded — desktop will not surface "
            "backups against EOS devices."
        )

    def test_arista_collector_strategy_is_netmiko(self):
        loader = DefinitionLoader(SHIPPED_DEFINITIONS_DIR)
        defs = loader.load_all()
        arista = defs["Arista"]
        assert arista.collector.strategy == "netmiko"
        assert arista.collector.netmiko_device_type == "arista_eos"


class TestAristaDefinitionViaEmbeddedServer:
    """Spin up the same ``ServerThread`` the desktop entrypoint uses
    and confirm the Arista definition is reachable over HTTP at
    ``GET /api/v1/definitions/Arista``."""

    def test_definition_listed_via_embedded_server(self, tmp_path):
        configs_dir = tmp_path / "configs"
        configs_dir.mkdir()
        settings = Settings(
            definitions_dir=SHIPPED_DEFINITIONS_DIR,
            configs_dir=configs_dir,
            backup_concurrency=1,
        )
        app = create_app(settings)

        port = _free_port()
        server = ServerThread(app, port=port, log_level="critical")
        server.start()
        try:
            server.wait_ready(timeout=10.0)
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/v1/definitions/Arista",
                timeout=5,
            ) as resp:
                assert resp.status == 200
                body = resp.read().decode("utf-8")
            # Spot-check key fields without re-parsing JSON — keeps the
            # test resilient to incidental field-order changes.
            assert '"vendor"' in body and "Arista" in body
            assert '"netmiko_device_type"' in body and "arista_eos" in body
        finally:
            server.stop()
            server.join(timeout=5.0)
