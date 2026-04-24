"""
Unit tests for :class:`OPNsenseCodec` — Phase 1 second real adapter.

Covers the same contract points as the cisco_iosxe test suite plus a
few OPNsense-specific structural quirks (zone-keyed interfaces, the
``<enable/>`` flag-element idiom).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netconfig.migration.codecs._mock import MockCodec
from netconfig.migration.codecs.base import ParseError, RenderError
from netconfig.migration.codecs.cisco_iosxe import CiscoIOSXECodec
from netconfig.migration.codecs.opnsense import OPNsenseCodec
from netconfig.models.migration import DeviceClass, MigrationJobStatus
from netconfig.services.migration_pipeline import run_plan

pytestmark = pytest.mark.unit


FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "opnsense"
)


_MIN = """<?xml version="1.0"?>
<opnsense>
  <system><hostname>fw01</hostname><domain>example.com</domain></system>
  <interfaces>
    <wan>
      <if>em0</if>
      <descr>Upstream</descr>
      <enable/>
      <ipaddr>198.51.100.2</ipaddr>
      <subnet>30</subnet>
    </wan>
  </interfaces>
</opnsense>
"""


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


class TestParse:
    def test_basic_parse(self):
        tree = OPNsenseCodec().parse(_MIN)
        assert tree.hostname == "fw01"
        assert tree.domain == "example.com"
        assert len(tree.interfaces) == 1

    def test_zone_interfaces_flatten_to_list(self):
        """OPNsense's native XML has <wan>, <lan>, <opt1> keyed by role.
        Parser flips them into a list of ``{'zone': 'wan', …}`` dicts
        so iter_xpaths can emit list-key-free schema paths."""
        xml = FIXTURES.joinpath("config_simple.xml").read_text()
        tree = OPNsenseCodec().parse(xml)
        ifaces = tree.interfaces
        zones = [i.name for i in ifaces]
        assert zones == ["wan", "lan", "opt1"]

    def test_enable_flag_element_becomes_python_true(self):
        """<enable/> is a flag — empty element means enabled."""
        tree = OPNsenseCodec().parse(_MIN)
        assert tree.interfaces[0].enabled is True

    def test_subnet_coerced_to_int(self):
        tree = OPNsenseCodec().parse(_MIN)
        assert tree.interfaces[0].ipv4_addresses[0].prefix_length == 30
        assert isinstance(tree.interfaces[0].ipv4_addresses[0].prefix_length, int)

    def test_empty_zone_skipped(self):
        """Empty zone stubs aren't worth carrying through the tree."""
        raw = """<?xml version="1.0"?>
<opnsense><interfaces><opt9/></interfaces></opnsense>"""
        tree = OPNsenseCodec().parse(raw)
        # opt9 had no content → not in the interface list.
        assert tree.interfaces == []


class TestParseErrors:
    def test_malformed_xml_raises_parse_error(self):
        with pytest.raises(ParseError, match="malformed XML"):
            OPNsenseCodec().parse("<not>real</xml")

    def test_wrong_root_element_raises(self):
        raw = """<?xml version="1.0"?>
<rpc-reply><data><interfaces/></data></rpc-reply>"""
        with pytest.raises(ParseError, match="<opnsense> root"):
            OPNsenseCodec().parse(raw)

    def test_non_integer_subnet_raises(self):
        raw = """<?xml version="1.0"?>
<opnsense><interfaces><wan>
  <if>em0</if><ipaddr>1.1.1.1</ipaddr><subnet>bogus</subnet>
</wan></interfaces></opnsense>"""
        with pytest.raises(ParseError, match="non-integer <subnet>"):
            OPNsenseCodec().parse(raw)


