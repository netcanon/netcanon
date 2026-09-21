"""
Unit tests for the Dell SmartFabric OS10 codec — Phase 1 surface.

Phase 1 scope (``docs/vendor-research/dell_os10/30-codec-plan.md`` § 8):
hostname, ``! Version`` banner, interfaces (description / admin state /
mtu / IPv4 + IPv6 CIDR / ``ip vrf forwarding`` / L2 switchport /
``channel-group``), SVI-derived VLANs, LAGs, VRF declarations, and static
routes.  SNMP / local users / VRRP are Phase 3 and are asserted NOT
parsed, so a future phase landing one of them updates this file
deliberately.

Phase 2 adds the render path, the canonical-stable
parse→render→parse round-trip, and Tier-3 loss surfacing.  The round-trip
comparison below mirrors ``test_real_captures::_compare`` exactly — same
metadata exclusions, same cosmetic-order sorting — so this codec is held
to the identical invariant the registered codecs are, despite not being
discoverable by that harness yet.

The codec is **not registered** (no ``@register``), so it is imported
directly here rather than through ``get_codec``.  Registration grows the
cross-vendor mesh from 132 to 156 ordered pairs and breaks
``test_cross_mesh_ci_guard``'s exact ``cells_total`` assertion; that is
Phase-4 work.

Every sample below is derived from grammar MEASURED across the 14 real
OS10 captures held out-of-tree at ``local/dell-os10/configs/`` (which are
gitignored — they carry real SHA-512 password hashes).  **The grammar is
verbatim; the content is not.**  Secrets are replaced with placeholders
and site-identifying labels are genericised — the captures come from
permissively-licensed public repos, but a test needs the SHAPE of a
description, never the operator's own name for a workload.
"""

from __future__ import annotations

from typing import Any

import pytest

from netcanon.migration._usm_keys import LOCALISED, PLAINTEXT
from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalLocalUser,
    CanonicalRoutingInstance,
    CanonicalVlan,
)
from netcanon.migration.codecs.base import ParseError
from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netcanon.migration.codecs.dell_os10 import DellOS10Codec

pytestmark = pytest.mark.unit


@pytest.fixture
def codec() -> DellOS10Codec:
    return DellOS10Codec()


# A trimmed but grammar-verbatim device dump (the `jetpack_S5232F-*`
# shape): `! Version` banner, explicit `ip vrf default`, a wall of
# `interface breakout` lines, lower-case three-segment ports, a trunk
# carrying BOTH `switchport access vlan` and `switchport trunk allowed
# vlan`, and a `management route` default.
_DEVICE_DUMP = (
    "! Version 10.5.1.0\n"
    "! Last configuration change at Feb  25 15:06:23 2020\n"
    "!\n"
    "ip vrf default\n"
    "!\n"
    "interface breakout 1/1/1 map 100g-1x\n"
    "interface breakout 1/1/2 map 100g-1x\n"
    "hostname S5232F-1\n"
    "system-user linuxadmin password <REDACTED>\n"
    "!\n"
    "interface vlan1\n"
    " no shutdown\n"
    "!\n"
    "interface vlan461\n"
    " description TENANT-A\n"
    " no shutdown\n"
    " ip address 192.168.46.3/26\n"
    "!\n"
    "interface port-channel100\n"
    " description UPLINK-SPINE\n"
    " no shutdown\n"
    " switchport mode trunk\n"
    " switchport access vlan 1\n"
    " switchport trunk allowed vlan 32,34,47,461\n"
    " mtu 9216\n"
    " vlt-port-channel 100\n"
    "!\n"
    "interface mgmt1/1/1\n"
    " no shutdown\n"
    " no ip address dhcp\n"
    " ip address 192.168.33.44/24\n"
    " ipv6 address autoconfig\n"
    "!\n"
    "interface ethernet1/1/30\n"
    " description Up-po100\n"
    " no shutdown\n"
    " channel-group 100 mode active\n"
    " no switchport\n"
    " mtu 9216\n"
    "!\n"
    "interface ethernet1/1/12\n"
    " shutdown\n"
    " switchport access vlan 1\n"
    "!\n"
    "management route 0.0.0.0/0 192.168.33.1\n"
    "!\n"
    "vlt-domain 1\n"
    " backup destination 192.168.33.45\n"
    "!\n"
)


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


class TestProbe:
    def test_sample_input_detected_high(self, codec):
        hit = codec.probe(codec.sample_input)
        assert hit is not None
        assert hit[0] >= 95, hit

    def test_breakout_marker_scores_98(self, codec):
        assert codec.probe(_DEVICE_DUMP) == (
            98, "OS10 `interface breakout ... map` port-splitting",
        )

    def test_system_user_linuxadmin_marker(self, codec):
        raw = (
            "! Version 10.5.2.4\n"
            "!\n"
            "system-user linuxadmin password <REDACTED>\n"
        )
        hit = codec.probe(raw)
        assert hit is not None and hit[0] == 98

    def test_vlt_domain_marker(self, codec):
        raw = "hostname tor1\n!\nvlt-domain 1\n backup destination 10.0.0.2\n"
        hit = codec.probe(raw)
        assert hit is not None and hit[0] == 96

    def test_ip_vrf_default_marker(self, codec):
        raw = "! Version 10.5.1.0\n!\nip vrf default\n!\nhostname leaf1\n"
        hit = codec.probe(raw)
        assert hit is not None and hit[0] >= 95

    def test_version_plus_three_segment_ports(self, codec):
        raw = (
            "! Version 10.5.1.0\n"
            "!\n"
            "hostname leaf1\n"
            "interface ethernet1/1/1\n"
            " no shutdown\n"
        )
        assert codec.probe(raw) == (
            90, "OS10 version banner + three-segment ethernet naming",
        )

    # ── Negative signals — each is a codec this one must NOT steal from ──

    def test_refuses_nxos_banner(self, codec):
        raw = (
            "!Command: show running-config\n"
            "version 9.3(11) Bios:version\n"
            "interface Ethernet1/1\n"
        )
        assert codec.probe(raw) is None

    def test_refuses_iosxe_banner(self, codec):
        raw = (
            "Building configuration...\n"
            "\n"
            "Current configuration : 1234 bytes\n"
            "!\n"
            "hostname r1\n"
        )
        assert codec.probe(raw) is None

    def test_refuses_dell_os9_ftos(self, codec):
        """Dell OS9 / FTOS is a DIFFERENT Dell grammar.

        Claiming it here would reproduce the exact fail-open PR #475
        closed — a confident wrong codec — only with Dell on both sides.
        OS9 is VLAN-centric (`tagged` / `untagged`) and uses
        `TenGigabitEthernet` naming; this codec parses neither.
        """
        raw = (
            "! Version 9.14(2.0)\n"
            "! Last configuration change at ...\n"
            "!\n"
            "hostname S4810-TOR1\n"
            "!\n"
            "interface TenGigabitEthernet 0/1\n"
            " no shutdown\n"
        )
        assert codec.probe(raw) is None

    def test_refuses_xml(self, codec):
        assert codec.probe("<?xml version='1.0'?><opnsense></opnsense>") is None

    def test_qos_leading_capture_returns_none(self, codec):
        """Documented limitation, pinned so it can't silently change.

        The four DellGEOS captures open with ~500 bytes of pure QoS and
        carry NO OS10-exclusive marker inside `probe_bytes=500`.  Honest
        `None` beats a weak structural guess that would start stealing
        other vendors' configs — see `30-codec-plan.md` § 9.1.
        """
        raw = (
            "!\n"
            "hostname OS10-S5212F-TOR1\n"
            "!\n"
            "dcbx enable\n"
            "!\n"
            "class-map type queuing Q0\n"
            " match queue 0\n"
            "!\n"
            "trust dot1p-map trust_map\n"
            " qos-group 0 dot1p 0-2,4-6\n"
            "!\n"
        )
        assert codec.probe(raw) is None


