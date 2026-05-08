"""Loopback + GRE tunnel emission and static-route gateway+interface
combination for the mikrotik_routeros renderer.

Phase 4b cross-vendor findings:

* cisco_iosxe (NETCONF) source: when a canonical interface carried
  ``interface_type="ianaift:softwareLoopback"`` (Cisco ``Loopback0``,
  Arista ``LoopbackN``, Junos ``lo0``), the previous render flowed
  the iface into the ``/interface ethernet`` block (no factory
  ``default-name`` to bind to) AND additionally synthesised the iface
  on-the-wire via ``/ip address add interface=loN`` -- RouterOS
  creates a phantom stub ethernet interface with no factory
  backing.  Same gap on ``ianaift:tunnel``.

* fortigate_cli source: a canonical ``CanonicalStaticRoute`` with
  BOTH ``gateway`` and ``interface`` populated had its interface
  field silently dropped by the ``elif`` ladder around
  ``render.py:374``.  RouterOS supports a combined ``gateway=<ip>%
  <iface>`` form that pins the next-hop IP to a specific egress
  interface.

These tests pin:

1. Loopback iface emits a dedicated ``/interface bridge add
   name=<name>`` declaration (RouterOS empty-bridge idiom for
   loopback -- no native loopback primitive).
2. GRE / tunnel iface emits a dedicated ``/interface gre add
   name=<name> remote-address=0.0.0.0`` declaration with a review
   comment about the placeholder endpoint (canonical model has no
   tunnel local/remote address pair).
3. Loopback / tunnel ifaces are EXCLUDED from the
   ``/interface ethernet`` block.
4. Plain ethernet / vlan ifaces with no loopback/tunnel marker
   continue to render normally (regression guard).
5. Static route with both gateway and interface populated emits
   ``gateway=<ip>%<iface>``.
6. Static route with only gateway emits ``gateway=<ip>`` (regression
   guard).
7. Static route with only interface emits ``gateway=<iface>``
   (regression guard).

RouterOS doc references (cited in render.py comments):
* Loopback empty-bridge idiom:
  https://wiki.mikrotik.com/wiki/Manual:Creating_IPv6_loopback_address
* GRE tunnel form:
  https://help.mikrotik.com/docs/spaces/ROS/pages/24805531/GRE
* Static route gateway%iface form:
  https://wiki.mikrotik.com/wiki/Manual:IP/Route
"""

import pytest
from netcanon.migration.canonical.intent import (
    CanonicalInterface,
    CanonicalIntent,
    CanonicalIPv4Address,
    CanonicalStaticRoute,
)
from netcanon.migration.codecs.mikrotik_routeros.render import render_intent



pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Issue 1: Loopback / Tunnel emission
# ---------------------------------------------------------------------------


def test_mikrotik_loopback_emits_dedicated_declaration():
    """A canonical interface with ``interface_type=
    'ianaift:softwareLoopback'`` emits a dedicated ``/interface
    bridge add name=<name>`` declaration (RouterOS empty-bridge
    idiom)."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="lo0",
                interface_type="ianaift:softwareLoopback",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="10.255.0.1", prefix_length=32,
                    ),
                ],
            ),
        ],
    )

    out = render_intent(intent)

    # Dedicated /interface bridge declaration.
    assert "/interface bridge" in out
    assert "add name=lo0" in out
    # Loopback IP still bound to lo0 (via /ip address).
    assert "/ip address" in out
    assert "add address=10.255.0.1/32 interface=lo0" in out
    # Loopback NOT in the /interface ethernet block.
    assert "find name=lo0" not in out
    assert "find default-name=lo0" not in out


def test_mikrotik_loopback_by_name_shape_emits_dedicated_declaration():
    """A canonical interface with the ``loN`` / ``loopbackN``
    name shape but no explicit interface_type still gets the
    dedicated declaration -- covers cross-vendor sources whose
    parsers don't populate the IANA-IF-MIB type."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="loopback1",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="10.255.0.2", prefix_length=32,
                    ),
                ],
            ),
        ],
    )

    out = render_intent(intent)

    assert "/interface bridge" in out
    assert "add name=loopback1" in out