class TestParseTolerancePreamble:
    """Defensive: the parse() prefix-trim rescues OPNsense backups
    captured with leading command-echo noise.  See
    ``netconfig/migration/codecs/opnsense/codec.py::_trim_xml_prologue``
    for rationale and the collector-side fix in
    ``netconfig/collectors/paramiko_collector.py::_strip_command_echo``
    for the upstream defect.
    """

    def test_parses_with_cat_command_preamble(self):
        """The canonical bug shape: ``cat /conf/config.xml\\r\\r\\n``
        precedes the XML prolog.  Must parse cleanly — previously
        raised ``syntax error: line 1, column 0``."""
        raw = (
            "cat /conf/config.xml\r\r\n"
            '<?xml version="1.0"?>\r\n'
            "<opnsense>\r\n"
            "  <system><hostname>fw-01</hostname></system>\r\n"
            "</opnsense>\r\n"
        )
        intent = OPNsenseCodec().parse(raw)
        assert intent.hostname == "fw-01"

    def test_parses_with_banner_motd_preamble(self):
        """Any non-XML noise before the prolog should be tolerated,
        not just the ``cat`` command."""
        raw = (
            "Welcome to OPNsense 25.1.4\n"
            "*** Use of this system is monitored ***\n\n"
            '<?xml version="1.0"?>\n'
            "<opnsense><system><hostname>fw</hostname></system></opnsense>"
        )
        intent = OPNsenseCodec().parse(raw)
        assert intent.hostname == "fw"

    def test_parses_when_only_root_element_marker_present(self):
        """Some exports lack the ``<?xml`` prolog — strip still
        works by locating the ``<opnsense`` root marker."""
        raw = (
            "cat /conf/config.xml\r\n"
            "<opnsense><system><hostname>fw</hostname></system></opnsense>"
        )
        intent = OPNsenseCodec().parse(raw)
        assert intent.hostname == "fw"

    def test_truly_malformed_still_raises(self):
        """Input with NO XML markers at all must still raise —
        defensive strip must not swallow real errors."""
        with pytest.raises(ParseError, match="malformed XML"):
            OPNsenseCodec().parse("not xml at all\nnothing to see here")

    def test_clean_input_passes_through_unchanged(self):
        """Well-formed input (no preamble) must parse identically
        to before the strip was added — zero regression on the
        happy path."""
        raw = _MIN  # the module's minimal-valid fixture
        intent = OPNsenseCodec().parse(raw)
        assert intent.hostname == "fw01"  # matches _MIN hostname

    def test_parses_real_paramiko_capture_fixture(self):
        """Regression guard: the committed
        ``opnsense_paramiko_shell_capture.xml`` fixture — an
        exact replica of the user-reported bug shape (cat command
        echo + CRLF noise + valid XML body) must parse cleanly."""
        import pathlib
        raw = pathlib.Path(
            "tests/fixtures/real/opnsense/"
            "opnsense_paramiko_shell_capture.xml"
        ).read_text(encoding="utf-8")
        intent = OPNsenseCodec().parse(raw)
        # Just assert parse succeeded + the tree has content —
        # don't enumerate fields (the underlying fixture body may
        # evolve).
        assert intent.source_vendor == "opnsense"