# ---------------------------------------------------------------------------
# Interface stanza scanning — the measured traps
# ---------------------------------------------------------------------------


class TestInterfaceStanzaTraps:
    def test_breakout_lines_create_no_interface(self, codec):
        """`interface breakout 1/1/1 map 100g-1x` sits at column 0 and
        begins with the word `interface` — 148 occurrences across the
        corpus.  A naive `^interface\\s+(\\S+)` anchor invents a port
        named `breakout` and absorbs the real config that follows."""
        intent = codec.parse(_DEVICE_DUMP)
        names = [i.name for i in intent.interfaces]
        assert "breakout" not in names
        assert not any(n.lower().startswith("breakout") for n in names)

    def test_interface_range_creates_no_interface(self, codec):
        raw = (
            "hostname tor1\n"
            "!\n"
            "interface range ethernet1/1/1-1/1/12\n"
            " description HCI-NODE\n"
            " switchport mode trunk\n"
            "!\n"
            "interface vlan700\n"
            " description MANAGEMENT\n"
            "!\n"
        )
        intent = codec.parse(raw)
        names = [i.name for i in intent.interfaces]
        assert "range" not in names
        assert names == ["vlan700"]

    def test_indented_range_block_does_not_pollute_previous_stanza(self, codec):
        """Two of the twelve `interface range` lines carry a LEADING SPACE.

        Anchoring the header at column 0 makes the whole block skip
        cleanly; without that, its `description` / `switchport` lines get
        absorbed into the preceding stanza.
        """
        raw = (
            "interface Vlan 717\n"
            " description STORAGE-7\n"
            " mtu 9216\n"
            " no shutdown\n"
            "!\n"
            " interface range ethernet1/1/1-1/1/12\n"
            " description HCI-NODE\n"
            " switchport mode trunk\n"
            " switchport access vlan 700\n"
            "!\n"
        )
        intent = codec.parse(raw)
        assert [i.name for i in intent.interfaces] == ["vlan717"]
        svi = intent.interfaces[0]
        assert svi.description == "STORAGE-7"
        # The range block's switchport config must NOT have leaked onto
        # the SVI.
        assert svi.switchport_mode is None
        assert svi.access_vlan is None

    def test_indented_bang_does_not_truncate_stanza(self, codec):
        """THE scanner trap.

        Device dumps separate an SVI's L3 block from its nested VRRP
        block with a ONE-SPACE `!`.  The shared
        `_scanner._default_terminator` fires on `line.strip() == "!"`,
        which would close the stanza at that separator and silently drop
        everything after it.  `mtu` is placed after the VRRP block purely
        so a Phase-1 field proves the stanza stayed open.
        """
        raw = (
            "interface vlan101\n"
            " description EDGE-TRANSIT\n"
            " no shutdown\n"
            " ip address 172.22.56.2/27\n"
            " !\n"
            " vrrp-group 11\n"
            "  priority 150\n"
            "  virtual-address 172.22.56.1\n"
            "  no preempt\n"
            " !\n"
            " mtu 9216\n"
            "!\n"
            "interface vlan102\n"
            " description APP-TIER\n"
            "!\n"
        )
        intent = codec.parse(raw)
        assert [i.name for i in intent.interfaces] == ["vlan101", "vlan102"]
        svi = intent.interfaces[0]
        assert svi.mtu == 9216, "indented `!` truncated the stanza"
        assert svi.ipv4_addresses[0].ip == "172.22.56.2"
        # The VRRP block sits BEHIND the indented `!`, which makes it the
        # strongest available proof that the separator did not close the
        # stanza: under the shared terminator the whole group vanishes.
        assert [g.group_id for g in svi.vrrp_groups] == [11]
        assert svi.vrrp_groups[0].virtual_ips == ["172.22.56.1"]
        assert svi.vrrp_groups[0].preempt is False
        assert intent.interfaces[1].description == "APP-TIER"

    @pytest.mark.parametrize(
        "header",
        ["interface vlan700", "interface Vlan 700", "interface vlan 700"],
    )
    def test_all_three_svi_spellings_normalise(self, codec, header):
        """Measured across the corpus: `vlan700` x161, `Vlan 700` x28,
        `vlan 700` x24.  All three must land on ONE canonical name or a
        single VLAN enters the tree twice."""
        intent = codec.parse(f"{header}\n description MANAGEMENT\n!\n")
        assert [i.name for i in intent.interfaces] == ["vlan700"]
        assert [v.id for v in intent.vlans] == [700]

    def test_autoconfig_and_negations_are_not_addresses(self, codec):
        """`ipv6 address autoconfig` (x10) and `no ip address [dhcp]` are
        markers and negations, not addresses."""
        raw = (
            "interface mgmt1/1/1\n"
            " no shutdown\n"
            " no ip address dhcp\n"
            " ip address 192.168.33.44/24\n"
            " ipv6 address autoconfig\n"
            "!\n"
            "interface vlan711\n"
            " description STORAGE-1\n"
            " no ip address\n"
            " mtu 9216\n"
            "!\n"
        )
        intent = codec.parse(raw)
        mgmt, svi = intent.interfaces
        assert [a.ip for a in mgmt.ipv4_addresses] == ["192.168.33.44"]
        assert mgmt.ipv6_addresses == []
        assert svi.ipv4_addresses == []
        assert svi.mtu == 9216


# ---------------------------------------------------------------------------
# Switchport — the access-vlan-on-a-trunk inversion
# ---------------------------------------------------------------------------


class TestSwitchport:
    def test_access_vlan_on_trunk_is_the_native_vlan(self, codec):
        """OS10 spells the native/untagged VLAN `switchport access vlan`
        even on a trunk port.  Mapping it to `access_vlan` there inverts
        the port's L2 semantics on every downstream codec — the class of
        defect #239 fixed for Junos.  OS10 emits no `switchport trunk
        native vlan` line at all (measured: 0), so this is the only route
        to a native VLAN."""
        intent = codec.parse(_DEVICE_DUMP)
        po = next(i for i in intent.interfaces if i.name == "port-channel100")
        assert po.switchport_mode == "trunk"
        assert po.trunk_native_vlan == 1
        assert po.access_vlan is None
        assert po.trunk_allowed_vlans == [32, 34, 47, 461]

    def test_access_vlan_on_access_port_is_the_access_vlan(self, codec):
        intent = codec.parse(_DEVICE_DUMP)
        eth = next(i for i in intent.interfaces if i.name == "ethernet1/1/12")
        assert eth.access_vlan == 1
        assert eth.trunk_native_vlan is None
        # No explicit `switchport mode access` line — OS10 defaults a
        # switched port to access, so the mode is inferred.
        assert eth.switchport_mode == "access"
        assert eth.enabled is False

    def test_resolution_does_not_depend_on_line_order(self, codec):
        """Both real trunk examples happen to put `switchport mode trunk`
        FIRST, but nothing in the grammar guarantees it.  The raw value is
        resolved once the stanza closes, so the reversed order must give
        the identical answer."""
        reversed_order = (
            "interface port-channel10\n"
            " switchport access vlan 700\n"
            " switchport mode trunk\n"
            " switchport trunk allowed vlan 701-710\n"
            "!\n"
        )
        po = codec.parse(reversed_order).interfaces[0]
        assert po.trunk_native_vlan == 700
        assert po.access_vlan is None
        assert po.trunk_allowed_vlans == list(range(701, 711))

    def test_routed_port_has_no_switchport_mode(self, codec):
        intent = codec.parse(_DEVICE_DUMP)
        eth = next(i for i in intent.interfaces if i.name == "ethernet1/1/30")
        assert eth.switchport_mode is None
        assert eth.lag_member_of == "port-channel100"
        assert eth.mtu == 9216


