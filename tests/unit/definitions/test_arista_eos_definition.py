"""
Unit tests for the shipped ``definitions/arista/eos/4.32.yaml`` definition.

Locks in the schema fields the backup pipeline relies on (collector
strategy, netmiko device-type, paging mode) and exercises the probe
regex map against synthetic-but-realistic Arista EOS ``show version``
output fragments.  Catches regex regressions before they hit a live
device.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from netcanon.collectors.probe import PROBE_TIMESTAMP_KEY, parse_probe_output
from netcanon.definitions.loader import DefinitionLoader
from netcanon.definitions.schema import DeviceDefinition

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_REPO_ROOT = Path(__file__).resolve().parents[3]
_ARISTA_DEFINITION_PATH = _REPO_ROOT / "definitions" / "arista" / "eos" / "4.32.yaml"


def _load_definition() -> DeviceDefinition:
    """Parse the shipped Arista EOS YAML directly through the schema."""
    raw = yaml.safe_load(_ARISTA_DEFINITION_PATH.read_text(encoding="utf-8"))
    return DeviceDefinition(**raw)


# Synthetic ``show version`` outputs covering the chassis families the
# regex must survive.  Realistic enough for regex testing — drawn from
# Arista EOS user guide examples — but contain no real serial numbers.

_SHOW_VERSION_DCS_7050 = """\
Arista DCS-7050SX-64-F
Hardware version:    11.04
Serial number:       JPE13120914ABC
System MAC address:  001c.7300.0aaa

Software image version: 4.32.0F
Architecture:           x86_64
Internal build version: 4.32.0F-39879672.4320F
Internal build ID:      f7b1c2c3-aaaa-bbbb-cccc-1234567890ab
Image format version:   3.0
Image optimization:     Default

Uptime:                 19 weeks, 1 day, 23 hours and 11 minutes
Total memory:           7820360 kB
Free memory:            5236708 kB
"""

_SHOW_VERSION_VEOS = """\
Arista vEOS-lab
Hardware version:
Serial number:           VM12345
System MAC address:      0800.27aa.bbcc

Software image version: 4.32.1F-EFT1
Architecture:           x86_64
Internal build version: 4.32.1F-EFT1-99999.4321FEFT1
Internal build ID:      deadbeef-1234-5678-9abc-def012345678

Uptime:                 0 weeks, 0 days, 1 hour and 7 minutes
Total memory:           2018212 kB
Free memory:            1456320 kB
"""

_SHOW_VERSION_CCS = """\
Arista CCS-720XP-48Y6
Hardware version:    01.20
Serial number:       JAS22340000XYZ
System MAC address:  fc:bd:67:00:00:01

Software image version: 4.32.2F
Architecture:           x86_64
Internal build version: 4.32.2F-44444.4322F

