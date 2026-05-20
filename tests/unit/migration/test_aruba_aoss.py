"""
Unit tests for the ``ArubaAOSSCodec`` — 4th real codec, Session C.

Covers the canonical contract (parse / render / round-trip / xpath /
capabilities / registry) plus AOS-S-specific quirks:

    * ``;`` comment character (not ``!``)
    * VLAN-centric port membership (``untagged 1-24``, ``tagged A1-A2``)
    * Port range expansion + compression
    * Both IP-address forms (``A.B.C.D/N`` and ``A.B.C.D M.M.M.M``)
    * ``ip default-gateway`` → 0.0.0.0/0 static route round-trip
    * ``routing`` keyword on routed ports (vs Cisco's ``no switchport``)
"""

from __future__ import annotations

from pathlib import Path

import pytest

import netcanon.migration  # noqa: F401

from netcanon.migration.codecs._mock import MockCodec
from netcanon.migration.codecs.aruba_aoss import ArubaAOSSCodec
from netcanon.migration.codecs.aruba_aoss.codec import (
    _format_port_list,
    _parse_port_list,
)
from netcanon.migration.codecs.base import ParseError, RenderError
from netcanon.migration.codecs.cisco_iosxe import CiscoIOSXECodec
from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalIPv4Address,
    CanonicalInterface,
    CanonicalStaticRoute,
    CanonicalVlan,
    CanonicalVRRPGroup,
)
from netcanon.models.migration import DeviceClass, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan

pytestmark = pytest.mark.unit


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "aruba_aoss"


_MIN = """\
hostname "test-sw"
vlan 10
   name "USERS"
   untagged 1-24
   tagged 25
   ip address 192.168.10.1/24
   exit
"""


# ---------------------------------------------------------------------------
# R3 field declarations
# ---------------------------------------------------------------------------


class TestR3Fields:
    def test_direction(self):
        assert ArubaAOSSCodec.direction == "bidirectional"

    def test_certainty(self):
        # Promoted from best_effort after three sanitised HPE Community
        # forum captures landed the corpus at 4 fixtures across 3 OS
        # versions (WC.16.07.0002, WB.16.08.0001, WC.16.10.0005), with
        # all four round-tripping cleanly.  The existing rendered-
        # template fixture remains a 4th data point but is not counted
        # toward OS-version diversity.  See tests/fixtures/real/RESULTS.md.
        assert ArubaAOSSCodec.certainty == "certified"

    def test_input_format(self):
        assert ArubaAOSSCodec.input_format == "cli-aruba-aoss"

    def test_vendor_id(self):
        assert ArubaAOSSCodec().capabilities.vendor_id == "aruba_aoss"

    def test_device_classes(self):
        classes = ArubaAOSSCodec().capabilities.device_classes
        assert DeviceClass.switch in classes
        assert DeviceClass.router in classes


# ---------------------------------------------------------------------------
# Port-list helpers
# ---------------------------------------------------------------------------


class TestPortListParsing:
    def test_numeric_range_expands(self):
        assert _parse_port_list("1-5") == ["1", "2", "3", "4", "5"]

    def test_alpha_range_expands(self):
        assert _parse_port_list("A1-A3") == ["A1", "A2", "A3"]

    def test_mixed_list(self):
        assert _parse_port_list("1,3-5,A1") == ["1", "3", "4", "5", "A1"]

    def test_dedup_preserves_first_occurrence(self):
        assert _parse_port_list("1,2,1") == ["1", "2"]

    # Stacked-switch range forms — these regressed silently for
    # months before the WC.16.11.0025 2930M real-capture fixture
    # surfaced the bug.  The old regex only handled bare numeric
    # and letter-prefix forms; slot-port and slot-letter-port
    # ranges either lost the slot prefix or dropped intermediate
    # ports entirely.  Round-trip stability hid it because the
    # format path was symmetrically broken.

    def test_stacked_slot_port_range_expands(self):
        """``1/1-1/24`` on a stacked 2930M / 3810M expands correctly
        to member 1's first 24 ports.  Regression guard — the old
        code produced ``["1"]`` for this input (slot prefix dropped
        in the expansion step)."""
        assert _parse_port_list("1/1-1/24") == [
            f"1/{n}" for n in range(1, 25)
        ]

    def test_stacked_slot_letter_port_range_expands(self):
        """``1/A1-1/A4`` — stack-member uplink module ports (the
        flexible-module A on a 2930M / 3810M).  Old regex failed
        to match entirely and returned the two endpoints verbatim
        (``["1/A1", "1/A4"]`` — missing 1/A2 and 1/A3)."""
        assert _parse_port_list("1/A1-1/A4") == [
            "1/A1", "1/A2", "1/A3", "1/A4",
        ]

    def test_second_stack_member_range_expands(self):
        """``2/1-2/48`` — member 2 of a multi-chassis stack."""
        assert _parse_port_list("2/1-2/48") == [
            f"2/{n}" for n in range(1, 49)
        ]

    def test_comma_separated_stacked_ranges(self):
        """Real-world form from the WC.16.11.0025 2930M fixture:
        ``untagged 1/1-1/47,1/A1-1/A4`` — comma-separated ranges
        with mixed slot-port + slot-letter-port forms."""
        assert _parse_port_list("1/1-1/47,1/A1-1/A4") == (
            [f"1/{n}" for n in range(1, 48)]
            + ["1/A1", "1/A2", "1/A3", "1/A4"]
        )

    def test_mismatched_prefix_rejected(self):
        """Prefix must match between lo and hi — ``1/1-2/1`` isn't
        a valid range (different stack members).  Pass through
        as-is without synthesising a cross-member range."""
        # Old and new code both return the two endpoints unchanged
        # because prefix_lo != prefix_hi.  Documenting via test so
        # the invariant doesn't quietly change.
        assert _parse_port_list("1/1-2/1") == ["1/1", "2/1"]


