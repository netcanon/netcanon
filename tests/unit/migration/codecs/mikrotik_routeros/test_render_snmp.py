"""
MikroTik RouterOS SNMP render coverage.

The codec consumes ``CanonicalSNMP`` and emits two RouterOS sections:

* ``/snmp set enabled=yes ...`` — the global agent state, where
  ``contact``, ``location``, and the (single) ``trap-target`` live.
* ``/snmp community`` — the v1/v2c default community (mutated via
  ``set [ find default=yes ] name=...``) and the SNMPv3 USM users
  (RouterOS overloads the community section for v3, see the
  ``CanonicalSNMPv3User`` docstring).

Wire forms are pinned against the RouterOS docs:

* https://help.mikrotik.com/docs/spaces/ROS/pages/8978566/SNMP

Coverage includes the cross-vendor cascade (juniper_junos source ->
mikrotik_routeros target round-trip via the canonical tree).
"""

from __future__ import annotations

import pytest
from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalSNMP,
    CanonicalSNMPv3User,
)
from netconfig.migration.codecs.juniper_junos.parse import (
    parse_intent as junos_parse,
)
from netconfig.migration.codecs.mikrotik_routeros import (
    MikroTikRouterOSCodec,
)
from netconfig.migration.codecs.mikrotik_routeros.parse import parse_intent
from netconfig.migration.codecs.mikrotik_routeros.render import render_intent



pytestmark = pytest.mark.unit

def test_mikrotik_renders_snmp_community() -> None:
    intent = CanonicalIntent()
    intent.snmp = CanonicalSNMP(community="public")
    out = render_intent(intent)

    assert "/snmp" in out
    assert "/snmp community" in out
    # The default community record gets mutated; RouterOS keeps a
    # single default community whose name comes from the canonical
    # community scalar.
    assert "set [ find default=yes ] name=public" in out


def test_mikrotik_renders_snmp_location_contact() -> None:
    intent = CanonicalIntent()
    intent.snmp = CanonicalSNMP(
        location="Synthetic Lab Rack 7",
        contact="noc@example.net",
    )
    out = render_intent(intent)

    assert "/snmp" in out
    assert 'contact="noc@example.net"' in out
    assert 'location="Synthetic Lab Rack 7"' in out


def test_mikrotik_renders_snmp_trap_hosts() -> None:
    intent = CanonicalIntent()
    intent.snmp = CanonicalSNMP(
        community="public",
        trap_hosts=["10.0.0.250", "10.0.0.251"],
    )
    out = render_intent(intent)

    # RouterOS's ``/snmp set trap-target=...`` accepts a comma-
    # separated host list (multi-target is preserved on render even
    # though the canonical->wire-form spec marks the cross-vendor
    # cascade as ``lossy``: parse-back collapses to a single value).
    assert "trap-target=10.0.0.250,10.0.0.251" in out


def test_mikrotik_renders_snmp_v3_user() -> None:
    intent = CanonicalIntent()
    intent.snmp = CanonicalSNMP(
        v3_users=[
            CanonicalSNMPv3User(
                name="monitor",
                auth_protocol="sha256",
                auth_passphrase="opaque-auth-blob",
                priv_protocol="aes256",
                priv_passphrase="opaque-priv-blob",
            ),
        ],
    )
    out = render_intent(intent)

    assert "/snmp community" in out
    assert "add name=monitor" in out
    # Canonical sha256 -> RouterOS-native SHA256 keyword.
    assert "authentication-protocol=SHA256" in out
    assert 'authentication-password="opaque-auth-blob"' in out
    # Canonical aes256 -> RouterOS aes-256-cfb (the default CFB variant
    # RouterOS exposes; see canonical->wire mapping in render.py).
    assert "encryption-protocol=aes-256-cfb" in out
    assert 'encryption-password="opaque-priv-blob"' in out


def test_mikrotik_no_snmp_emits_nothing() -> None:
    """Regression guard: when ``intent.snmp`` is None the renderer
    must NOT emit any ``/snmp`` block."""
    intent = CanonicalIntent()
    out = render_intent(intent)

    assert "/snmp" not in out


def test_mikrotik_empty_snmp_emits_nothing() -> None:
    intent = CanonicalIntent()
    intent.snmp = CanonicalSNMP()
    out = render_intent(intent)

    assert "/snmp" not in out


def test_junos_to_mikrotik_snmp_round_trips() -> None:
    """Cross-vendor cascade: Junos source carrying community / location
    / contact survives through MikroTik render + parse.  trap_hosts is
    classified ``lossy`` for this pair (RouterOS one-target limit) so
    we only assert the three ``good`` scalars round-trip."""
    junos_src = (
        'set snmp community public authorization read-only\n'
        'set snmp location "Synthetic Lab Rack 7"\n'
        'set snmp contact "noc@example.net"\n'
    )
    intent = junos_parse(junos_src)
    rendered = MikroTikRouterOSCodec().render(intent)
    back = parse_intent(rendered)

    assert back.snmp is not None
    assert back.snmp.community == "public"
    assert back.snmp.location == "Synthetic Lab Rack 7"
    assert back.snmp.contact == "noc@example.net"
