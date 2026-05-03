"""Parser symmetry for ``family inet dhcp`` on the Junos codec.

Wave-6 commit ``5edf800`` added render-side emit for
``CanonicalInterface.dhcp_client=True`` — the renderer now produces
``set interfaces <name> unit 0 family inet dhcp`` (and the
sub-interface variant ``set interfaces <parent> unit <N> family
inet dhcp``).  Before this fix the parser silently ignored that
token, so a same-vendor Junos round-trip dropped the DHCP intent
back to ``dhcp_client=False`` and any cross-vendor flow that
landed on Junos-set-input lost the flag too.

These tests guard the four token shapes the renderer can emit
plus the dotted-unit shorthand operators may paste in directly.
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
)
from netconfig.migration.codecs.juniper_junos.parse import parse_intent
from netconfig.migration.codecs.juniper_junos.render import render_intent

pytestmark = pytest.mark.unit


def test_junos_parse_family_inet_dhcp_sets_dhcp_client() -> None:
    """``set interfaces ge-0/0/0 unit 0 family inet dhcp`` must
    canonicalise to ``dhcp_client=True`` with no static IPv4."""
    cfg = "set interfaces ge-0/0/0 unit 0 family inet dhcp\n"
    intent = parse_intent(cfg)
    assert len(intent.interfaces) == 1
    iface = intent.interfaces[0]
    assert iface.name == "ge-0/0/0"
    assert iface.dhcp_client is True
    assert iface.ipv4_addresses == []


def test_junos_parse_family_inet_address_dhcp_client_false() -> None:
    """Regression guard: a static IPv4 address line must NOT flip
    ``dhcp_client`` (it stays at the default ``False``).  Without
    this guard the new branch could leak the flag onto static-
    addressed interfaces."""
    cfg = (
        "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/24\n"
    )
    intent = parse_intent(cfg)
    assert len(intent.interfaces) == 1
    iface = intent.interfaces[0]
    assert iface.dhcp_client is False
    assert len(iface.ipv4_addresses) == 1
    assert iface.ipv4_addresses[0].ip == "10.0.0.1"
    assert iface.ipv4_addresses[0].prefix_length == 24


def test_junos_parse_dot_unit_family_inet_dhcp_sets_dhcp_client() -> None:
    """The dotted-unit shorthand
    ``set interfaces ge-0/0/0.0 family inet dhcp`` is semantically
    equivalent to ``... unit 0 family inet dhcp``.  Parser must
    collapse onto the parent interface (no spurious
    ``ge-0/0/0.0`` stub) and set ``dhcp_client=True``."""
    cfg = "set interfaces ge-0/0/0.0 family inet dhcp\n"
    intent = parse_intent(cfg)
    assert len(intent.interfaces) == 1
    iface = intent.interfaces[0]
    assert iface.name == "ge-0/0/0"
    assert iface.dhcp_client is True
    assert iface.ipv4_addresses == []


def test_junos_round_trip_dhcp_client() -> None:
    """Build ``CanonicalIntent`` with ``dhcp_client=True``, render to
    Junos set-form, parse it back; the flag must survive."""
    src = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="ge-0/0/0",
                dhcp_client=True,
            ),
        ],
    )
    rendered = render_intent(src)
    # Render-side emit must be present (sanity check on the wire-
    # format symmetry — guards against a renderer regression).
    assert (
        "set interfaces ge-0/0/0 unit 0 family inet dhcp" in rendered
    )
    reparsed = parse_intent(rendered)
    assert len(reparsed.interfaces) == 1
    iface = reparsed.interfaces[0]
    assert iface.name == "ge-0/0/0"
    assert iface.dhcp_client is True
    assert iface.ipv4_addresses == []
