"""
Unit tests for the shipped ``definitions/cisco/nx-os/10.x.yaml`` definition.

Locks in the schema fields the backup pipeline relies on (collector
strategy, netmiko device-type, paging mode, distinct type_key) and
exercises the probe regex map against synthetic-but-realistic NX-OS
``show version`` fragments spanning the modern ``NXOS:`` and legacy
``system:`` version lines.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from netcanon.collectors.probe import PROBE_TIMESTAMP_KEY, parse_probe_output
from netcanon.definitions.loader import DefinitionLoader
from netcanon.definitions.schema import DeviceDefinition

pytestmark = pytest.mark.unit


_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFINITION_PATH = _REPO_ROOT / "definitions" / "cisco" / "nx-os" / "10.x.yaml"


def _load_definition() -> DeviceDefinition:
    raw = yaml.safe_load(_DEFINITION_PATH.read_text(encoding="utf-8"))
    return DeviceDefinition(**raw)


# Synthetic ``show version`` outputs — realistic shapes drawn from Cisco
# NX-OS docs, no real serials.  Modern boxes report ``NXOS: version``,
# older ones ``system:    version``.

_SHOW_VERSION_NXOS_10 = """\
Cisco Nexus Operating System (NX-OS) Software
Software
  BIOS: version 07.69
  NXOS: version 10.3(2)
Hardware
  cisco Nexus9000 C93180YC-EX Chassis
  Intel(R) Xeon(R) CPU
  Processor Board ID FDO12345ABC
  Device name: leaf1
"""

_SHOW_VERSION_NXOS_LEGACY = """\
Software
  system:    version 7.0(3)I7(8)
Hardware
  cisco Nexus9000 C9396PX Chassis
  Processor Board ID SAL1234ABCD
"""


class TestSchemaCompliance:
    def test_definition_file_exists(self):
        assert _DEFINITION_PATH.is_file()

    def test_loads_under_pydantic_schema(self):
        assert isinstance(_load_definition(), DeviceDefinition)

    def test_vendor_and_os(self):
        d = _load_definition()
        assert d.vendor == "Cisco"
        assert d.os == "NX-OS"

    def test_type_key_is_distinct_from_cisco(self):
        """NX-OS must NOT reuse the ``Cisco`` type_key (owned by IOS-XE);
        a collision would silently drop one definition from load_all()."""
        d = _load_definition()
        assert d.type_key == "CiscoNXOS"

    def test_file_extension_cfg(self):
        assert _load_definition().file_extension == "cfg"

    def test_loaded_via_definition_loader(self):
        defs = DefinitionLoader(_REPO_ROOT / "definitions").load_all()
        assert "CiscoNXOS" in defs, sorted(defs.keys())
        # Coexists with the IOS-XE ``Cisco`` family base — no collision.
        assert "Cisco" in defs
        assert defs["CiscoNXOS"].os == "NX-OS"


class TestCollectorWiring:
    def test_strategy_is_netmiko(self):
        assert _load_definition().collector.strategy == "netmiko"

    def test_netmiko_device_type_is_cisco_nxos(self):
        assert _load_definition().collector.netmiko_device_type == "cisco_nxos"


class TestConnectionFlags:
    def test_needs_enable_is_false(self):
        """NX-OS logs the admin role straight into ``#``; no enable mode."""
        assert _load_definition().connection.needs_enable is False

    def test_cisco_more_paging_is_false(self):
        """netmiko cisco_nxos disables paging natively; the SPACE-injection
        flag is IOS/IOS-XE-only and ignored by the netmiko collector."""
        assert _load_definition().connection.cisco_more_paging is False

    def test_no_terminal_length_zero_in_pre(self):
        """AGENTS.md hard rule: we never issue ``terminal length 0`` —
        netmiko owns paging."""
        d = _load_definition()
        assert d.commands.pre == []
        assert all("terminal length" not in c for c in d.commands.pre)


class TestCommandsBlock:
    def test_config_command_is_show_running_config(self):
        assert _load_definition().commands.config == "show running-config"

    def test_pre_and_post_are_empty(self):
        d = _load_definition()
        assert d.commands.pre == []
        assert d.commands.post == []


class TestPromptPatterns:
    def test_trailing_matches_exec_and_config_prompts(self):
        import re

        d = _load_definition()
        compiled = [re.compile(p) for p in d.prompts.trailing]
        assert any(p.match("leaf1#") for p in compiled)
        assert any(p.match("leaf1(config)#") for p in compiled)


class TestProbeRegexes:
    def test_probe_command_is_show_version(self):
        assert _load_definition().probe.command == "show version"

    def test_required_patterns_present(self):
        patterns = _load_definition().probe.patterns
        assert "detected_os_version" in patterns
        assert "detected_model" in patterns

    @pytest.mark.parametrize(
        "sample,version,model,serial",
        [
            (_SHOW_VERSION_NXOS_10, "10.3", "C93180YC-EX", "FDO12345ABC"),
            (_SHOW_VERSION_NXOS_LEGACY, "7.0", "C9396PX", "SAL1234ABCD"),
        ],
    )
    def test_extracts_facts(self, sample, version, model, serial):
        facts = parse_probe_output(sample, _load_definition().probe)
        assert facts.get("detected_os_version") == version
        assert facts.get("detected_model") == model
        assert facts.get("detected_serial") == serial

    def test_probe_timestamp_attached(self):
        facts = parse_probe_output(_SHOW_VERSION_NXOS_10, _load_definition().probe)
        assert PROBE_TIMESTAMP_KEY in facts

    def test_probe_misses_silently_on_empty_input(self):
        assert parse_probe_output("", _load_definition().probe) == {}
