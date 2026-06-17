"""
Unit tests for the shipped ``definitions/vyos/vyos/1.x.yaml`` definition.

Locks in the backup-pipeline schema fields and the VyOS-specific choices:
the set-form config command (``show configuration commands``, which the
vyos migration codec accepts), the ``conf`` file extension matching the
real-capture fixtures, and operational-mode session behaviour (no enable).
Exercises the version probe against a realistic VyOS ``show version``.
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
_DEFINITION_PATH = _REPO_ROOT / "definitions" / "vyos" / "vyos" / "1.x.yaml"


def _load_definition() -> DeviceDefinition:
    raw = yaml.safe_load(_DEFINITION_PATH.read_text(encoding="utf-8"))
    return DeviceDefinition(**raw)


_SHOW_VERSION_VYOS = """\
Version:          VyOS 1.4.0
Release train:    sagitta
Built by:         Sentrium S.L.
Build UUID:       abc-123
Hardware vendor:  VMware, Inc.
Hardware model:   VMware Virtual Platform
Hardware S/N:     VMware-42abc
Hardware UUID:    deadbeef-1234
"""


class TestSchemaCompliance:
    def test_definition_file_exists(self):
        assert _DEFINITION_PATH.is_file()

    def test_loads_under_pydantic_schema(self):
        assert isinstance(_load_definition(), DeviceDefinition)

    def test_vendor_and_os(self):
        d = _load_definition()
        assert d.vendor == "VyOS"
        assert d.os == "VyOS"

    def test_type_key(self):
        assert _load_definition().type_key == "VyOS"

    def test_file_extension_conf(self):
        """``conf`` matches the convention used by the vyos real-capture
        fixtures (tests/fixtures/real/vyos/*.conf)."""
        assert _load_definition().file_extension == "conf"

    def test_notes_no_longer_flags_not_validated(self):
        """VyOS graduated: the backup was live-validated against a real VyOS
        rolling instance (2026-06-17), so the provisional marker is dropped."""
        notes = _load_definition().notes
        assert "NOT YET VALIDATED" not in notes
        assert "LIVE-VALIDATED" in notes

    def test_loaded_via_definition_loader(self):
        defs = DefinitionLoader(_REPO_ROOT / "definitions").load_all()
        assert "VyOS" in defs, sorted(defs.keys())
        assert defs["VyOS"].vendor == "VyOS"


class TestCollectorWiring:
    def test_strategy_is_netmiko(self):
        assert _load_definition().collector.strategy == "netmiko"

    def test_netmiko_device_type_is_vyos(self):
        assert _load_definition().collector.netmiko_device_type == "vyos"


class TestConnectionFlags:
    def test_needs_enable_is_false(self):
        """VyOS SSH lands in operational mode (``$``); no enable equivalent."""
        assert _load_definition().connection.needs_enable is False

    def test_cisco_more_paging_is_false(self):
        assert _load_definition().connection.cisco_more_paging is False


class TestCommandsBlock:
    def test_config_command_is_show_configuration_commands(self):
        """Set-form dump; the vyos codec's Phase-6 front-end accepts it."""
        assert _load_definition().commands.config == "show configuration commands"

    def test_pre_and_post_are_empty(self):
        d = _load_definition()
        assert d.commands.pre == []
        assert d.commands.post == []


class TestPromptPatterns:
    def test_trailing_matches_operational_prompt(self):
        import re

        d = _load_definition()
        compiled = [re.compile(p) for p in d.prompts.trailing]
        assert any(p.match("vyos@vyos:~$") for p in compiled)


class TestProbeRegexes:
    def test_probe_command_is_show_version(self):
        assert _load_definition().probe.command == "show version"

    def test_required_patterns_present(self):
        patterns = _load_definition().probe.patterns
        assert "detected_os_version" in patterns
        assert "detected_model" in patterns

    def test_extracts_facts(self):
        facts = parse_probe_output(_SHOW_VERSION_VYOS, _load_definition().probe)
        assert facts.get("detected_os_version") == "1.4"
        assert facts.get("detected_model") == "VMware Virtual Platform"
        assert facts.get("detected_serial") == "VMware-42abc"

    def test_probe_timestamp_attached(self):
        facts = parse_probe_output(_SHOW_VERSION_VYOS, _load_definition().probe)
        assert PROBE_TIMESTAMP_KEY in facts

    def test_probe_misses_silently_on_empty_input(self):
        assert parse_probe_output("", _load_definition().probe) == {}
