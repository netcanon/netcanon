"""
Focused unit tests for the Aruba AOS-CX codec (``aruba_aoscx``).

The generic harnesses already cover the broad guarantees — synthetic
round-trip (``test_synthetic_kitchen_sink_round_trips.py`` auto-discovers
``tests/fixtures/synthetic/aruba_aoscx/kitchen_sink.cfg``), capability-
matrix honesty, bidirectionality invariants, and the cross-mesh smoke
matrix.  This module pins the AOS-CX-SPECIFIC behaviours that those
generic tests don't isolate:

* the ``!Version ArubaOS-CX`` probe + its non-collision with the legacy
  ``aruba_aoss`` codec and with Arista EOS,
* multi-token interface-name parsing (``interface vlan 11`` /
  ``interface 1/1/1`` / the ``interface vxlan`` interception),
* the type-aware default admin-state (loopbacks up, everything else
  down),
* the ``vrf <name>`` declaration + ``vrf attach`` interface bind,
* (Phase 2) the L2 switchport surface (``no routing`` + ``vlan access`` /
  ``vlan trunk``), LAGs (``interface lag N`` + ``lag N`` + ``lacp mode``),
  and local users (``user … group … password ciphertext``),
* the port-name bridge round-trip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.aruba_aoscx import port_names
from netcanon.migration.codecs.aruba_aoscx.codec import ArubaAOSCXCodec
from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit

_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "synthetic" / "aruba_aoscx" / "kitchen_sink.cfg"
)

_SAMPLE = """\
!
!Version ArubaOS-CX FL.10.13.1000
!export-password: default
hostname Leaf1
user admin group administrators password ciphertext FAKECIPHERTEXTBLOBADMIN
user netops group operators password ciphertext FAKECIPHERTEXTBLOBNETOPS
snmp-server community FAKECOMMUNITY
snmp-server system-location Data Center 1
snmp-server system-contact noc@example.net
snmpv3 user monitor auth sha auth-pass ciphertext FAKEAUTHBLOB priv aes priv-pass ciphertext FAKEPRIVBLOB
!
vrf RED
vlan 1
vlan 10
    name USERS
    description User access VLAN
vlan 20
    name VOICE
interface 1/1/1
    no shutdown
    mtu 9198
    ip address 198.51.100.1/31
interface 1/1/2
    no shutdown
    no routing
    vlan access 10
interface 1/1/3
    no shutdown
    no routing
    vlan trunk native 1
    vlan trunk allowed 10,20
interface 1/1/4
    no shutdown
    lag 1
interface 1/1/5
    no shutdown
    lag 1
interface lag 1 multi-chassis
    no shutdown
    description Server-LAG
    no routing
    vlan trunk native 1
    vlan trunk allowed all
    lacp mode active
interface lag 2
    no shutdown
    no routing
    vlan access 20
interface vlan 10
    no shutdown
    vrf attach RED
    ip address 10.10.10.1/24
    active-gateway ip mac 02:00:0a:0a:0a:01
    active-gateway ip 10.10.10.254
interface loopback 0
    ip address 10.255.0.1/32
ip route 0.0.0.0/0 198.51.100.2
"""

# A legacy AOS-S config + an Arista config — used to prove the AOS-CX
# probe does NOT steal captures that belong to sibling codecs.
_AOSS_SAMPLE = """\
; J9850A Configuration Editor; Created on release #WC.16.11
hostname "sw-edge-01"
vlan 10
   name "USERS"
   untagged 1-24
   exit
interface 1
   name "Desk 1"
   exit
"""

_ARISTA_SAMPLE = """\
! device: spine1 (DCS-7050, EOS-4.28.0F)
!
hostname spine1
!
interface Ethernet1
   no switchport
   ip address 10.0.0.1/31
