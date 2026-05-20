"""
Unit tests for :class:`OPNsenseCodec` — Phase 1 second real adapter.

Covers the same contract points as the cisco_iosxe test suite plus a
few OPNsense-specific structural quirks (zone-keyed interfaces, the
``<enable/>`` flag-element idiom).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs._mock import MockCodec
from netcanon.migration.codecs.base import ParseError, RenderError
from netcanon.migration.codecs.cisco_iosxe import CiscoIOSXECodec
from netcanon.migration.codecs.opnsense import OPNsenseCodec
from netcanon.models.migration import DeviceClass, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan

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
        """OPNsense's native XML has <wan>, <lan>, <opt1> keyed by role,
        each carrying a ``<if>`` child that names the underlying physical
        interface (``em0`` / ``em1`` / ``em2``).  The parser prefers the
        ``<if>`` text as the canonical name so that round-trips through
        ``_zone_tag_for``'s lossy sanitisation preserve the original
        port-name identity for cross-vendor intents.  See
        ``netcanon/migration/codecs/opnsense/parse.py``
        ``_parse_interface_zone_canonical`` for the resolution rule.
        """
        xml = FIXTURES.joinpath("config_simple.xml").read_text()
        tree = OPNsenseCodec().parse(xml)
        ifaces = tree.interfaces
        names = [i.name for i in ifaces]
        # <if>em0</if>, <if>em1</if>, <if>em2</if> in the fixture
        assert names == ["em0", "em1", "em2"]

    def test_enable_flag_element_becomes_python_true(self):
        """<enable/> is a flag — empty element means enabled."""
        tree = OPNsenseCodec().parse(_MIN)
        assert tree.interfaces[0].enabled is True

    def test_subnet_coerced_to_int(self):
        tree = OPNsenseCodec().parse(_MIN)
        assert tree.interfaces[0].ipv4_addresses[0].prefix_length == 30
        assert isinstance(tree.interfaces[0].ipv4_addresses[0].prefix_length, int)

    def test_empty_zone_round_trips_as_named_iface(self):
        """An empty zone stub used to be dropped under the "no <if> AND
        zero children → return None" rule.  That rule was load-bearing
        in the empty-zone-drop defect: render emitted self-closing
        ``<optN/>`` for sparse interfaces and parse then dropped them,
        so disabled-only / IPless ifaces lost their canonical record
        on round-trip.  The rule is gone — a named zone with no
        children round-trips as a CanonicalInterface with just the
        zone-tag name set (legacy fallback path)."""
        raw = """<?xml version="1.0"?>
