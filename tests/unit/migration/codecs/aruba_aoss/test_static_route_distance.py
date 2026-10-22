"""Aruba AOS-S static-route admin-distance (metric) round-trip (Fid-F7 follow-up).

A route carrying a trailing ``distance N`` / bare-metric token used to fail the
end-anchored ``_IP_ROUTE_RE`` gateway match and be silently dropped WHOLE.  The
distance is now captured into ``CanonicalStaticRoute.metric`` and emitted on
render.  A ``blackhole`` route is read as the tree's discard (``Null0``);
``reject``, which answers with an ICMP error the tree does not hold, is
left out and said in a row (see
``test_a_route_the_switch_takes.py`` beside this module).
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec
from netcanon.migration.codecs.mikrotik_routeros.codec import (
    MikroTikRouterOSCodec,
)

pytestmark = pytest.mark.unit

ARUBA = ArubaAOSSCodec()
MIKROTIK = MikroTikRouterOSCodec()


def _routes(cfg: str) -> dict:
    return {r.destination: r for r in ARUBA.parse(cfg).static_routes}


@pytest.mark.parametrize(
    ("line", "dest", "metric"),
    [
        # ``distance N`` keyword form (the HEAD-review reproducer).
        ("ip route 10.0.0.0/8 192.168.10.1 distance 200", "10.0.0.0/8", 200),
        # Legacy dotted-mask + bare trailing metric.
        ("ip route 172.16.0.0 255.255.0.0 192.168.10.2 5", "172.16.0.0/16", 5),
        # No distance → metric 0 (device default), must still round-trip.
        ("ip route 192.168.99.0/24 10.0.0.254", "192.168.99.0/24", 0),
        # IPv6 with distance.
        ("ipv6 route 2001:db8::/32 fe80::1 distance 30", "2001:db8::/32", 30),
    ],
)
def test_distance_route_parses_with_metric(line, dest, metric):
    routes = _routes("hostname t\n" + line + "\n")
    assert dest in routes, f"route {dest} was dropped (the pre-fix bug)"
    assert routes[dest].metric == metric


def test_distance_survives_aruba_to_mikrotik():
    cfg = (
        "hostname t\n"
        "ip route 10.0.0.0/8 192.168.10.1 distance 200\n"
        "ipv6 route 2001:db8::/32 fe80::1 distance 30\n"
    )
    intent = ARUBA.parse(cfg)
    back = {
        r.destination: r
        for r in MIKROTIK.parse(MIKROTIK.render(intent)).static_routes
    }
    assert back["10.0.0.0/8"].metric == 200
    assert back["2001:db8::/32"].metric == 30


def test_distance_survives_aruba_self_round_trip():
    cfg = "hostname t\nip route 10.0.0.0/8 192.168.10.1 distance 200\n"
    intent = ARUBA.parse(cfg)
    back = {
        r.destination: r
        for r in ARUBA.parse(ARUBA.render(intent)).static_routes
    }
    assert back["10.0.0.0/8"].metric == 200


def test_a_blackhole_route_is_read_as_the_discard():
    route = _routes("hostname t\nip route 10.0.0.0/8 blackhole\n")["10.0.0.0/8"]
    assert (route.gateway, route.interface) == ("", "Null0")


@pytest.mark.parametrize("gw", ["null0", "reject"])
def test_a_route_of_no_form_read_here_is_said(gw):
    # ``reject`` discards with an ICMP error, which the tree's one discard
    # does not say; ``null0`` is no next hop of AOS-S's.
    cfg = f"hostname t\nip route 10.0.0.0/8 {gw}\n"
    assert "10.0.0.0/8" not in _routes(cfg)
    rows = ARUBA.parse(cfg).dropped_tier3_sections
    assert any(row.startswith(f"ip route 10.0.0.0/8 {gw} (") for row in rows), rows