# ---------------------------------------------------------------------------
# Static routes — the management-route trap
# ---------------------------------------------------------------------------


class TestStaticRoutes:
    def test_management_route_does_not_reach_the_global_rib(self, codec):
        """`management route` outnumbers `ip route` 8:2 in the corpus and
        installs a default into the management VRF ONLY.  Parsing it as a
        normal static route puts a management-only default into the
        global RIB."""
        intent = codec.parse(_DEVICE_DUMP)
        assert len(intent.static_routes) == 1
        route = intent.static_routes[0]
        assert route.destination == "0.0.0.0/0"
        assert route.gateway == "192.168.33.1"
        assert route.vrf == "management"
        # The global RIB must be empty.
        assert [r for r in intent.static_routes if not r.vrf] == []

    def test_ip_route_is_a_global_route(self, codec):
        intent = codec.parse("ip route 0.0.0.0/0 192.168.100.1\n")
        route = intent.static_routes[0]
        assert route.vrf == ""
        assert route.gateway == "192.168.100.1"

    def test_ip_route_vrf_form(self, codec):
        intent = codec.parse("ip route vrf green 203.0.113.0/24 10.0.0.2\n")
        route = intent.static_routes[0]
        assert route.vrf == "green"
        assert route.destination == "203.0.113.0/24"

    def test_legacy_dotted_mask_form(self, codec):
        """Documented in the 10.5.2 User Guide (L15622) but exercised by
        NO capture in the corpus, so it is pinned synthetically here."""
        intent = codec.parse("ip route 192.0.2.0 255.255.255.0 198.51.100.1\n")
        route = intent.static_routes[0]
        assert route.destination == "192.0.2.0/24"
        assert route.gateway == "198.51.100.1"

    def test_space_separated_interface_next_hop(self, codec):
        """`ip route 10.1.1.0/24 ethernet 1/1/1` — a fixed `(\\S+)`
        next-hop capture fails to match this outright and drops the route
        silently."""
        intent = codec.parse("ip route 10.1.1.0/24 ethernet 1/1/1\n")
        route = intent.static_routes[0]
        assert route.gateway == ""
        assert route.interface == "ethernet 1/1/1"

    def test_administrative_distance_becomes_metric(self, codec):
        intent = codec.parse("ip route 10.2.0.0/16 10.0.0.2 200\n")
        assert intent.static_routes[0].metric == 200

    def test_ipv6_route(self, codec):
        intent = codec.parse("ipv6 route 2001:db8::/32 2001:db8:1::1\n")
        route = intent.static_routes[0]
        assert route.destination == "2001:db8::/32"
        assert route.gateway == "2001:db8:1::1"


# ---------------------------------------------------------------------------
# VLANs, LAGs, VRFs
# ---------------------------------------------------------------------------


class TestVlans:
    def test_vlans_are_derived_from_svis(self, codec):
        """OS10 declares no top-level `vlan <id>` stanza and no `tagged` /
        `untagged` member lines (measured: 0 of each), so an SVI is the
        only statement that a VLAN exists."""
        intent = codec.parse(_DEVICE_DUMP)
        by_id = {v.id: v for v in intent.vlans}
        assert 461 in by_id
        assert by_id[461].name == "TENANT-A"
        assert [a.ip for a in by_id[461].ipv4_addresses] == ["192.168.46.3"]

    def test_switchport_membership_projects_onto_vlans(self, codec):
        intent = codec.parse(_DEVICE_DUMP)
        by_id = {v.id: v for v in intent.vlans}
        # 461 is both an SVI and a member of po100's trunk-allowed list.
        assert "port-channel100" in by_id[461].tagged_ports
        # VLAN 1 is po100's native VLAN and ethernet1/1/12's access VLAN.
        assert "ethernet1/1/12" in by_id[1].untagged_ports

    def test_trunk_only_vlans_are_pruned_as_phantoms(self, codec):
        """VLANs 32 / 34 / 47 appear ONLY inside po100's `trunk allowed`
        list — no SVI, no access or native port — so the phantom-VLAN
        guard drops them.  Pinned explicitly because the alternative
        (materialising a record for every id in a range) is how a
        `switchport trunk allowed vlan 1-4094` line inflates the tree by
        thousands of phantom VLANs."""
        intent = codec.parse(_DEVICE_DUMP)
        assert {v.id for v in intent.vlans} == {1, 461}

    def test_wide_trunk_range_does_not_inflate_vlans(self, codec):
        """The phantom-VLAN guard: a wide `trunk allowed` range must not
        materialise thousands of VLAN records."""
        raw = (
            "interface ethernet1/1/1\n"
            " switchport mode trunk\n"
            " switchport trunk allowed vlan 1-4094\n"
            "!\n"
        )
        intent = codec.parse(raw)
        assert len(intent.vlans) <= 1

    def test_quoted_description_is_unquoted(self, codec):
        intent = codec.parse(
            'interface vlan710\n description "mgmt 10.0.1.0/24"\n!\n'
        )
        assert intent.vlans[0].name == "mgmt 10.0.1.0/24"


class TestLags:
    def test_lag_from_declaration_and_membership(self, codec):
        intent = codec.parse(_DEVICE_DUMP)
        assert [lag.name for lag in intent.lags] == ["port-channel100"]
        lag = intent.lags[0]
        assert lag.members == ["ethernet1/1/30"]
        assert lag.mode == "active"

    def test_passive_mode_maps_through(self, codec):
        raw = (
            "interface ethernet1/1/5\n"
            " channel-group 7 mode passive\n"
            "!\n"
        )
        assert codec.parse(raw).lags[0].mode == "passive"


class TestVrf:
    def test_ip_vrf_default_is_not_a_routing_instance(self, codec):
        """OS10 states the global RIB as an explicit `ip vrf default`
        stanza — it is one of the markers that identifies an OS10 config
        at all, but it is not a VRF."""
        intent = codec.parse(_DEVICE_DUMP)
        assert [ri.name for ri in intent.routing_instances] == []

    def test_named_vrf_declaration_and_interface_bind(self, codec):
        raw = (
            "ip vrf infra_bmc_mgmt\n"
            "!\n"
            "interface vlan125\n"
            " description OOB-BMC\n"
            " ip vrf forwarding infra_bmc_mgmt\n"
            " ip address 10.60.48.131/26\n"
            "!\n"
        )
        intent = codec.parse(raw)
        assert [ri.name for ri in intent.routing_instances] == ["infra_bmc_mgmt"]
        assert intent.interfaces[0].vrf == "infra_bmc_mgmt"

    def test_interface_bind_alone_conjures_no_phantom_instance(self, codec):
        raw = (
            "interface vlan125\n"
            " ip vrf forwarding never_declared\n"
            "!\n"
        )
        intent = codec.parse(raw)
        assert intent.routing_instances == []
        assert intent.interfaces[0].vrf == "never_declared"