class TestPortListFormatting:
    def test_contiguous_numeric_compresses(self):
        assert _format_port_list(["1", "2", "3", "4"]) == "1-4"

    def test_noncontiguous_comma_joined(self):
        assert _format_port_list(["1", "3", "5"]) == "1,3,5"

    def test_alpha_prefix_groups(self):
        assert _format_port_list(["A1", "A2", "A3"]) == "A1-A3"

    def test_mixed_prefixes(self):
        assert _format_port_list(["1", "2", "A1", "A2"]) == "1-2,A1-A2"

    def test_single_port(self):
        assert _format_port_list(["25"]) == "25"


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


class TestParse:
    def test_hostname_parsed(self):
        tree = ArubaAOSSCodec().parse(_MIN)
        assert tree.hostname == "test-sw"

    def test_vlan_centric_membership(self):
        """The architecturally interesting test: VLAN carries its own
        port list (what Aruba natively does, what the canonical model
        was designed around)."""
        tree = ArubaAOSSCodec().parse(_MIN)
        vlan = tree.vlans[0]
        assert vlan.id == 10
        assert vlan.name == "USERS"
        assert vlan.untagged_ports == [
            str(n) for n in range(1, 25)
        ]
        assert vlan.tagged_ports == ["25"]

    def test_svi_ip_on_vlan_stanza(self):
        tree = ArubaAOSSCodec().parse(_MIN)
        vlan = tree.vlans[0]
        assert len(vlan.ipv4_addresses) == 1
        assert vlan.ipv4_addresses[0].ip == "192.168.10.1"
        assert vlan.ipv4_addresses[0].prefix_length == 24

    def test_svi_produces_vlan_interface(self):
        """VLANs with an IP address also surface as Vlan<N> interfaces
        so downstream codecs that expect per-interface L3 see them."""
        tree = ArubaAOSSCodec().parse(_MIN)
        names = [i.name for i in tree.interfaces]
        assert "Vlan10" in names

    def test_fixture_full_tree(self):
        raw = FIXTURES.joinpath("show_run_simple.txt").read_text()
        tree = ArubaAOSSCodec().parse(raw)
        assert tree.hostname == "sw-edge-01"

        # 3 VLANs in fixture.
        assert {v.id for v in tree.vlans} == {1, 10, 20}

        # VLAN 1's 'no untagged 1-24' removes default; 'untagged 25-26,A1'
        # then adds those back.  When VLAN 20 subsequently claims
        # ``untagged 25-26``, AOS-Switch reassigns those ports off
        # VLAN 1 (move-on-reassign semantic; HPE Aruba 2930F config
        # guide / "VLAN port assignments").  After the Wave 7c
        # parser hardening, VLAN 1 retains only ``A1``; ports 25 + 26
        # land on VLAN 20.
        vlan1 = next(v for v in tree.vlans if v.id == 1)
        assert vlan1.untagged_ports == ["A1"]
        vlan20 = next(v for v in tree.vlans if v.id == 20)
        assert vlan20.untagged_ports == ["25", "26"]

        # 3 physical interfaces + 2 Vlan SVI interfaces = 5.
        iface_names = {i.name for i in tree.interfaces}
        assert "1" in iface_names
        assert "25" in iface_names
        assert "A1" in iface_names
        assert "Vlan10" in iface_names
        assert "Vlan20" in iface_names

        # Routed port A1 has its /30.
        a1 = next(i for i in tree.interfaces if i.name == "A1")
        assert a1.ipv4_addresses[0].ip == "10.0.0.2"
        assert a1.ipv4_addresses[0].prefix_length == 30

        # Default gateway becomes a 0.0.0.0/0 static route.
        default = next(r for r in tree.static_routes if r.destination == "0.0.0.0/0")
        assert default.gateway == "10.0.0.1"

        # Explicit ip route also there.
        named = next(r for r in tree.static_routes if r.destination == "192.168.99.0/24")
        assert named.gateway == "10.0.0.254"

    def test_dotted_decimal_mask_accepted(self):
        raw = (
            'vlan 20\n'
            '   ip address 192.168.20.1 255.255.255.0\n'
            '   exit\n'
        )
        tree = ArubaAOSSCodec().parse(raw)
        assert tree.vlans[0].ipv4_addresses[0].prefix_length == 24

    def test_comment_character_is_semicolon(self):
        """Lines starting with ';' must be ignored (AOS-S doesn't use '!')."""
        raw = '; a banner comment\nhostname "survived"\n'
        tree = ArubaAOSSCodec().parse(raw)
        assert tree.hostname == "survived"

    def test_no_untagged_strips_ports(self):
        """`no untagged 1-24` should remove ports previously added."""
        raw = (
            'vlan 5\n'
            '   untagged 1-10\n'
            '   no untagged 2-4\n'
            '   exit\n'
        )
        tree = ArubaAOSSCodec().parse(raw)
        ports = tree.vlans[0].untagged_ports
        assert "1" in ports
        assert "2" not in ports
        assert "5" in ports


