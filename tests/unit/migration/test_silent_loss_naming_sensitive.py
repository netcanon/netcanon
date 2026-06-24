"""Silent-loss guard for NAMING-SENSITIVE surfaces — LAG + L2 VLAN membership.

The value-detail guard (``test_silent_loss_list_subfields``) and the
registry honesty guard (``test_registry_capability_honesty``) BOTH
deliberately exclude LAG members + switchport: a single universal
kitchen-sink can't tell a true drop from a vendor-name mismatch (a LAG
member named for the wrong vendor fails to render and merely *looks*
dropped — see ``test_registry_capability_honesty`` lines on the "third
honesty direction"). This module closes that residual gap with:

* **Per-codec NATIVE-named intents** (``_NATIVE``) — every interface / LAG /
  member name is spelled the way THAT codec renders it, so a drop is
  unambiguous rather than a naming artifact.
* **The switchport→vlan transform** (``project_switchport_to_vlan``) applied
  before render, so the probe matches the real port-centric *source* shape a
  target codec receives in the migration pipeline (a bare interface-field
  intent with empty VLAN port lists is a tree no real source parse produces).
* **Naming-independent survival checks** — LAG members by cardinality
  (``len(members) > 0``); L2 VLAN membership on EITHER canonical
  representation (per-interface ``switchport`` fields OR VLAN-centric
  ``tagged-ports`` / ``untagged-ports`` lists), since the transform keeps the
  two in sync and a codec that preserves either has not lost the binding.

**Base-identity-coverage rule** (same as the value-detail guard): a codec
must declare a sub-detail lossy/unsupported only when it KEEPS the identity
(the LAG, the VLAN) yet DROPS the sub-detail.  A codec that drops the whole
surface, or declares the identity itself lossy/unsupported, surfaces the
loss there and is exempt.

**Verified 2026-06-24** (native census in the silent-loss ledger): with
native names every L2 switch codec round-trips these surfaces; the L3 /
firewall / router codecs honestly declare them unsupported.  The one real
silent loss this sweep found — ``opnsense`` / ``mikrotik_routeros`` /
``fortigate_cli`` keep ``/vlans/vlan/id`` supported but structurally drop the
multi-port ``tagged-ports`` / ``untagged-ports`` lists (they bind a VLAN to a
single parent sub-interface) — is now declared unsupported in those three
matrices; this guard pins that.  Otherwise it is a REGRESSION LOCK, not a
bug report.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
    CanonicalVlan,
)
from netcanon.migration.canonical.transforms import project_switchport_to_vlan

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

_ETH = "ianaift:ethernetCsmacd"

#: Per-codec NATIVE naming, empirically verified (2026-06-24 native census) to
#: render + re-parse without a vendor-name mismatch.
#:   ``lag``   — native LAG / bundle / aggregate name.
#:   ``ports`` — two native physical port names (used as LAG members AND as the
#:               access / trunk ports of the VLAN-membership probe).
_NATIVE: dict[str, dict] = {
    # cisco_iosxe is the NETCONF stub: it renders interfaces only (no LAG /
    # VLAN), and declares access-vlan + /vlans/vlan/id unsupported, so every
    # case below exits via the declared/identity-not-kept exemptions.  Its
    # dropped-field honesty is covered by its own dedicated guard
    # (codecs/cisco_iosxe/test_capability_matrix_honesty.py).
    "cisco_iosxe":       {"lag": "Port-channel1", "ports": ["GigabitEthernet1", "GigabitEthernet2"]},
    "arista_eos":        {"lag": "Port-Channel1", "ports": ["Ethernet1", "Ethernet2"]},
    "aruba_aoscx":       {"lag": "lag1", "ports": ["1/1/5", "1/1/6"]},
    "aruba_aoss":        {"lag": "trk1", "ports": ["23", "24"]},
    "cisco_iosxe_cli":   {"lag": "Port-channel1", "ports": ["GigabitEthernet0/0/1", "GigabitEthernet0/0/2"]},
    "cisco_iosxr":       {"lag": "Bundle-Ether1", "ports": ["GigabitEthernet0/0/0/1", "GigabitEthernet0/0/0/2"]},
    "cisco_nxos":        {"lag": "port-channel1", "ports": ["Ethernet1/1", "Ethernet1/2"]},
    "fortigate_cli":     {"lag": "agg1", "ports": ["port1", "port2"]},
    "juniper_junos":     {"lag": "ae0", "ports": ["ge-0/0/1", "ge-0/0/2"]},
    "mikrotik_routeros": {"lag": "bond1", "ports": ["ether1", "ether2"]},
    "opnsense":          {"lag": "lagg0", "ports": ["em0", "em1"]},
    "vyos":              {"lag": "bond0", "ports": ["eth0", "eth1"]},
}


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


def _loss_declared(codec) -> set[str]:
    caps = codec.capabilities
    return {lp.path for lp in caps.lossy} | {u.path for u in caps.unsupported}


def _lag_intent(spec: dict) -> CanonicalIntent:
    """A LAG bundling two native physical members."""
    return CanonicalIntent(
        hostname="h",
        interfaces=[
            CanonicalInterface(name=p, default_name=p, interface_type=_ETH,
                               lag_member_of=spec["lag"])
            for p in spec["ports"]
        ],
        lags=[CanonicalLAG(name=spec["lag"], members=list(spec["ports"]), mode="active")],
    )


def _membership_intent(spec: dict) -> CanonicalIntent:
    """An access port + a trunk port carrying VLAN 10/20/99 membership, with
    the switchport→vlan transform applied so BOTH canonical representations
    (per-interface + VLAN-centric port lists) are populated — the realistic
    port-centric source shape a target codec receives."""
    acc, trunk = spec["ports"]
    intent = CanonicalIntent(
        hostname="h",
        interfaces=[
            CanonicalInterface(name=acc, default_name=acc, interface_type=_ETH,
                               switchport_mode="access", access_vlan=10),
            CanonicalInterface(name=trunk, default_name=trunk, interface_type=_ETH,
                               switchport_mode="trunk", trunk_allowed_vlans=[10, 20],
                               trunk_native_vlan=99),
        ],
        vlans=[CanonicalVlan(id=10, name="V10"), CanonicalVlan(id=20, name="V20"),
               CanonicalVlan(id=99, name="V99")],
    )
    project_switchport_to_vlan(intent)
    return intent


def _vlan_membership_survives(rp: CanonicalIntent) -> bool:
    """True iff the VLAN 10 port binding survived on EITHER canonical
    representation (per-interface switchport OR VLAN-centric port lists)."""
    iface = any(i.access_vlan == 10 or i.trunk_allowed_vlans for i in rp.interfaces)
    vlanlist = any(v.untagged_ports or v.tagged_ports for v in rp.vlans)
    return iface or vlanlist


# ---------------------------------------------------------------------------
# Guard-the-guard sanity
# ---------------------------------------------------------------------------


def test_registry_is_non_empty():
    assert len(_CODEC_NAMES) >= 11, _CODEC_NAMES


def test_native_map_covers_every_codec():
    """Every bidirectional codec must have a `_NATIVE` entry, else its
    parametrized cases would KeyError instead of probing."""
    missing = sorted(set(_CODEC_NAMES) - set(_NATIVE))
    assert not missing, f"_NATIVE missing native names for: {missing}"


# ---------------------------------------------------------------------------
# LAG members + lag-member-of
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _CODEC_NAMES)
def test_lag_members_preserved_or_declared(name: str):
    """A codec that renders a LAG (keeps ``/lags/lag/name``) must preserve its
    member list (cardinality > 0) or declare ``/lags/lag/members`` lossy/
    unsupported — else a real member drop reports ``severity: ok``."""
    codec = get_codec(name)
    declared = _loss_declared(codec)
    if "/lags/lag/members" in declared:
        return  # honestly declared
    rp = codec.parse(codec.render(_lag_intent(_NATIVE[name])))
    if not rp.lags:
        return  # whole-LAG drop — not a member sub-detail loss
    members = max((len(lag.members) for lag in rp.lags), default=0)
    assert members > 0, (
        f"{name}: renders the LAG (keeps /lags/lag/name) but DROPS all "
        f"members, and the matrix declares /lags/lag/members neither lossy "
        f"nor unsupported — validate_against reports 'supported' while the "
        f"member ports are silently discarded. Add a LossyPath/UnsupportedPath."
    )


@pytest.mark.parametrize("name", _CODEC_NAMES)
def test_lag_member_of_preserved_or_declared(name: str):
    """The per-member back-pointer ``/interfaces/interface/lag-member-of`` must
    survive on a codec that renders the LAG, or be declared."""
    codec = get_codec(name)
    declared = _loss_declared(codec)
    if "/interfaces/interface/lag-member-of" in declared:
        return
    rp = codec.parse(codec.render(_lag_intent(_NATIVE[name])))
    if not rp.lags:
        return
    member_of_kept = any(i.lag_member_of for i in rp.interfaces)
    assert member_of_kept, (
        f"{name}: renders the LAG but no interface carries lag-member-of on "
        f"re-parse, and the matrix declares /interfaces/interface/lag-member-of "
        f"neither lossy nor unsupported — silent membership loss."
    )


# ---------------------------------------------------------------------------
# L2 VLAN membership — per-interface switchport + VLAN-centric port lists
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _CODEC_NAMES)
def test_per_interface_switchport_preserved_or_declared(name: str):
    """The per-interface switchport surface (access-vlan / trunk-allowed-vlans)
    must survive the round-trip, OR be declared unsupported/lossy.

    L2 switches preserve it; the L3 router/firewall codecs declare it
    unsupported (they have no per-port switchport model)."""
    codec = get_codec(name)
    declared = _loss_declared(codec)
    rp = codec.parse(codec.render(_membership_intent(_NATIVE[name])))
    access_iface = any(i.access_vlan == 10 for i in rp.interfaces)
    trunk_iface = any(sorted(i.trunk_allowed_vlans) == [10, 20] for i in rp.interfaces)
    if not access_iface and "/interfaces/interface/access-vlan" not in declared:
        pytest.fail(
            f"{name}: render drops the per-interface access-vlan and the matrix "
            f"declares /interfaces/interface/access-vlan neither lossy nor "
            f"unsupported — validate_against reports 'supported' while the "
            f"port→VLAN binding is discarded."
        )
    if not trunk_iface and "/interfaces/interface/trunk-allowed-vlans" not in declared:
        pytest.fail(
            f"{name}: render drops the per-interface trunk-allowed-vlans and the "
            f"matrix declares it neither lossy nor unsupported — silent loss."
        )


@pytest.mark.parametrize("name", _CODEC_NAMES)
def test_vlan_port_lists_preserved_or_declared(name: str):
    """The VLAN-centric port-membership lists (``/vlans/vlan/tagged-ports`` +
    ``untagged-ports``) must survive on a codec that keeps the VLAN identity,
    OR be declared lossy/unsupported.

    This is the surface the 2026-06-24 sweep found genuinely silently lost on
    the firewall/router codecs (opnsense / mikrotik / fortigate), which bind a
    VLAN to a single parent sub-interface and so cannot represent multi-port
    membership.  Exempt when the codec drops the VLAN identity wholesale
    (cisco_iosxr models VLANs as dot1q sub-interfaces) or declares
    ``/vlans/vlan/id`` itself unsupported (vyos)."""
    codec = get_codec(name)
    declared = _loss_declared(codec)
    if "/vlans/vlan/id" in declared:
        return  # identity itself declared unsupported (whole-VLAN surface)
    rp = codec.parse(codec.render(_membership_intent(_NATIVE[name])))
    if not any(v.id == 10 for v in rp.vlans):
        return  # whole-VLAN drop (dot1q-subif model) — a different surface
    # Membership preserved on EITHER representation → no loss of the binding.
    if _vlan_membership_survives(rp):
        return
    # Totally lost on both representations → the VLAN-centric leaves MUST be
    # declared (the per-interface twin is asserted by the test above).
    missing = {"/vlans/vlan/tagged-ports", "/vlans/vlan/untagged-ports"} - declared
    assert not missing, (
        f"{name}: keeps /vlans/vlan/id supported but DROPS multi-port VLAN "
        f"membership on every canonical representation, and the matrix declares "
        f"these neither lossy nor unsupported: {sorted(missing)} — "
        f"validate_against reports 'supported' while the port→VLAN bindings are "
        f"silently discarded. Add an UnsupportedPath/LossyPath."
    )


# ---------------------------------------------------------------------------
# Anti-vacuous guards (guard the guard)
# ---------------------------------------------------------------------------


def test_lag_probe_is_live():
    """At least most codecs must actually render a LAG and keep its members,
    else the LAG probe is testing nothing (e.g. every native name went stale)."""
    kept = 0
    for name in _CODEC_NAMES:
        rp = get_codec(name).parse(get_codec(name).render(_lag_intent(_NATIVE[name])))
        if rp.lags and max((len(lag.members) for lag in rp.lags), default=0) > 0:
            kept += 1
    assert kept >= 8, f"only {kept} codecs round-trip LAG members — probe likely stale"


def test_switchport_probe_is_live():
    """At least the L2 switch codecs must preserve VLAN membership, proving the
    membership probe exercises a real supported surface (not vacuous)."""
    kept = 0
    for name in _CODEC_NAMES:
        rp = get_codec(name).parse(get_codec(name).render(_membership_intent(_NATIVE[name])))
        if any(v.id == 10 for v in rp.vlans) and _vlan_membership_survives(rp):
            kept += 1
    assert kept >= 5, f"only {kept} codecs preserve VLAN membership — probe likely stale"


def test_firewall_codecs_declare_vlan_membership_unsupported():
    """Pin the 2026-06-24 finding: the single-parent-VLAN codecs MUST declare
    the VLAN port-membership lists unsupported/lossy.  A regression that
    removed the declaration would re-introduce the silent loss this sweep
    closed (validate_against would report the dropped membership 'supported')."""
    for name in ("opnsense", "mikrotik_routeros", "fortigate_cli"):
        declared = _loss_declared(get_codec(name))
        for leaf in ("/vlans/vlan/tagged-ports", "/vlans/vlan/untagged-ports"):
            assert leaf in declared, (
                f"{name}: {leaf} is no longer declared lossy/unsupported — the "
                f"codec drops multi-port VLAN membership, so this re-opens a "
                f"silent loss (see test_silent_loss_naming_sensitive docstring)."
            )