# ---------------------------------------------------------------------------
# Metadata + Phase-3 surfaces that must NOT be parsed yet
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_hostname_and_version(self, codec):
        intent = codec.parse(_DEVICE_DUMP)
        assert intent.hostname == "S5232F-1"
        assert intent.source_version == "10.5.1.0"
        assert intent.source_vendor == "dell_os10"
        assert intent.source_format == "cli-dellos10"

    def test_operator_config_without_banner_has_no_version(self, codec):
        intent = codec.parse("hostname OS10-S5212F-TOR1\n!\n")
        assert intent.source_version == ""

    def test_empty_input_raises_parse_error(self, codec):
        with pytest.raises(ParseError):
            codec.parse("   \n")

    def test_xml_input_raises_parse_error(self, codec):
        with pytest.raises(ParseError):
            codec.parse("<?xml version='1.0'?><opnsense><system/></opnsense>")


class TestVrrp:
    """OS10 runs REAL VRRP — no HSRP normalisation, unlike NX-OS."""

    _VRRP = (
        "interface vlan101\n"
        " description EDGE\n"
        " no shutdown\n"
        " mtu 9216\n"
        " ip address 172.22.56.2/27\n"
        " !\n"
        " vrrp-group 11\n"
        "  priority 150\n"
        "  virtual-address 172.22.56.1\n"
        "  no preempt\n"
        "!\n"
    )

    def test_group_is_parsed_as_real_vrrp(self, codec):
        group = codec.parse(self._VRRP).interfaces[0].vrrp_groups[0]
        assert group.group_id == 11
        assert group.mode == "vrrp", "OS10 needs no HSRP normalisation"
        assert group.virtual_ips == ["172.22.56.1"]
        assert group.priority == 150
        assert group.preempt is False

    def test_preempt_defaults_to_enabled(self, codec):
        """OS10 runs real VRRP, which preempts by default — `no preempt`
        x16 in the corpus, a bare `preempt` line never."""
        raw = (
            "interface vlan700\n"
            " vrrp-group 7\n"
            "  virtual-address 10.0.0.1\n"
            "!\n"
        )
        group = codec.parse(raw).interfaces[0].vrrp_groups[0]
        assert group.preempt is True
        assert group.priority == 100

    def test_multiple_virtual_addresses_on_one_line(self, codec):
        """`virtual-address` takes up to TEN addresses (10.5.2 User Guide
        L58972); capturing only the first would silently drop the rest."""
        raw = (
            "interface vlan700\n"
            " vrrp-group 7\n"
            "  virtual-address 10.0.0.1 10.0.0.2 10.0.0.3\n"
            "!\n"
        )
        group = codec.parse(raw).interfaces[0].vrrp_groups[0]
        assert group.virtual_ips == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]

    def test_priority_flow_control_is_not_eaten_as_a_vrrp_priority(self, codec):
        """`priority-flow-control mode on` appears 24 times in the corpus
        on ordinary data ports.  An unanchored `priority` pattern would
        match it and corrupt the group's election priority."""
        raw = (
            "interface ethernet1/1/15\n"
            " priority-flow-control mode on\n"
            " vrrp-group 7\n"
            "  virtual-address 10.0.0.1\n"
            "  priority-flow-control mode on\n"
            "!\n"
        )
        group = codec.parse(raw).interfaces[0].vrrp_groups[0]
        assert group.priority == 100

    def test_two_groups_on_one_interface(self, codec):
        raw = (
            "interface vlan700\n"
            " vrrp-group 7\n"
            "  virtual-address 10.0.0.1\n"
            " vrrp-group 8\n"
            "  virtual-address 10.0.0.2\n"
            "  priority 200\n"
            "!\n"
        )
        groups = codec.parse(raw).interfaces[0].vrrp_groups
        assert [g.group_id for g in groups] == [7, 8]
        assert groups[1].priority == 200

    def test_round_trip(self, codec):
        first = codec.parse(self._VRRP)
        second = codec.parse(codec.render(first))
        assert _compare(first) == _compare(second)

    def test_render_emits_only_non_default_values(self, codec):
        """A real device prints neither `priority 100` nor a bare
        `preempt`, so emitting them would add lines no switch produces."""
        raw = (
            "interface vlan700\n"
            " vrrp-group 7\n"
            "  virtual-address 10.0.0.1\n"
            "!\n"
        )
        out = codec.render(codec.parse(raw))
        assert " vrrp-group 7" in out
        assert "  virtual-address 10.0.0.1" in out
        assert "priority" not in out
        assert "preempt" not in out

    def test_mode_is_declared_lossy_not_supported(self, codec):
        """A cross-vendor HSRP / CARP group reinterprets as VRRP here —
        the virtual-IP intent survives but the wire protocol changes."""
        assert codec.capabilities.classify(
            "/interfaces/interface/vrrp-groups/group/mode"
        ) == "lossy"

    def test_chassis_wide_vrrp_settings_are_surfaced_as_dropped(self, codec):
        """`vrrp version` / `vrrp delay reload` are SYSTEM-wide, but the
        canonical record is per-interface, so they have no home and are
        permanently dropped."""
        raw = "vrrp version 3\nvrrp delay reload 180\nhostname tor1\n"
        sections = codec.parse(raw).dropped_tier3_sections
        assert "vrrp version" in sections
        assert "vrrp delay" in sections


class TestPhase3bSurfacesNotParsedYet:
    """Guards so a later phase updates this file deliberately rather than
    silently changing the matrix's meaning."""

    def test_usm_passphrase_paths_are_declared_not_defaulted(self, codec):
        """`classify()` defaults an UNDECLARED xpath to `supported`, i.e.
        silent loss.  OS10 localises USM keys against the switch's own
        engine ID, so claiming they migrate would be exactly the #471
        failure in a new grammar — both leaves must be declared.  They are
        `lossy` (not unsupported) now that the user itself renders: the
        anchor survives, the device-bound key does not."""
        declared = _loss_declared(codec)
        assert "/snmp/v3-user/auth-passphrase" in declared
        assert "/snmp/v3-user/priv-passphrase" in declared

    def test_timezone_is_declared_unsupported(self, codec):
        """Pre-satisfies `test_tier1_wiring_honesty`, which requires
        `/system/timezone` be declared unsupported on every codec — it
        will apply to this one the moment it registers."""
        declared = {p.path for p in codec.capabilities.unsupported}
        assert "/system/timezone" in declared

    def test_syslog_is_not_claimed_supported(self, codec):
        """`test_tier1_wiring_honesty` pins an EXACT roster of codecs
        declaring `/system/syslog-server` supported.  Phase 1 parses no
        `logging server`, so claiming it would both be false and break
        that roster on registration."""
        assert "/system/syslog-server" not in set(codec.capabilities.supported)


# ---------------------------------------------------------------------------
# Port-name bridge
# ---------------------------------------------------------------------------


