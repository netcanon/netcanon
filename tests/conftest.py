"""
Root pytest fixtures shared across all test layers.

Automatically imported by pytest for every test module.  Function-scoped
fixtures (the default) give each test a completely isolated environment:
fresh tmp directories, a new ``FileConfigStore``, and a new ``FastAPI``
application instance created via the ``create_app(settings)`` factory.

Session-scoped resources for the live-server E2E layer live in
``tests/e2e/conftest.py`` so they don't slow down unit and integration runs.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from netconfig.collectors.base import BaseCollector
from netconfig.config import Settings
from netconfig.definitions.schema import DeviceDefinition
from netconfig.models.device import DeviceTarget


# ---------------------------------------------------------------------------
# Canned YAML strings written to tmp directories
# ---------------------------------------------------------------------------

CISCO_YAML = textwrap.dedent("""\
    vendor: Cisco
    os: IOS-XE
    type_key: Cisco
    priority: 10
    file_extension: cfg
    connection:
      needs_enable: true
      cisco_more_paging: true
      opnsense_shell_menu: false
    commands:
      pre: []
      config: "show running-config"
      post: []
    prompts:
      trailing:
        - '^\\S+[#>]\\s*$'
    collector:
      strategy: netmiko
      netmiko_device_type: cisco_xe
    notes: Cisco IOS-XE test definition.
""")

OPNSENSE_YAML = textwrap.dedent("""\
    vendor: OPNsense
    os: OPNsense
    type_key: OPNsense
    priority: 10
    file_extension: xml
    connection:
      needs_enable: false
      cisco_more_paging: false
      opnsense_shell_menu: true
    commands:
      pre: []
      config: "cat /conf/config.xml"
      post:
        - "exit"
    prompts:
      trailing:
        - '^root@\\S+:.*[#$]\\s*$'
    collector:
      strategy: paramiko_shell
    notes: OPNsense test definition.
""")


# ---------------------------------------------------------------------------
# Canned SSH output
# ---------------------------------------------------------------------------

CISCO_FAKE_OUTPUT = (
    "Building configuration...\n\n"
    "Current configuration : 1234 bytes\n"
    "!\nversion 17.9\nhostname Router\n!\nend\n"
)
OPNSENSE_FAKE_OUTPUT = (
    '<?xml version="1.0"?>\n'
    "<opnsense><version>25.1</version></opnsense>\n"
)


# ---------------------------------------------------------------------------
# FakeCollector — drop-in for real SSH, used by integration and E2E tests
# ---------------------------------------------------------------------------


class FakeCollector(BaseCollector):
    """Synchronous collector that returns canned output without SSH.

    Pass a custom *output* string to tailor the fake response; the default
    is a minimal Cisco running-config snippet suitable for most tests.

    This class is defined here (not in a helper module) so it is importable
    from ``conftest`` without extra sys.path manipulation.
    """

    def __init__(self, output: str = CISCO_FAKE_OUTPUT) -> None:
        self._output = output

    def collect(
        self,
        device: DeviceTarget,  # noqa: ARG002
        definition: DeviceDefinition,  # noqa: ARG002
    ) -> str:
        """Return the canned output regardless of device or definition."""
        return self._output


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_definitions_dir(tmp_path: Path) -> Path:
    """Tmp directory populated with two valid YAML definition files.

    Creates the following layout::

        <tmp>/
          definitions/
            cisco/cisco.yaml        (Cisco IOS-XE, strategy=netmiko)
            opnsense/opnsense.yaml  (OPNsense, strategy=paramiko_shell)

    Returns the ``definitions/`` path — pass this to ``Settings.definitions_dir``.
    """
    defs_dir = tmp_path / "definitions"
    (defs_dir / "cisco").mkdir(parents=True)
    (defs_dir / "cisco" / "cisco.yaml").write_text(CISCO_YAML, encoding="utf-8")
    (defs_dir / "opnsense").mkdir()
    (defs_dir / "opnsense" / "opnsense.yaml").write_text(OPNSENSE_YAML, encoding="utf-8")
    return defs_dir


@pytest.fixture()
def test_settings(sample_definitions_dir: Path, tmp_path: Path) -> Settings:
    """``Settings`` instance wired to test-only tmp directories.

    * ``definitions_dir``   → ``<tmp>/definitions/`` (two test definitions)
    * ``configs_dir``       → ``<tmp>/configs/``      (empty initially)
    * ``backup_concurrency`` → ``1`` — tests default to serial execution
      so device status transitions are deterministic and ordering-sensitive
      assertions stay stable.  Override per-test via
      ``test_settings.model_copy(update={"backup_concurrency": N})`` when
      you explicitly want to exercise the thread pool.
    """
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    return Settings(
        definitions_dir=sample_definitions_dir,
        configs_dir=configs_dir,
        backup_concurrency=1,
    )


@pytest.fixture()
def test_app(test_settings: Settings):
    """Fresh ``FastAPI`` application instance created from *test_settings*.

    Each test that requests this fixture gets an independent application with
    its own in-memory job registry and its own ``FileConfigStore``.
    """
    from netconfig.main import create_app

    return create_app(test_settings)


@pytest.fixture()
def fake_collector() -> FakeCollector:
    """A ``FakeCollector`` returning the default Cisco canned output."""
    return FakeCollector()