class TestParseLocalUserContinuationLine:
    """Regression for the terminal-wrap-on-paste bug.

    AOS-S devices emit ``password manager user-name "X" sha1 "<hash>"``
    on a single physical line, but the long sha1 hash means the line
    wraps when copy-pasted from a console / browser / chat client.
    Operators paste the wrapped form into the migrate workbench:

      password manager user-name "admin" sha1
       "deadbeef0000000000000000000000000000dead"

    The original parser regex required everything on one line and
    silently dropped the user — the rename modal then showed
    ``Local users: 0`` even when the source clearly declared one.
    """

    def test_single_line_form_still_works(self):
        """Same-line form is the normal AOS-S output and must keep
        working after the continuation-line fallback ships."""
        raw = (
            'hostname "sw"\n'
            'password manager user-name "admin" sha1 "ababab"\n'
        )
        tree = ArubaAOSSCodec().parse(raw)
        assert len(tree.local_users) == 1
        assert tree.local_users[0].name == "admin"
        assert tree.local_users[0].hashed_password == "sha1:ababab"

    def test_continuation_line_form_recovered(self):
        raw = (
            'hostname "sw"\n'
            'password manager user-name "admin" sha1\n'
            ' "deadbeef0000000000000000000000000000dead"\n'
        )
        tree = ArubaAOSSCodec().parse(raw)
        assert len(tree.local_users) == 1
        u = tree.local_users[0]
        assert u.name == "admin"
        assert u.privilege_level == 15
        assert u.role == "manager"
        assert u.hashed_password == (
            "sha1:deadbeef0000000000000000000000000000dead"
        )

    def test_continuation_line_with_blank_separator(self):
        """Some clipboard pipelines insert a blank line between the
        head and the continuation.  Tolerate it."""
        raw = (
            'password manager user-name "admin" sha1\n'
            '\n'
            ' "abcdef1234567890"\n'
        )
        tree = ArubaAOSSCodec().parse(raw)
        assert len(tree.local_users) == 1
        assert tree.local_users[0].hashed_password == "sha1:abcdef1234567890"

    def test_operator_role_continuation(self):
        """Same fallback path applies to ``password operator`` (role
        privilege=1) — not just ``manager``."""
        raw = (
            'password operator user-name "monitor" sha1\n'
            ' "1234"\n'
        )
        tree = ArubaAOSSCodec().parse(raw)
        assert len(tree.local_users) == 1
        u = tree.local_users[0]
        assert u.name == "monitor"
        assert u.privilege_level == 1
        assert u.role == "operator"

    def test_head_without_continuation_emits_user_with_empty_hash(self):
        """If the operator pasted only the head line (continuation
        missing entirely), surface the user record with an empty
        hash so the rename modal still shows the username — better
        than silently dropping it."""
        raw = 'password manager user-name "admin" sha1\n'
        tree = ArubaAOSSCodec().parse(raw)
        assert len(tree.local_users) == 1
        assert tree.local_users[0].name == "admin"
        assert tree.local_users[0].hashed_password == "sha1:"


class TestParseErrors:
    def test_empty_input_raises(self):
        with pytest.raises(ParseError, match="empty input"):
            ArubaAOSSCodec().parse("")

    def test_xml_input_rejected(self):
        with pytest.raises(ParseError, match="looks like XML"):
            ArubaAOSSCodec().parse("<?xml version='1.0'?>")

    def test_json_input_rejected(self):
        with pytest.raises(ParseError, match="looks like JSON"):
            ArubaAOSSCodec().parse('{"key": "value"}')


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