class TestPortNames:
    @pytest.mark.parametrize(
        "name,kind,coords",
        [
            ("ethernet1/1/15", "physical", (1, 1, 15)),
            ("mgmt1/1/1", "mgmt", (1, 1, 1)),
        ],
    )
    def test_three_segment_names(self, codec, name, kind, coords):
        ident = codec.classify_port_name(name)
        assert ident.kind == kind
        assert (ident.stack, ident.module, ident.port) == coords
        assert ident.original == name

    @pytest.mark.parametrize(
        "name,kind,index",
        [
            ("port-channel10", "lag", 10),
            ("vlan700", "svi", 700),
            ("loopback0", "loopback", 0),
        ],
    )
    def test_logical_names(self, codec, name, kind, index):
        ident = codec.classify_port_name(name)
        assert ident.kind == kind
        assert ident.index == index

    def test_breakout_subport_is_classified_not_unknown(self, codec):
        """74 subport names appear across the corpus.  Unlike NX-OS's
        ambiguous three-part form, OS10's `:<lane>` suffix is
        unambiguous, so it classifies rather than falling through to
        `unknown`."""
        ident = codec.classify_port_name("ethernet1/1/10:1")
        assert ident.kind == "breakout"
        assert ident.breakout_lane == 1
        assert ident.breakout_parent == "ethernet1/1/10"

    def test_breakout_has_no_target_representation(self, codec):
        """Classified honestly, but NOT formattable: emitting a lane on a
        target whose parent port has no matching `interface breakout ...
        map` profile produces config the device rejects."""
        ident = codec.classify_port_name("ethernet1/1/10:1")
        assert codec.format_port_identity(ident) is None

    def test_round_trip_through_identity(self, codec):
        for name in ("ethernet1/1/15", "port-channel10", "vlan700", "loopback0"):
            ident = codec.classify_port_name(name)
            assert codec.format_port_identity(ident) == name

    def test_two_segment_foreign_identity_gains_a_node_segment(self, codec):
        """An NX-OS `Ethernet1/1` carries only module/port; OS10 names
        always have three segments, so the node defaults to 1."""
        from netcanon.migration.canonical.port_names import PortIdentity

        ident = PortIdentity(kind="physical", module=1, port=1, original="Ethernet1/1")
        assert codec.format_port_identity(ident) == "ethernet1/1/1"

    def test_unknown_name_falls_through(self, codec):
        assert codec.classify_port_name("ether1").kind == "unknown"


# ---------------------------------------------------------------------------
# Parse-only contract
# ---------------------------------------------------------------------------


class TestCodecContract:
    def test_direction_is_bidirectional(self, codec):
        assert codec.direction == "bidirectional"

    def test_input_format_is_in_the_catalogue(self, codec):
        from netcanon.migration.codecs.base import INPUT_FORMATS

        assert codec.input_format in INPUT_FORMATS

    def test_codec_is_registered(self):
        """Phase 4 registered the codec.

        This assertion was `not in list_codecs()` for Phases 1-3, which
        made the sequencing explicit rather than incidental: registration
        grows the mesh from 132 to 156 ordered pairs and could not land
        until the 24 pair-expectation YAMLs and the re-cut baseline landed
        with it.  Flipped here, in that same change.
        """
        from netcanon.migration.codecs.registry import (
            list_codecs,
            list_public_codecs,
        )

        assert "dell_os10" in list_codecs()
        # Not hidden — it must reach the target dropdown and auto-detection.
        assert "dell_os10" in list_public_codecs()


# ---------------------------------------------------------------------------
# Phase 2 — render + round-trip
# ---------------------------------------------------------------------------


def _compare(intent: CanonicalIntent) -> dict[str, Any]:
    """Strip metadata + sort cosmetic-order list fields.

    A verbatim mirror of ``test_real_captures::_compare`` and its
    synthetic twin.  Reproduced rather than imported because those live
    in harnesses that discover codecs through ``list_codecs()``, which
    cannot see this codec until it registers — but the invariant it
    checks must be identical, or Phase 4 would discover a round-trip
    failure the moment registration made the real harness apply.
    """
    d = intent.model_dump()
    d.pop("source_vendor", None)
    d.pop("source_format", None)
    d.pop("source_version", None)
    # Populated only on the SOURCE-side parse; render re-emits no Tier-3
    # stanzas, so the second parse correctly yields an empty list.
    d.pop("dropped_tier3_sections", None)
    for key, id_key in [
        ("interfaces", "name"),
        ("vlans", "id"),
        ("static_routes", "destination"),
        ("lags", "name"),
        ("routing_instances", "name"),
    ]:
        if key in d and isinstance(d[key], list):
            d[key] = sorted(d[key], key=lambda x: x.get(id_key, ""))
    for v in d.get("vlans", []):
        v["tagged_ports"] = sorted(v.get("tagged_ports") or [])
        v["untagged_ports"] = sorted(v.get("untagged_ports") or [])
    for lag in d.get("lags", []):
        lag["members"] = sorted(lag.get("members") or [])
    for iface in d.get("interfaces", []):
        iface["trunk_allowed_vlans"] = sorted(
            iface.get("trunk_allowed_vlans") or []
        )
    return d


# An operator-authored config: the `Vlan <N>` spelling, a quoted
# description, a named VRF, and an IPv6 address.
_OPERATOR_CONFIG = (
    "hostname OS10-TOR1\n"
    "!\n"
    "ip vrf tenant_a\n"
    "!\n"
    "interface Vlan 700\n"
    ' description "mgmt 10.0.1.0/24"\n'
    " no shutdown\n"
    " ip address 10.0.0.122/24\n"
    "!\n"
    "interface Vlan 711\n"
    " description STORAGE-1\n"
    " mtu 9216\n"
    " no shutdown\n"
    "!\n"
    "interface ethernet1/1/5\n"
    " description HCI-NODE\n"
    " no shutdown\n"
    " channel-group 7 mode passive\n"
    "!\n"
    "interface port-channel7\n"
    " no shutdown\n"
    " switchport mode trunk\n"
    " switchport access vlan 700\n"
    " switchport trunk allowed vlan 711,713\n"
    "!\n"
    "interface vlan125\n"
    " ip vrf forwarding tenant_a\n"
    " ipv6 address 2001:db8::1/64\n"
    " no shutdown\n"
    "!\n"
    "ip route 0.0.0.0/0 192.168.100.1\n"
    "management route 0.0.0.0/0 192.168.33.1\n"
)


class TestRoundTrip:
    @pytest.mark.parametrize(
        "raw", [_DEVICE_DUMP, _OPERATOR_CONFIG], ids=["device", "operator"],
    )
    def test_round_trip_is_canonical_stable(self, codec, raw):
        """``parse(render(parse(raw))) == parse(raw)``.

        The render need not be byte-identical to the input — real configs
        carry comments and directives we do not model.  What must hold is
        that the canonical representation STABILISES after one
        round-trip; otherwise the codec is lossy in a way that compounds,
        or non-deterministic in render.
        """
        first = codec.parse(raw)
        rendered = codec.render(first)
        second = codec.parse(rendered)
        assert _compare(first) == _compare(second)

    def test_render_output_reparses_without_raising(self, codec):
        rendered = codec.render(codec.parse(_DEVICE_DUMP))
        assert isinstance(codec.parse(rendered), CanonicalIntent)

    def test_native_vlan_survives_the_round_trip(self, codec):
        """The inversion that matters most: OS10 has no `switchport trunk
        native vlan` line, so the native VLAN must re-emit with the
        `access vlan` keyword.  Anything else round-trips into
        `access_vlan` and flips the port's L2 semantics."""
        second = codec.parse(codec.render(codec.parse(_DEVICE_DUMP)))
        po = next(i for i in second.interfaces if i.name == "port-channel100")
        assert po.switchport_mode == "trunk"
        assert po.trunk_native_vlan == 1
        assert po.access_vlan is None

    def test_management_route_survives_the_round_trip(self, codec):
        second = codec.parse(codec.render(codec.parse(_DEVICE_DUMP)))
        assert [r.vrf for r in second.static_routes] == ["management"]
        assert [r for r in second.static_routes if not r.vrf] == []

    def test_empty_hostname_stays_empty(self, codec):
        """Substituting a default for an absent hostname (what the NX-OS
        render does, because its `vdc` wrapper needs a name) would
        re-parse as that default and drift."""
        first = codec.parse("ip route 0.0.0.0/0 10.0.0.1\n")
        assert first.hostname == ""
        second = codec.parse(codec.render(first))
        assert second.hostname == ""

    def test_lag_mode_survives_the_round_trip(self, codec):
        second = codec.parse(codec.render(codec.parse(_OPERATOR_CONFIG)))
        lag = next(x for x in second.lags if x.name == "port-channel7")
        assert lag.mode == "passive"
        assert lag.members == ["ethernet1/1/5"]