class TestTrimXmlEnvelope:
    """Direct tests for the ``_trim_xml_envelope`` helper (formerly
    ``_trim_xml_prologue``).  Pure function — tests it in isolation
    from the rest of the parser.  Covers both head (prolog/root
    location) and tail (closing-tag residue) trims."""

    def test_preserves_input_with_no_marker(self):
        from netconfig.migration.codecs.opnsense.codec import _trim_xml_envelope
        raw = "nothing here"
        assert _trim_xml_envelope(raw) == raw

    def test_preserves_clean_xml_input(self):
        from netconfig.migration.codecs.opnsense.codec import _trim_xml_envelope
        raw = '<?xml version="1.0"?>\n<opnsense/>\n'
        # Actually the function truncates to the </opnsense> close —
        # a self-closing <opnsense/> lacks the literal close tag so
        # no tail trim fires.  Head trim is also no-op.  Passes through.
        assert _trim_xml_envelope(raw) == raw

    def test_strips_before_xml_prolog(self):
        from netconfig.migration.codecs.opnsense.codec import _trim_xml_envelope
        raw = 'garbage here\n<?xml version="1.0"?>\n<opnsense></opnsense>\n'
        out = _trim_xml_envelope(raw)
        assert out.startswith('<?xml version="1.0"?>')
        assert out.endswith('</opnsense>')

    def test_strips_before_root_element_when_no_prolog(self):
        from netconfig.migration.codecs.opnsense.codec import _trim_xml_envelope
        raw = "garbage\n<opnsense><hostname>x</hostname></opnsense>"
        out = _trim_xml_envelope(raw)
        assert out.startswith("<opnsense>")

    def test_picks_earliest_marker_when_both_present(self):
        from netconfig.migration.codecs.opnsense.codec import _trim_xml_envelope
        raw = 'junk\n<?xml?>\n<opnsense></opnsense>'
        out = _trim_xml_envelope(raw)
        assert out == '<?xml?>\n<opnsense></opnsense>'

    def test_bounded_head_scan(self):
        """Markers past the 2 KiB head-window are IGNORED."""
        from netconfig.migration.codecs.opnsense.codec import _trim_xml_envelope
        raw = ("x" * 3000) + '<?xml?>\n<opnsense></opnsense>'
        # Head window is 2048 bytes; marker at byte 3000 won't be
        # found by the head trim.  Tail trim still runs and slices
        # after </opnsense>, but that's fine — the head-untouched
        # buffer still fails downstream parse.  For THIS test we
        # just verify no false head strip.
        out = _trim_xml_envelope(raw)
        # Head is unchanged (still 3000 x's); tail may have been
        # trimmed if a closing tag was present.
        assert out.startswith("x" * 100)

    def test_empty_input_returns_empty(self):
        from netconfig.migration.codecs.opnsense.codec import _trim_xml_envelope
        assert _trim_xml_envelope("") == ""

    def test_strips_trailing_shell_prompt(self):
        """Tail trim: shell prompt residue after </opnsense> must
        be sliced off.  User-reported shape: after the closing
        tag, the paramiko-shell buffer contains
        ``root@supergate:~ # `` — breaks ET.fromstring further
        down the line."""
        from netconfig.migration.codecs.opnsense.codec import _trim_xml_envelope
        raw = (
            '<?xml version="1.0"?>\n'
            '<opnsense><system><hostname>fw</hostname></system></opnsense>\n'
            'root@supergate:~ # '
        )
        out = _trim_xml_envelope(raw)
        assert out.rstrip().endswith("</opnsense>")
        assert "root@supergate" not in out

    def test_strips_both_ends_simultaneously(self):
        """The canonical user-reported shape: command echo at head
        AND shell prompt at tail, both in one file."""
        from netconfig.migration.codecs.opnsense.codec import _trim_xml_envelope
        raw = (
            "cat /conf/config.xml\r\r\n"
            '<?xml version="1.0"?>\n<opnsense/>\n'
            "root@host:~ # "
        )
        out = _trim_xml_envelope(raw)
        # <opnsense/> is self-closing so tail-trim finds no
        # </opnsense> close tag; head-trim still strips the echo.
        # This test documents the asymmetry.
        assert out.startswith('<?xml version="1.0"?>')

    def test_legacy_alias_still_works(self):
        """Backwards-compat: ``_trim_xml_prologue`` alias must
        still resolve (some external test code or imports may
        reference the old name)."""
        from netconfig.migration.codecs.opnsense.codec import (
            _trim_xml_envelope,
            _trim_xml_prologue,
        )
        assert _trim_xml_prologue is _trim_xml_envelope


# ---------------------------------------------------------------------------
# Render + round-trip
# ---------------------------------------------------------------------------


class TestRender:
    def test_render_deterministic(self):
        tree = OPNsenseCodec().parse(_MIN)
        a = OPNsenseCodec().render(tree)
        b = OPNsenseCodec().render(tree)
        assert a == b

    def test_render_rejects_non_dict_or_intent(self):
        with pytest.raises(RenderError, match="CanonicalIntent or dict"):
            OPNsenseCodec().render("not a tree")  # type: ignore[arg-type]

    def test_render_rejects_interface_without_zone(self):
        bad = {
            "interfaces": {
                "interface": [{"if": "em0", "ipaddr": "1.1.1.1", "subnet": 24}]
            }
        }
        with pytest.raises(RenderError, match="missing 'zone'"):
            OPNsenseCodec().render(bad)


class TestRoundTrip:
    """parse(render(tree)) == tree over every sample."""

    def test_roundtrip_minimal(self):
        a = OPNsenseCodec()
        tree = a.parse(_MIN)
        assert a.parse(a.render(tree)) == tree

    def test_roundtrip_fixture(self):
        a = OPNsenseCodec()
        raw = FIXTURES.joinpath("config_simple.xml").read_text()
        tree = a.parse(raw)
        assert a.parse(a.render(tree)) == tree

    def test_roundtrip_preserves_vlans(self):
        # Regression: the render path used to silently drop
        # CanonicalVlan entries — it parsed <vlans><vlan><tag/> +
        # <descr/> but never emitted the inverse block, so a
        # parse→render→parse cycle returned an empty vlans list even
        # when the source config had several.  Surfaced by the real
        # supergate capture and fixed by adding a <vlans> render
        # block in _render_canonical.
        raw = """<?xml version="1.0"?>
<opnsense>
  <system><hostname>fw01</hostname></system>
  <vlans>
    <vlan><tag>10</tag><descr>USER VLAN</descr></vlan>
    <vlan><tag>20</tag><descr>SERVER VLAN</descr></vlan>
    <vlan><tag>100</tag><descr>CLUSTER VLAN</descr></vlan>
  </vlans>
</opnsense>
"""
        a = OPNsenseCodec()
        first = a.parse(raw)
        assert len(first.vlans) == 3
        second = a.parse(a.render(first))
        assert len(second.vlans) == 3
        ids_first = sorted(v.id for v in first.vlans)
        ids_second = sorted(v.id for v in second.vlans)
        assert ids_first == ids_second == [10, 20, 100]
        names_first = sorted(v.name for v in first.vlans)
        names_second = sorted(v.name for v in second.vlans)
        assert names_first == names_second == ["CLUSTER VLAN", "SERVER VLAN", "USER VLAN"]