class TestRender:
    def test_render_deterministic(self):
        tree = ArubaAOSSCodec().parse(_MIN)
        a = ArubaAOSSCodec().render(tree)
        b = ArubaAOSSCodec().render(tree)
        assert a == b

    def test_render_rejects_non_canonical(self):
        with pytest.raises(RenderError, match="CanonicalIntent"):
            ArubaAOSSCodec().render({"foo": "bar"})  # type: ignore[arg-type]

    def test_render_hostname_quoted(self):
        tree = CanonicalIntent(hostname="my-switch")
        out = ArubaAOSSCodec().render(tree)
        assert 'hostname "my-switch"' in out

    def test_render_vlan_with_port_list(self):
        tree = CanonicalIntent(vlans=[
            CanonicalVlan(
                id=10,
                name="Users",
                untagged_ports=["1", "2", "3", "4"],
                tagged_ports=["25", "26"],
            ),
        ])
        out = ArubaAOSSCodec().render(tree)
        assert "vlan 10" in out
        assert '   name "Users"' in out
        assert "   untagged 1-4" in out
        assert "   tagged 25-26" in out
        assert "   exit" in out

    def test_render_default_route_uses_default_gateway(self):
        tree = CanonicalIntent(static_routes=[
            CanonicalStaticRoute(destination="0.0.0.0/0", gateway="10.0.0.1"),
        ])
        out = ArubaAOSSCodec().render(tree)
        assert "ip default-gateway 10.0.0.1" in out
        assert "ip route 0.0.0.0" not in out

    def test_render_non_default_uses_ip_route(self):
        tree = CanonicalIntent(static_routes=[
            CanonicalStaticRoute(destination="10.10.0.0/16", gateway="10.0.0.1"),
        ])
        out = ArubaAOSSCodec().render(tree)
        assert "ip route 10.10.0.0/16 10.0.0.1" in out

    def test_render_routed_port_emits_routing_keyword(self):
        tree = CanonicalIntent(interfaces=[
            CanonicalInterface(
                name="A1",
                enabled=True,
                ipv4_addresses=[CanonicalIPv4Address(ip="10.0.0.2", prefix_length=30)],
            ),
        ])
        out = ArubaAOSSCodec().render(tree)
        assert "interface A1" in out
        assert "   routing" in out
        assert "   ip address 10.0.0.2/30" in out

    def test_disabled_interface_emits_disable(self):
        tree = CanonicalIntent(interfaces=[
            CanonicalInterface(name="24", enabled=False),
        ])
        out = ArubaAOSSCodec().render(tree)
        assert "   disable" in out


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_roundtrip_minimal(self):
        codec = ArubaAOSSCodec()
        tree = codec.parse(_MIN)
        tree2 = codec.parse(codec.render(tree))
        assert tree.hostname == tree2.hostname
        assert {v.id for v in tree.vlans} == {v.id for v in tree2.vlans}

    def test_roundtrip_fixture_preserves_vlan_membership(self):
        """The architecturally important round-trip: port lists survive."""
        codec = ArubaAOSSCodec()
        raw = FIXTURES.joinpath("show_run_simple.txt").read_text()
        tree = codec.parse(raw)
        tree2 = codec.parse(codec.render(tree))
        for v1 in tree.vlans:
            v2 = next(v for v in tree2.vlans if v.id == v1.id)
            assert v1.name == v2.name, f"vlan {v1.id} name mismatch"
            assert v1.tagged_ports == v2.tagged_ports, (
                f"vlan {v1.id} tagged mismatch"
            )
            assert v1.untagged_ports == v2.untagged_ports, (
                f"vlan {v1.id} untagged mismatch"
            )


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


class TestCapabilities:
    def test_declares_vlan_membership_xpaths(self):
        caps = ArubaAOSSCodec().capabilities
        assert "/vlans/vlan/tagged-ports" in caps.supported
        assert "/vlans/vlan/untagged-ports" in caps.supported

    def test_filter_rule_unsupported(self):
        paths = [up.path for up in ArubaAOSSCodec().capabilities.unsupported]
        assert "/filter/rule" in paths


# ---------------------------------------------------------------------------
# iter_xpaths
# ---------------------------------------------------------------------------


