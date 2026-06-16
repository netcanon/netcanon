"""FortiGate VLAN-heuristic guard: loopback / tunnel logical units must
NOT be classified as dot1q VLAN sub-interfaces.

The dotted-form detector (``<parent>.<unit>``) used to match Junos
loopback (``lo0.2``) and secure-tunnel (``st0.100``) logical units, so
the render emitted ``set type vlan`` / ``set vlanid`` for them and the
re-parse produced phantom ``vlans`` records the source never had — a
cross-vendor round-trip drift surfaced by the JNPRAutomate MNHA vSRX
capture.  ``looks_like_vlan_iface`` / ``vlan_id_for`` now exclude
loopback/tunnel parents; genuine dot1q forms (``port1.10``,
``LAG_INTERNAL.100``) are unaffected.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.fortigate_cli.vlan_heuristics import (
    looks_like_vlan_iface,
    vlan_id_for,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "name",
    ["lo0.2", "lo0.10", "st0.100", "st0.200", "loopback0.5",
     "tunnel1.7", "gr-0/0/0.0"],
)
def test_loopback_and_tunnel_units_are_not_vlans(name: str) -> None:
    assert looks_like_vlan_iface(name) is False
    assert vlan_id_for(name, []) is None


@pytest.mark.parametrize(
    "name,expected_id",
    [("port1.10", 10), ("LAG_INTERNAL.100", 100), ("vlan20", 20),
     ("internal.4093", 4093)],
)
def test_genuine_dot1q_and_factory_vlans_still_detected(
    name: str, expected_id: int,
) -> None:
    assert looks_like_vlan_iface(name) is True
    assert vlan_id_for(name, []) == expected_id
