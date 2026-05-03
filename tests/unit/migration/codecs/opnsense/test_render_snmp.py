"""
OPNsense SNMP render coverage.

The codec emits the OPNsense ``<snmpd>`` element under ``<opnsense>``
with ``<rocommunity>``, ``<syslocation>``, ``<syscontact>``, and
zero-or-more ``<traphost>`` children.  These map to the bsnmpd /
net-snmp plugin's storage shape used by the OPNsense GUI.

Wire form is pinned against the OPNsense plugin docs and a real
config.xml fixture:

* https://docs.opnsense.org/development/api/plugins/netsnmp.html

SNMPv3 USM users are intentionally NOT rendered — the OPNsense
capability matrix lists ``/snmp/v3-user`` as unsupported because
v3 user records live in the bsnmpd plugin's snmpd.conf
(``createUser`` lines), NOT in config.xml.  The
juniper_junos__opnsense expectation YAML pins this as
``disposition: unsupported``.

Coverage includes the cross-vendor cascade (juniper_junos source ->
opnsense target round-trip via the canonical tree).
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
from netconfig.migration.codecs.opnsense import OPNsenseCodec
from netconfig.migration.codecs.opnsense.parse import parse_intent
from netconfig.migration.codecs.opnsense.render import render_intent



pytestmark = pytest.mark.unit

def test_opnsense_renders_snmp_community() -> None:
    intent = CanonicalIntent()
    intent.snmp = CanonicalSNMP(community="public")
    out = render_intent(intent)

    assert "<snmpd>" in out
    assert "<rocommunity>public</rocommunity>" in out


def test_opnsense_renders_snmp_location_contact() -> None:
    intent = CanonicalIntent()
    intent.snmp = CanonicalSNMP(
        location="Synthetic Lab Rack 7",
        contact="noc@example.net",
    )
    out = render_intent(intent)

    assert "<syslocation>Synthetic Lab Rack 7</syslocation>" in out
    assert "<syscontact>noc@example.net</syscontact>" in out


def test_opnsense_renders_snmp_trap_hosts() -> None:
    intent = CanonicalIntent()
    intent.snmp = CanonicalSNMP(
        community="public",
        trap_hosts=["10.0.0.250", "10.0.0.251"],
    )
    out = render_intent(intent)

    # OPNsense flattens trap-host list to repeated <traphost> elements.
    assert "<traphost>10.0.0.250</traphost>" in out
    assert "<traphost>10.0.0.251</traphost>" in out


def test_opnsense_v3_users_drop_by_design() -> None:
    """OPNsense classifies SNMPv3 USM as unsupported in config.xml
    (lives in the bsnmpd plugin's snmpd.conf, not config.xml).  The
    renderer must NOT emit any v3-user element even when v3 users are
    present on the canonical tree — the cross-pair expectation YAML
    pins this as ``disposition: unsupported``."""
    intent = CanonicalIntent()
    intent.snmp = CanonicalSNMP(
        community="public",
        v3_users=[
            CanonicalSNMPv3User(
                name="monitor",
                auth_protocol="sha256",
                auth_passphrase="hash",
                priv_protocol="aes256",
                priv_passphrase="hash",
            ),
        ],
    )
    out = render_intent(intent)

    # No v3 element shapes appear (snmpv3, snmpuser, v3user, etc.).
    lower = out.lower()
    assert "<snmpv3" not in lower
    assert "<snmpuser" not in lower
    assert "<v3user" not in lower
    # The v2c surface still renders normally.
    assert "<rocommunity>public</rocommunity>" in out


def test_opnsense_no_snmp_emits_nothing() -> None:
    """Regression guard: when ``intent.snmp`` is None the renderer
    must NOT emit any ``<snmpd>`` element."""
    intent = CanonicalIntent()
    out = render_intent(intent)

    assert "<snmpd>" not in out


def test_opnsense_empty_snmp_emits_nothing() -> None:
    intent = CanonicalIntent()
    intent.snmp = CanonicalSNMP()
    out = render_intent(intent)

    assert "<snmpd>" not in out


def test_junos_to_opnsense_snmp_round_trips() -> None:
    """Cross-vendor cascade: Junos source carrying community / location
    / contact / trap_hosts survives through OPNsense render + parse.
    All four scalars are classified ``good`` for this pair; v3_users is
    expected to drop (``unsupported``)."""
    junos_src = (
        'set snmp community public authorization read-only\n'
        'set snmp location "Synthetic Lab Rack 7"\n'
        'set snmp contact "noc@example.net"\n'
        'set snmp trap-group monitoring targets 10.0.0.250\n'
        'set snmp trap-group monitoring targets 10.0.0.251\n'
    )
    intent = junos_parse(junos_src)
    rendered = OPNsenseCodec().render(intent)
    back = parse_intent(rendered)

    assert back.snmp is not None
    assert back.snmp.community == "public"
    assert back.snmp.location == "Synthetic Lab Rack 7"
    assert back.snmp.contact == "noc@example.net"
    assert back.snmp.trap_hosts == ["10.0.0.250", "10.0.0.251"]