class TestIterXpaths:
    def test_xpaths_match_capability_matrix(self):
        caps = ArubaAOSSCodec().capabilities
        declared = (
            set(caps.supported)
            | {lp.path for lp in caps.lossy}
            | {up.path for up in caps.unsupported}
        )
        raw = FIXTURES.joinpath("show_run_simple.txt").read_text()
        tree = ArubaAOSSCodec().parse(raw)
        for x in ArubaAOSSCodec().iter_xpaths(tree):
            assert x in declared, f"walker emitted undeclared xpath: {x!r}"

    def test_vlan_port_membership_emitted(self):
        tree = ArubaAOSSCodec().parse(_MIN)
        xs = list(ArubaAOSSCodec().iter_xpaths(tree))
        assert "/vlans/vlan/tagged-ports" in xs
        assert "/vlans/vlan/untagged-ports" in xs


# ---------------------------------------------------------------------------
# Auto-detection probe
# ---------------------------------------------------------------------------


class TestProbe:
    def test_matches_procurve_banner(self):
        raw = (
            "; J9729A Configuration Editor; Created on release #WC.16.11\n"
            'hostname "sw01"\n'
        )
        hit = ArubaAOSSCodec.probe(raw)
        assert hit is not None
        assert hit[0] >= 95

    def test_matches_structural_markers(self):
        raw = (
            "hostname sw\n"
            "vlan 10\n"
            "   untagged 1-24\n"
            "   exit\n"
            "interface 1\n"
            "   routing\n"
            "   exit\n"
        )
        hit = ArubaAOSSCodec.probe(raw)
        assert hit is not None
        assert hit[0] >= 85

    def test_ignores_cisco_cli(self):
        raw = "!\ninterface GigabitEthernet0/0/0\n ip address 10.0.0.1 255.255.255.0\n!\n"
        assert ArubaAOSSCodec.probe(raw) is None

    def test_ignores_xml(self):
        assert ArubaAOSSCodec.probe("<?xml version='1.0'?>") is None


# ---------------------------------------------------------------------------
# Cross-adapter story
# ---------------------------------------------------------------------------


class TestCrossAdapter:
    def test_aruba_to_opnsense(self):
        """Aruba AOS-S parsed and rendered as OPNsense config.xml."""
        from netcanon.migration.codecs.opnsense import OPNsenseCodec
        raw = FIXTURES.joinpath("show_run_simple.txt").read_text()
        job = run_plan(ArubaAOSSCodec(), OPNsenseCodec(), raw)
        assert job.status is MigrationJobStatus.completed
        assert job.rendered is not None
        assert "<hostname>sw-edge-01</hostname>" in job.rendered

    def test_aruba_to_iosxe_netconf(self):
        """Aruba -> Cisco IOS-XE NETCONF.  Validates that the
        canonical tree generated from VLAN-centric Aruba input renders
        into OpenConfig XML.

        The cisco_iosxe NETCONF codec is a Phase 0.5 stub whose render
        emits ONLY the openconfig-interfaces subtree.  Aruba sources
        carry hostname / VLANs / SNMP / etc. that the target render
        drops; the matrix honestly declares those surfaces unsupported
        (Wave 10γ-2), so this run terminates as ``partial`` with a
        block-severity validation report rather than ``completed``.
        The ``<interfaces>`` subtree is still emitted — that's the
        narrow surface this codec covers."""
        raw = FIXTURES.joinpath("show_run_simple.txt").read_text()
        job = run_plan(ArubaAOSSCodec(), CiscoIOSXECodec(), raw)
        assert job.status is MigrationJobStatus.partial
        assert job.validation is not None
        assert job.validation.severity == "block"
        assert "<interfaces" in (job.rendered or "")

    def test_cisco_cli_to_aruba(self):
        """Cisco CLI -> Aruba AOS-S.  VLAN definitions transfer;
        per-interface switchport assignment doesn't round-trip into
        VLAN-centric membership yet (that's a transform-layer job)."""
        ios_cli = (
            "hostname iostoaruba\n"
            "!\nvlan 10\n name Users\n!\n"
            "interface GigabitEthernet0/0/0\n"
            " description Uplink\n"
            " ip address 10.0.0.2 255.255.255.252\n"
            " no shutdown\n!\n"
            "ip route 0.0.0.0 0.0.0.0 10.0.0.1\n"
            "!\nend\n"
        )
        job = run_plan(CiscoIOSXECLICodec(), ArubaAOSSCodec(), ios_cli)
        assert job.status is MigrationJobStatus.completed
        assert 'hostname "iostoaruba"' in (job.rendered or "")
        assert "vlan 10" in (job.rendered or "")

    def test_class_guard_aruba_mock(self):
        """Aruba [switch,router] ∩ Mock [switch,router] = {switch,router}."""
        job = run_plan(ArubaAOSSCodec(), MockCodec(), _MIN)
        assert "Device-class guard" not in (job.error or "")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_aruba_in_registry(self):
        from netcanon.migration.codecs.registry import list_codecs
        assert "aruba_aoss" in list_codecs()

    def test_five_real_codecs_registered(self):
        from netcanon.migration.codecs.registry import list_codecs
        codecs = list_codecs()
        for expected in (
            "cisco_iosxe", "cisco_iosxe_cli", "opnsense",
            "mikrotik_routeros", "aruba_aoss", "mock",
        ):
            assert expected in codecs