<opnsense><interfaces><opt9/></interfaces></opnsense>"""
        tree = OPNsenseCodec().parse(raw)
        assert len(tree.interfaces) == 1
        assert tree.interfaces[0].name == "opt9"


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
    ``netcanon/migration/codecs/opnsense/codec.py::_trim_xml_prologue``
    for rationale and the collector-side fix in
    ``netcanon/collectors/paramiko_collector.py::_strip_command_echo``
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
        from netcanon.migration.codecs.opnsense.codec import _trim_xml_envelope
        raw = "nothing here"
        assert _trim_xml_envelope(raw) == raw

    def test_preserves_clean_xml_input(self):
        from netcanon.migration.codecs.opnsense.codec import _trim_xml_envelope
        raw = '<?xml version="1.0"?>\n<opnsense/>\n'
        # Actually the function truncates to the </opnsense> close —
        # a self-closing <opnsense/> lacks the literal close tag so
        # no tail trim fires.  Head trim is also no-op.  Passes through.
        assert _trim_xml_envelope(raw) == raw

    def test_strips_before_xml_prolog(self):
        from netcanon.migration.codecs.opnsense.codec import _trim_xml_envelope
        raw = 'garbage here\n<?xml version="1.0"?>\n<opnsense></opnsense>\n'
        out = _trim_xml_envelope(raw)
        assert out.startswith('<?xml version="1.0"?>')
        assert out.endswith('</opnsense>')

    def test_strips_before_root_element_when_no_prolog(self):
        from netcanon.migration.codecs.opnsense.codec import _trim_xml_envelope
        raw = "garbage\n<opnsense><hostname>x</hostname></opnsense>"
        out = _trim_xml_envelope(raw)
        assert out.startswith("<opnsense>")

    def test_picks_earliest_marker_when_both_present(self):
        from netcanon.migration.codecs.opnsense.codec import _trim_xml_envelope
        raw = 'junk\n<?xml?>\n<opnsense></opnsense>'
        out = _trim_xml_envelope(raw)
        assert out == '<?xml?>\n<opnsense></opnsense>'

    def test_bounded_head_scan(self):
        """Markers past the 2 KiB head-window are IGNORED."""
        from netcanon.migration.codecs.opnsense.codec import _trim_xml_envelope
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
        from netcanon.migration.codecs.opnsense.codec import _trim_xml_envelope
        assert _trim_xml_envelope("") == ""

    def test_strips_trailing_shell_prompt(self):
        """Tail trim: shell prompt residue after </opnsense> must
        be sliced off.  User-reported shape: after the closing
        tag, the paramiko-shell buffer contains
        ``root@supergate:~ # `` — breaks ET.fromstring further
        down the line."""
        from netcanon.migration.codecs.opnsense.codec import _trim_xml_envelope
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
        from netcanon.migration.codecs.opnsense.codec import _trim_xml_envelope
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
        from netcanon.migration.codecs.opnsense.codec import (
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
# CARP groups (Wave B — mode="carp" discriminator)
# ---------------------------------------------------------------------------


_CARP_MIN = """<?xml version="1.0"?>
<opnsense>
  <system><hostname>fw-ha-a</hostname></system>
  <interfaces>
    <lan>
      <if>ixl0</if>
      <descr>LAN</descr>
      <enable/>
      <ipaddr>10.0.10.2</ipaddr>
      <subnet>24</subnet>
    </lan>
  </interfaces>
  <virtualip>
    <vip>
      <mode>carp</mode>
      <interface>lan</interface>
      <vhid>10</vhid>
      <advskew>0</advskew>
      <advbase>1</advbase>
      <password>secret-passphrase</password>
      <subnet>10.0.10.254</subnet>
      <subnet_bits>24</subnet_bits>
      <descr>HA pair management VIP</descr>
      <type>single</type>
    </vip>
  </virtualip>
</opnsense>
"""


class TestCARPGroups:
    """Wire-up for OPNsense CARP virtual-IPs under <virtualip>/<vip>.

    Wave B (v0.2.0) — the BSD CARP HA primitive maps to
    :class:`CanonicalVRRPGroup` with ``mode="carp"``.  Tests cover
    parse, render, advskew↔priority normalisation, the alias-map
    interface back-pointer resolution, non-CARP mode filtering, and
    the Lossy round-trip for foreign mode groups.

    Grammar reference: docs/v0.2.0-planning/01-vrrp-canonical/
    02-per-vendor-grammar.md § 8 "OPNsense".
    """

    # ------------------------------------------------------------------
    # Parse side
    # ------------------------------------------------------------------

    def test_parse_carp_vip_promotes_to_vrrp_group(self):
        """Single <vip><mode>carp</mode> entry must surface as a
        CanonicalVRRPGroup attached to the named interface."""
        intent = OPNsenseCodec().parse(_CARP_MIN)
        # Interface "lan" maps to canonical name "ixl0" via the
        # alias map (<lan><if>ixl0</if>).
        ifaces = {i.name: i for i in intent.interfaces}
        assert "ixl0" in ifaces
        groups = ifaces["ixl0"].vrrp_groups
        assert len(groups) == 1
        g = groups[0]
        assert g.mode == "carp"
        assert g.group_id == 10
        assert g.virtual_ips == ["10.0.10.254"]
        assert g.description == "HA pair management VIP"

    def test_parse_skips_ipalias_mode(self):
        """<mode>ipalias</mode> is NOT a CARP VIP — additional IP
        alias on an interface.  Must NOT promote to CanonicalVRRPGroup."""
        raw = """<?xml version="1.0"?>
