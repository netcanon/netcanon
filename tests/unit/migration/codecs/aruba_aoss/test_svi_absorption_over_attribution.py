"""Aruba AOS-S SVI absorption — guard against over-attribution.

Phase 4b cross-vendor agent (arista_eos source) flagged the Aruba
SVI absorption logic as the top high-severity codec finding: "Aruba
SVI absorption emits the SVI's IP onto every VLAN object — likely the
L3 VRF-bound SVI is being absorbed onto every VLAN row."

Root cause traced to ``render.py`` ``_VLAN_ID_DOTTED_RE`` matching
``<alpha>.<digits>`` too broadly.  Cisco / Arista routed
sub-interfaces (``Ethernet1.10``, ``Port-Channel10.30``) carry their
own IP for an 802.1Q sub-interface — they are NOT the absorbed-into-
``vlan`` block SVI.  But the dotted regex matched them and the
``iface_by_vlan_id`` index picked them as fallback SVI candidates,
stamping a sub-interface's IP onto an unrelated ``vlan N`` block.

These tests pin the correct behaviour:

* Distinct SVIs (``Vlan10``, ``Vlan11``) emit their OWN IP into their
  OWN ``vlan N`` block; no cross-contamination.
* A VRF-bound SVI's IP does not leak onto an unrelated VLAN's block.
* Cisco-style routed sub-interfaces (``Ethernet1.10`` with an IP) do
  NOT absorb their IP into ``vlan 10`` — that's a sub-interface, not
  an SVI.
* OPNsense-style ``vlanN.M`` and Junos-style ``irb.N`` and
  FortiGate-style ``portN.M`` continue to absorb correctly (these
  ARE the SVIs on those vendors).
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalVlan,
)
from netconfig.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec

pytestmark = pytest.mark.unit


def _vlan_block(out: str, vid: int) -> str:
    """Slice the rendered ``vlan <vid>`` block (header through `exit`)."""
    header = f"vlan {vid}\n"
    if header not in out:
        return ""
    start = out.index(header)
    rest = out[start:]
    end = rest.index("   exit") + len("   exit")
    return rest[:end]


# ---------------------------------------------------------------------------
# Distinct SVIs - no cross-attribution
# ---------------------------------------------------------------------------


def test_aruba_svi_absorption_does_not_over_attribute_to_other_vlans() -> None:
    """Two SVIs, distinct IPs.  Each VLAN gets ONLY its own SVI's IP."""
    intent = CanonicalIntent(
        vlans=[
            CanonicalVlan(id=10, name="V10"),
            CanonicalVlan(id=11, name="V11"),
        ],
        interfaces=[
            CanonicalInterface(
                name="Vlan10",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="192.168.10.1", prefix_length=24,
                )],
            ),
            CanonicalInterface(
                name="Vlan11",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="192.168.11.1", prefix_length=24,
                )],
            ),
        ],
    )
    out = ArubaAOSSCodec().render(intent)
    block10 = _vlan_block(out, 10)
    block11 = _vlan_block(out, 11)
    assert "ip address 192.168.10.1/24" in block10
    assert "ip address 192.168.11.1/24" not in block10
    assert "ip address 192.168.11.1/24" in block11
    assert "ip address 192.168.10.1/24" not in block11


def test_aruba_svi_absorption_with_vrf_bound_svi_does_not_leak_to_unbound_vlan() -> None:
    """A VRF-bound SVI's IP must not appear on a sibling VLAN's block.

    Mirrors the arista_eos labval shape: per-VRF SVIs (``Vlan3000``..
    ``Vlan3003``) each carry the same IP because they're MLAG iBGP
    peer links per VRF.  The absorption layer must keep each one in
    its own ``vlan N`` block — not stamp ``Vlan3000``'s IP onto
    ``vlan 4093`` etc.  (VRF bindings themselves are lossy on AOS-S
    since the platform doesn't support VRFs the same way; we're only
    asserting the IP placement.)
    """
    intent = CanonicalIntent(
        vlans=[
            CanonicalVlan(id=3000, name="MLAG_iBGP_OP"),
            CanonicalVlan(id=4093, name="LEAF_PEER_L3"),
        ],
        interfaces=[
            CanonicalInterface(
                name="Vlan3000",
                description="VRF Tenant_A_OP_Zone iBGP peer",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="10.255.251.2", prefix_length=31,
                )],
            ),
            CanonicalInterface(
                name="Vlan4093",
                description="LEAF_PEER L3",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="10.255.252.2", prefix_length=31,
                )],
            ),
        ],
    )
    out = ArubaAOSSCodec().render(intent)
    block_3000 = _vlan_block(out, 3000)
    block_4093 = _vlan_block(out, 4093)
    assert "ip address 10.255.251.2/31" in block_3000
    assert "ip address 10.255.252.2/31" not in block_3000
    assert "ip address 10.255.252.2/31" in block_4093
    assert "ip address 10.255.251.2/31" not in block_4093


# ---------------------------------------------------------------------------
# Sub-interface (NOT SVI) must not absorb
# ---------------------------------------------------------------------------


