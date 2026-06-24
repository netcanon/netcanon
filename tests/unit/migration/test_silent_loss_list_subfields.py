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
