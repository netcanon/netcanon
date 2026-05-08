"""
Unit tests for the pure-function probe-output parser.

Covers: fact extraction with various regex shapes, graceful
handling of pattern compile errors, the probe_timestamp
auto-attachment contract, and no-op behaviour when a definition
doesn't declare a probe.
"""

from __future__ import annotations

import pytest

from netcanon.collectors.probe import PROBE_TIMESTAMP_KEY, parse_probe_output
from netcanon.definitions.schema import ProbeConfig

pytestmark = pytest.mark.unit


# Canned real-world "show version" output fragments — abbreviated
# but shaped enough to exercise the regex patterns each vendor uses.
_CISCO_IOSXE_OUTPUT = """\
Cisco IOS Software [Cupertino], Catalyst L3 Switch Software (CAT9K_IOSXE), Version 17.12.03, RELEASE SOFTWARE (fc4)
Technical Support: http://www.cisco.com/techsupport
Copyright (c) 1986-2024 by Cisco Systems, Inc.

ROM: IOS-XE ROMMON
BOOTLDR: System Bootstrap, Version 17.12.1r[FC1], RELEASE SOFTWARE

cisco-sw uptime is 5 weeks, 2 days, 17 hours, 14 minutes
System returned to ROM by Reload Command at 00:05:22 UTC Sat Jan 13 2024
System image file is "flash:packages.conf"

Model Number                       : C9300-48P
System Serial Number               : FJC2500B123
"""

_ARUBA_OUTPUT = """\
Image stamp:    /ws/swbuildm/rel_ventura_qaoff/code/build/mbl(swbuildm_rel_ventura_qaoff_rel_ventura)
                Sep 21 2023 17:57:13
                WC.16.11.0025
                1852
Boot Image:     Primary
Active Configuration:

HP 2930F 48G 4SFP+ Switch
"""


class TestCiscoProbeRegexes:
    """Shape of the regex patterns a real cisco_iosxe definition
    would declare.  Locks in that the parser handles the common
    show-version fragments."""

    _CISCO_PATTERNS = {
        "detected_os_version": r"Version\s+([\d.]+(?:\(\w+\))?)",
        "detected_model": r"Model Number\s+:\s+(\S+)",
    }

    def test_extracts_version(self):
        facts = parse_probe_output(
            _CISCO_IOSXE_OUTPUT,
            ProbeConfig(command="show version", patterns=self._CISCO_PATTERNS),
        )
        assert facts["detected_os_version"] == "17.12.03"

    def test_extracts_model(self):
        facts = parse_probe_output(
            _CISCO_IOSXE_OUTPUT,
            ProbeConfig(command="show version", patterns=self._CISCO_PATTERNS),
        )
        assert facts["detected_model"] == "C9300-48P"

    def test_timestamp_attached_on_success(self):
        facts = parse_probe_output(
            _CISCO_IOSXE_OUTPUT,
            ProbeConfig(command="show version", patterns=self._CISCO_PATTERNS),
        )
        assert PROBE_TIMESTAMP_KEY in facts
        # ISO-8601 format check — "2026-04-22T..."
        assert "T" in facts[PROBE_TIMESTAMP_KEY]


class TestArubaProbeRegexes:
    """Aruba AOS-S show-version has a distinct shape (no "Model Number :"
    label, no "Version" prefix).  The regex patterns a definition
    ships are vendor-specific."""

    _ARUBA_PATTERNS = {
        "detected_os_version": r"(WC\.\d+\.\d+\.\d+)",
        "detected_model": r"HP\s+(\S+)\s+\d+[A-Z]",
    }

    def test_extracts_aos_version_stamp(self):
        facts = parse_probe_output(
            _ARUBA_OUTPUT,
            ProbeConfig(command="show version", patterns=self._ARUBA_PATTERNS),
        )
        assert facts["detected_os_version"] == "WC.16.11.0025"

    def test_extracts_aruba_model(self):
        facts = parse_probe_output(
            _ARUBA_OUTPUT,
            ProbeConfig(command="show version", patterns=self._ARUBA_PATTERNS),
        )
        assert facts["detected_model"] == "2930F"


class TestParserEdgeCases:
    def test_empty_probe_config_returns_empty_dict(self):
        """No patterns configured → nothing to extract → empty dict."""
        facts = parse_probe_output(_CISCO_IOSXE_OUTPUT, ProbeConfig())
        assert facts == {}

    def test_no_matches_returns_empty_dict(self):
        """Patterns present but none match → empty dict (and NO
        probe_timestamp — timestamp is gated on a successful match
        so empty results don't masquerade as a successful probe)."""
        facts = parse_probe_output(
            "uninteresting output",
            ProbeConfig(patterns={"detected_os_version": r"Version\s+([\d.]+)"}),
        )
        assert facts == {}

    def test_malformed_regex_skipped_silently(self):
        """A bad pattern should not take down the other facts."""
        facts = parse_probe_output(
            _CISCO_IOSXE_OUTPUT,
            ProbeConfig(patterns={
                "detected_os_version": r"Version\s+([\d.]+)",
                "broken": r"[unclosed",
            }),
        )
        # Good pattern still works.
        assert facts["detected_os_version"] == "17.12.03"
        # Bad one silently absent.
        assert "broken" not in facts

    def test_pattern_without_capture_group_takes_whole_match(self):
        facts = parse_probe_output(
            "firmware_build:2024.04.01",
            ProbeConfig(patterns={"build": r"\d{4}\.\d{2}\.\d{2}"}),
        )
        assert facts["build"] == "2024.04.01"

    def test_multiline_flag_on_patterns(self):
        """Patterns anchor per-line — ^/$ must match line bounds, not
        just buffer bounds."""
        output = "line 1\nserial FJC2500B123\nline 3"
        facts = parse_probe_output(
            output,
            ProbeConfig(patterns={"serial": r"^serial\s+(\S+)$"}),
        )
        assert facts["serial"] == "FJC2500B123"

    def test_value_stripping(self):
        """Capture-group values have leading/trailing whitespace
        stripped — real show-version output often has trailing
        whitespace before the newline."""
        facts = parse_probe_output(
            "Version    17.12.03   \n",
            ProbeConfig(patterns={"v": r"Version\s+(.+)"}),
        )
        assert facts["v"] == "17.12.03"