# ---------------------------------------------------------------------------
# VRRP groups (Wave B v0.2.0)
# ---------------------------------------------------------------------------


# Synthetic AOS-S config with a single VRRP group — the smallest
# input that exercises the parse and render paths end-to-end.
_VRRP_BASIC = """\
hostname "vrrp-test"
vlan 100
   name "MGMT"
   ip address 10.0.100.1 255.255.255.0
   ip vrrp vrid 10
      virtual-ip-address 10.0.100.254
      priority 110
      preempt
      enable
      exit
   exit
"""


# Two VRRP groups on the same VLAN — used to exercise the loop
# variant of the parser dispatch (one sub-block followed by
# another, both inside the same ``vlan N`` body).
_VRRP_MULTI = """\
hostname "vrrp-multi"
vlan 200
   name "USERS"
   ip address 10.0.200.1/24
   ip vrrp vrid 20
      virtual-ip-address 10.0.200.254
      priority 110
      preempt
      enable
      exit
   ip vrrp vrid 21
      virtual-ip-address 10.0.200.253
      priority 90
      enable
      exit
   exit
"""


class TestVRRPGroups:
    """Wire-up tests for the v0.2.0 Wave B classic-VRRP path."""

    # ----------------------------- Parse -----------------------------

    def test_parse_basic_group_attaches_to_vlan_interface(self):
        """A single ``ip vrrp vrid`` block inside a VLAN stanza
        surfaces as one CanonicalVRRPGroup on the synthesised
        Vlan<N> CanonicalInterface."""
        tree = ArubaAOSSCodec().parse(_VRRP_BASIC)
        svi = next(i for i in tree.interfaces if i.name == "Vlan100")
        assert len(svi.vrrp_groups) == 1
        group = svi.vrrp_groups[0]
        assert group.group_id == 10
        assert group.mode == "vrrp"
        assert group.virtual_ips == ["10.0.100.254"]
        assert group.priority == 110
        assert group.preempt is True

    def test_parse_preempt_off_when_not_listed(self):
        """AOS-S vendor default is preempt=False (operators add the
        ``preempt`` token to opt in).  Differs from the canonical
        default which is True — parse must override."""
        raw = (
            'vlan 50\n'
            '   ip address 10.0.50.1/24\n'
            '   ip vrrp vrid 5\n'
            '      virtual-ip-address 10.0.50.254\n'
            '      enable\n'
            '      exit\n'
            '   exit\n'
        )
        tree = ArubaAOSSCodec().parse(raw)
        svi = next(i for i in tree.interfaces if i.name == "Vlan50")
        assert svi.vrrp_groups[0].preempt is False

    def test_parse_multiple_groups_in_same_vlan(self):
        """Two ``ip vrrp vrid`` blocks inside the same VLAN stanza
        parse into two distinct CanonicalVRRPGroup records on the
        single Vlan<N> interface, ordered by source appearance."""
        tree = ArubaAOSSCodec().parse(_VRRP_MULTI)
        svi = next(i for i in tree.interfaces if i.name == "Vlan200")
        assert len(svi.vrrp_groups) == 2
        ids = [g.group_id for g in svi.vrrp_groups]
        assert ids == [20, 21]
        # Second group has no preempt token; default-off applies.
        second = svi.vrrp_groups[1]
        assert second.priority == 90
        assert second.preempt is False

    def test_parse_authentication_plaintext_password(self):
        """``authentication mode plaintext-password "X"`` lands as
        ``"plain:X"`` on the canonical authentication field."""
        raw = (
            'vlan 30\n'
            '   ip address 10.0.30.1/24\n'
            '   ip vrrp vrid 3\n'
            '      virtual-ip-address 10.0.30.254\n'
            '      authentication mode plaintext-password "SECRET"\n'
            '      enable\n'
            '      exit\n'
            '   exit\n'
        )
        tree = ArubaAOSSCodec().parse(raw)
        svi = next(i for i in tree.interfaces if i.name == "Vlan30")
        assert svi.vrrp_groups[0].authentication == "plain:SECRET"

    def test_parse_default_priority_when_omitted(self):
        """Omitting ``priority`` keeps the canonical default of 100."""
        raw = (
            'vlan 70\n'
            '   ip address 10.0.70.1/24\n'
            '   ip vrrp vrid 7\n'
            '      virtual-ip-address 10.0.70.254\n'
            '      enable\n'
            '      exit\n'
            '   exit\n'
        )
        tree = ArubaAOSSCodec().parse(raw)
        svi = next(i for i in tree.interfaces if i.name == "Vlan70")
        assert svi.vrrp_groups[0].priority == 100

    def test_parse_enable_token_consumed_without_field(self):
        """``enable`` flag is platform-mandatory but has no canonical
        per-group field.  Parser must consume it without barfing or
        leaving the group in a half-parsed state."""
        tree = ArubaAOSSCodec().parse(_VRRP_BASIC)
        svi = next(i for i in tree.interfaces if i.name == "Vlan100")
        # The group still parses with virtual_ip + priority; the
        # ``enable`` line is silently consumed.
        assert svi.vrrp_groups[0].virtual_ips == ["10.0.100.254"]

    # ----------------------------- Render -----------------------------

    def test_render_emits_nested_vrrp_block(self):
        """Render emits ``ip vrrp vrid N`` + body + ``exit`` inside
        the ``vlan N`` stanza."""
        tree = CanonicalIntent(
            vlans=[CanonicalVlan(
                id=100, name="MGMT",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="10.0.100.1", prefix_length=24,
                )],
            )],
            interfaces=[CanonicalInterface(
                name="Vlan100",
                interface_type="ianaift:l3ipvlan",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="10.0.100.1", prefix_length=24,
                )],
                vrrp_groups=[CanonicalVRRPGroup(
                    group_id=10,
                    virtual_ips=["10.0.100.254"],
                    priority=110,
                    preempt=True,
                )],
            )],
        )
        out = ArubaAOSSCodec().render(tree)
        # The block must sit INSIDE the vlan stanza.
        assert "vlan 100" in out
        assert "   ip vrrp vrid 10" in out
        assert "      virtual-ip-address 10.0.100.254" in out
        assert "      priority 110" in out
        assert "      preempt" in out
        assert "      enable" in out
        assert "      exit" in out

    def test_render_omits_priority_when_default(self):
        """Default priority 100 stays off the wire (terse output)."""
        tree = CanonicalIntent(
            vlans=[CanonicalVlan(
                id=80,
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="10.0.80.1", prefix_length=24,
                )],
            )],
            interfaces=[CanonicalInterface(
                name="Vlan80",
                interface_type="ianaift:l3ipvlan",
                vrrp_groups=[CanonicalVRRPGroup(
                    group_id=8,
                    virtual_ips=["10.0.80.254"],
                    priority=100,  # default
                )],
            )],
        )
        out = ArubaAOSSCodec().render(tree)
        assert "      priority" not in out

    def test_render_emits_authentication_when_plain(self):
        tree = CanonicalIntent(
            vlans=[CanonicalVlan(
                id=30,
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="10.0.30.1", prefix_length=24,
                )],
            )],
            interfaces=[CanonicalInterface(
                name="Vlan30",
                interface_type="ianaift:l3ipvlan",
                vrrp_groups=[CanonicalVRRPGroup(
                    group_id=3,
                    virtual_ips=["10.0.30.254"],
                    authentication="plain:SECRET",
                )],
            )],
        )
        out = ArubaAOSSCodec().render(tree)
        assert 'authentication mode plaintext-password "SECRET"' in out

    def test_render_multi_virtual_ip_emits_lossy_review_comment(self):
        """AOS-S accepts ONE virtual-ip-address per vrid.  Cross-
        vendor input with multi-IP groups (Cisco IOS-XE secondaries,
        Junos virtual-address [ ... ]) drops the tail with a
        ``; review:`` comment."""
        tree = CanonicalIntent(
            vlans=[CanonicalVlan(
                id=40,
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="10.0.40.1", prefix_length=24,
                )],
            )],
            interfaces=[CanonicalInterface(
                name="Vlan40",
                interface_type="ianaift:l3ipvlan",
                vrrp_groups=[CanonicalVRRPGroup(
                    group_id=4,
                    virtual_ips=[
                        "10.0.40.254", "10.0.40.253", "10.0.40.252",
                    ],
                )],
            )],
        )
        out = ArubaAOSSCodec().render(tree)
        # First VIP is emitted.
        assert "      virtual-ip-address 10.0.40.254" in out
        # Tail VIPs become review comments.
        assert "10.0.40.253 dropped" in out
        assert "10.0.40.252 dropped" in out
        # And NOT as additional non-comment virtual-ip-address lines.
        active_vip_lines = [
            line for line in out.splitlines()
            if "virtual-ip-address" in line
            and not line.lstrip().startswith(";")
        ]
        assert len(active_vip_lines) == 1

    def test_render_anycast_mode_surfaces_review_comment(self):
        """AOS-S has NO anycast / HSRP / CARP grammar.  Groups with
        non-``vrrp`` mode emit a review comment and don't produce
        an ``ip vrrp vrid`` block."""
        tree = CanonicalIntent(
            vlans=[CanonicalVlan(
                id=60,
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="10.0.60.1", prefix_length=24,
                )],
            )],
            interfaces=[CanonicalInterface(
                name="Vlan60",
                interface_type="ianaift:l3ipvlan",
                vrrp_groups=[CanonicalVRRPGroup(
                    group_id=6,
                    mode="anycast",
                    virtual_ips=["10.0.60.254"],
                )],
            )],
        )
        out = ArubaAOSSCodec().render(tree)
        assert "ip vrrp vrid" not in out
        assert "review" in out
        assert "'anycast'" in out

    # ----------------------------- Round-trip -----------------------------

    def test_roundtrip_basic_vrrp(self):
        """parse(render(tree)) preserves all VRRP fields on a single
        group with explicit priority + preempt."""
        codec = ArubaAOSSCodec()
        tree1 = codec.parse(_VRRP_BASIC)
        rendered = codec.render(tree1)
        tree2 = codec.parse(rendered)
        svi1 = next(i for i in tree1.interfaces if i.name == "Vlan100")
        svi2 = next(i for i in tree2.interfaces if i.name == "Vlan100")
        assert len(svi1.vrrp_groups) == len(svi2.vrrp_groups) == 1
        g1, g2 = svi1.vrrp_groups[0], svi2.vrrp_groups[0]
        assert g1.group_id == g2.group_id
        assert g1.virtual_ips == g2.virtual_ips
        assert g1.priority == g2.priority
        assert g1.preempt == g2.preempt

    def test_roundtrip_multi_group(self):
        """Multiple groups on the same VLAN survive round-trip in
        order with correct per-group state."""
        codec = ArubaAOSSCodec()
        tree1 = codec.parse(_VRRP_MULTI)
        tree2 = codec.parse(codec.render(tree1))
        svi1 = next(i for i in tree1.interfaces if i.name == "Vlan200")
        svi2 = next(i for i in tree2.interfaces if i.name == "Vlan200")
        assert [g.group_id for g in svi1.vrrp_groups] == [
            g.group_id for g in svi2.vrrp_groups
        ]
        assert [g.priority for g in svi1.vrrp_groups] == [
            g.priority for g in svi2.vrrp_groups
        ]
        assert [g.preempt for g in svi1.vrrp_groups] == [
            g.preempt for g in svi2.vrrp_groups
        ]
        assert [g.virtual_ips for g in svi1.vrrp_groups] == [
            g.virtual_ips for g in svi2.vrrp_groups
        ]

    def test_roundtrip_authentication_plaintext(self):
        """Plaintext-password authentication round-trips through the
        ``plain:`` opaque-token convention."""
        codec = ArubaAOSSCodec()
        raw = (
            'vlan 30\n'
            '   ip address 10.0.30.1/24\n'
            '   ip vrrp vrid 3\n'
            '      virtual-ip-address 10.0.30.254\n'
            '      authentication mode plaintext-password "SECRET"\n'
            '      enable\n'
            '      exit\n'
            '   exit\n'
        )
        tree1 = codec.parse(raw)
        tree2 = codec.parse(codec.render(tree1))
        svi = next(i for i in tree2.interfaces if i.name == "Vlan30")
        assert svi.vrrp_groups[0].authentication == "plain:SECRET"

    # ----------------------------- Capabilities -----------------------------

    def test_capability_vrrp_supported(self):
        """Wave B flips ``/interfaces/interface/vrrp-groups/group``
        from unsupported to supported."""
        caps = ArubaAOSSCodec().capabilities
        assert "/interfaces/interface/vrrp-groups/group" in caps.supported
        unsupported_paths = [up.path for up in caps.unsupported]
        assert (
            "/interfaces/interface/vrrp-groups/group"
            not in unsupported_paths
        )

    def test_capability_anycast_remains_unsupported(self):
        """AOS-S has no anycast-gateway grammar — these paths stay
        unsupported even after the VRRP wire-up lands."""
        unsupported_paths = [
            up.path for up in ArubaAOSSCodec().capabilities.unsupported
        ]
        assert (
            "/interfaces/interface/ipv4/address/virtual-gateway-address"
            in unsupported_paths
        )
        assert (
            "/interfaces/interface/ipv6/address/virtual-gateway-address"
            in unsupported_paths
        )
        assert "/anycast-gateway-mac" in unsupported_paths

    def test_capability_virtual_ips_declared_lossy(self):
        """Single-IP-per-vrid restriction surfaces as a LossyPath
        so the migration validator can warn cross-vendor users."""
        lossy_paths = [lp.path for lp in ArubaAOSSCodec().capabilities.lossy]
        assert (
            "/interfaces/interface/vrrp-groups/group/virtual-ips"
            in lossy_paths
        )