Uptime:                 5 weeks
Total memory:           4039244 kB
Free memory:            2811420 kB
"""


# ---------------------------------------------------------------------------
# Schema + collector wiring
# ---------------------------------------------------------------------------


class TestSchemaCompliance:
    """The shipped YAML must validate against ``DeviceDefinition``."""

    def test_definition_file_exists(self):
        assert _ARISTA_DEFINITION_PATH.is_file(), (
            f"Expected Arista EOS definition at {_ARISTA_DEFINITION_PATH}"
        )

    def test_loads_under_pydantic_schema(self):
        definition = _load_definition()
        assert isinstance(definition, DeviceDefinition)

    def test_vendor_and_os(self):
        definition = _load_definition()
        assert definition.vendor == "Arista"
        assert definition.os == "EOS"

    def test_type_key(self):
        """``Arista`` is the primary lookup key — single-word convention
        matching the shipped Cisco/Fortigate definitions, and avoids the
        file_store filename-parser ambiguity that bites underscore- and
        dot-bearing keys (``arista_eos_4.32`` would mis-parse on GET)."""
        definition = _load_definition()
        assert definition.type_key == "Arista"

    def test_file_extension_cfg(self):
        definition = _load_definition()
        assert definition.file_extension == "cfg"

    def test_loaded_via_definition_loader(self):
        """End-to-end: the production loader picks the file up and
        registers it under the ``Arista`` type_key."""
        loader = DefinitionLoader(_REPO_ROOT / "definitions")
        defs = loader.load_all()
        assert "Arista" in defs, (
            f"Arista type_key missing from shipped definitions: "
            f"{sorted(defs.keys())}"
        )
        assert defs["Arista"].vendor == "Arista"


class TestCollectorWiring:
    def test_strategy_is_netmiko(self):
        definition = _load_definition()
        assert definition.collector.strategy == "netmiko"

    def test_netmiko_device_type_is_arista_eos(self):
        """``arista_eos`` is the netmiko device-type string for EOS;
        the netmiko_collector module documents the supported set."""
        definition = _load_definition()
        assert definition.collector.netmiko_device_type == "arista_eos"


class TestConnectionFlags:
    def test_needs_enable_is_true(self):
        """SSH lands at user-exec ``>``; enable required for show running."""
        definition = _load_definition()
        assert definition.connection.needs_enable is True

    def test_cisco_more_paging_is_true(self):
        """Per AGENTS.md hard rule: space-injection, NEVER terminal length 0."""
        definition = _load_definition()
        assert definition.connection.cisco_more_paging is True

    def test_opnsense_shell_menu_is_false(self):
        definition = _load_definition()
        assert definition.connection.opnsense_shell_menu is False


class TestCommandsBlock:
    def test_config_command_is_show_running_config(self):
        definition = _load_definition()
        assert definition.commands.config == "show running-config"

    def test_pre_and_post_are_empty(self):
        """Netmiko's space-injection handles paging — no explicit pre/post
        is required like FortiOS needs."""
        definition = _load_definition()
        assert definition.commands.pre == []
        assert definition.commands.post == []


class TestPromptPatterns:
    def test_trailing_pattern_matches_user_exec_prompt(self):
        import re

        definition = _load_definition()
        assert definition.prompts.trailing, "trailing prompt list must not be empty"
        compiled = [re.compile(p) for p in definition.prompts.trailing]
        # User-exec
        assert any(p.match("switch>") for p in compiled)
        # Privileged
        assert any(p.match("switch#") for p in compiled)


# ---------------------------------------------------------------------------
# Probe regex coverage
# ---------------------------------------------------------------------------


class TestProbeRegexes:
    """The probe must survive realistic ``show version`` fragments
    spanning DCS hardware, vEOS, and the newer CCS line."""

    def test_probe_command_is_show_version(self):
        definition = _load_definition()
        assert definition.probe.command == "show version"

    def test_required_patterns_present(self):
        """``detected_os_version`` and ``detected_model`` feed
        DefinitionLoader.resolve(); they're contractually required."""
        definition = _load_definition()
        assert "detected_os_version" in definition.probe.patterns
        assert "detected_model" in definition.probe.patterns

    @pytest.mark.parametrize(
        "sample,expected_version,expected_model",
        [
            (_SHOW_VERSION_DCS_7050, "4.32", "DCS-7050SX-64-F"),
            (_SHOW_VERSION_VEOS, "4.32", "vEOS-lab"),
            (_SHOW_VERSION_CCS, "4.32", "CCS-720XP-48Y6"),
        ],
    )
    def test_extracts_version_and_model(
        self, sample, expected_version, expected_model
    ):
        definition = _load_definition()
        facts = parse_probe_output(sample, definition.probe)
        assert facts.get("detected_os_version") == expected_version
        assert facts.get("detected_model") == expected_model

    def test_extracts_serial_when_pattern_present(self):
        """Optional fact for asset audit — must not be required by the
        layered-resolver but should still extract when present."""
        definition = _load_definition()
        facts = parse_probe_output(_SHOW_VERSION_DCS_7050, definition.probe)
        assert facts.get("detected_serial") == "JPE13120914ABC"

    def test_probe_timestamp_attached(self):
        definition = _load_definition()
        facts = parse_probe_output(_SHOW_VERSION_DCS_7050, definition.probe)
        assert PROBE_TIMESTAMP_KEY in facts

    def test_probe_misses_silently_on_empty_input(self):
        """Empty / unrecognised output → empty fact dict, no crash, no
        masquerading timestamp."""
        definition = _load_definition()
        assert parse_probe_output("", definition.probe) == {}

    def test_version_capture_strips_patch_level(self):
        """Capture must be major.minor only so overlays declared with
        ``os_version: "4.32"`` resolve when the device reports
        ``4.32.0F`` / ``4.32.1F-EFT1`` / ``4.32.2F``."""
        definition = _load_definition()
        for sample in (_SHOW_VERSION_DCS_7050, _SHOW_VERSION_VEOS, _SHOW_VERSION_CCS):
            facts = parse_probe_output(sample, definition.probe)
            # No ``F`` / ``EFT1`` / ``.0`` patch suffix in captured value.
            assert facts["detected_os_version"] == "4.32"
