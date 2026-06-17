"""
Unit tests for the shipped ``definitions/aruba/aos-cx/10.x.yaml`` definition.

Locks in the backup-pipeline schema fields and asserts the type_key is
distinct from the AOS-S ``Aruba`` family base (AOS-CX is a different NOS).
Exercises the version probe against a realistic AOS-CX ``show version``
fragment (the ``Version : FL.10.10.1000`` platform-prefixed line).
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
_DEFINITION_PATH = _REPO_ROOT / "definitions" / "aruba" / "aos-cx" / "10.x.yaml"


def _load_definition() -> DeviceDefinition:
    raw = yaml.safe_load(_DEFINITION_PATH.read_text(encoding="utf-8"))
    return DeviceDefinition(**raw)


_SHOW_VERSION_AOSCX = """\
-----------------------------------------------------------------------------
ArubaOS-CX
(c) Copyright 2017-2023 Hewlett Packard Enterprise Development LP
-----------------------------------------------------------------------------
Version      : FL.10.10.1000
Build Date   : 2023-05-09 17:00:00 PDT
Build ID     : ArubaOS-CX:FL.10.10.1000:...
"""


class TestSchemaCompliance:
    def test_definition_file_exists(self):
        assert _DEFINITION_PATH.is_file()

    def test_loads_under_pydantic_schema(self):
        assert isinstance(_load_definition(), DeviceDefinition)

    def test_vendor_and_os(self):
        d = _load_definition()
        assert d.vendor == "Aruba"
        assert d.os == "AOS-CX"

    def test_type_key_is_distinct_from_aos_s(self):
        """AOS-CX must NOT reuse the ``Aruba`` type_key (owned by AOS-S /
        ex-ProCurve) — they are different NOSes with different sessions."""
        d = _load_definition()
        assert d.type_key == "ArubaCX"

    def test_file_extension_cfg(self):
        assert _load_definition().file_extension == "cfg"

    def test_loaded_via_definition_loader(self):
        defs = DefinitionLoader(_REPO_ROOT / "definitions").load_all()
        assert "ArubaCX" in defs, sorted(defs.keys())
        # Coexists with the AOS-S ``Aruba`` family base — no collision.
        assert "Aruba" in defs
        assert defs["ArubaCX"].os == "AOS-CX"
        assert defs["Aruba"].os == "AOS-S"


class TestCollectorWiring:
    def test_strategy_is_netmiko(self):
        assert _load_definition().collector.strategy == "netmiko"

    def test_netmiko_device_type_is_aruba_aoscx(self):
        assert _load_definition().collector.netmiko_device_type == "aruba_aoscx"


class TestConnectionFlags:
    def test_needs_enable_is_false(self):
        """AOS-CX SSH lands in manager ``#``; no enable-mode escalation."""
        assert _load_definition().connection.needs_enable is False

    def test_cisco_more_paging_is_false(self):
        """netmiko aruba_aoscx disables paging natively (``no page``)."""
        assert _load_definition().connection.cisco_more_paging is False

    def test_no_terminal_length_zero_in_pre(self):
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
    def test_trailing_matches_manager_and_operator_prompts(self):
        import re

        d = _load_definition()
        compiled = [re.compile(p) for p in d.prompts.trailing]
        assert any(p.match("switch#") for p in compiled)
        assert any(p.match("switch>") for p in compiled)


class TestProbeRegexes:
    def test_probe_command_is_show_version(self):
        assert _load_definition().probe.command == "show version"

    def test_version_pattern_present(self):
        assert "detected_os_version" in _load_definition().probe.patterns

    def test_extracts_version_from_platform_prefixed_line(self):
        """``Version : FL.10.10.1000`` → ``10.10`` (the two-letter platform
        prefix is stripped, major.minor captured for overlay pins)."""
        facts = parse_probe_output(_SHOW_VERSION_AOSCX, _load_definition().probe)
        assert facts.get("detected_os_version") == "10.10"

    def test_probe_timestamp_attached(self):
        facts = parse_probe_output(_SHOW_VERSION_AOSCX, _load_definition().probe)
        assert PROBE_TIMESTAMP_KEY in facts

    def test_probe_misses_silently_on_empty_input(self):
        assert parse_probe_output("", _load_definition().probe) == {}
