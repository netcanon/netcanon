"""
Unit tests for the shipped ``definitions/cisco/ios-xr/7.x.yaml`` definition.

Locks in the backup-pipeline schema fields (collector strategy, netmiko
device-type, paging mode, distinct type_key) and exercises the probe
regex map against synthetic IOS-XR ``show version`` fragments spanning
the ASR 9000 and NCS platform families.
"""

from __future__ import annotations

import pytest
import yaml

from netcanon.collectors.probe import PROBE_TIMESTAMP_KEY, parse_probe_output
from netcanon.definitions import LIBRARY_DIR
from netcanon.definitions.loader import DefinitionLoader
from netcanon.definitions.schema import DeviceDefinition

pytestmark = pytest.mark.unit


_DEFINITION_PATH = LIBRARY_DIR / "cisco" / "ios-xr" / "7.x.yaml"


def _load_definition() -> DeviceDefinition:
    raw = yaml.safe_load(_DEFINITION_PATH.read_text(encoding="utf-8"))
    return DeviceDefinition(**raw)


_SHOW_VERSION_ASR9K = """\
Cisco IOS XR Software, Version 7.5.2 LNT
Copyright (c) 2013-2022 by Cisco Systems, Inc.

Build Information:
 Built By     : builder
cisco ASR9K Series (Intel 686 F6M14S) processor
"""

_SHOW_VERSION_NCS = """\
Cisco IOS XR Software, Version 7.3.1
cisco NCS-5501 () processor
"""


class TestSchemaCompliance:
    def test_definition_file_exists(self):
        assert _DEFINITION_PATH.is_file()

    def test_loads_under_pydantic_schema(self):
        assert isinstance(_load_definition(), DeviceDefinition)

    def test_vendor_and_os(self):
        d = _load_definition()
        assert d.vendor == "Cisco"
        assert d.os == "IOS-XR"

    def test_type_key_is_distinct_from_cisco(self):
        d = _load_definition()
        assert d.type_key == "CiscoIOSXR"

    def test_file_extension_cfg(self):
        assert _load_definition().file_extension == "cfg"

    def test_notes_flag_not_validated_on_live_hardware(self):
        """Honesty marker surfaced in the /definitions Notes column —
        the backup actuation has never run against real hardware."""
        assert "NOT YET VALIDATED" in _load_definition().notes

    def test_loaded_via_definition_loader(self):
        defs = DefinitionLoader(LIBRARY_DIR).load_all()
        assert "CiscoIOSXR" in defs, sorted(defs.keys())
        assert "Cisco" in defs  # coexists with IOS-XE family base
        assert defs["CiscoIOSXR"].os == "IOS-XR"


class TestCollectorWiring:
    def test_strategy_is_netmiko(self):
        assert _load_definition().collector.strategy == "netmiko"

    def test_netmiko_device_type_is_cisco_xr(self):
        assert _load_definition().collector.netmiko_device_type == "cisco_xr"


class TestConnectionFlags:
    def test_needs_enable_is_false(self):
        """IOS-XR SSH lands in exec mode; no enable-mode escalation."""
        assert _load_definition().connection.needs_enable is False

    def test_cisco_more_paging_is_false(self):
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
    def test_trailing_matches_xr_exec_prompt(self):
        import re

        d = _load_definition()
        compiled = [re.compile(p) for p in d.prompts.trailing]
        assert any(p.match("RP/0/RP0/CPU0:router1#") for p in compiled)
        assert any(p.match("router1#") for p in compiled)


class TestProbeRegexes:
    def test_probe_command_is_show_version(self):
        assert _load_definition().probe.command == "show version"

    def test_required_patterns_present(self):
        patterns = _load_definition().probe.patterns
        assert "detected_os_version" in patterns
        assert "detected_model" in patterns

    @pytest.mark.parametrize(
        "sample,version,model",
        [
            (_SHOW_VERSION_ASR9K, "7.5", "ASR9K"),
            (_SHOW_VERSION_NCS, "7.3", "NCS-5501"),
        ],
    )
    def test_extracts_version_and_model(self, sample, version, model):
        facts = parse_probe_output(sample, _load_definition().probe)
        assert facts.get("detected_os_version") == version
        assert facts.get("detected_model") == model

    def test_probe_timestamp_attached(self):
        facts = parse_probe_output(_SHOW_VERSION_ASR9K, _load_definition().probe)
        assert PROBE_TIMESTAMP_KEY in facts

    def test_probe_misses_silently_on_empty_input(self):
        assert parse_probe_output("", _load_definition().probe) == {}
