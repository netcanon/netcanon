"""
FortiGate CLI SNMP render coverage.

The codec consumes ``CanonicalSNMP`` (community / location / contact /
trap_hosts / v3_users) and emits the FortiOS ``config system snmp
sysinfo`` + ``config system snmp community`` + ``config system snmp
user`` blocks.  These tests pin the wire forms from the FortiOS 7.x
CLI reference:

* https://docs.fortinet.com/document/fortigate/7.6.4/cli-reference/111967164/config-system-snmp-community
* https://docs.fortinet.com/document/fortigate/7.6.6/cli-reference/292257317/config-system-snmp-user

Coverage includes the cross-vendor cascade (juniper_junos source ->
fortigate_cli target round-trip via the canonical tree) since that is
the path Phase 4b flagged for SNMP fidelity audits.
"""

from __future__ import annotations

import pytest
from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalSNMP,
    CanonicalSNMPv3User,
)
from netcanon.migration.codecs.fortigate_cli import FortiGateCLICodec
from netcanon.migration.codecs.fortigate_cli.parse import parse_intent
from netcanon.migration.codecs.fortigate_cli.render import render_intent
from netcanon.migration.codecs.juniper_junos.parse import (
    parse_intent as junos_parse,
)



pytestmark = pytest.mark.unit

def test_fortigate_renders_snmp_community() -> None:
    intent = CanonicalIntent()
    intent.snmp = CanonicalSNMP(community="public")
    out = render_intent(intent)

    assert "config system snmp community" in out
    assert "    edit 1" in out
    assert '        set name "public"' in out


def test_fortigate_renders_snmp_location_contact() -> None:
    intent = CanonicalIntent()
    intent.snmp = CanonicalSNMP(
        location="Synthetic Lab Rack 7",
        contact="noc@example.net",
    )
    out = render_intent(intent)

    # sysinfo carries location + contact.
    assert "config system snmp sysinfo" in out
    assert "    set status enable" in out
    assert '    set location "Synthetic Lab Rack 7"' in out
    assert '    set contact-info "noc@example.net"' in out


def test_fortigate_renders_snmp_trap_hosts() -> None:
    intent = CanonicalIntent()
    intent.snmp = CanonicalSNMP(
        community="public",
        trap_hosts=["10.0.0.250", "10.0.0.251"],
    )
    out = render_intent(intent)

    # Trap targets nest inside ``config hosts`` per FortiOS schema.
    assert "        config hosts" in out
    assert "            edit 1" in out
    assert '                set ip "10.0.0.250 255.255.255.255"' in out
    assert "            edit 2" in out
    assert '                set ip "10.0.0.251 255.255.255.255"' in out


def test_fortigate_renders_snmp_trap_hosts_without_community() -> None:
    """trap_hosts must survive even when the source emitted no v2c
    community (e.g. SNMPv3-only deployments).  FortiOS nests trap
    targets inside a community record, so the renderer synthesises a
    minimal ``public`` community to host them.
    """
    intent = CanonicalIntent()
    intent.snmp = CanonicalSNMP(trap_hosts=["10.0.0.250"])
    out = render_intent(intent)

    assert "config system snmp community" in out
    # Synthesised default community name keeps the trap-target list
    # attached to a valid record.
    assert '        set name "public"' in out
    assert '                set ip "10.0.0.250 255.255.255.255"' in out


def test_fortigate_renders_snmp_v3_user_auth_priv() -> None:
    intent = CanonicalIntent()
    intent.snmp = CanonicalSNMP(
        v3_users=[
            CanonicalSNMPv3User(
                name="monitor",
                group="netadmin",
                auth_protocol="sha256",
                auth_passphrase="ENC opaque-auth-blob",
                priv_protocol="aes256",
                priv_passphrase="ENC opaque-priv-blob",
            ),
        ],
    )
    out = render_intent(intent)

    assert "config system snmp user" in out
    assert '    edit "monitor"' in out
    assert "        set security-level auth-priv" in out
    assert "        set auth-proto sha256" in out
    assert '        set auth-pwd "ENC opaque-auth-blob"' in out
    assert "        set priv-proto aes256" in out
    assert '        set priv-pwd "ENC opaque-priv-blob"' in out


def test_fortigate_renders_snmp_v3_user_no_priv() -> None:
    """auth-no-priv is a valid USM mode; FortiOS expects the
    explicit security-level keyword."""
    intent = CanonicalIntent()
    intent.snmp = CanonicalSNMP(
        v3_users=[
            CanonicalSNMPv3User(
                name="auth-only",
                auth_protocol="md5",
                auth_passphrase="hash",
            ),
        ],
    )
    out = render_intent(intent)

    assert "        set security-level auth-no-priv" in out
    assert "        set auth-proto md5" in out


def test_fortigate_no_snmp_emits_nothing() -> None:
    """Regression guard: when ``intent.snmp`` is None the renderer
    must NOT emit any ``config system snmp`` block."""
    intent = CanonicalIntent()
    out = render_intent(intent)

    assert "config system snmp" not in out


def test_fortigate_empty_snmp_emits_nothing() -> None:
    """Empty SNMP record (no fields populated) is equivalent to no
    SNMP at all."""
    intent = CanonicalIntent()
    intent.snmp = CanonicalSNMP()
    out = render_intent(intent)

    assert "config system snmp" not in out


def test_junos_to_fortigate_snmp_round_trips() -> None:
    """Cross-vendor cascade: Junos source carrying community / location
    / contact / trap_hosts survives parse -> FortiGate render ->
    FortiGate parse with all four fields preserved."""
    junos_src = (
        'set snmp community public authorization read-only\n'
        'set snmp location "Synthetic Lab Rack 7"\n'
        'set snmp contact "noc@example.net"\n'
        'set snmp trap-group monitoring targets 10.0.0.250\n'
        'set snmp trap-group monitoring targets 10.0.0.251\n'
    )
    intent = junos_parse(junos_src)
    rendered = FortiGateCLICodec().render(intent)
    back = parse_intent(rendered)

    assert back.snmp is not None
    assert back.snmp.community == "public"
    assert back.snmp.location == "Synthetic Lab Rack 7"
    assert back.snmp.contact == "noc@example.net"
    assert back.snmp.trap_hosts == ["10.0.0.250", "10.0.0.251"]