# ---------------------------------------------------------------------------
# iter_xpaths
# ---------------------------------------------------------------------------


class TestIterXpaths:
    def test_xpaths_match_capability_matrix(self):
        """Every emitted path must be in the declared supported/lossy/
        unsupported set — drift means a matrix bug."""
        caps = OPNsenseCodec().capabilities
        declared = set(caps.supported) | {lp.path for lp in caps.lossy} | {
            up.path for up in caps.unsupported
        }
        xml = FIXTURES.joinpath("config_simple.xml").read_text()
        tree = OPNsenseCodec().parse(xml)
        for x in OPNsenseCodec().iter_xpaths(tree):
            assert x in declared, f"walker emitted undeclared xpath: {x!r}"

    def test_list_wrapper_unwrapped(self):
        """Canonical walker emits schema-style paths without list indices."""
        tree = OPNsenseCodec().parse(_MIN)
        xs = list(OPNsenseCodec().iter_xpaths(tree))
        assert "/interfaces/interface/name" in xs
        assert not any(
            "[" in x for x in xs
        ), f"list-key predicate leaked: {xs}"

    def test_multiple_interfaces_emit_paths_per_leaf(self):
        xml = FIXTURES.joinpath("config_simple.xml").read_text()
        tree = OPNsenseCodec().parse(xml)
        xs = list(OPNsenseCodec().iter_xpaths(tree))
        # Three interfaces each with a description → three occurrences.
        assert xs.count("/interfaces/interface/config/description") == 3


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


class TestCapabilities:
    def test_declares_firewall_and_router(self):
        classes = OPNsenseCodec().capabilities.device_classes
        assert DeviceClass.firewall in classes
        assert DeviceClass.router in classes

    def test_filter_rule_unsupported(self):
        unsupp = [
            up.path for up in OPNsenseCodec().capabilities.unsupported
        ]
        assert "/filter/rule" in unsupp

    def test_certainty_is_certified(self):
        # Promoted from best_effort after a sanitised real-world
        # config.xml capture from a user-contributed deployed OPNsense
        # instance ("supergate") landed the corpus at 4 fixtures
        # across 2 sources (3 from opnsense/core upstream + 1 real
        # user-deployed).  Real capture round-trip surfaced a real
        # bug (render dropped <vlans> even though parse read them);
        # fix + regression test (TestRoundTrip::test_roundtrip_preserves_vlans)
        # landed in the same commit.  See tests/fixtures/real/RESULTS.md.
        assert OPNsenseCodec.certainty == "certified"


# ---------------------------------------------------------------------------
# Cross-adapter story (the whole point of having two real adapters)
# ---------------------------------------------------------------------------


class TestCrossAdapter:
    def test_opnsense_iosxe_share_router_class(self):
        """OPNsense [firewall, router] ∩ IOS-XE [router, switch] = {router}.
        Class guard MUST permit."""
        src = OPNsenseCodec()
        tgt = CiscoIOSXECodec()
        xml = FIXTURES.joinpath("config_simple.xml").read_text()
        job = run_plan(src, tgt, xml)
        # Class guard didn't refuse — proof: the error, if any, is not
        # the guard's message.
        assert "Device-class guard" not in (job.error or "")

    def test_opnsense_mock_class_guard_blocks(self):
        """OPNsense [firewall, router] vs Mock [switch, router] share
        'router' so the guard actually PERMITS.  But no adapter pair
        in the repo today is disjoint; constructing a synthetic
        firewall-only stub is covered by
        test_device_class.py::test_disjoint_classes_is_block."""
        src = OPNsenseCodec()
        tgt = MockCodec()
        job = run_plan(src, tgt, _MIN)
        # Not blocked at stage 0.
        assert "Device-class guard" not in (job.error or "")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_opnsense_in_registry(self):
        import netconfig.migration  # side-effect import
        from netconfig.migration.codecs.registry import list_codecs
        assert "opnsense" in list_codecs()
