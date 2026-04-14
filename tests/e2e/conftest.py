"""
E2E test fixtures: live Uvicorn server + Playwright browser.

Architecture
------------
* A **session-scoped** Uvicorn server is started in a daemon thread so it
  persists for the entire test session.  This avoids the cost of starting and
  stopping a server per test.
* ``get_collector`` is patched at the module level before ``create_app`` is
  called, so every background backup task returns canned output without
  attempting real SSH connections.
* The ``base_url`` fixture override tells pytest-playwright to resolve all
  relative ``page.goto("/...")`` calls against the live server URL.
* The Playwright ``page`` fixture is function-scoped (pytest-playwright default),
  so each test gets a fresh browser page with a clean history and local storage.

Running E2E tests
-----------------
E2E tests require both Playwright browsers and a working Python environment::

    playwright install chromium
    pytest tests/e2e -m e2e -v

To skip E2E tests (e.g. in CI without a display)::

    pytest -m "not e2e"
"""
from __future__ import annotations

import socket
import textwrap
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.conftest import CISCO_FAKE_OUTPUT, FakeCollector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Bind to port 0 to let the OS assign a free port, then release it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


_CISCO_YAML = textwrap.dedent("""\
    vendor: Cisco
    os: IOS-XE
    type_key: Cisco
    priority: 10
    file_extension: cfg
    connection:
      needs_enable: true
      handle_paging: true
      needs_shell_menu: false
    commands:
      config: "show running-config"
    collector:
      strategy: netmiko
      netmiko_device_type: cisco_xe
    notes: Cisco IOS-XE E2E test definition.
""")

_OPNSENSE_YAML = textwrap.dedent("""\
    vendor: OPNsense
    os: OPNsense
    type_key: OPNsense
    priority: 10
    file_extension: xml
    connection:
      needs_shell_menu: true
    commands:
      config: "cat /conf/config.xml"
    collector:
      strategy: paramiko_shell
    notes: OPNsense E2E test definition.
""")


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _e2e_definitions_dir(tmp_path_factory) -> Path:
    """Session-scoped definition directory with two test YAML files."""
    defs_dir: Path = tmp_path_factory.mktemp("e2e_defs")
    (defs_dir / "cisco").mkdir()
    (defs_dir / "cisco" / "cisco.yaml").write_text(_CISCO_YAML, encoding="utf-8")
    (defs_dir / "opnsense").mkdir()
    (defs_dir / "opnsense" / "opnsense.yaml").write_text(
        _OPNSENSE_YAML, encoding="utf-8"
    )
    return defs_dir


@pytest.fixture(scope="session")
def _e2e_configs_dir(tmp_path_factory) -> Path:
    """Session-scoped empty configs directory."""
    return tmp_path_factory.mktemp("e2e_configs")


@pytest.fixture(scope="session")
def live_server_url(_e2e_definitions_dir: Path, _e2e_configs_dir: Path) -> str:
    """Start a Uvicorn server in a daemon thread and return its base URL.

    The server is started once per test session and torn down when the session
    ends.  ``get_collector`` is patched so no real SSH connections are attempted.
    """
    import uvicorn

    from netconfig.config import Settings
    from netconfig.main import create_app

    settings = Settings(
        definitions_dir=_e2e_definitions_dir,
        configs_dir=_e2e_configs_dir,
    )

    port = _find_free_port()

    fake = FakeCollector(output=CISCO_FAKE_OUTPUT)
    with patch(
        "netconfig.api.routes.backups.get_collector",
        return_value=fake,
    ):
        app = create_app(settings)
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        # Wait for the server to accept connections (up to 10 seconds)
        import httpx

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                httpx.get(f"http://127.0.0.1:{port}/", timeout=0.5)
                break
            except Exception:
                time.sleep(0.1)
        else:
            server.should_exit = True
            raise RuntimeError(
                f"E2E live server on port {port} did not respond within 10 seconds"
            )

        yield f"http://127.0.0.1:{port}"

        server.should_exit = True
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def base_url(live_server_url: str) -> str:
    """Override pytest-playwright's ``base_url`` to point at the live server.

    With this in place, ``page.goto("/")`` resolves to
    ``http://127.0.0.1:<port>/`` inside all E2E tests.
    """
    return live_server_url
