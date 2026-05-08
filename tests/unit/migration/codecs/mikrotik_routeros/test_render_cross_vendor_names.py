"""Cross-vendor name handling for the mikrotik_routeros renderer.

Phase-4 finding (rank 2 in `tests/fixtures/real/PHASE4_RECONCILIATION.md`):
the previous `/interface ethernet` filter required interface names
matching `^ether\\d`, so any cross-vendor source intent (Junos
`ge-0/0/0`, OPNsense `wan`/`lan`/`opt1`, Cisco `GigabitEthernet0/0/0`)
silently dropped its description / mtu / enabled state on render.

These tests pin the broadened filter: emit ethernet rows for any
interface that isn't already owned by the VLAN, bridge, or LAG
sections, and confirm the round-trip preserves attributes.
"""

import pytest
from netcanon.migration.canonical.intent import (
    CanonicalInterface,
    CanonicalIntent,
    CanonicalIPv4Address,
)
from netcanon.migration.codecs.mikrotik_routeros.parse import parse_intent
from netcanon.migration.codecs.mikrotik_routeros.render import render_intent



pytestmark = pytest.mark.unit

def test_render_non_ether_iface_preserves_attrs():
    """Non-`ether*` names emit /interface ethernet rows with attrs intact."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="ge-0/0/1",
                description="trunk",
                mtu=9216,
                enabled=False,
            ),
            CanonicalInterface(name="wan", enabled=True),
            CanonicalInterface(
                name="lan",
                enabled=True,
                ipv4_addresses=[
                    CanonicalIPv4Address(ip="10.0.0.1", prefix_length=24),
                ],
            ),
        ]
    )

    out = render_intent(intent)

    assert "/interface ethernet" in out
    for name in ("ge-0/0/1", "wan", "lan"):
        assert name in out, f"name {name!r} dropped from render"

    roundtrip = parse_intent(out)
    by_name = {i.name: i for i in roundtrip.interfaces}
    assert by_name["ge-0/0/1"].description == "trunk"
    assert by_name["ge-0/0/1"].mtu == 9216
    assert by_name["ge-0/0/1"].enabled is False
    assert "wan" in by_name
    assert "lan" in by_name


def test_render_excludes_vlan_bridge_lag_from_ethernet_block():
    """Names that look like VLAN/bridge/LAG must not leak into ethernet."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(name="vlan100", description="USERS"),
            CanonicalInterface(name="bridge1", description="local-bridge"),
            CanonicalInterface(name="bond1", description="LAG"),
            CanonicalInterface(name="ether1", description="phys"),
        ]
    )

    out = render_intent(intent)

    # ether1 should appear as a /interface ethernet row.  vlan100,
    # bridge1, bond1 should NOT — those have their own sections.
    ethernet_section = out.split("/interface ethernet")[1].split("/interface")[0]
    assert "ether1" in ethernet_section
    for excluded in ("vlan100", "bridge1", "bond1"):
        assert excluded not in ethernet_section, (
            f"unexpectedly emitted in /interface ethernet: {excluded}"
        )


def test_render_excludes_subinterface_unit_form_from_ethernet_block():
    """Junos/IOS subinterface unit form (`ge-0/0/0.10`) is a VLAN/SVI,
    not an ethernet row.  The exclusion filter recognises the
    ``.<digits>`` suffix and routes it away from /interface ethernet."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(name="ge-0/0/0", description="trunk-base"),
            CanonicalInterface(name="ge-0/0/0.10", description="USERS subif"),
        ]
    )

    out = render_intent(intent)
    ethernet_section = out.split("/interface ethernet")[1].split("/interface")[0]
    assert "ge-0/0/0" in ethernet_section
    assert "ge-0/0/0.10" not in ethernet_section


def test_render_excludes_cisco_port_channel_and_aruba_trunk_from_ethernet_block():
    """Cross-vendor LAG names (Cisco Port-channel, Aruba trkN, Junos aeN)
    must not be emitted as /interface ethernet rows."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(name="GigabitEthernet0/0/0"),
            CanonicalInterface(name="Port-channel1"),
            CanonicalInterface(name="Trk1"),
            CanonicalInterface(name="ae0"),
        ]
    )

    out = render_intent(intent)
    ethernet_section = out.split("/interface ethernet")[1].split("/interface")[0]
    assert "GigabitEthernet0/0/0" in ethernet_section
    for excluded in ("Port-channel1", "Trk1", "ae0"):
        assert excluded not in ethernet_section, (
            f"unexpectedly emitted in /interface ethernet: {excluded}"
        )
