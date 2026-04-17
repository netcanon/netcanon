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
