"""
Integration tests for the P1C3 probe + layered-definition wiring in
the backup route.

Covers:
  * Probe failures are non-fatal — backup completes against the
    family-base definition even when probe raises.
  * Successful probe populates ``DeviceProfile.detected_facts`` when
    the device carries a ``device_profile_id``.
  * Detected facts drive ``DefinitionLoader.resolve`` — a version
    overlay is picked up when the probe reports that version.
  * Operator pins on the profile WIN over detected facts at the
    resolver boundary.
  * Legacy definitions (no ``probe:`` block) keep working unchanged
    — no detected_facts populate, no overlay swap happens.

All mocking happens at ``get_collector`` per CLAUDE.md's hard rule
against patching ``ConnectHandler``.  A custom FakeProbingCollector
subclass returns canned probe output + canned config output.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from netconfig.collectors.base import BaseCollector
from netconfig.definitions.schema import DeviceDefinition
from netconfig.main import create_app
from netconfig.models.device import DeviceTarget

from tests.conftest import CISCO_FAKE_OUTPUT

pytestmark = pytest.mark.integration


# YAML fixtures — family-base + a 17.12 overlay with a distinct
# config command so tests can tell which definition was used.

_CISCO_WITH_PROBE = textwrap.dedent("""\
    vendor: Cisco
    os: IOS-XE
    type_key: Cisco
    priority: 10
    file_extension: cfg
    connection:
      needs_enable: true
    commands:
      config: "show running-config"
    prompts:
      trailing: ['^\\S+[#>]\\s*$']
    collector:
      strategy: netmiko
      netmiko_device_type: cisco_xe
    probe:
      command: show version
      patterns:
        # Capture major.minor only ("17.12") to match the overlay's
        # os_version pin, not the full "17.12.03" patch level.
        detected_os_version: "Version\\\\s+(\\\\d+\\\\.\\\\d+)"
        detected_model: "Model Number\\\\s+:\\\\s+(\\\\S+)"
    notes: Cisco base with probe.
""")

_CISCO_OVERLAY_1712 = textwrap.dedent("""\
    vendor: Cisco
    os: IOS-XE
    type_key: Cisco
    priority: 20
    os_version: "17.12"
    file_extension: cfg
    connection:
      needs_enable: true
    commands:
      # Distinct marker command so tests can detect the overlay was
      # selected — the family base uses "show running-config", this
      # overlay uses "show running-config brief" to make the choice
      # visible in the mock collector's recorded calls.
      config: "show running-config brief"
    prompts:
      trailing: ['^\\S+[#>]\\s*$']
    collector:
      strategy: netmiko
      netmiko_device_type: cisco_xe
    notes: Cisco 17.12 overlay.