!
"""


@pytest.fixture()
def codec() -> ArubaAOSCXCodec:
    return ArubaAOSCXCodec()


# ---------------------------------------------------------------------------
# Registration + metadata
# ---------------------------------------------------------------------------

def test_registered() -> None:
    c = get_codec("aruba_aoscx")
    assert isinstance(c, ArubaAOSCXCodec)
    assert c.input_format == "cli-aoscx"
    assert c.direction == "bidirectional"
    assert c.certainty == "certified"


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------

def test_probe_detects_version_banner() -> None:
    result = ArubaAOSCXCodec.probe(_SAMPLE)
    assert result is not None
    score, _reason = result
    assert score >= 95


def test_probe_structural_fallback_without_banner() -> None:
    no_banner = "\n".join(
        line for line in _SAMPLE.splitlines()
        if "ArubaOS-CX" not in line
    )
    result = ArubaAOSCXCodec.probe(no_banner)
    assert result is not None
    score, _reason = result
    assert score >= 90


def test_probe_does_not_steal_aoss() -> None:
    """The AOS-CX probe must reject a legacy AOS-S config (`;` banner +
    bare-numeric `interface N` + `untagged`)."""
    assert ArubaAOSCXCodec.probe(_AOSS_SAMPLE) is None


def test_probe_does_not_steal_arista() -> None:
    """The AOS-CX probe must reject an Arista EOS config."""
    assert ArubaAOSCXCodec.probe(_ARISTA_SAMPLE) is None


# ---------------------------------------------------------------------------
# Parse — core surfaces
# ---------------------------------------------------------------------------

def test_parse_hostname_and_vrf(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    assert intent.hostname == "Leaf1"
    assert intent.source_version == "FL.10.13.1000"
    assert [ri.name for ri in intent.routing_instances] == ["RED"]


def test_parse_vlans_with_name_and_description(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    by_id = {v.id: v for v in intent.vlans}
    assert set(by_id) >= {1, 10, 20}
    assert by_id[10].name == "USERS"
    assert by_id[10].description == "User access VLAN"


def test_parse_static_route(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    assert len(intent.static_routes) == 1
    route = intent.static_routes[0]
    assert route.destination == "0.0.0.0/0"
    assert route.gateway == "198.51.100.2"


def test_ipv6_static_route_render_and_round_trip(codec: ArubaAOSCXCodec) -> None:
    # AOS-CX keys the AF off the keyword: an IPv6 destination must render
    # ``ipv6 route`` (``ip route <v6>`` is invalid CLI) and round-trip.
    from netcanon.migration.canonical.intent import (
        CanonicalIntent,
        CanonicalStaticRoute,
    )
    intent = CanonicalIntent(hostname="r1", static_routes=[
        CanonicalStaticRoute(destination="10.0.0.0/8", gateway="192.0.2.1"),
        CanonicalStaticRoute(destination="2001:db8:1::/48", gateway="2001:db8::1"),
    ])
    out = codec.render(intent)
    assert "ip route 10.0.0.0/8 192.0.2.1" in out
    assert "ipv6 route 2001:db8:1::/48 2001:db8::1" in out
    assert "ip route 2001" not in out  # v6 never on the bare ``ip route``
    reparsed = codec.parse(out)
    assert any(
        r.destination == "2001:db8:1::/48" and r.gateway == "2001:db8::1"
        for r in reparsed.static_routes
    )


# ---------------------------------------------------------------------------
# Multi-token interface names + stanza interception
# ---------------------------------------------------------------------------

def test_multitoken_interface_names(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    names = {i.name for i in intent.interfaces}
    assert "1/1/1" in names
    assert "vlan 10" in names
    assert "loopback 0" in names


def test_interface_lag_materialized_modifier_stripped(
    codec: ArubaAOSCXCodec,
) -> None:
    """Phase 2: `interface lag N [multi-chassis]` IS materialised as a
    kind-lag interface, and the `multi-chassis` modifier never leaks into
    the name."""
    intent = codec.parse(_SAMPLE)
    names = {i.name for i in intent.interfaces}
    assert "lag 1" in names
    assert "lag 1 multi-chassis" not in names
    assert port_names.classify_port_name("lag 1").kind == "lag"


def test_interface_vxlan_not_materialised_as_interface(
    codec: ArubaAOSCXCodec,
) -> None:
    """`interface vxlan N` is the VTEP — a VXLAN config container, never a
    real interface; its sub-commands populate ``vxlan_vnis`` instead.  A
    ``vni`` with no nested ``vlan`` child (the L3VNI shape) yields no L2
    record (symmetric-IRB L3VNI is deferred)."""
    raw = (
        "!Version ArubaOS-CX FL.10.13.1000\n"
        "hostname x\n"
        "interface vxlan 1\n"
        "    source ip 1.1.1.1\n"
        "    vni 10\n"
    )
    intent = codec.parse(raw)
    assert not any(
        i.name.lower().startswith("vxlan") for i in intent.interfaces
    )
    assert intent.vxlan_vnis == []  # vni with no `vlan` child → no record


def test_parse_vxlan_l2vni_binding(codec: ArubaAOSCXCodec) -> None:
    """`interface vxlan / vni N / vlan M` populates a CanonicalVxlan with
    the VLAN↔VNI binding; the `source ip` lands in source_interface
    (verbatim — AOS-CX states the VTEP source as an address)."""
    raw = (
        "!Version ArubaOS-CX FL.10.13.1000\n"
        "hostname leaf\n"
        "interface vxlan 1\n"
        "    source ip 10.0.0.1\n"
        "    no shutdown\n"
        "    vni 10020\n"
        "        vlan 20\n"
        "    vni 10010\n"
        "        vlan 10\n"
    )
    intent = codec.parse(raw)
    # Records are returned sorted by vlan_id regardless of file order.
    assert [
        (v.vlan_id, v.vni, v.source_interface) for v in intent.vxlan_vnis
    ] == [(10, 10010, "10.0.0.1"), (20, 10020, "10.0.0.1")]


def test_render_vxlan_grammar(codec: ArubaAOSCXCodec) -> None:
    """Render emits the AOS-CX VTEP stanza (interface vxlan 1 / source ip
    / vni / nested vlan), sorted by vlan_id."""
    raw = (
        "!Version ArubaOS-CX FL.10.13.1000\n"
        "hostname leaf\n"
        "vlan 10\n"
        "vlan 20\n"
        "interface vxlan 1\n"
        "    source ip 10.0.0.1\n"
        "    vni 10010\n"
        "        vlan 10\n"
        "    vni 10020\n"
        "        vlan 20\n"
    )
    out = codec.render(codec.parse(raw))
    assert "interface vxlan 1" in out
    assert "    source ip 10.0.0.1" in out
    assert "    vni 10010" in out
    assert "        vlan 10" in out
    assert out.index("vni 10010") < out.index("vni 10020")


def test_render_vxlan_omits_non_ip_source(codec: ArubaAOSCXCodec) -> None:
    """A cross-vendor source whose source_interface is an interface NAME
    (not an IP) renders the VNI bindings but omits the malformed
    `source ip` line."""
    from netcanon.migration.canonical.intent import (
        CanonicalIntent,
        CanonicalVxlan,
    )
    intent = CanonicalIntent(
        hostname="leaf",
        vxlan_vnis=[
            CanonicalVxlan(vlan_id=10, vni=10010, source_interface="loopback0"),
        ],
    )
    out = codec.render(intent)
    assert "interface vxlan 1" in out
    assert "    vni 10010" in out
    assert "source ip" not in out


def test_interface_l3_addressing(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    by_name = {i.name: i for i in intent.interfaces}
    eth = by_name["1/1/1"]
    assert eth.mtu == 9198
    assert eth.ipv4_addresses[0].ip == "198.51.100.1"
    assert eth.ipv4_addresses[0].prefix_length == 31


def test_vrf_attach_binds_interface(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    svi = next(i for i in intent.interfaces if i.name == "vlan 10")
    assert svi.vrf == "RED"


# ---------------------------------------------------------------------------
# Phase 2 — L2 switchport
# ---------------------------------------------------------------------------

def test_switchport_access(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    port = next(i for i in intent.interfaces if i.name == "1/1/2")
    assert port.switchport_mode == "access"
    assert port.access_vlan == 10


def test_switchport_trunk(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    port = next(i for i in intent.interfaces if i.name == "1/1/3")
    assert port.switchport_mode == "trunk"
    assert port.trunk_native_vlan == 1
    assert sorted(port.trunk_allowed_vlans) == [10, 20]


def test_trunk_allowed_all_is_empty_list(codec: ArubaAOSCXCodec) -> None:
    """`vlan trunk allowed all` maps to an empty allowed-list (which the
    render re-emits as `all`)."""
    intent = codec.parse(_SAMPLE)
    lag = next(i for i in intent.interfaces if i.name == "lag 1")
    assert lag.switchport_mode == "trunk"
    assert lag.trunk_allowed_vlans == []


# ---------------------------------------------------------------------------
# Phase 2 — LAGs
# ---------------------------------------------------------------------------

def test_lag_members_and_mode(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    by_name = {lag.name: lag for lag in intent.lags}
    assert set(by_name) == {"lag 1", "lag 2"}
    assert sorted(by_name["lag 1"].members) == ["1/1/4", "1/1/5"]
    assert by_name["lag 1"].mode == "active"
    # No `lacp mode` line on lag 2 -> static aggregation.
    assert by_name["lag 2"].members == []
    assert by_name["lag 2"].mode == "static"


def test_lag_member_back_reference(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    member = next(i for i in intent.interfaces if i.name == "1/1/4")
    assert member.lag_member_of == "lag 1"


# ---------------------------------------------------------------------------
# Phase 2 — local users
# ---------------------------------------------------------------------------

def test_local_users(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    by_name = {u.name: u for u in intent.local_users}
    assert set(by_name) == {"admin", "netops"}
    assert by_name["admin"].role == "administrators"
    assert by_name["admin"].privilege_level == 15
    assert by_name["admin"].hashed_password == "FAKECIPHERTEXTBLOBADMIN"
    # Non-admin group -> privilege 1 (lossy numeric mapping).
    assert by_name["netops"].role == "operators"
    assert by_name["netops"].privilege_level == 1


# ---------------------------------------------------------------------------
# Phase 2b — SNMP
# ---------------------------------------------------------------------------

def test_parse_snmp(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    assert intent.snmp is not None
    assert intent.snmp.community == "FAKECOMMUNITY"
    # `system-location` value carries spaces — captured to end of line.
    assert intent.snmp.location == "Data Center 1"
    assert intent.snmp.contact == "noc@example.net"
    users = {u.name: u for u in intent.snmp.v3_users}
    assert "monitor" in users
    assert users["monitor"].auth_protocol == "sha"
    assert users["monitor"].auth_passphrase == "FAKEAUTHBLOB"
    assert users["monitor"].priv_protocol == "aes"
    assert users["monitor"].priv_passphrase == "FAKEPRIVBLOB"


def test_render_snmp_grammar(codec: ArubaAOSCXCodec) -> None:
    out = codec.render(codec.parse(_SAMPLE))
    assert "snmp-server community FAKECOMMUNITY" in out
    assert "snmp-server system-location Data Center 1" in out
    assert "snmp-server system-contact noc@example.net" in out
    assert "snmpv3 user monitor auth sha auth-pass ciphertext" in out
    assert "priv aes priv-pass ciphertext" in out


# ---------------------------------------------------------------------------
# Phase 3 — active-gateway anycast
# ---------------------------------------------------------------------------

def test_parse_active_gateway(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    svi = next(i for i in intent.interfaces if i.name == "vlan 10")
    # The `active-gateway ip <vip>` attaches to the SVI's primary address
    # (distinct from the SVI's own ip — Arista-VARP style).
    assert svi.ipv4_addresses[0].ip == "10.10.10.1"
    assert svi.ipv4_addresses[0].virtual_gateway_address == "10.10.10.254"
    # The MAC is the chassis-wide anycast gateway MAC (colon-hex).
    assert intent.anycast_gateway_mac == "02:00:0a:0a:0a:01"


def test_render_active_gateway(codec: ArubaAOSCXCodec) -> None:
    out = codec.render(codec.parse(_SAMPLE))
    assert "active-gateway ip mac 02:00:0a:0a:0a:01" in out
    assert "active-gateway ip 10.10.10.254" in out


# ---------------------------------------------------------------------------
# Type-aware default admin-state
# ---------------------------------------------------------------------------

def test_default_admin_state_type_aware(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    by_name = {i.name: i for i in intent.interfaces}
    assert by_name["loopback 0"].enabled is True
    assert by_name["1/1/1"].enabled is True


def test_bare_physical_defaults_down(codec: ArubaAOSCXCodec) -> None:
    raw = (
        "!Version ArubaOS-CX FL.10.13.1000\n"
        "hostname x\n"
        "interface 1/1/9\n"
        "    description bare\n"
    )
    intent = codec.parse(raw)
    iface = next(i for i in intent.interfaces if i.name == "1/1/9")
    assert iface.enabled is False


# ---------------------------------------------------------------------------
# Round-trip (sorted compare, mirroring the harness normalisation)
# ---------------------------------------------------------------------------

def _normalise(intent):
    """Return comparable views of the canonical lists the codec populates,
    sorted so render-order vs file-order doesn't register as drift."""
    return {
        "hostname": intent.hostname,
        "anycast_mac": intent.anycast_gateway_mac,
        "vrfs": [ri.name for ri in intent.routing_instances],
        "vlans": sorted(
            (
                v.id, v.name, v.description,
                tuple(sorted(v.tagged_ports)),
                tuple(sorted(v.untagged_ports)),
            )
            for v in intent.vlans
        ),
        "interfaces": sorted(
            (
                i.name,
                i.enabled,
                i.mtu,
                i.vrf,
                i.switchport_mode,
                i.access_vlan,
                tuple(sorted(i.trunk_allowed_vlans)),
                i.trunk_native_vlan,
                i.lag_member_of,
                tuple(
                    (a.ip, a.prefix_length, a.virtual_gateway_address)
                    for a in i.ipv4_addresses
                ),
                tuple((a.ip, a.prefix_length) for a in i.ipv6_addresses),
            )
            for i in intent.interfaces
        ),
        "lags": sorted(
            (lag.name, tuple(sorted(lag.members)), lag.mode)
            for lag in intent.lags
        ),
        "users": sorted(
            (u.name, u.role, u.privilege_level, u.hashed_password)
            for u in intent.local_users
        ),
        "routes": sorted(
            (r.destination, r.gateway, r.interface, r.metric)
            for r in intent.static_routes
        ),
        "vxlan": sorted(
            (x.vlan_id, x.vni, x.source_interface)
            for x in intent.vxlan_vnis
        ),
        "snmp": (
            None if intent.snmp is None else (
                intent.snmp.community,
                intent.snmp.location,
                intent.snmp.contact,
                tuple(
                    (u.name, u.auth_protocol, u.auth_passphrase,
                     u.priv_protocol, u.priv_passphrase)
                    for u in intent.snmp.v3_users
                ),
            )
        ),
    }


