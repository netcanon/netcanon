"""Silent-loss guard for list sub-detail VALUE fields (Bucket-C).

``CapabilityMatrix.classify`` defaults any walker-yielded xpath not
explicitly declared lossy/unsupported to ``"supported"`` (see
``netcanon/models/migration.py``).  For a list's identity leaf that is
fine — the registry honesty guards in
``test_registry_capability_honesty`` already cover whole-field +
naming-independent drops.  The residual silent-loss gap this guard
closes is a VALUE *sub-detail* of a list entry that a codec drops on
render while still rendering — and declaring ``supported`` — the list's
*identity* leaf.

Concrete case verified live (cisco_nxos → arista_eos): a VXLAN VNI's
BUM-replication multicast-group + ingress-replication flood-list drop on
render, but the VLAN↔VNI binding (``/vxlan-vnis/vni``) survives and is
declared supported.  Because ``classify`` is exact-string match, the
dropped sub-details default to ``supported`` → ``validate_against``
reports ``severity: ok`` and the migrate banner is green while the
overlay reachability config silently vanishes.

**Base-identity-coverage rule.**  A codec must declare a sub-detail leaf
lossy/unsupported only when it KEEPS (renders, and does not loss-declare)
the list's identity leaf yet DROPS the sub-detail.  A codec that already
loss-declares the identity leaf surfaces the whole-surface loss there, so
the sub-detail defaulting to ``supported`` is harmless noise — exempt.
Likewise, a codec whose render does not keep the identity leaf at all has
a *whole-surface* drop (a different guard's concern), not a sub-detail
silent loss.

**Why targeted intents.**  The universal kitchen-sink in
``test_registry_capability_honesty`` deliberately sets mutually-exclusive
fields together (trunk + access VLAN, dhcp-client + static IP,
multicast-group + flood-list) to maximise walker coverage — which
manufactures *false* sub-detail drops (whichever mode the codec doesn't
pick "drops").  Each case here uses a single-mode, non-contradictory
intent so a drop is unambiguous.

Stage 2+ extends ``_CASES`` with more clean naming-independent value
sub-details (e.g. ``/snmp/v3-user/engine-id``, anycast
``virtual-gateway-mac``) — each with its own targeted intent.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalSNMP,
    CanonicalSNMPv3User,
    CanonicalVlan,
    CanonicalVxlan,
)

# Explicit imports so every codec is registered when this module runs
# standalone (mirrors run_full_mesh.py / test_registry_capability_honesty).
from netcanon.migration.codecs import (  # noqa: F401
    arista_eos,
    aruba_aoscx,
    aruba_aoss,
    cisco_iosxe,
    cisco_iosxe_cli,
    cisco_iosxr,
    cisco_nxos,
    fortigate_cli,
    juniper_junos,
    mikrotik_routeros,
    opnsense,
    vyos,
)
from netcanon.migration.codecs.registry import get_codec, list_codecs

pytestmark = pytest.mark.unit


def _bidirectional_codec_names() -> list[str]:
    names = []
    for name in sorted(list_codecs()):
        if name == "mock":
            continue
        codec = get_codec(name)
        if getattr(codec, "direction", "bidirectional") == "bidirectional":
            names.append(name)
    return names


_CODEC_NAMES = _bidirectional_codec_names()


# ---------------------------------------------------------------------------
# Targeted single-mode intents — one BUM-replication mode each so a drop is
# unambiguous (a VNI uses multicast OR ingress-replication, never both).
# ---------------------------------------------------------------------------


def _vxlan_intent(vx: CanonicalVxlan) -> CanonicalIntent:
    return CanonicalIntent(
        hostname="leaf1",
        interfaces=[
            CanonicalInterface(
                name="Ethernet1",
                default_name="Ethernet1",
                ipv4_addresses=[CanonicalIPv4Address(ip="10.0.0.1", prefix_length=24)],
            )
        ],
        vlans=[CanonicalVlan(id=10, name="V10")],
        vxlan_vnis=[vx],
    )


def _mcast_intent() -> CanonicalIntent:
    return _vxlan_intent(
        CanonicalVxlan(
            vlan_id=10, vni=10010, mcast_group="239.1.1.1",
            source_interface="Loopback0", udp_port=4789,
        )
    )


def _flood_intent() -> CanonicalIntent:
    return _vxlan_intent(
        CanonicalVxlan(
            vlan_id=10, vni=10010, flood_list=["10.0.0.5", "10.0.0.6"],
            source_interface="Loopback0", udp_port=4789,
        )
    )


def _vni_kept(reparsed: CanonicalIntent) -> bool:
    return bool(reparsed.vxlan_vnis)


def _mcast_survived(reparsed: CanonicalIntent) -> bool:
    return any(v.mcast_group == "239.1.1.1" for v in reparsed.vxlan_vnis)


def _flood_survived(reparsed: CanonicalIntent) -> bool:
    return any(
        sorted(v.flood_list) == ["10.0.0.5", "10.0.0.6"]
        for v in reparsed.vxlan_vnis
    )


def _vlan_desc_intent() -> CanonicalIntent:
    """A VLAN carrying a description distinct from its name, plus an access
    port so codecs that only render referenced VLANs still emit it."""
    return CanonicalIntent(
        hostname="sw",
        interfaces=[
            CanonicalInterface(
                name="Ethernet1", default_name="Ethernet1",
                switchport_mode="access", access_vlan=10,
            )
        ],
        vlans=[CanonicalVlan(id=10, name="ENG", description="Engineering-VLAN")],
    )


def _vlan_kept(reparsed: CanonicalIntent) -> bool:
    return any(v.id == 10 for v in reparsed.vlans)


def _vlan_desc_survived(reparsed: CanonicalIntent) -> bool:
    return any(v.description == "Engineering-VLAN" for v in reparsed.vlans)


def _v3_engineid_intent() -> CanonicalIntent:
    """A single SNMPv3 USM user carrying an explicit engineID."""
    return CanonicalIntent(
        hostname="r",
        interfaces=[CanonicalInterface(name="Ethernet1", default_name="Ethernet1")],
        snmp=CanonicalSNMP(
            v3_users=[
                CanonicalSNMPv3User(
                    name="u1", group="g1",
                    auth_protocol="sha", auth_passphrase="authpass12345",
                    priv_protocol="aes", priv_passphrase="privpass12345",
                    engine_id="80000009ff",
                )
            ]
        ),
    )


def _v3_user_kept(reparsed: CanonicalIntent) -> bool:
    return bool(reparsed.snmp and reparsed.snmp.v3_users)


def _v3_engineid_survived(reparsed: CanonicalIntent) -> bool:
    users = reparsed.snmp.v3_users if reparsed.snmp else []
    return any(u.engine_id == "80000009ff" for u in users)


def _varp_intent() -> CanonicalIntent:
    """An SVI carrying a SEPARATE anycast/VARP virtual IP + MAC (the
    Arista/Junos shape where the virtual gateway address differs from the
    interface's own address), on both IPv4 and IPv6."""
    return CanonicalIntent(
        hostname="sw",
        vlans=[CanonicalVlan(id=10, name="V10")],
        interfaces=[
            CanonicalInterface(
                name="Vlan10", default_name="Vlan10",
                interface_type="ianaift:l3ipvlan",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="10.0.0.2", prefix_length=24,
                    virtual_gateway_address="10.0.0.1",
                    virtual_gateway_mac="00:00:5e:00:01:01")],
                ipv6_addresses=[CanonicalIPv6Address(
                    ip="2001:db8::2", prefix_length=64,
                    virtual_gateway_address="2001:db8::1",
                    virtual_gateway_mac="00:00:5e:00:02:01")],
            )
        ],
    )