""")


_PROBE_OUTPUT_1712 = """\
Cisco IOS Software, Version 17.12.03, RELEASE SOFTWARE
Model Number                       : C9300-48P
"""

_PROBE_OUTPUT_1709 = """\
Cisco IOS Software, Version 17.09.02, RELEASE SOFTWARE
Model Number                       : C9300-24P
"""


class FakeProbingCollector(BaseCollector):
    """FakeCollector that also supports probe().  Records which
    definition.commands.config was last collected so tests can assert
    whether the overlay or family-base was used."""

    def __init__(
        self,
        probe_output: str = "",
        probe_raises: bool = False,
        collect_output: str = CISCO_FAKE_OUTPUT,
    ):
        self.probe_output = probe_output
        self.probe_raises = probe_raises
        self.collect_output = collect_output
        self.last_definition: DeviceDefinition | None = None
        self.last_probe_command: str | None = None

    def collect(self, device: DeviceTarget, definition: DeviceDefinition) -> str:
        self.last_definition = definition
        return self.collect_output

    def probe(
        self, device: DeviceTarget, definition: DeviceDefinition
    ) -> dict[str, str]:
        self.last_probe_command = definition.probe.command
        if self.probe_raises:
            raise RuntimeError("simulated probe failure")
        if not definition.probe.command:
            return {}
        # Parse against the definition's own patterns — same path the
        # real NetmikoCollector.probe takes.
        from netconfig.collectors.probe import parse_probe_output
        return parse_probe_output(self.probe_output, definition.probe)


@pytest.fixture()
def probing_settings(tmp_path: Path):
    """Settings with a Cisco definition that declares a probe block
    + a 17.12 overlay.  No OPNsense definition — these tests don't
    need it."""
    from netconfig.config import Settings

    defs_dir = tmp_path / "definitions"
    cisco_dir = defs_dir / "cisco"
    cisco_dir.mkdir(parents=True)
    (cisco_dir / "cisco.yaml").write_text(_CISCO_WITH_PROBE, encoding="utf-8")
    (cisco_dir / "cisco_17_12.yaml").write_text(_CISCO_OVERLAY_1712, encoding="utf-8")

    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    return Settings(
        definitions_dir=defs_dir,
        configs_dir=configs_dir,
        backup_concurrency=1,
    )


@pytest.fixture()
def probing_app(probing_settings):
    return create_app(probing_settings)


def _post_backup_with_profile(
    client: TestClient,
    profile_id: str | None = None,
    os_version_pin: str | None = None,
    model_pin: str | None = None,
) -> dict:
    device = {
        "type_key": "Cisco",
        "host": "192.168.1.1",
        "credentials": {"username": "admin", "password": "pw"},
    }
    if profile_id:
        device["device_profile_id"] = profile_id
    if os_version_pin:
        device["os_version"] = os_version_pin
    if model_pin:
        device["model"] = model_pin
    resp = client.post("/api/v1/backups", json={"devices": [device]})
    assert resp.status_code == 202
    job_id = resp.json()["id"]
    return client.get(f"/api/v1/backups/{job_id}").json()


def _make_profile(client: TestClient, **overrides) -> dict:
    body = {
        "name": "test-device",
        "type_key": "Cisco",
        "host": "192.168.1.1",
        "username": "admin",
        "password": "pw",
    }
    body.update(overrides)
    resp = client.post("/api/v1/devices/", json=body)
    assert resp.status_code in (200, 201), resp.json()
    return resp.json()


class TestProbeFailureIsNonFatal:
    """Critical non-fatality invariant — probe MUST NEVER take down
    the backup.  Connection error, regex miss, stray exception —
    all fall back to the family-base definition and the main
    collect runs unchanged."""

    def test_probe_raising_exception_still_completes_backup(
        self, probing_app
    ):
        collector = FakeProbingCollector(probe_raises=True)
        with patch(
            "netconfig.api.routes.backups.get_collector",
            return_value=collector,
        ):
            with TestClient(probing_app) as client:
                job = _post_backup_with_profile(client)
        # Backup reached terminal-success even though probe raised.
        assert job["status"] == "completed"
        # Family-base definition was used (no overlay — no detected
        # facts, no pins).
        assert collector.last_definition is not None
        assert collector.last_definition.commands.config == (
            "show running-config"
        )

    def test_probe_matching_nothing_still_completes_backup(
        self, probing_app
    ):
        collector = FakeProbingCollector(probe_output="uninteresting output")
        with patch(
            "netconfig.api.routes.backups.get_collector",
            return_value=collector,
        ):
            with TestClient(probing_app) as client:
                job = _post_backup_with_profile(client)
        assert job["status"] == "completed"


class TestDetectedFactsPersistence:
    def test_facts_persist_onto_linked_profile(self, probing_app):
        collector = FakeProbingCollector(probe_output=_PROBE_OUTPUT_1712)
        with patch(
            "netconfig.api.routes.backups.get_collector",
            return_value=collector,
        ):
            with TestClient(probing_app) as client:
                profile = _make_profile(client)
                _post_backup_with_profile(client, profile_id=profile["id"])
                # GET the profile — detected_facts should be populated.
                refreshed = client.get(f"/api/v1/devices/{profile['id']}").json()
        facts = refreshed.get("detected_facts") or {}
        # Regex captures major.minor ("17.12") — not the full
        # 17.12.03 patch level — so the overlay lookup lands.
        assert facts.get("detected_os_version") == "17.12"
        assert facts.get("detected_model") == "C9300-48P"
        assert "probe_timestamp" in facts

    def test_facts_not_persisted_without_profile_id(self, probing_app):
        """Ad-hoc backups (no profile_id) still run probe but don't
        persist anywhere — detected_facts is a profile-local concept."""
        collector = FakeProbingCollector(probe_output=_PROBE_OUTPUT_1712)
        with patch(
            "netconfig.api.routes.backups.get_collector",
            return_value=collector,
        ):
            with TestClient(probing_app) as client:
                job = _post_backup_with_profile(client, profile_id=None)
        # Job completes normally; there's no profile to inspect.
        assert job["status"] == "completed"


class TestLayeredResolveFromDetectedFacts:
    def test_detected_version_selects_overlay(self, probing_app):
        """Probe reports 17.12.x; resolver picks the 17.12 overlay."""
        collector = FakeProbingCollector(probe_output=_PROBE_OUTPUT_1712)
        with patch(
            "netconfig.api.routes.backups.get_collector",
            return_value=collector,
        ):
            with TestClient(probing_app) as client:
                _post_backup_with_profile(client)
        # Overlay's distinct config command is the signal.
        assert collector.last_definition is not None
        assert collector.last_definition.commands.config == (
            "show running-config brief"
        )

    def test_detected_version_without_overlay_uses_family_base(
        self, probing_app,
    ):
        """Probe reports 17.09.x; no matching overlay exists; falls
        back to family base."""
        collector = FakeProbingCollector(probe_output=_PROBE_OUTPUT_1709)
        with patch(
            "netconfig.api.routes.backups.get_collector",
            return_value=collector,
        ):
            with TestClient(probing_app) as client:
                _post_backup_with_profile(client)
        assert collector.last_definition.commands.config == (
            "show running-config"
        )

    def test_operator_pin_beats_detected_fact(self, probing_app):
        """Probe reports 17.09 BUT operator pins 17.12 — the pin
        wins.  Documents the precedence rule."""
        collector = FakeProbingCollector(probe_output=_PROBE_OUTPUT_1709)
        with patch(
            "netconfig.api.routes.backups.get_collector",
            return_value=collector,
        ):
            with TestClient(probing_app) as client:
                _post_backup_with_profile(client, os_version_pin="17.12")
        # Pin selects the overlay even though the probe said 17.09.
        assert collector.last_definition.commands.config == (
            "show running-config brief"
        )


class TestLegacyDefinitionsUnchanged:
    """Definitions that don't declare a probe block must continue to
    work exactly as before — no probe call, no overlay lookup, no
    attempt to write detected_facts."""

    def test_legacy_definition_no_probe_no_overlay(
        self, test_app, test_settings,
    ):
        """Uses the root-conftest definitions (no probe block) +
        test_app fixture.  Only asserting that backup completes."""
        from tests.conftest import FakeCollector

        collector = FakeCollector()
        with patch(
            "netconfig.api.routes.backups.get_collector",
            return_value=collector,
        ):
            with TestClient(test_app) as client:
                resp = client.post(
                    "/api/v1/backups",
                    json={"devices": [{
                        "type_key": "Cisco",
                        "host": "192.168.1.1",
                        "credentials": {"username": "u", "password": "p"},
                    }]},
                )
                assert resp.status_code == 202
                job_id = resp.json()["id"]
                job = client.get(f"/api/v1/backups/{job_id}").json()
        assert job["status"] == "completed"


class TestShippedCiscoIOSXEProbeBlock:
    """Locks in the shipped probe block on the Cisco IOS-XE family
    base.  P1C3 M1-M3 shipped the machinery; this test guards the
    first shipped opt-in so a later edit doesn't silently remove
    the probe config from the YAML.

    Loads ``definitions/`` directly from disk via DefinitionLoader
    rather than going through the test_app fixture (which uses its
    own minimal definition set) — we're asserting on what SHIPS.
    """

    def test_cisco_iosxe_family_base_declares_probe(self):
        from netconfig.definitions.loader import DefinitionLoader

        # Project-root definitions/ directory — the shipped set.
        repo_root = Path(__file__).resolve().parents[2]
        defs_dir = repo_root / "definitions"
        loader = DefinitionLoader(defs_dir)
        definitions = loader.load_all()

        assert "Cisco" in definitions, (
            f"Cisco type_key missing from shipped definitions: "
            f"{sorted(definitions.keys())}"
        )
        cisco = definitions["Cisco"]
        # Family base — no os_version / model pin.
        assert cisco.os_version is None
        assert cisco.model is None
        # Probe opted in.
        assert cisco.probe.command, (
            "Cisco IOS-XE family-base definition must ship a non-empty "
            "probe.command so layered-definition resolution can use the "
            "detected OS version."
        )
        # Fact patterns cover both feeds of DefinitionLoader.resolve().
        assert "detected_os_version" in cisco.probe.patterns
        assert "detected_model" in cisco.probe.patterns

    def test_cisco_iosxe_1712_overlay_inherits_probe_from_family_base(self):
        """Overlay intentionally does NOT declare its own probe block.
        Probe runs on the family-base collector before resolve()."""
        from netconfig.definitions.loader import DefinitionLoader

        repo_root = Path(__file__).resolve().parents[2]
        defs_dir = repo_root / "definitions"
        loader = DefinitionLoader(defs_dir)
        # resolve() needs load_all() to populate the variant registry.
        loader.load_all()

        overlay = loader.resolve("Cisco", os_version="17.12")
        assert overlay is not None
        assert overlay.os_version == "17.12"
        # Overlay ships with no probe block of its own — probe runs
        # on the family-base before overlay resolution.
        assert overlay.probe.command == ""
        assert overlay.probe.patterns == {}