def test_round_trip_sample(codec: ArubaAOSCXCodec) -> None:
    once = codec.parse(_SAMPLE)
    twice = codec.parse(codec.render(once))
    assert _normalise(twice) == _normalise(once)


def test_round_trip_kitchen_sink(codec: ArubaAOSCXCodec) -> None:
    raw = _FIXTURE.read_text(encoding="utf-8")
    once = codec.parse(raw)
    twice = codec.parse(codec.render(once))
    assert _normalise(twice) == _normalise(once)


def test_render_emits_version_banner(codec: ArubaAOSCXCodec) -> None:
    out = codec.render(codec.parse(_SAMPLE))
    assert "!Version ArubaOS-CX" in out
    assert ArubaAOSCXCodec.probe(out) is not None


def test_render_l2_and_lag_grammar(codec: ArubaAOSCXCodec) -> None:
    """Render emits the AOS-CX L2 + LAG grammar (no routing / vlan access
    / vlan trunk allowed all / lacp mode / lag membership)."""
    out = codec.render(codec.parse(_SAMPLE))
    assert "no routing" in out
    assert "vlan access 10" in out
    assert "vlan trunk allowed all" in out
    assert "lacp mode active" in out
    assert "    lag 1" in out
    assert "user admin group administrators password ciphertext" in out