def _v4_addrs(reparsed: CanonicalIntent):
    return [a for i in reparsed.interfaces for a in i.ipv4_addresses]


def _v6_addrs(reparsed: CanonicalIntent):
    return [a for i in reparsed.interfaces for a in i.ipv6_addresses]


def _v4_ip_kept(reparsed: CanonicalIntent) -> bool:
    return any(a.ip == "10.0.0.2" for a in _v4_addrs(reparsed))


def _v6_ip_kept(reparsed: CanonicalIntent) -> bool:
    return any(a.ip == "2001:db8::2" for a in _v6_addrs(reparsed))


def _v4_vga_survived(reparsed: CanonicalIntent) -> bool:
    return any(a.virtual_gateway_address for a in _v4_addrs(reparsed))


def _v6_vga_survived(reparsed: CanonicalIntent) -> bool:
    return any(a.virtual_gateway_address for a in _v6_addrs(reparsed))


def _v4_vgm_survived(reparsed: CanonicalIntent) -> bool:
    return any(a.virtual_gateway_mac for a in _v4_addrs(reparsed))


def _v6_vgm_survived(reparsed: CanonicalIntent) -> bool:
    return any(a.virtual_gateway_mac for a in _v6_addrs(reparsed))


def _tunnel_intent() -> CanonicalIntent:
    """A GRE tunnel interface carrying a tunnel_type discriminator."""
    return CanonicalIntent(
        hostname="r",
        interfaces=[CanonicalInterface(
            name="Tunnel0", default_name="Tunnel0",
            interface_type="ianaift:tunnel", tunnel_type="gre")],
    )