<opnsense>
  <interfaces><lan><if>em0</if><ipaddr>10.0.0.1</ipaddr><subnet>24</subnet></lan></interfaces>
  <virtualip>
    <vip>
      <mode>ipalias</mode>
      <interface>lan</interface>
      <vhid>0</vhid>
      <subnet>10.0.0.5</subnet>
      <subnet_bits>32</subnet_bits>
    </vip>
  </virtualip>
</opnsense>"""
        intent = OPNsenseCodec().parse(raw)
        ifaces = {i.name: i for i in intent.interfaces}
        assert ifaces["em0"].vrrp_groups == []

    def test_parse_skips_proxyarp_mode(self):
        """<mode>proxyarp</mode> — ARP responder for off-link hosts.
        Not an election-based HA primitive; must NOT promote."""
        raw = """<?xml version="1.0"?>
<opnsense>
  <interfaces><lan><if>em0</if></lan></interfaces>
  <virtualip>
    <vip>
      <mode>proxyarp</mode>
      <interface>lan</interface>
      <subnet>203.0.113.5</subnet>
      <subnet_bits>32</subnet_bits>
    </vip>
  </virtualip>
</opnsense>"""
        intent = OPNsenseCodec().parse(raw)
        ifaces = {i.name: i for i in intent.interfaces}
        assert ifaces["em0"].vrrp_groups == []

    def test_parse_mixed_modes_only_carp_promoted(self):
        """When <virtualip> contains both CARP and non-CARP modes,
        only CARP entries become CanonicalVRRPGroup records."""
        raw = """<?xml version="1.0"?>
<opnsense>
  <interfaces><lan><if>em0</if><ipaddr>10.0.0.1</ipaddr><subnet>24</subnet></lan></interfaces>
  <virtualip>
    <vip>
      <mode>ipalias</mode>
      <interface>lan</interface>
      <subnet>10.0.0.99</subnet>
      <subnet_bits>32</subnet_bits>
    </vip>
    <vip>
      <mode>carp</mode>
      <interface>lan</interface>
      <vhid>5</vhid>
      <advskew>50</advskew>
      <advbase>1</advbase>
      <password>x</password>
      <subnet>10.0.0.254</subnet>
      <subnet_bits>24</subnet_bits>
    </vip>
    <vip>
      <mode>proxyarp</mode>
      <interface>lan</interface>
      <subnet>10.0.0.30</subnet>
      <subnet_bits>32</subnet_bits>
    </vip>
  </virtualip>
</opnsense>"""
        intent = OPNsenseCodec().parse(raw)
        ifaces = {i.name: i for i in intent.interfaces}
        groups = ifaces["em0"].vrrp_groups
        assert len(groups) == 1
        assert groups[0].mode == "carp"
        assert groups[0].group_id == 5

    def test_advskew_to_priority_normalization(self):
        """OPNsense's election bias inverts canonical priority: lower
        advskew wins, so priority = 254 - advskew.  Verify the
        mapping for a few representative values."""
        # advskew=0 → priority=254 (max-win configuration).
        raw_0 = _CARP_MIN  # already advskew=0
        intent_0 = OPNsenseCodec().parse(raw_0)
        ifaces_0 = {i.name: i for i in intent_0.interfaces}
        assert ifaces_0["ixl0"].vrrp_groups[0].priority == 254
        # advskew=100 → priority=154.
        raw_100 = _CARP_MIN.replace(
            "<advskew>0</advskew>", "<advskew>100</advskew>",
        )
        intent_100 = OPNsenseCodec().parse(raw_100)
        ifaces_100 = {i.name: i for i in intent_100.interfaces}
        assert ifaces_100["ixl0"].vrrp_groups[0].priority == 154
        # advskew=253 → priority=1 (min-win configuration).
        raw_253 = _CARP_MIN.replace(
            "<advskew>0</advskew>", "<advskew>253</advskew>",
        )
        intent_253 = OPNsenseCodec().parse(raw_253)
        ifaces_253 = {i.name: i for i in intent_253.interfaces}
        assert ifaces_253["ixl0"].vrrp_groups[0].priority == 1

    def test_authentication_carp_key_scheme(self):
        """CARP password must surface as ``carp-key:<value>`` so
        cross-vendor renders see the scheme tag and can route to a
        review comment for VRRP targets."""
        intent = OPNsenseCodec().parse(_CARP_MIN)
        ifaces = {i.name: i for i in intent.interfaces}
        auth = ifaces["ixl0"].vrrp_groups[0].authentication
        assert auth == "carp-key:secret-passphrase"

    def test_advbase_to_advertisement_interval(self):
        """<advbase> seconds → CanonicalVRRPGroup.advertisement_interval."""
        raw = _CARP_MIN.replace("<advbase>1</advbase>", "<advbase>3</advbase>")
        intent = OPNsenseCodec().parse(raw)
        ifaces = {i.name: i for i in intent.interfaces}
        assert ifaces["ixl0"].vrrp_groups[0].advertisement_interval == 3

    def test_parse_interface_alias_resolution(self):
        """OPNsense's <interface>NAME refers to the LOGICAL zone alias
        (lan/wan/optN/operator-named).  Canonical iface name comes from
        the zone's <if> child.  Parser must resolve the alias through
        the alias map.  Here: <interface>opt2</interface> + zone
        <opt2><if>vlan0.10</if> → attach to CanonicalInterface name
        'vlan0.10'."""
        raw = """<?xml version="1.0"?>
