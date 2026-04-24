"""
Unit tests for GAP 6 VXLAN/EVPN codec wire-up (Arista + Junos).

Covers parse + render + round-trip for:
- CanonicalVxlan (VLAN→VNI mappings)
- CanonicalRoutingInstance (VRF declarations with RD + RTs +
  instance_type + L3 VNI)
- CanonicalInterface.vrf (per-interface VRF membership)

GAP 5 landed the canonical schema; GAP 6 wires Arista EOS +
Juniper Junos codecs to populate and emit it.  EVPN Type-5 per-
prefix records remain Unsupported on both — Type-5 announcements
are modelled via CanonicalRoutingInstance.l3_vni (a VRF property).
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalRoutingInstance,
    CanonicalVlan,
    CanonicalVxlan,
)
from netconfig.migration.codecs.arista_eos import AristaEOSCodec
from netconfig.migration.codecs.juniper_junos import JunosCodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Arista EOS — parse
# ---------------------------------------------------------------------------


class TestAristaVxlanParse:
    def test_vlan_vni_mapping(self):
        raw = (
            "interface Vxlan1\n"
            "   vxlan source-interface Loopback0\n"
            "   vxlan vlan 100 vni 10100\n"
            "   vxlan vlan 200 vni 10200\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        vnis = [(v.vlan_id, v.vni) for v in intent.vxlan_vnis]
        assert vnis == [(100, 10100), (200, 10200)]

    def test_vxlan_stanza_not_materialised_as_interface(self):
        """Vxlan1 is a VXLAN config container, not a real interface.
        Its sub-commands populate CanonicalVxlan records; the Vxlan1
        name should NOT appear in tree.interfaces."""
        raw = (
            "interface Vxlan1\n"
            "   vxlan source-interface Loopback0\n"
            "   vxlan vlan 100 vni 10100\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        names = [i.name for i in intent.interfaces]
        assert "Vxlan1" not in names

    def test_vxlan_malformed_line_tolerated(self):
        raw = (
            "interface Vxlan1\n"
            "   vxlan vlan not-a-number vni 10100\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert len(intent.vxlan_vnis) == 0


class TestAristaVrfParse:
    def test_vrf_instance_declaration(self):
        raw = (
            "vrf instance TENANT_A\n"
            "vrf instance TENANT_B\n"
        )
        intent = AristaEOSCodec().parse(raw)
        names = [r.name for r in intent.routing_instances]
        assert names == ["TENANT_A", "TENANT_B"]
        for ri in intent.routing_instances:
            assert ri.instance_type == "vrf"
            assert ri.route_distinguisher == ""
            assert ri.l3_vni is None

    def test_interface_vrf_membership(self):
        raw = (
            "vrf instance TENANT_A\n"
            "!\n"
            "interface Ethernet1\n"
            "   vrf TENANT_A\n"
            "   ip address 10.1.0.1/24\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = next(i for i in intent.interfaces if i.name == "Ethernet1")
        assert iface.vrf == "TENANT_A"

    def test_l3_vni_mapping(self):
        """`vxlan vrf <name> vni <N>` populates ri.l3_vni."""
        raw = (
            "vrf instance TENANT_A\n"
            "!\n"
            "interface Vxlan1\n"
            "   vxlan vrf TENANT_A vni 15001\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        ri = next(r for r in intent.routing_instances if r.name == "TENANT_A")
        assert ri.l3_vni == 15001

    def test_l3_vni_autocreates_vrf_record(self):
        """If `vxlan vrf X vni N` references a VRF that hasn't been
        declared via `vrf instance X`, autocreate the record so the
        L3 VNI info doesn't disappear."""
        raw = (
            "interface Vxlan1\n"
            "   vxlan vrf TENANT_ORPHAN vni 99999\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        ri = next(
            (r for r in intent.routing_instances if r.name == "TENANT_ORPHAN"),
            None,
        )
        assert ri is not None
        assert ri.l3_vni == 99999

    def test_router_bgp_vrf_rd_rts(self):
        raw = (
            "vrf instance TENANT_A\n"
            "!\n"
            "router bgp 65001\n"
            "   neighbor 10.0.0.2 remote-as 65002\n"
            "   !\n"
            "   vrf TENANT_A\n"
            "      rd 192.168.1.1:100\n"
            "      route-target import evpn 100:100\n"
            "      route-target export evpn 100:100\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        ri = next(r for r in intent.routing_instances if r.name == "TENANT_A")
        assert ri.route_distinguisher == "192.168.1.1:100"
        assert ri.rt_imports == ["100:100"]
        assert ri.rt_exports == ["100:100"]

    def test_router_bgp_vrf_rd_separator_shared(self):
        """`route-target both <rt>` populates both import and export."""
        raw = (
            "vrf instance TENANT_A\n"
            "!\n"
            "router bgp 65001\n"
            "   vrf TENANT_A\n"
            "      rd 1.1.1.1:5001\n"
            "      route-target both 5001:5001\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        ri = next(r for r in intent.routing_instances if r.name == "TENANT_A")
        assert ri.rt_imports == ["5001:5001"]
        assert ri.rt_exports == ["5001:5001"]


# ---------------------------------------------------------------------------
# Arista EOS — render
# ---------------------------------------------------------------------------


class TestAristaVxlanRender:
    def test_render_vxlan_vnis(self):
        intent = CanonicalIntent(
            hostname="leaf1",
            vxlan_vnis=[
                CanonicalVxlan(vlan_id=100, vni=10100),
                CanonicalVxlan(vlan_id=200, vni=10200),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "interface Vxlan1" in out
        assert "   vxlan vlan 100 vni 10100" in out
        assert "   vxlan vlan 200 vni 10200" in out

    def test_render_vrf_instances(self):
        intent = CanonicalIntent(
            hostname="leaf1",
            routing_instances=[
                CanonicalRoutingInstance(name="TENANT_A"),
                CanonicalRoutingInstance(name="TENANT_B"),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "vrf instance TENANT_A" in out
        assert "vrf instance TENANT_B" in out

    def test_render_interface_vrf(self):
        intent = CanonicalIntent(
            hostname="leaf1",
            routing_instances=[
                CanonicalRoutingInstance(name="TENANT_A"),
            ],
            interfaces=[
                CanonicalInterface(
                    name="Ethernet1",
                    vrf="TENANT_A",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.1.0.1", prefix_length=24),
                    ],
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "interface Ethernet1" in out
        assert "   vrf TENANT_A" in out
        assert "   ip address 10.1.0.1/24" in out

    def test_render_l3_vni(self):
        intent = CanonicalIntent(
            hostname="leaf1",
            routing_instances=[
                CanonicalRoutingInstance(name="TENANT_A", l3_vni=15001),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "interface Vxlan1" in out
        assert "   vxlan vrf TENANT_A vni 15001" in out

    def test_render_bgp_vrf_rd_rts_matched(self):
        """When import == export RTs, render compact ``route-target
        both <rt>`` form."""
        intent = CanonicalIntent(
            hostname="leaf1",
            routing_instances=[
                CanonicalRoutingInstance(
                    name="TENANT_A",
                    route_distinguisher="1.1.1.1:5001",
                    rt_imports=["5001:5001"],
                    rt_exports=["5001:5001"],
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "router bgp 65000" in out
        assert "   vrf TENANT_A" in out
        assert "      rd 1.1.1.1:5001" in out
        assert "      route-target both 5001:5001" in out


class TestAristaVxlanRoundTrip:
    def test_roundtrip_full_evpn_leaf(self):
        """End-to-end: build a canonical EVPN leaf, render, re-parse,
        verify all the VXLAN/VRF/L3-VNI/RD/RT data survives."""
        intent = CanonicalIntent(
            hostname="leaf1",
            vlans=[
                CanonicalVlan(id=100, name="V100"),
                CanonicalVlan(id=200, name="V200"),
            ],
            vxlan_vnis=[
                CanonicalVxlan(vlan_id=100, vni=10100),
                CanonicalVxlan(vlan_id=200, vni=10200),
            ],
            routing_instances=[
                CanonicalRoutingInstance(
                    name="TENANT_A",
                    route_distinguisher="1.1.1.1:5001",
                    rt_imports=["5001:5001"],
                    rt_exports=["5001:5001"],
                    l3_vni=15001,
                ),
            ],
            interfaces=[
                CanonicalInterface(
                    name="Ethernet1",
                    vrf="TENANT_A",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.1.0.1", prefix_length=24),
                    ],
                ),
            ],
        )
        codec = AristaEOSCodec()
        rendered = codec.render(intent)
        second = codec.parse(rendered)
        # VXLAN VNIs round-trip.
        assert sorted((v.vlan_id, v.vni) for v in second.vxlan_vnis) == [
            (100, 10100), (200, 10200),
        ]
        # VRF round-trips with RD + RTs + L3 VNI.
        ri = next(r for r in second.routing_instances if r.name == "TENANT_A")
        assert ri.route_distinguisher == "1.1.1.1:5001"
        assert ri.rt_imports == ["5001:5001"]
        assert ri.rt_exports == ["5001:5001"]
        assert ri.l3_vni == 15001
        # Per-interface VRF membership round-trips.
        iface = next(i for i in second.interfaces if i.name == "Ethernet1")
        assert iface.vrf == "TENANT_A"


# ---------------------------------------------------------------------------
# Juniper Junos — parse
# ---------------------------------------------------------------------------


class TestJunosVxlanParse:
    def test_vlan_vni_mapping(self):
        raw = (
            "set vlans V100 vlan-id 100\n"
            "set vlans V100 vxlan vni 10100\n"
        )
        intent = JunosCodec().parse(raw)
        assert len(intent.vxlan_vnis) == 1
        assert intent.vxlan_vnis[0].vlan_id == 100
        assert intent.vxlan_vnis[0].vni == 10100

    def test_vxlan_without_vlan_id_skipped(self):
        """vxlan vni line alone without prior vlan-id declaration
        silently drops — v1 doesn't stash pending mappings."""
        raw = "set vlans V100 vxlan vni 10100\n"
        intent = JunosCodec().parse(raw)
        assert len(intent.vxlan_vnis) == 0


class TestJunosRoutingInstancesParse:
    def test_instance_type_vrf(self):
        raw = "set routing-instances TENANT_A instance-type vrf\n"
        intent = JunosCodec().parse(raw)
        assert len(intent.routing_instances) == 1
        assert intent.routing_instances[0].name == "TENANT_A"
        assert intent.routing_instances[0].instance_type == "vrf"

    def test_route_distinguisher(self):
        raw = (
            "set routing-instances TENANT_A instance-type vrf\n"
            "set routing-instances TENANT_A route-distinguisher 1.1.1.1:100\n"
        )
        intent = JunosCodec().parse(raw)
        ri = intent.routing_instances[0]
        assert ri.route_distinguisher == "1.1.1.1:100"

    def test_vrf_target_shared(self):
        """``vrf-target target:X`` populates both import and export."""
        raw = (
            "set routing-instances TENANT_A instance-type vrf\n"
            "set routing-instances TENANT_A vrf-target target:65000:100\n"
        )
        intent = JunosCodec().parse(raw)
        ri = intent.routing_instances[0]
        assert ri.rt_imports == ["65000:100"]
        assert ri.rt_exports == ["65000:100"]

    def test_vrf_target_split(self):
        raw = (
            "set routing-instances TENANT_A instance-type vrf\n"
            "set routing-instances TENANT_A vrf-target import "
            "target:65000:100\n"
            "set routing-instances TENANT_A vrf-target export "
            "target:65000:200\n"
        )
        intent = JunosCodec().parse(raw)
        ri = intent.routing_instances[0]
        assert ri.rt_imports == ["65000:100"]
        assert ri.rt_exports == ["65000:200"]

    def test_interface_vrf_assignment(self):
        raw = (
            "set interfaces ge-0/0/1 unit 0 family inet address 10.0.0.1/24\n"
            "set routing-instances TENANT_A instance-type vrf\n"
            "set routing-instances TENANT_A interface ge-0/0/1.0\n"
        )
        intent = JunosCodec().parse(raw)
        iface = next(
            i for i in intent.interfaces if i.name == "ge-0/0/1"
        )
        assert iface.vrf == "TENANT_A"

    def test_interface_vrf_creates_stub_for_undeclared_iface(self):
        """routing-instances interface <X> where X wasn't declared
        via ``set interfaces`` creates a stub so VRF membership
        doesn't silently vanish."""
        raw = (
            "set routing-instances TENANT_A instance-type vrf\n"
            "set routing-instances TENANT_A interface ge-9/9/9.0\n"
        )
        intent = JunosCodec().parse(raw)
        iface = next(
            (i for i in intent.interfaces if i.name == "ge-9/9/9"),
            None,
        )
        assert iface is not None
        assert iface.vrf == "TENANT_A"

    def test_evpn_ip_prefix_routes_vni_populates_l3_vni(self):
        raw = (
            "set routing-instances TENANT_A instance-type vrf\n"
            "set routing-instances TENANT_A protocols evpn "
            "ip-prefix-routes vni 50000\n"
        )
        intent = JunosCodec().parse(raw)
        ri = intent.routing_instances[0]
        assert ri.l3_vni == 50000

    def test_pending_interfaces_cleaned_up(self):
        """The ``_pending_interfaces`` side-attribute used during
        dispatch should be removed after materialisation — must not
        leak into model_dump serialisation."""
        raw = (
            "set routing-instances TENANT_A instance-type vrf\n"
            "set routing-instances TENANT_A interface ge-0/0/1.0\n"
        )
        intent = JunosCodec().parse(raw)
        ri = intent.routing_instances[0]
        # Should not have _pending_interfaces on the pydantic model.
        assert not hasattr(ri, "_pending_interfaces")
        # And model_dump should not include it.
        assert "_pending_interfaces" not in ri.model_dump()


# ---------------------------------------------------------------------------
# Juniper Junos — render
# ---------------------------------------------------------------------------


class TestJunosVxlanRender:
    def test_render_vlan_vni(self):
        intent = CanonicalIntent(
            vlans=[CanonicalVlan(id=100, name="V100")],
            vxlan_vnis=[CanonicalVxlan(vlan_id=100, vni=10100)],
        )
        out = JunosCodec().render(intent)
        assert "set vlans V100 vlan-id 100" in out
        assert "set vlans V100 vxlan vni 10100" in out

    def test_render_vrf_declaration(self):
        intent = CanonicalIntent(
            routing_instances=[
                CanonicalRoutingInstance(
                    name="TENANT_A",
                    route_distinguisher="1.1.1.1:100",
                    rt_imports=["65000:100"],
                    rt_exports=["65000:100"],
                ),
            ],
        )
        out = JunosCodec().render(intent)
        assert "set routing-instances TENANT_A instance-type vrf" in out
        assert "set routing-instances TENANT_A route-distinguisher 1.1.1.1:100" in out
        assert "set routing-instances TENANT_A vrf-target target:65000:100" in out

    def test_render_vrf_interface_binding(self):
        """Interface with vrf=X renders as ``set routing-instances X
        interface <iface>.0`` (unit 0 suffix added when the canonical
        name has no dot)."""
        intent = CanonicalIntent(
            routing_instances=[CanonicalRoutingInstance(name="TENANT_A")],
            interfaces=[
                CanonicalInterface(name="ge-0/0/1", vrf="TENANT_A"),
            ],
        )
        out = JunosCodec().render(intent)
        assert (
            "set routing-instances TENANT_A interface ge-0/0/1.0" in out
        )

    def test_render_vrf_subinterface_binding(self):
        """Sub-interface name already has dot; no extra .0 suffix."""
        intent = CanonicalIntent(
            routing_instances=[CanonicalRoutingInstance(name="TENANT_A")],
            interfaces=[
                CanonicalInterface(name="ge-0/0/1.100", vrf="TENANT_A"),
            ],
        )
        out = JunosCodec().render(intent)
        assert (
            "set routing-instances TENANT_A interface ge-0/0/1.100" in out
        )

    def test_render_l3_vni(self):
        intent = CanonicalIntent(
            routing_instances=[
                CanonicalRoutingInstance(name="TENANT_A", l3_vni=50000),
            ],
        )
        out = JunosCodec().render(intent)
        assert (
            "set routing-instances TENANT_A protocols evpn "
            "ip-prefix-routes vni 50000" in out
        )

    def test_render_rt_split(self):
        intent = CanonicalIntent(
            routing_instances=[
                CanonicalRoutingInstance(
                    name="TENANT_A",
                    rt_imports=["65000:100"],
                    rt_exports=["65000:200"],
                ),
            ],
        )
        out = JunosCodec().render(intent)
        assert (
            "set routing-instances TENANT_A vrf-target "
            "import target:65000:100" in out
        )
        assert (
            "set routing-instances TENANT_A vrf-target "
            "export target:65000:200" in out
        )


class TestJunosVxlanRoundTrip:
    def test_roundtrip_full_evpn(self):
        raw = (
            "set vlans V100 vlan-id 100\n"
            "set vlans V100 vxlan vni 10100\n"
            "set vlans V200 vlan-id 200\n"
            "set vlans V200 vxlan vni 10200\n"
            "set interfaces ge-0/0/1 unit 0 family inet address 10.0.0.1/31\n"
            "set routing-instances TENANT_A instance-type vrf\n"
            "set routing-instances TENANT_A route-distinguisher 1.1.1.1:100\n"
            "set routing-instances TENANT_A vrf-target target:65000:100\n"
            "set routing-instances TENANT_A interface ge-0/0/1.0\n"
            "set routing-instances TENANT_A protocols evpn "
            "ip-prefix-routes vni 50000\n"
        )
        codec = JunosCodec()
        first = codec.parse(raw)
        rendered = codec.render(first)
        second = codec.parse(rendered)
        # VXLAN VNIs round-trip.
        assert sorted((v.vlan_id, v.vni) for v in second.vxlan_vnis) == [
            (100, 10100), (200, 10200),
        ]
        # VRF round-trips.
        ri = next(r for r in second.routing_instances if r.name == "TENANT_A")
        assert ri.route_distinguisher == "1.1.1.1:100"
        assert ri.rt_imports == ["65000:100"]
        assert ri.rt_exports == ["65000:100"]
        assert ri.l3_vni == 50000
        # Per-interface VRF membership round-trips.
        iface = next(
            i for i in second.interfaces if i.name == "ge-0/0/1"
        )
        assert iface.vrf == "TENANT_A"


# ---------------------------------------------------------------------------
# Cross-fixture regression — real EVPN captures now populate the schema
# ---------------------------------------------------------------------------


class TestRealEvpnFixtureCoverage:
    """Regression guards: the real EVPN fixtures must surface the
    expected VXLAN/VRF data now that GAP 6 wired them up."""

    def test_arista_labval_leaf2a_vxlan_and_vrfs(self):
        import pathlib
        raw = pathlib.Path(
            "tests/fixtures/real/arista_eos/"
            "batfish_labval_dc1_leaf2a_eos4230.txt"
        ).read_text(encoding="utf-8")
        intent = AristaEOSCodec().parse(raw)
        # 9 VLAN-to-VNI mappings (vlans 110-141, 160).
        assert len(intent.vxlan_vnis) == 9
        # 5 VRFs (MGMT + 4 tenants).
        vrf_names = {r.name for r in intent.routing_instances}
        assert vrf_names == {
            "MGMT",
            "Tenant_A_APP_Zone",
            "Tenant_A_DB_Zone",
            "Tenant_A_OP_Zone",
            "Tenant_A_WEB_Zone",
        }
        # Tenant VRFs have L3 VNI; MGMT doesn't.
        op = next(
            r for r in intent.routing_instances
            if r.name == "Tenant_A_OP_Zone"
        )
        assert op.l3_vni == 15001
        assert op.route_distinguisher == "192.168.255.4:15001"
        assert op.rt_imports == ["15001:15001"]

    def test_junos_evpntype5_router1_vxlan_and_vrfs(self):
        import pathlib
        raw = pathlib.Path(
            "tests/fixtures/real/junos/"
            "batfish_evpntype5_router1_junos2541.set"
        ).read_text(encoding="utf-8")
        intent = JunosCodec().parse(raw)
        # 4 VLAN-to-VNI mappings.
        assert len(intent.vxlan_vnis) == 4
        # 3 VRFs: TENANT-A, TENANT-B, mgmt_junos.
        vrf_names = {r.name for r in intent.routing_instances}
        assert "TENANT-A" in vrf_names
        assert "TENANT-B" in vrf_names
        # TENANT-A has Type-5 L3 VNI 50000.
        a = next(
            r for r in intent.routing_instances if r.name == "TENANT-A"
        )
        assert a.l3_vni == 50000
        assert a.route_distinguisher == "172.16.0.100:10000"
        assert a.rt_imports == ["65000:10000"]

    def test_junos_l3vpn_pe1_vrf(self):
        import pathlib
        raw = pathlib.Path(
            "tests/fixtures/real/junos/"
            "batfish_l3vpn_pe1_junos2541.set"
        ).read_text(encoding="utf-8")
        intent = JunosCodec().parse(raw)
        # 1 VRF: CUSTOMERS.
        vrf_names = {r.name for r in intent.routing_instances}
        assert "CUSTOMERS" in vrf_names
        ri = next(
            r for r in intent.routing_instances if r.name == "CUSTOMERS"
        )
        assert ri.route_distinguisher == "10.255.0.1:100"
        assert ri.rt_imports == ["65000:100"]
        assert ri.rt_exports == ["65000:100"]
        # L3VPN fixture doesn't use EVPN Type-5.
        assert ri.l3_vni is None