class TestRenderForm:
    def test_native_vlan_uses_the_access_vlan_keyword(self, codec):
        out = codec.render(codec.parse(_DEVICE_DUMP))
        assert " switchport mode trunk" in out
        assert " switchport access vlan 1" in out
        assert "native vlan" not in out

    def test_management_route_keeps_its_own_keyword(self, codec):
        out = codec.render(codec.parse(_DEVICE_DUMP))
        assert "management route 0.0.0.0/0 192.168.33.1" in out
        assert "ip route 0.0.0.0/0" not in out

    def test_svi_renders_in_the_device_form(self, codec):
        """Device output normalises to `interface vlan<N>`; operators
        write `Vlan <N>`.  Render emits what a real switch prints."""
        out = codec.render(codec.parse(_OPERATOR_CONFIG))
        assert "interface vlan700" in out
        assert "interface Vlan 700" not in out

    def test_explicit_ip_vrf_default_is_emitted(self, codec):
        """One line, and it makes our own output self-identifying."""
        out = codec.render(codec.parse(_DEVICE_DUMP))
        assert "ip vrf default" in out

    def test_named_vrf_is_declared_before_the_interface_bind(self, codec):
        out = codec.render(codec.parse(_OPERATOR_CONFIG))
        assert "ip vrf tenant_a" in out
        assert out.index("ip vrf tenant_a") < out.index("ip vrf forwarding")

    def test_vrf_bind_precedes_the_address(self, codec):
        """Changing an interface's VRF clears its addresses on commit, so
        the bind has to come first."""
        out = codec.render(codec.parse(_OPERATOR_CONFIG))
        block = out.split("interface vlan125")[1].split("!")[0]
        assert block.index("ip vrf forwarding") < block.index("ipv6 address")

    def test_named_vlan_without_an_svi_is_synthesised(self, codec):
        """A cross-vendor VLAN carrying a name has no other OS10
        representation — `interface vlan<N>` is the only one."""
        tree = CanonicalIntent(vlans=[CanonicalVlan(id=10, name="PROD")])
        out = codec.render(tree)
        assert "interface vlan10" in out
        assert " description PROD" in out

    def test_projection_only_vlan_is_not_synthesised(self, codec):
        """VLAN 5 is known ONLY from switchport membership.  Emitting an
        SVI for it would add an interface the source tree never had and
        drift the `interfaces` list on re-parse — the membership already
        reconstructs it."""
        first = codec.parse(
            "interface ethernet1/1/1\n switchport access vlan 5\n!\n"
        )
        assert {v.id for v in first.vlans} == {5}
        out = codec.render(first)
        assert "interface vlan5" not in out
        second = codec.parse(out)
        assert {v.id for v in second.vlans} == {5}
        assert [i.name for i in second.interfaces] == ["ethernet1/1/1"]

    def test_empty_lag_declaration_is_not_invented(self, codec):
        """A port-channel known only from a member's `channel-group` line
        must not gain a stanza — re-parse rebuilds it from that line."""
        first = codec.parse(
            "interface ethernet1/1/5\n channel-group 7 mode active\n!\n"
        )
        out = codec.render(first)
        assert "interface port-channel7" not in out
        assert [x.name for x in codec.parse(out).lags] == ["port-channel7"]


class TestRenderedOutputIsDetectedCorrectly:
    """Our own render must not reproduce the defect PR #475 closed."""

    def test_rendered_output_is_not_claimed_by_cisco(self, codec):
        """`cisco_iosxe_cli` confidently claimed every Dell config at
        confidence 95 until #475.  Emitting a config our own ecosystem
        re-detects as Cisco would reintroduce that fail-open from the
        render side."""
        rendered = codec.render(codec.parse(_DEVICE_DUMP))
        assert CiscoIOSXECLICodec.probe(rendered[:500]) is None

    def test_rendered_output_is_self_detecting(self, codec):
        rendered = codec.render(codec.parse(_DEVICE_DUMP))
        hit = codec.probe(rendered[:500])
        assert hit is not None and hit[0] >= 95

    def test_no_invented_timestamp_banner(self, codec):
        """A real dump's second line is `! Last configuration change at
        <timestamp>` — the exact string that caused the mis-detection.
        We would have to invent it, so we do not emit it."""
        out = codec.render(codec.parse(_DEVICE_DUMP))
        assert "Last configuration change" not in out


class TestTier3LossSurfacing:
    _TIER3_CONFIG = (
        "! Version 10.5.1.0\n"
        "!\n"
        "interface breakout 1/1/1 map 100g-1x\n"
        "interface breakout 1/1/2 map 100g-1x\n"
        "interface breakout 1/1/3 map 100g-1x\n"
        "hostname tor1\n"
        "!\n"
        "class-map type queuing Q0\n"
        " match queue 0\n"
        "!\n"
        "system qos\n"
        " trust-map dot1p trust_map\n"
        "!\n"
        "vlt-domain 1\n"
        " backup destination 192.168.255.2\n"
        "!\n"
        "router bgp 65001\n"
        "!\n"
    )

    def test_dropped_sections_are_surfaced(self, codec):
        sections = codec.parse(self._TIER3_CONFIG).dropped_tier3_sections
        assert "vlt-domain 1" in sections
        assert "system qos" in sections
        assert "router bgp 65001" in sections
        assert "class-map type queuing Q0" in sections

    def test_breakout_label_is_deduped_to_one_entry(self, codec):
        """A 32-port switch carries 32 distinct `interface breakout`
        lines.  Capturing the port/profile tail would flood the
        operator's banner with 32 near-identical rows."""
        sections = codec.parse(self._TIER3_CONFIG).dropped_tier3_sections
        breakout = [s for s in sections if s.startswith("interface breakout")]
        assert breakout == ["interface breakout"]

    def test_parsed_surfaces_are_not_flagged_as_dropped(self, codec):
        """`hostname` / `interface` / `ip vrf` / routes ARE parsed, so
        flagging them would tell the operator they were lost."""
        sections = codec.parse(_DEVICE_DUMP).dropped_tier3_sections
        joined = " ".join(sections)
        assert "hostname" not in joined
        assert "ip vrf default" not in joined
        assert "management route" not in joined

    def test_tier3_is_excluded_from_round_trip_comparison(self, codec):
        """Render re-emits no Tier-3 stanzas, so the second parse yields
        an empty list by design — it is metadata about the INPUT, not
        canonical config data."""
        first = codec.parse(self._TIER3_CONFIG)
        second = codec.parse(codec.render(first))
        assert first.dropped_tier3_sections != []
        assert second.dropped_tier3_sections == []
        assert _compare(first) == _compare(second)


# ---------------------------------------------------------------------------
# Declared losses are real — and capability-matrix honesty
# ---------------------------------------------------------------------------


def _loss_declared(codec) -> set[str]:
    caps = codec.capabilities
    return {lp.path for lp in caps.lossy} | {u.path for u in caps.unsupported}


#: The ONLY walkable leaves allowed to rely on ``classify()``'s
#: ``supported`` default — i.e. the ones this codec genuinely round-trips.
#: Every other walkable leaf must be named explicitly in the matrix, or it
#: claims a migration the codec does not perform.  Each entry here is
#: proved by a counter-case in
#: :class:`TestUndeclaredPathsGenuinelyRoundTrip`.
_ROUND_TRIPPING_UNDECLARED = {
    "/interfaces/interface/ipv4/address/secondary-ip",
    "/interfaces/interface/ipv6/address/scope",
    "/routing-instances/instance",
    "/routing/static-route/gateway",
    "/routing/static-route/interface",
    "/routing/static-route/metric",
    "/vlans/vlan/ipv4/address/ip",
    "/vlans/vlan/ipv4/address/secondary-ip",
}