# ---------------------------------------------------------------------------
# Capability matrix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/system/hostname",
    "/interfaces/interface/ipv4/address/ip",
    "/vlans/vlan/name",
    "/routing/static-route",
    "/routing-instances/instance/name",
    "/interfaces/interface/switchport-mode",
    "/interfaces/interface/lag-member-of",
    "/vlans/vlan/untagged-ports",
    "/lags/lag/name",
    "/local-users/user/name",
    "/local-users/user/role",
    "/snmp/community",
    "/snmp/location",
    "/snmp/contact",
    "/snmp/v3-user",
    "/interfaces/interface/ipv4/address/virtual-gateway-address",
    "/anycast-gateway-mac",
    "/vxlan-vnis/vni",
])
def test_matrix_supported(codec: ArubaAOSCXCodec, path: str) -> None:
    assert codec.capabilities.classify(path) == "supported"


@pytest.mark.parametrize("path", [
    "/interfaces/interface/config/type",
    # audit bb47f21 T0-1: AOS-CX renders the LAG `lacp mode` but a `passive`
    # bundle re-parses as `static`, so the mode is lossy (was wrongly listed
    # supported — the value-corruption the LAG-mode fidelity guard now pins).
    "/lags/lag/mode",
    "/local-users/user/privilege-level",
    "/snmp/v3-user/auth-passphrase",
    # PR-2a (audit e5b77d7): the SNMPv3 sub-field leaves are now WALKED, so
    # AOS-CX's auth/priv downgrade + key re-key + dropped VACM group are
    # declared lossy (were silent KNOWN_GAP before).
    "/snmp/v3-user/auth-protocol",
    "/snmp/v3-user/priv-protocol",
    "/snmp/v3-user/priv-passphrase",
    "/snmp/v3-user/group",
    "/vxlan-vnis/source-interface",
])
def test_matrix_lossy(codec: ArubaAOSCXCodec, path: str) -> None:
    assert codec.capabilities.classify(path) == "lossy"


