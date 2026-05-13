"""
Tests for :func:`netcanon.migration.codecs._input_shape.detect_input_shape`.

The helper centralises XML / JSON detection across every CLI codec's
``parse()`` guard + ``probe()`` classmethod.  Pre-Phase-3-R4.2 each
codec did ``stripped.startswith("<")`` which broke on real captures
prefixed with shell-command echo (``cat /conf/config.xml\\n<?xml...``).
These tests pin the new behaviour: tolerate framing junk, still
correctly identify the shape.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs._input_shape import detect_input_shape


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Happy-path: clean XML / JSON / CLI inputs without any framing junk
# ---------------------------------------------------------------------------


class TestCleanInputs:
    """No leading junk — the simplest cases the helper must cover."""

    def test_xml_declaration(self):
        assert detect_input_shape("<?xml version='1.0'?>") == "xml"

    def test_xml_root_element_no_declaration(self):
        assert detect_input_shape("<opnsense>\n  <system/>\n</opnsense>") == "xml"

    def test_json_object(self):
        assert detect_input_shape('{"hostname": "r1", "interfaces": []}') == "json"

    def test_ios_cli_is_none(self):
        cli = "! IOS config\nhostname router1\ninterface Vlan10\n exit"
        assert detect_input_shape(cli) is None

    def test_junos_set_style_is_none(self):
        junos = "set system host-name r1\nset interfaces ge-0/0/0 unit 0"
        assert detect_input_shape(junos) is None

    def test_aruba_aoss_is_none(self):
        # Leading ';' is the AOS-S comment marker — not XML, not JSON.
        aoss = "; J9772A Configuration Editor; Created on release #YA.16.10\nhostname Aruba2930F"
        assert detect_input_shape(aoss) is None


# ---------------------------------------------------------------------------
# The user-reported case: framing junk before the actual XML
# ---------------------------------------------------------------------------


class TestFramingTolerance:
    """Real captures have leading shell echo / banners / motd / blank
    lines before the actual config body opens.  Pre-R4.2 the inline
    ``stripped.startswith("<")`` guard missed these — the regression
    that motivated this helper."""

    def test_opnsense_capture_with_shell_echo(self):
        # The exact shape of the user's reported file:
        #   cat /conf/config.xml\r\r\r\n<?xml version="1.0"?>...
        raw = (
            "cat /conf/config.xml\r\r\r\n"
            '<?xml version="1.0"?>\r\r\n'
            "<opnsense>\r\r\n"
            "  <theme>opnsense</theme>"
        )
        assert detect_input_shape(raw) == "xml"

    def test_cisco_session_transcript_before_xml(self):
        # A NETCONF response captured via session transcript — the
        # ``show xml ... | display xml`` style.
        raw = (
            "router# show running-config | format xml\r\n"
            "Building configuration...\r\n"
            "\r\n"
            "<?xml version='1.0'?>\r\n"
            "<config>...</config>"
        )
        assert detect_input_shape(raw) == "xml"

    def test_motd_banner_before_xml(self):
        raw = (
            "*****************************************\n"
            "* AUTHORIZED ACCESS ONLY                *\n"
            "*****************************************\n"
            "\n"
            "<?xml version='1.0'?>"
        )
        assert detect_input_shape(raw) == "xml"

    def test_json_with_leading_pager_echo(self):
        # NetOps automation that pipes through ``head`` or a pager.
        raw = (
            "<--- More --->\n"
            "{\n"
            '  "hostname": "r1"\n'
            "}"
        )
        assert detect_input_shape(raw) == "json"


# ---------------------------------------------------------------------------
# Negative cases: things that look XML-ish but ARE legitimate CLI
# ---------------------------------------------------------------------------


class TestNoFalsePositivesOnCli:
    """CLI config text that contains ``<`` or ``{`` characters
    mid-token must NOT trip the helper — false positives would mean
    real configs get rejected as XML by every CLI parser."""

    def test_ios_description_with_angle_brackets(self):
        # Descriptions sometimes carry HTML-like markup or arrows.
        cli = (
            "interface GigabitEthernet0/0\n"
            " description <upstream link to ISP> (priority)\n"
            " no shutdown"
        )
        assert detect_input_shape(cli) is None

    def test_ios_comment_with_angle_brackets(self):
        cli = (
            "! <-- BGP peer config below -->\n"
            "router bgp 65001"
        )
        assert detect_input_shape(cli) is None

    def test_junos_braces_not_at_column_zero(self):
        # Junos curly-brace syntax — ``{`` always appears after a
        # keyword, never at start of a stripped line standalone.
        # (The first non-empty line ``system {`` stripped starts with
        # ``system``, not ``{``.)
        junos = (
            "system {\n"
            "  host-name r1;\n"
            "  services {\n"
            "    ssh;\n"
            "  }\n"
            "}"
        )
        assert detect_input_shape(junos) is None


# ---------------------------------------------------------------------------
# Bounded scan: large inputs don't slow the helper down
# ---------------------------------------------------------------------------


class TestBoundedScan:
    def test_default_max_lines_5_stops_after_5_nonempty(self):
        # 10 non-empty junk lines, then real XML on line 11 — should
        # NOT be detected (we only scan first 5 non-empty by default).
        raw = "\n".join(["junk{}".format(i) for i in range(10)]) + "\n<?xml?>"
        assert detect_input_shape(raw) is None

    def test_higher_max_lines_finds_it(self):
        raw = "\n".join(["junk{}".format(i) for i in range(10)]) + "\n<?xml?>"
        assert detect_input_shape(raw, max_lines=20) == "xml"

    def test_empty_lines_dont_count_toward_max_lines(self):
        # Three blank lines + XML should always detect, regardless of
        # max_lines — empty lines are skipped, not counted.
        raw = "\n\n\n\n\n<?xml?>"
        assert detect_input_shape(raw, max_lines=2) == "xml"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_string_returns_none(self):
        assert detect_input_shape("") is None

    def test_whitespace_only_returns_none(self):
        assert detect_input_shape("\n\n  \t\n") is None

    def test_xml_with_namespace_prefix(self):
        raw = "<rpc-reply xmlns='urn:ietf:params:xml:ns:netconf:base:1.0'>"
        assert detect_input_shape(raw) == "xml"

    def test_xml_with_only_root_self_close(self):
        assert detect_input_shape("<empty/>") == "xml"

    def test_single_letter_starts_xml_must_have_separator(self):
        # Just "<a" without trailing separator isn't enough; "<a>" is.
        assert detect_input_shape("<a") is None
        assert detect_input_shape("<a>") == "xml"