def _tunnel_iface_kept(reparsed: CanonicalIntent) -> bool:
    return any(i.name == "Tunnel0" for i in reparsed.interfaces)


def _tunnel_type_survived(reparsed: CanonicalIntent) -> bool:
    return any(i.tunnel_type == "gre" for i in reparsed.interfaces)


def _svi_intent() -> CanonicalIntent:
    """A VLAN carrying its SVI / management L3 on the VLAN record itself (the
    Junos ``irb`` / Aruba SVI-on-VLAN shape, with NO sibling Vlan<N> interface)
    — folded onto ``CanonicalVlan.ipv4_addresses`` by project_svi_to_vlan."""
    return CanonicalIntent(
        hostname="r",
        vlans=[CanonicalVlan(
            id=11, name="BLUE",
            ipv4_addresses=[CanonicalIPv4Address(ip="10.11.0.1", prefix_length=24)])],
    )


def _svi_vlan_kept(reparsed: CanonicalIntent) -> bool:
    return any(v.id == 11 for v in reparsed.vlans)


def _svi_ip_survived(reparsed: CanonicalIntent) -> bool:
    # The SVI address may round-trip on EITHER canonical representation: the
    # VLAN record (SVI-model targets re-fold via project_svi_to_vlan) OR an
    # interface (FortiGate renders it on a routed VLAN sub-interface).  Either
    # means the L3 reached the target — no reachability loss.  A genuine
    # dropper (nxos/iosxr/aoscx/opnsense/mikrotik) leaves it on neither.
    on_vlan = any(a.ip == "10.11.0.1" for v in reparsed.vlans for a in v.ipv4_addresses)
    on_iface = any(
        a.ip == "10.11.0.1" for i in reparsed.interfaces for a in i.ipv4_addresses
    )
    return on_vlan or on_iface


class _Case:
    """One (leaf, identity, targeted-intent) silent-loss probe."""

    def __init__(
        self,
        *,
        case_id: str,
        leaf: str,
        identity: str,
        intent: Callable[[], CanonicalIntent],
        identity_kept: Callable[[CanonicalIntent], bool],
        subdetail_survived: Callable[[CanonicalIntent], bool],
    ) -> None:
        self.id = case_id
        self.leaf = leaf
        self.identity = identity
        self.intent = intent
        self.identity_kept = identity_kept
        self.subdetail_survived = subdetail_survived