def test_snmpv3_crypto_downgrade_reasons_name_the_downgrade(
    codec: ArubaAOSCXCodec,
) -> None:
    # Audit 81d9740 T0-3 (interim) + e5b77d7 PR-2a: AOS-CX collapses SNMPv3
    # auth -> SHA-1 and priv -> AES-128. Now that the auth-protocol /
    # priv-protocol leaves are WALKED (PR-2a), the operator-facing lossy reason
    # on each must NAME the cryptographic downgrade, not merely a re-key, so a
    # security downgrade is never mislabelled as routine.
    reasons = {lp.path: lp.reason.lower() for lp in codec.capabilities.lossy}
    auth = reasons["/snmp/v3-user/auth-protocol"]
    assert "downgrad" in auth and "sha-1" in auth
    priv = reasons["/snmp/v3-user/priv-protocol"]
    assert "downgrad" in priv and "aes-128" in priv
    # The walked auth-passphrase reason (the original 81d9740 interim) still
    # names the downgrade too — kept for continuity.
    assert "downgrad" in reasons["/snmp/v3-user/auth-passphrase"]


@pytest.mark.parametrize("path", [
    "/snmp/trap-host",
    "/vxlan-vnis/l2vni-route-target",
    "/routing-instances/instance/l3-vni",
    "/routing-protocols/bgp",
    "/interfaces/interface/ipv6/address/virtual-gateway-address",
    "/routing-instances/instance/route-distinguisher",
])
def test_matrix_unsupported(codec: ArubaAOSCXCodec, path: str) -> None:
    assert codec.capabilities.classify(path) == "unsupported"


# ---------------------------------------------------------------------------
# Port-name bridge
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,kind", [
    ("1/1/1", "physical"),
    ("vlan 10", "svi"),
    ("lag 1", "lag"),
    ("loopback 0", "loopback"),
    ("vxlan 1", "vtep"),
    ("mgmt", "mgmt"),
])
def test_port_name_classify(name: str, kind: str) -> None:
    assert port_names.classify_port_name(name).kind == kind


@pytest.mark.parametrize("name", [
    "1/1/1", "vlan 10", "lag 1", "loopback 0", "vxlan 1", "mgmt",
])
def test_port_name_round_trip(name: str) -> None:
    ident = port_names.classify_port_name(name)
    assert port_names.format_port_identity(ident) == name