<opnsense>
  <interfaces>
    <opt2>
      <if>vlan0.10</if>
      <ipaddr>10.10.10.2</ipaddr>
      <subnet>24</subnet>
    </opt2>
  </interfaces>
  <virtualip>
    <vip>
      <mode>carp</mode>
      <interface>opt2</interface>
      <vhid>20</vhid>
      <advskew>0</advskew>
      <advbase>1</advbase>
      <password>pw</password>
      <subnet>10.10.10.1</subnet>
      <subnet_bits>24</subnet_bits>
    </vip>
  </virtualip>
</opnsense>"""
        intent = OPNsenseCodec().parse(raw)
        ifaces = {i.name: i for i in intent.interfaces}
        # The canonical name is the <if> text, not the zone tag.
        assert "vlan0.10" in ifaces
        groups = ifaces["vlan0.10"].vrrp_groups
        assert len(groups) == 1
        assert groups[0].group_id == 20

    def test_parse_orphan_vip_does_not_create_iface(self):
        """A <vip> whose <interface> doesn't match any parsed zone
        must be SKIPPED — we don't invent a phantom CanonicalInterface
        to hang the group on.  Operator intent is lost (signaled via
        the Lossy declaration) but intent.interfaces stays clean."""
        raw = """<?xml version="1.0"?>
<opnsense>
  <interfaces><lan><if>em0</if></lan></interfaces>
  <virtualip>
    <vip>
      <mode>carp</mode>
      <interface>opt99</interface>
      <vhid>10</vhid>
      <advskew>0</advskew>
      <advbase>1</advbase>
      <password>x</password>
      <subnet>10.0.99.1</subnet>
      <subnet_bits>24</subnet_bits>
    </vip>
  </virtualip>
</opnsense>"""
        intent = OPNsenseCodec().parse(raw)
        # Only the originally-declared interface — no phantom opt99.
        names = sorted(i.name for i in intent.interfaces)
        assert names == ["em0"]
        # And no VRRP group attached to em0 (the orphan didn't fall
        # through to a default attachment).
        assert intent.interfaces[0].vrrp_groups == []

    def test_parse_empty_virtualip_envelope(self):
        """The supergate real fixture has <virtualip><vip/></virtualip>
        (empty self-closing).  Must NOT crash and must yield zero
        VRRP groups."""
        raw = """<?xml version="1.0"?>
<opnsense>
  <interfaces><lan><if>em0</if></lan></interfaces>
  <virtualip version="1.0.1" persisted_at="0" description="x">
    <vip/>
  </virtualip>