def test_mikrotik_gre_tunnel_emits_dedicated_declaration():
    """A canonical interface with ``interface_type='ianaift:tunnel'``
    emits a dedicated ``/interface gre add name=<name>
    remote-address=0.0.0.0`` declaration with a review comment."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="gre1",
                interface_type="ianaift:tunnel",
                description="Site-to-site tunnel",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="172.16.100.1", prefix_length=30,
                    ),
                ],
            ),
        ],
    )

    out = render_intent(intent)

    assert "/interface gre" in out
    assert "name=gre1" in out
    # Placeholder endpoint sentinel.
    assert "remote-address=0.0.0.0" in out
    # Source description carries through as the comment.
    assert "Site-to-site tunnel" in out
    # The tunnel IP still binds via /ip address -- no stub synthesis.
    assert "add address=172.16.100.1/30 interface=gre1" in out
    # Tunnel NOT in the /interface ethernet block.
    assert "find name=gre1" not in out
    assert "find default-name=gre1" not in out


def test_mikrotik_tunnel_without_description_emits_review_comment():
    """When a tunnel iface has no description, the render emits a
    review comment so operators are warned about the placeholder
    endpoints."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="gre2",
                interface_type="ianaift:tunnel",
            ),
        ],
    )

    out = render_intent(intent)

    assert "/interface gre" in out
    assert "name=gre2" in out
    assert "remote-address=0.0.0.0" in out
    assert "review" in out.lower()


def test_mikrotik_no_interface_type_no_synthetic_declaration():
    """Regression guard: a plain ethernet iface (no loopback /
    tunnel marker) flows into the /interface ethernet block as
    before -- does NOT trigger a phantom /interface bridge or
    /interface gre line."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="ether1",
                description="WAN uplink",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="192.0.2.1", prefix_length=24,
                    ),
                ],
            ),
        ],
    )

    out = render_intent(intent)

    assert "/interface ethernet" in out
    assert "find default-name=ether1" in out
    # No spurious bridge or gre declarations for a plain ethernet.
    assert "/interface bridge" not in out
    assert "/interface gre" not in out


# ---------------------------------------------------------------------------
# Issue 2: Static-route gateway + interface combination
# ---------------------------------------------------------------------------


def test_mikrotik_static_route_with_gateway_and_interface_emits_both():
    """When BOTH gateway and interface are populated on a canonical
    static route, the render emits the RouterOS combined form
    ``gateway=<ip>%<iface>`` rather than silently dropping one."""
    intent = CanonicalIntent(
        static_routes=[
            CanonicalStaticRoute(
                destination="0.0.0.0/0",
                gateway="192.168.1.1",
                interface="ether1",
            ),
        ],
    )

    out = render_intent(intent)

    assert "/ip route" in out
    assert "gateway=192.168.1.1%ether1" in out
    # NOT the prior bug shape (gateway alone, interface dropped).
    assert "gateway=192.168.1.1\n" not in out
    assert "gateway=192.168.1.1 " not in out


def test_mikrotik_static_route_with_gateway_only_unchanged():
    """Regression guard: gateway-only routes still emit
    ``gateway=<ip>`` exactly as before."""
    intent = CanonicalIntent(
        static_routes=[
            CanonicalStaticRoute(
                destination="10.0.0.0/8",
                gateway="192.168.1.254",
            ),
        ],
    )

    out = render_intent(intent)

    assert "/ip route" in out
    assert "gateway=192.168.1.254" in out
    assert "%" not in out


def test_mikrotik_static_route_with_interface_only_unchanged():
    """Regression guard: interface-only routes still emit
    ``gateway=<iface>``."""
    intent = CanonicalIntent(
        static_routes=[
            CanonicalStaticRoute(
                destination="10.0.0.0/24",
                interface="ether2",
            ),
        ],
    )

    out = render_intent(intent)

    assert "/ip route" in out
    assert "gateway=ether2" in out
    assert "%" not in out