class TestUndeclaredPathsGenuinelyRoundTrip:
    """Counter-cases for every leaf left to the ``supported`` default.

    Over-declaring a loss is not free — ``test_roundtrip_emitted_xpath_
    not_unsupported`` fails any path that survives a round-trip while
    declared unsupported — so "declare everything" is not a safe
    shortcut.  Each leaf below is left undeclared BECAUSE it survives,
    and these prove it.
    """

    def test_ipv6_link_local_scope_is_reinferred(self, codec):
        """Render emits no `link-local` keyword; the parser recovers the
        scope from the fe80::/10 prefix (RFC 4291), which is exactly why
        the CLI codecs that do the same stay `supported` here."""
        first = codec.parse(
            "interface vlan700\n ipv6 address fe80::1/64\n!\n"
        )
        assert first.interfaces[0].ipv6_addresses[0].scope == "link-local"
        second = codec.parse(codec.render(first))
        assert second.interfaces[0].ipv6_addresses[0].scope == "link-local"

    def test_static_route_gateway_interface_and_metric_survive(self, codec):
        first = codec.parse("ip route 10.0.0.0/8 ethernet 1/1/1 10.9.9.9 200\n")
        route = first.static_routes[0]
        assert (route.gateway, route.interface, route.metric) == (
            "10.9.9.9", "ethernet 1/1/1", 200,
        )
        back = codec.parse(codec.render(first)).static_routes[0]
        assert (back.gateway, back.interface, back.metric) == (
            "10.9.9.9", "ethernet 1/1/1", 200,
        )

    def test_routing_instance_anchor_survives(self, codec):
        first = codec.parse("ip vrf tenant_a\n!\n")
        back = codec.parse(codec.render(first))
        assert [ri.name for ri in back.routing_instances] == ["tenant_a"]

    def test_vlan_record_ipv4_survives_via_the_synthesised_svi(self, codec):
        """A VLAN carrying an address but NO interface gets an SVI
        synthesised for it, so both the address and its secondary flag
        come back."""
        tree = CanonicalIntent(
            vlans=[
                CanonicalVlan(
                    id=700,
                    name="MGMT",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.0.0.2", prefix_length=24),
                        CanonicalIPv4Address(
                            ip="10.0.1.2", prefix_length=24, is_secondary=True,
                        ),
                    ],
                ),
            ],
        )
        back = codec.parse(codec.render(tree))
        vlan = next(v for v in back.vlans if v.id == 700)
        assert [a.ip for a in vlan.ipv4_addresses] == ["10.0.0.2", "10.0.1.2"]
        assert [a.is_secondary for a in vlan.ipv4_addresses] == [False, True]


class TestDeclaredLossesAreReal:
    """Every ``LossyPath`` is PROVED by a render→parse probe.

    ``classify()`` defaults an undeclared xpath to ``supported``, so a
    field the render drops while its anchor survives makes
    ``validate_against`` report ``severity: ok`` over discarded data.
    These probes assert BOTH halves — that the drop genuinely happens and
    that it is declared — so a declaration cannot drift into folklore,
    and closing a loss later fails here until the declaration is removed
    in the same change.
    """

    def test_instance_type_downgrades_to_plain_vrf(self, codec):
        tree = CanonicalIntent(
            routing_instances=[
                CanonicalRoutingInstance(name="tenant_a", instance_type="mac-vrf"),
            ],
        )
        back = codec.parse(codec.render(tree))
        # Anchor survives...
        assert [ri.name for ri in back.routing_instances] == ["tenant_a"]
        # ...the discriminator does not.
        assert back.routing_instances[0].instance_type == "vrf"
        assert "/routing-instances/instance/instance-type" in _loss_declared(codec)

    def test_vlan_description_is_dropped(self, codec):
        tree = CanonicalIntent(
            vlans=[CanonicalVlan(id=10, name="PROD", description="finance tier")],
        )
        back = codec.parse(codec.render(tree))
        assert [v.id for v in back.vlans] == [10]
        assert back.vlans[0].name == "PROD"
        assert back.vlans[0].description == ""
        assert "/vlans/vlan/description" in _loss_declared(codec)

    def test_ipv4_virtual_gateway_address_is_dropped(self, codec):
        tree = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="vlan700",
                    ipv4_addresses=[
                        CanonicalIPv4Address(
                            ip="10.0.0.2",
                            prefix_length=24,
                            virtual_gateway_address="10.0.0.1",
                        ),
                    ],
                ),
            ],
        )
        back = codec.parse(codec.render(tree))
        addr = back.interfaces[0].ipv4_addresses[0]
        assert addr.ip == "10.0.0.2"
        assert addr.virtual_gateway_address == ""
        assert (
            "/interfaces/interface/ipv4/address/virtual-gateway-address"
            in _loss_declared(codec)
        )

    def test_ipv6_virtual_gateway_address_is_dropped(self, codec):
        tree = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="vlan700",
                    ipv6_addresses=[
                        CanonicalIPv6Address(
                            ip="2001:db8::2",
                            prefix_length=64,
                            virtual_gateway_address="2001:db8::1",
                        ),
                    ],
                ),
            ],
        )
        back = codec.parse(codec.render(tree))
        addr = back.interfaces[0].ipv6_addresses[0]
        assert addr.ip == "2001:db8::2"
        assert addr.virtual_gateway_address == ""
        assert (
            "/interfaces/interface/ipv6/address/virtual-gateway-address"
            in _loss_declared(codec)
        )

    def test_tunnel_type_is_dropped_while_the_port_survives(self, codec):
        tree = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="tunnel1",
                    tunnel_type="gre",
                    interface_type="ianaift:tunnel",
                ),
            ],
        )
        back = codec.parse(codec.render(tree))
        assert [i.name for i in back.interfaces] == ["tunnel1"]
        assert back.interfaces[0].tunnel_type == ""
        assert "/interfaces/interface/tunnel-type" in _loss_declared(codec)

    def test_secondary_ipv4_flag_does_survive(self, codec):
        """Counter-case: `is_secondary` IS re-emitted, so it must NOT be
        declared lossy.  Without a counter-case the class above only
        proves the matrix can over-declare."""
        tree = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="vlan700",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.0.0.2", prefix_length=24),
                        CanonicalIPv4Address(
                            ip="10.0.1.2", prefix_length=24, is_secondary=True,
                        ),
                    ],
                ),
            ],
        )
        back = codec.parse(codec.render(tree))
        flags = [a.is_secondary for a in back.interfaces[0].ipv4_addresses]
        assert flags == [False, True]