def test_aruba_routed_subinterface_does_not_absorb_into_vlan() -> None:
    """Cisco / Arista routed sub-interface ``Ethernet1.10`` must NOT
    have its IP stamped onto ``vlan 10`` — it's a sub-interface that
    happens to encapsulate dot1Q 10, NOT the absorbed-into-VLAN SVI.

    The proper SVI shape on Cisco / Arista is ``interface Vlan10``
    (``Vlan<N>`` canonical name).  A bare-letter dotted form like
    ``Ethernet1.10`` or ``Port-Channel10.30`` represents an L3
    sub-interface that the Aruba renderer must keep separate.
    """
    intent = CanonicalIntent(
        vlans=[CanonicalVlan(id=10, name="V10")],
        interfaces=[
            # Routed sub-interface — NOT an SVI.
            CanonicalInterface(
                name="Ethernet1.10",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="99.99.99.99", prefix_length=30,
                )],
            ),
        ],
    )
    out = ArubaAOSSCodec().render(intent)
    block_10 = _vlan_block(out, 10)
    # The sub-interface's IP must NOT appear inside the vlan 10 block.
    assert "ip address 99.99.99.99/30" not in block_10
    # No spurious ip-address line at all (vlan 10 has no real SVI).
    assert "ip address" not in block_10


def test_aruba_port_channel_subinterface_does_not_absorb() -> None:
    """Same shape as the Ethernet sub-interface guard, but for the
    Cisco / Arista LAG sub-interface form ``Port-Channel10.30``.  The
    trailing ``.30`` is dot1Q encapsulation — not vlan 30's SVI.
    """
    intent = CanonicalIntent(
        vlans=[CanonicalVlan(id=30, name="V30")],
        interfaces=[
            CanonicalInterface(
                name="Port-Channel10.30",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="172.16.30.1", prefix_length=24,
                )],
            ),
        ],
    )
    out = ArubaAOSSCodec().render(intent)
    block_30 = _vlan_block(out, 30)
    assert "ip address 172.16.30.1/24" not in block_30
    assert "ip address" not in block_30


# ---------------------------------------------------------------------------
# Real SVI dotted-forms still absorb (regression guards for Finding 4)
# ---------------------------------------------------------------------------


def test_aruba_opnsense_vlan_dotted_form_still_absorbs() -> None:
    """Regression guard for Finding 4: OPNsense ``vlan0.10`` IS the SVI
    for vlan 10 on that vendor — it MUST continue to absorb.
    """
    intent = CanonicalIntent(
        vlans=[CanonicalVlan(id=10, name="V10")],
        interfaces=[CanonicalInterface(
            name="vlan0.10",
            ipv4_addresses=[CanonicalIPv4Address(
                ip="192.168.10.1", prefix_length=24,
            )],
        )],
    )
    out = ArubaAOSSCodec().render(intent)
    assert "ip address 192.168.10.1/24" in _vlan_block(out, 10)


def test_aruba_junos_irb_dotted_form_still_absorbs() -> None:
    """Regression guard: Junos ``irb.100`` IS the SVI for vlan 100 on
    that vendor — it must continue to absorb.
    """
    intent = CanonicalIntent(
        vlans=[CanonicalVlan(id=100, name="V100")],
        interfaces=[CanonicalInterface(
            name="irb.100",
            ipv4_addresses=[CanonicalIPv4Address(
                ip="172.16.100.3", prefix_length=24,
            )],
        )],
    )
    out = ArubaAOSSCodec().render(intent)
    assert "ip address 172.16.100.3/24" in _vlan_block(out, 100)


def test_aruba_fortigate_port_dotted_form_still_absorbs() -> None:
    """Regression guard: FortiGate ``port1.10`` IS the SVI for vlan 10
    on that vendor — it must continue to absorb.
    """
    intent = CanonicalIntent(
        vlans=[CanonicalVlan(id=10, name="V10")],
        interfaces=[CanonicalInterface(
            name="port1.10",
            ipv4_addresses=[CanonicalIPv4Address(
                ip="10.0.10.1", prefix_length=24,
            )],
        )],
    )
    out = ArubaAOSSCodec().render(intent)
    assert "ip address 10.0.10.1/24" in _vlan_block(out, 10)


# ---------------------------------------------------------------------------
# Mixed source: sub-interface present alongside real SVI - real SVI wins
# ---------------------------------------------------------------------------


def test_aruba_real_svi_wins_over_subinterface_with_same_id() -> None:
    """When BOTH a routed sub-interface ``Ethernet1.10`` AND a real
    ``Vlan10`` SVI exist, the real SVI's IP wins and the sub-interface
    keeps its own IP on a separate stanza.
    """
    intent = CanonicalIntent(
        vlans=[CanonicalVlan(id=10, name="V10")],
        interfaces=[
            CanonicalInterface(
                name="Ethernet1.10",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="99.99.99.99", prefix_length=30,
                )],
            ),
            CanonicalInterface(
                name="Vlan10",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="10.10.10.1", prefix_length=24,
                )],
            ),
        ],
    )
    out = ArubaAOSSCodec().render(intent)
    block_10 = _vlan_block(out, 10)
    assert "ip address 10.10.10.1/24" in block_10
    assert "ip address 99.99.99.99/30" not in block_10
    # The sub-interface's IP still appears somewhere (its own stanza),
    # just not inside vlan 10.
    assert "99.99.99.99/30" in out
