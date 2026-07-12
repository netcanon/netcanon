"""Static-route administrative-distance (metric) round-trip — promotion #7.

A floating static route (a backup default with a raised admin distance) must
carry its distance token through render and reparse; without it the backup
silently becomes co-equal with the primary and failover is destroyed.  This
graduated four codecs from ``/routing/static-route/metric`` lossy -> supported:
arista_eos, mikrotik_routeros, fortigate_cli, cisco_iosxr.  The four donor
codecs (cisco_iosxe_cli, cisco_nxos, vyos, aruba_aoscx) already supported it.
"""
from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalStaticRoute,
)
from netcanon.migration.codecs.arista_eos.codec import AristaEOSCodec
from netcanon.migration.codecs.cisco_iosxr.codec import CiscoIOSXRCodec
from netcanon.migration.codecs.fortigate_cli.codec import FortiGateCLICodec
from netcanon.migration.codecs.mikrotik_routeros.codec import (
    MikroTikRouterOSCodec,
)

_GRADUATED = [
    pytest.param(AristaEOSCodec, id="arista_eos"),
    pytest.param(MikroTikRouterOSCodec, id="mikrotik_routeros"),
    pytest.param(FortiGateCLICodec, id="fortigate_cli"),
    pytest.param(CiscoIOSXRCodec, id="cisco_iosxr"),
]


def _round_trip(codec, routes):
    intent = CanonicalIntent(hostname="rt", static_routes=routes)
    reparsed = codec.parse(codec.render(intent))
    return {r.destination: r for r in reparsed.static_routes}


@pytest.mark.parametrize("codec_cls", _GRADUATED)
def test_metric_is_supported(codec_cls):
    assert codec_cls().capabilities.classify(
        "/routing/static-route/metric"
    ) == "supported"


@pytest.mark.parametrize("codec_cls", _GRADUATED)
def test_floating_default_metric_round_trips(codec_cls):
    """A metric-250 backup default survives; the metric-0 primary stays 0."""
    codec = codec_cls()
    by_dest = _round_trip(codec, [
        CanonicalStaticRoute(destination="10.0.0.0/24", gateway="192.0.2.1"),
        CanonicalStaticRoute(
            destination="0.0.0.0/0", gateway="192.0.2.254", metric=250,
        ),
    ])
    assert by_dest["0.0.0.0/0"].metric == 250
    # Distance-less routes must not gain a spurious metric.
    assert by_dest["10.0.0.0/24"].metric == 0


@pytest.mark.parametrize("codec_cls", _GRADUATED)
def test_metric_zero_emits_no_distance_token(codec_cls):
    """Negative control: metric 0 renders no distance keyword."""
    codec = codec_cls()
    rendered = codec.render(CanonicalIntent(
        hostname="rt",
        static_routes=[CanonicalStaticRoute(
            destination="10.0.0.0/24", gateway="192.0.2.1",
        )],
    ))
    assert "set distance" not in rendered  # fortigate
    assert "distance=" not in rendered      # mikrotik
    # arista/iosxr trailing-int distance: the only tokens are dest + next-hop.
    for line in rendered.splitlines():
        if "192.0.2.1" in line and "route" in line.lower():
            assert not line.rstrip().split()[-1].isdigit(), line


def test_cisco_iosxr_clamps_metric_to_254():
    """IOS-XR max installable distance is 254 (255 = unreachable)."""
    codec = CiscoIOSXRCodec()
    by_dest = _round_trip(codec, [CanonicalStaticRoute(
        destination="0.0.0.0/0", gateway="192.0.2.254", metric=255,
    )])
    assert by_dest["0.0.0.0/0"].metric == 254


def test_arista_interface_nexthop_carries_metric():
    """An aggregate anchor (``ip route <agg> Null0 250``) keeps its distance."""
    codec = AristaEOSCodec()
    by_dest = _round_trip(codec, [CanonicalStaticRoute(
        destination="10.99.0.0/16", interface="Null0", metric=250,
    )])
    route = by_dest["10.99.0.0/16"]
    assert route.interface == "Null0"
    assert route.metric == 250
