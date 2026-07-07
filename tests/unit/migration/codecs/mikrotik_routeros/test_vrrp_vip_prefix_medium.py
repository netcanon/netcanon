"""MikroTik VRRP VIP prefix must round-trip (2026-07-06 review MEDIUM #22).

RouterOS models the VRRP virtual IP with its own mask on the
``/ip address add address=X/Y interface=vrrpN`` line.  The parser stashed the
prefix but ``_materialise_vrrp_groups`` dropped it (written, never read), so
render fell back to the PARENT interface's prefix — a same-vendor sanitize
silently rewrote e.g. a ``/28`` VIP to the parent's ``/24``, altering the
connected route.  The fix carries the prefix on ``CanonicalVRRPGroup`` and
render prefers it.

No committed MikroTik VRRP fixture exists, so this is mesh-flat.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec

pytestmark = pytest.mark.unit

_CFG = """\
/interface ethernet
add name=ether1
/interface vrrp
add interface=ether1 name=vrrp10 vrid=10 priority=110
/ip address
add address=10.0.0.1/24 interface=ether1
add address=10.0.0.100/28 interface=vrrp10
"""


def _group(intent):
    return next(
        g for iface in intent.interfaces for g in iface.vrrp_groups
    )


def test_vip_prefix_is_parsed_onto_the_group():
    intent = MikroTikRouterOSCodec().parse(_CFG)
    assert _group(intent).virtual_ip_prefix == 28


def test_vip_prefix_round_trips_not_parent_fallback():
    codec = MikroTikRouterOSCodec()
    rendered = codec.render(codec.parse(_CFG))
    # The VIP row must keep its own /28 — NOT the parent ether1 /24.
    assert "add address=10.0.0.100/28 interface=vrrp10" in rendered
    assert "10.0.0.100/24" not in rendered
    # And it survives a full round-trip on the canonical surface.
    assert _group(codec.parse(rendered)).virtual_ip_prefix == 28