</opnsense>"""
        intent = OPNsenseCodec().parse(raw)
        # Just check no exception and no spurious groups.
        for iface in intent.interfaces:
            assert iface.vrrp_groups == []

    def test_parse_no_virtualip_block(self):
        """When the <virtualip> element is entirely absent, parse
        must produce zero CanonicalVRRPGroup records — no crash,
        no false-positive."""
        raw = _MIN  # no <virtualip>
        intent = OPNsenseCodec().parse(raw)
        for iface in intent.interfaces:
            assert iface.vrrp_groups == []

    def test_parse_ipv6_vip_populates_virtual_ipv6s(self):
        """IPv6 CARP VIPs land in virtual_ipv6s (split by literal
        family — presence of ':' and absence of '.')."""
        raw = """<?xml version="1.0"?>
<opnsense>
  <interfaces>
    <lan>
      <if>em0</if>
      <ipaddrv6>2001:db8::2</ipaddrv6>
      <subnetv6>64</subnetv6>
    </lan>
  </interfaces>
  <virtualip>
    <vip>
      <mode>carp</mode>
      <interface>lan</interface>
      <vhid>10</vhid>
      <advskew>0</advskew>
      <advbase>1</advbase>
      <password>pw</password>
      <subnet>2001:db8::1</subnet>
      <subnet_bits>64</subnet_bits>
    </vip>
  </virtualip>