class TestLocalUsers:
    _USERS = (
        "hostname tor1\n"
        "system-user linuxadmin password $6$SSSSSSSS$BBBBBBBB\n"
        "username admin password $6$SSSSSSSS$BBBBBBBB role sysadmin priv-lvl 15\n"
        "username reader password Passphrase0 role netoperator\n"
    )

    def test_priv_lvl_is_read_when_stated(self, codec):
        admin = codec.parse(self._USERS).local_users[0]
        assert (admin.name, admin.role, admin.privilege_level) == (
            "admin", "sysadmin", 15,
        )

    def test_priv_lvl_is_derived_from_the_role_when_omitted(self, codec):
        """`priv-lvl` is genuinely optional — 2 of the 8 real `username`
        lines omit it, so a parser that requires it drops those accounts
        silently."""
        reader = codec.parse(self._USERS).local_users[1]
        assert (reader.role, reader.privilege_level) == ("netoperator", 1)

    def test_system_user_is_not_modelled_as_a_login(self, codec):
        """`system-user linuxadmin` is the switch's underlying Linux shell
        account.  Re-emitting it as a `username` would convert a shell
        account into a NOS operator, so it is surfaced as a dropped
        section instead — and the label carries no hash."""
        intent = codec.parse(self._USERS)
        assert [u.name for u in intent.local_users] == ["admin", "reader"]
        assert "system-user" in intent.dropped_tier3_sections
        assert not any("$6$" in s for s in intent.dropped_tier3_sections)

    def test_users_round_trip(self, codec):
        first = codec.parse(self._USERS)
        second = codec.parse(codec.render(first))
        assert [u.model_dump() for u in first.local_users] == [
            u.model_dump() for u in second.local_users
        ]

    def test_a_hash_os10_cannot_consume_is_refused_not_re_emitted(self, codec):
        """Re-emitting an unconsumable digest would make the digest itself
        the password — the #460 fail-open.  A bcrypt value has no OS10
        form, so the account drops and a review comment takes its place."""
        bcrypt = "$2y$10$" + "B" * 53
        tree = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(
                    name="opnuser", hashed_password=bcrypt,
                    role="sysadmin", privilege_level=15,
                ),
            ],
        )
        out = codec.render(tree)
        assert "B" * 40 not in out
        assert "review:" in out and "opnuser" in out
        assert "username opnuser password" not in out

    def test_a_user_with_no_secret_survives_the_round_trip(self, codec):
        """The render emits no password clause for a secret-less
        cross-vendor account, so the parser must accept that form — else
        the account vanishes on re-parse."""
        tree = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(
                    name="nopass", role="netoperator", privilege_level=1,
                ),
            ],
        )
        back = codec.parse(codec.render(tree))
        assert [u.name for u in back.local_users] == ["nopass"]
        assert back.local_users[0].hashed_password == ""


class TestSnmp:
    _SNMP = (
        "hostname tor1\n"
        'snmp-server contact "Contact Support"\n'
        'snmp-server location "Rack 1"\n'
        "snmp-server host 10.0.0.9 traps version 3 priv netmon\n"
        "snmp-server user netmon netmon 3 auth sha AUTHKEY0 priv aes PRIVKEY0\n"
    )

    def test_quoted_contact_and_location_are_unquoted(self, codec):
        snmp = codec.parse(self._SNMP).snmp
        assert snmp.contact == "Contact Support"
        assert snmp.location == "Rack 1"

    def test_trap_host_is_harvested(self, codec):
        assert codec.parse(self._SNMP).snmp.trap_hosts == ["10.0.0.9"]

    def test_v3_user_without_marker_is_stamped_plaintext(self, codec):
        """The one real `snmp-server user` line in the whole capture
        corpus carries NO `localized` marker, so it is a passphrase the
        switch localises itself — kind comes from the grammar, never from
        the value's shape (#460)."""
        user = codec.parse(self._SNMP).snmp.v3_users[0]
        assert (user.name, user.group) == ("netmon", "netmon")
        assert (user.auth_protocol, user.priv_protocol) == ("sha", "aes")
        assert user.auth_kind == PLAINTEXT
        assert user.priv_kind == PLAINTEXT

    def test_v3_user_with_marker_is_stamped_localised(self, codec):
        """Manual-attested (10.5.2 User Guide L9085): no capture in the
        corpus exercises the marked form, so it is covered synthetically
        rather than implied to have fixture backing."""
        raw = (
            "snmp-server user marked grp 3 auth md5 DIGEST00 "
            "priv des DIGEST01 localized\n"
        )
        user = codec.parse(raw).snmp.v3_users[0]
        assert user.auth_kind == LOCALISED
        assert user.priv_kind == LOCALISED

    def test_priv_cipher_cannot_swallow_the_key(self, codec):
        """The cipher is an ENUMERATED token.  A greedy `(\\S+)\\s+(\\S+)`
        pair would take the priv KEY as the cipher and `localized` as the
        key, landing real key material in the unsanitised `priv_protocol`
        field — the NX-OS disclosure this shape exists to avoid."""
        raw = (
            "snmp-server user u1 g1 3 auth md5 AUTHKEY0 "
            "priv aes PRIVKEY0 localized\n"
        )
        user = codec.parse(raw).snmp.v3_users[0]
        assert user.priv_protocol == "aes"
        assert user.priv_passphrase == "PRIVKEY0"

    def test_no_snmp_lines_leaves_no_stub(self, codec):
        assert codec.parse("hostname tor1\n").snmp is None

    def test_snmp_round_trips(self, codec):
        first = codec.parse(self._SNMP)
        second = codec.parse(codec.render(first))
        assert first.snmp.model_dump() == second.snmp.model_dump()


class TestCapabilityMatrixHonesty:
    """Pre-satisfies the registry-wide honesty guards.

    ``test_registry_capability_honesty`` and the three walk-expansion
    guards (PR-2a / 2b / 2c) derive their roster from the codec registry,
    so they enrol this codec AUTOMATICALLY the moment it registers in
    Phase 4.  Running the same checks here means registration cannot
    discover a matrix that has been wrong since Phase 1.
    """

    def test_every_supported_path_is_walkable(self, codec):
        """A declared path the canonical walker never emits is
        unreachable by ``validate_against`` (classify is exact-string
        match) — a dead declaration."""
        from tests.unit.migration.test_registry_capability_honesty import (
            _WALKABLE,
        )

        unreachable = [
            p for p in codec.capabilities.supported if p not in _WALKABLE
        ]
        assert not unreachable, (
            f"supported paths the walker never yields: {unreachable}"
        )

    def test_no_declaration_overlaps(self, codec):
        caps = codec.capabilities
        supported = set(caps.supported)
        assert not (supported & {lp.path for lp in caps.lossy})
        assert not (supported & {u.path for u in caps.unsupported})

    def test_vrrp_mode_is_never_silently_supported(self, codec):
        """No codec renders every FHRP family, so the family
        discriminator can never round-trip guaranteed — it must be
        declared, never left to the supported fail-open."""
        assert codec.capabilities.classify(
            "/interfaces/interface/vrrp-groups/group/mode"
        ) in {"lossy", "unsupported"}

    def test_no_walkable_path_silently_defaults_to_supported(self, codec):
        """The whole matrix, checked at once.

        ``classify()`` is an exact-string match, so a walkable leaf the
        matrix never names defaults to ``supported`` — claiming a
        migration the codec does not perform.  The ONLY leaves allowed to
        rely on that default are ones this codec genuinely round-trips,
        each proved by a counter-case in
        :class:`TestUndeclaredPathsGenuinelyRoundTrip`.

        Declaring a parent does NOT cover its children: this guard was
        added after ``/interfaces/interface/vrrp-groups/group`` was
        declared unsupported while all ten of its sub-fields still
        classified ``supported``.
        """
        from tests.unit.migration.test_registry_capability_honesty import (
            _WALKABLE,
        )

        caps = codec.capabilities
        declared = (
            set(caps.supported)
            | {lp.path for lp in caps.lossy}
            | {u.path for u in caps.unsupported}
        )
        assert _WALKABLE - declared == _ROUND_TRIPPING_UNDECLARED

    def test_render_survives_the_maximal_intent(self, codec):
        """The walk-expansion guards feed ``_maximal_intent()`` through
        every registered codec.  Rendering a tree carrying every
        canonical surface at once must not raise, even though most of
        them are surfaces this codec does not emit."""
        from tests.unit.migration.test_registry_capability_honesty import (
            _maximal_intent,
        )

        out = codec.render(_maximal_intent())
        assert isinstance(codec.parse(out), CanonicalIntent)