_CASES = [
    _Case(
        case_id="vxlan-mcast-group",
        leaf="/vxlan-vnis/mcast-group",
        identity="/vxlan-vnis/vni",
        intent=_mcast_intent,
        identity_kept=_vni_kept,
        subdetail_survived=_mcast_survived,
    ),
    _Case(
        case_id="vxlan-flood-list",
        leaf="/vxlan-vnis/flood-list",
        identity="/vxlan-vnis/vni",
        intent=_flood_intent,
        identity_kept=_vni_kept,
        subdetail_survived=_flood_survived,
    ),
    # -- Stage 2: clean naming-independent value sub-details --
    _Case(
        case_id="vlan-description",
        leaf="/vlans/vlan/description",
        identity="/vlans/vlan/id",
        intent=_vlan_desc_intent,
        identity_kept=_vlan_kept,
        subdetail_survived=_vlan_desc_survived,
    ),
    _Case(
        case_id="snmp-v3-engine-id",
        leaf="/snmp/v3-user/engine-id",
        identity="/snmp/v3-user",
        intent=_v3_engineid_intent,
        identity_kept=_v3_user_kept,
        subdetail_survived=_v3_engineid_survived,
    ),
    # -- Stage 3: anycast/VARP + tunnel value sub-details (per-codec
    # representation nuance verified by an adversarial workflow) --
    _Case(
        case_id="varp-vga-v4",
        leaf="/interfaces/interface/ipv4/address/virtual-gateway-address",
        identity="/interfaces/interface/ipv4/address/ip",
        intent=_varp_intent,
        identity_kept=_v4_ip_kept,
        subdetail_survived=_v4_vga_survived,
    ),
    _Case(
        case_id="varp-vga-v6",
        leaf="/interfaces/interface/ipv6/address/virtual-gateway-address",
        identity="/interfaces/interface/ipv6/address/ip",
        intent=_varp_intent,
        identity_kept=_v6_ip_kept,
        subdetail_survived=_v6_vga_survived,
    ),
    _Case(
        case_id="varp-vgm-v4",
        leaf="/interfaces/interface/ipv4/address/virtual-gateway-mac",
        identity="/interfaces/interface/ipv4/address/virtual-gateway-address",
        intent=_varp_intent,
        identity_kept=_v4_vga_survived,
        subdetail_survived=_v4_vgm_survived,
    ),
    _Case(
        case_id="varp-vgm-v6",
        leaf="/interfaces/interface/ipv6/address/virtual-gateway-mac",
        identity="/interfaces/interface/ipv6/address/virtual-gateway-address",
        intent=_varp_intent,
        identity_kept=_v6_vga_survived,
        subdetail_survived=_v6_vgm_survived,
    ),
    _Case(
        case_id="tunnel-type",
        leaf="/interfaces/interface/tunnel-type",
        identity="/interfaces/interface/name",
        intent=_tunnel_intent,
        identity_kept=_tunnel_iface_kept,
        subdetail_survived=_tunnel_type_survived,
    ),
    # -- VLAN SVI / management L3 (blind-audit 3ec11f3 T0-2): the VLAN-record
    # IP was unwalked, so a codec that drops it on render reported severity:ok.
    # Now walked (/vlans/vlan/ipv4/address/ip) + declared lossy on the droppers
    # (nxos/iosxr/aoscx/opnsense/mikrotik); SVI-model targets preserve it. --
    _Case(
        case_id="vlan-svi-ipv4",
        leaf="/vlans/vlan/ipv4/address/ip",
        identity="/vlans/vlan/id",
        intent=_svi_intent,
        identity_kept=_svi_vlan_kept,
        subdetail_survived=_svi_ip_survived,
    ),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_registry_is_non_empty():
    """Sanity: the bidirectional registry resolved to the expected fleet."""
    assert len(_CODEC_NAMES) >= 11, _CODEC_NAMES


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c.id)
@pytest.mark.parametrize("name", _CODEC_NAMES)
def test_dropped_list_subdetail_is_declared(name: str, case: _Case):
    """A list sub-detail VALUE the codec drops on render — while keeping the
    list's identity leaf supported — must be declared lossy/unsupported,
    else live validation reports ``severity: ok`` while the data is
    discarded (silent-loss class; base-identity-coverage rule)."""
    codec = get_codec(name)
    caps = codec.capabilities
    loss_declared = (
        {lp.path for lp in caps.lossy} | {u.path for u in caps.unsupported}
    )

    # Exempt: whole-surface loss already surfaced via the identity leaf.
    if case.identity in loss_declared:
        return

    reparsed = codec.parse(codec.render(case.intent()))

    # Exempt: render did not keep the identity leaf → whole-surface drop,
    # which is a different guard's concern (not a sub-detail silent loss).
    if not case.identity_kept(reparsed):
        return

    # Sub-detail round-trips → no loss.
    if case.subdetail_survived(reparsed):
        return

    # Identity kept but sub-detail dropped: MUST be declared.
    assert case.leaf in loss_declared, (
        f"{name}: render keeps the {case.identity} identity leaf but DROPS "
        f"the {case.leaf} sub-detail, and the matrix declares it neither "
        f"lossy nor unsupported — so validate_against reports 'supported' "
        f"(severity ok) while the value is silently discarded.  Add a "
        f"LossyPath/UnsupportedPath for {case.leaf} (exact walker spelling)."
    )


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c.id)
def test_some_codec_demonstrates_each_case(case: _Case):
    """Guard the guard: for every probe at least one codec must actually
    keep the identity leaf yet drop the sub-detail, else the case is
    vacuous (its intent never triggers the assertion path anywhere)."""
    triggered = False
    for name in _CODEC_NAMES:
        codec = get_codec(name)
        caps = codec.capabilities
        loss_declared = (
            {lp.path for lp in caps.lossy} | {u.path for u in caps.unsupported}
        )
        if case.identity in loss_declared:
            continue
        reparsed = codec.parse(codec.render(case.intent()))
        if case.identity_kept(reparsed) and not case.subdetail_survived(reparsed):
            triggered = True
            break
    assert triggered, (
        f"case {case.id!r} never finds a codec that keeps {case.identity} "
        f"while dropping {case.leaf} — the probe is vacuous; revisit the "
        f"targeted intent."
    )