</opnsense>"""
        intent = OPNsenseCodec().parse(raw)
        ifaces = {i.name: i for i in intent.interfaces}
        g = ifaces["em0"].vrrp_groups[0]
        assert g.virtual_ipv6s == ["2001:db8::1"]
        assert g.virtual_ips == []

    # ------------------------------------------------------------------
    # Render side
    # ------------------------------------------------------------------

    def test_render_emits_virtualip_block(self):
        """Round-trip render of a CARP group must produce a
        <virtualip>/<vip><mode>carp</mode> envelope with all the
        canonical fields restored to OPNsense's XML wire shape."""
        intent = OPNsenseCodec().parse(_CARP_MIN)
        out = OPNsenseCodec().render(intent)
        assert "<virtualip>" in out
        assert "<mode>carp</mode>" in out
        assert "<vhid>10</vhid>" in out
        assert "<subnet>10.0.10.254</subnet>" in out
        assert "<password>secret-passphrase</password>" in out
        # advskew=0 (priority=254 round-trips to advskew=254-254=0).
        assert "<advskew>0</advskew>" in out
        assert "<advbase>1</advbase>" in out

    def test_render_round_trips(self):
        """parse(render(parse(_CARP_MIN))) should be stable — the
        round-trip invariant holds for the CARP wire-up."""
        a = OPNsenseCodec()
        first = a.parse(_CARP_MIN)
        second = a.parse(a.render(first))
        # CanonicalIntent compares by field; check the VRRP groups
        # match exactly across the round-trip.
        first_ifaces = {i.name: i for i in first.interfaces}
        second_ifaces = {i.name: i for i in second.interfaces}
        assert first_ifaces.keys() == second_ifaces.keys()
        for name in first_ifaces:
            assert (
                first_ifaces[name].vrrp_groups
                == second_ifaces[name].vrrp_groups
            )

    def test_render_skips_non_carp_modes(self):
        """A CanonicalVRRPGroup with mode='vrrp' (or hsrp) must NOT
        emit a <vip> entry.  OPNsense has no native VRRP/HSRP under
        <virtualip>; the Lossy declaration in the capability matrix
        warns the operator the group will be dropped."""
        from netcanon.migration.canonical.intent import (
            CanonicalIntent,
            CanonicalInterface,
            CanonicalIPv4Address,
            CanonicalVRRPGroup,
        )
        intent = CanonicalIntent(
            source_vendor="opnsense",
            source_format="xml-opnsense",
            hostname="fw01",
        )
        iface = CanonicalInterface(
            name="lan",
            enabled=True,
            ipv4_addresses=[CanonicalIPv4Address(ip="10.0.0.2", prefix_length=24)],
        )
        iface.vrrp_groups.append(CanonicalVRRPGroup(
            group_id=10,
            mode="vrrp",  # ← classic VRRP, not CARP
            virtual_ips=["10.0.0.1"],
            priority=110,
        ))
        intent.interfaces.append(iface)
        out = OPNsenseCodec().render(intent)
        # No <virtualip> envelope at all (no CARP groups, so block omitted).
        assert "<virtualip>" not in out
        assert "<mode>vrrp</mode>" not in out
        assert "<vhid>" not in out

    def test_render_hsrp_mode_also_skipped(self):
        """mode='hsrp' (Cisco proprietary) is equally non-emittable
        on OPNsense.  Same drop behaviour as mode='vrrp'."""
        from netcanon.migration.canonical.intent import (
            CanonicalIntent,
            CanonicalInterface,
            CanonicalVRRPGroup,
        )
        intent = CanonicalIntent()
        iface = CanonicalInterface(name="em0")
        iface.vrrp_groups.append(CanonicalVRRPGroup(
            group_id=1,
            mode="hsrp",
            virtual_ips=["192.168.1.1"],
        ))
        intent.interfaces.append(iface)
        out = OPNsenseCodec().render(intent)
        assert "<virtualip>" not in out

    def test_render_advskew_round_trip(self):
        """priority=154 → advskew=100 on render (inverse of parse)."""
        from netcanon.migration.canonical.intent import (
            CanonicalIntent,
            CanonicalInterface,
            CanonicalIPv4Address,
            CanonicalVRRPGroup,
        )
        intent = CanonicalIntent()
        iface = CanonicalInterface(
            name="lan",
            ipv4_addresses=[CanonicalIPv4Address(ip="10.0.0.2", prefix_length=24)],
        )
        iface.vrrp_groups.append(CanonicalVRRPGroup(
            group_id=10,
            mode="carp",
            virtual_ips=["10.0.0.1"],
            priority=154,
            authentication="carp-key:pw",
        ))
        intent.interfaces.append(iface)
        out = OPNsenseCodec().render(intent)
        assert "<advskew>100</advskew>" in out

    def test_render_no_groups_omits_virtualip_block(self):
        """Intent with zero CARP groups must NOT emit an empty
        <virtualip/> envelope — keep output minimal for the
        no-HA common case."""
        intent = OPNsenseCodec().parse(_MIN)  # no virtualip
        out = OPNsenseCodec().render(intent)
        assert "<virtualip" not in out

    def test_render_carp_password_strips_scheme_tag(self):
        """Render must strip the ``carp-key:`` prefix when emitting
        <password> — OPNsense's element value is the raw passphrase,
        not the canonical scheme-tagged form."""
        intent = OPNsenseCodec().parse(_CARP_MIN)
        out = OPNsenseCodec().render(intent)
        assert "<password>secret-passphrase</password>" in out
        # And the scheme tag does not leak into the XML.
        assert "carp-key:" not in out

    # ------------------------------------------------------------------
    # Capability matrix wiring
    # ------------------------------------------------------------------

    def test_capability_matrix_vrrp_now_supported(self):
        """Wave B promotes /interfaces/interface/vrrp-groups/group
        from unsupported to supported.  The classify() resolution
        still flags it as lossy (mode-restriction LossyPath wins
        over the supported entry per the matrix's strictest-wins
        rule)."""
        caps = OPNsenseCodec().capabilities
        path = "/interfaces/interface/vrrp-groups/group"
        # Not in unsupported anymore.
        assert path not in [up.path for up in caps.unsupported]
        # And IS in supported.
        assert path in caps.supported
        # The classify() rule returns "lossy" because the LossyPath
        # entry has the same path and lossy beats supported.
        assert caps.classify(path) == "lossy"

    def test_capability_matrix_lossy_explains_carp_only(self):
        """The LossyPath entry for VRRP groups must explain WHY
        it's lossy — non-CARP modes drop, advskew↔priority is
        approximate."""
        caps = OPNsenseCodec().capabilities
        lossy_paths = {lp.path: lp for lp in caps.lossy}
        assert "/interfaces/interface/vrrp-groups/group" in lossy_paths
        lp = lossy_paths["/interfaces/interface/vrrp-groups/group"]
        # The reason must mention the mode restriction.
        assert "carp" in lp.reason.lower()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_opnsense_in_registry(self):
        import netcanon.migration  # side-effect import
        from netcanon.migration.codecs.registry import list_codecs
        assert "opnsense" in list_codecs()
