"""
Unit tests for :class:`CanonicalRADIUSServer` wire-through across codecs.

Covers the last Tier 2 item from translator-plans.txt.  Mirrors the
same shape as SNMP / local_users / DHCP wire-throughs: one class per
codec, parse + render + round-trip + a cross-codec integration.
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalRADIUSServer,
)
from netconfig.migration.codecs.aruba_aoss import ArubaAOSSCodec
from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netconfig.migration.codecs.fortigate_cli import FortiGateCLICodec
from netconfig.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netconfig.migration.codecs.opnsense import OPNsenseCodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Cisco IOS-XE CLI
# ---------------------------------------------------------------------------


class TestCiscoRADIUSParse:
    def test_modern_named_stanza(self):
        raw = """\
radius server MyRadius
 address ipv4 10.0.0.4 auth-port 1812 acct-port 1813
 key 7 082E0F1F5F
!
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        assert len(intent.radius_servers) == 1
        s = intent.radius_servers[0]
        assert s.host == "10.0.0.4"
        assert s.auth_port == 1812
        assert s.acct_port == 1813
        assert s.key == "7 082E0F1F5F"

    def test_legacy_host_one_liner(self):
        raw = "radius-server host 10.0.0.5 auth-port 1645 key fakekey123\n"
        intent = CiscoIOSXECLICodec().parse(raw)
        s = intent.radius_servers[0]
        assert s.host == "10.0.0.5"
        assert s.auth_port == 1645
        assert s.acct_port == 1813  # default
        assert s.key == "fakekey123"

    def test_legacy_host_without_key(self):
        raw = "radius-server host 10.0.0.6\n"
        intent = CiscoIOSXECLICodec().parse(raw)
        s = intent.radius_servers[0]
        assert s.host == "10.0.0.6"
        assert s.key == ""

    def test_modern_and_legacy_coexist(self):
        raw = """\
radius server Modern
 address ipv4 10.0.0.4 auth-port 1812
 key 7 abc123
!
radius-server host 10.0.0.5 auth-port 1645 key legacykey
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        hosts = [s.host for s in intent.radius_servers]
        assert set(hosts) == {"10.0.0.4", "10.0.0.5"}

    def test_modern_stanza_without_auth_ports_uses_defaults(self):
        raw = """\
radius server Simple
 address ipv4 10.0.0.4
 key plaintext
!
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        s = intent.radius_servers[0]
        assert s.auth_port == 1812
        assert s.acct_port == 1813


# ---------------------------------------------------------------------------
# Aruba AOS-S
# ---------------------------------------------------------------------------


class TestArubaRADIUSParseRender:
    def test_inline_key_form(self):
        raw = 'hostname "sw1"\nradius-server host 10.0.0.4 key "secret123"\n'
        intent = ArubaAOSSCodec().parse(raw)
        assert len(intent.radius_servers) == 1
        assert intent.radius_servers[0].host == "10.0.0.4"
        assert intent.radius_servers[0].key == "secret123"

    def test_global_key_backfills_hostless_servers(self):
        """Real AOS-S configs commonly declare the secret globally and
        multiple host lines separately.  The parser should backfill
        the global key onto any server without an inline one."""
        raw = """\
hostname "sw1"
radius-server host 10.0.0.4
radius-server host 10.0.0.5
radius-server key "fallback-secret"
"""
        intent = ArubaAOSSCodec().parse(raw)
        for server in intent.radius_servers:
            assert server.key == "fallback-secret"

    def test_inline_key_not_clobbered_by_global(self):
        """Global key should only apply to servers without an inline
        one."""
        raw = """\
radius-server host 10.0.0.4 key "specific"
radius-server host 10.0.0.5
radius-server key "global-fallback"
"""
        intent = ArubaAOSSCodec().parse(raw)
        by_host = {s.host: s for s in intent.radius_servers}
        assert by_host["10.0.0.4"].key == "specific"
        assert by_host["10.0.0.5"].key == "global-fallback"

    def test_render_emits_host_line_with_key(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            radius_servers=[CanonicalRADIUSServer(
                host="10.0.0.4", key="secret123",
            )],
        )
        out = ArubaAOSSCodec().render(intent)
        assert 'radius-server host 10.0.0.4 key "secret123"' in out

    def test_render_omits_key_when_empty(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            radius_servers=[CanonicalRADIUSServer(host="10.0.0.4", key="")],
        )
        out = ArubaAOSSCodec().render(intent)
        # Exact line: "radius-server host 10.0.0.4" with no key suffix.
        assert "radius-server host 10.0.0.4\n" in out

    def test_round_trip(self):
        raw = """\
hostname "sw1"
radius-server host 10.0.0.4 key "secret1"
radius-server host 10.0.0.5 key "secret2"
"""
        c = ArubaAOSSCodec()
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert [(s.host, s.key) for s in first.radius_servers] \
               == [(s.host, s.key) for s in second.radius_servers]


# ---------------------------------------------------------------------------
# OPNsense
# ---------------------------------------------------------------------------


class TestOPNsenseRADIUSParseRender:
    def test_parse_authserver_radius(self):
        raw = """\
<opnsense>
<system>
<authserver>
<name>Corp</name>
<type>radius</type>
<host>10.0.0.4</host>
<radius_secret>secret123</radius_secret>
<radius_auth_port>1812</radius_auth_port>
<radius_acct_port>1813</radius_acct_port>
</authserver>
</system>
</opnsense>
"""
        intent = OPNsenseCodec().parse(raw)
        s = intent.radius_servers[0]
        assert s.host == "10.0.0.4"
        assert s.key == "secret123"
        assert s.auth_port == 1812
        assert s.acct_port == 1813

    def test_non_radius_authserver_ignored(self):
        """<authserver type="ldap"> must not become a RADIUS record."""
        raw = """\
<opnsense>
<system>
<authserver>
<name>LDAP</name>
<type>ldap</type>
<host>ldap.corp.local</host>
</authserver>
</system>
</opnsense>
"""
        intent = OPNsenseCodec().parse(raw)
        assert intent.radius_servers == []

    def test_render_emits_authserver_element(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            radius_servers=[CanonicalRADIUSServer(
                host="10.0.0.4", key="secret123",
            )],
        )
        out = OPNsenseCodec().render(intent)
        assert "<authserver>" in out
        assert "<type>radius</type>" in out
        assert "<host>10.0.0.4</host>" in out
        assert "<radius_secret>secret123</radius_secret>" in out

    def test_round_trip(self):
        raw = """\
<opnsense>
<system>
<authserver>
<name>A</name>
<type>radius</type>
<host>10.0.0.4</host>
<radius_secret>k1</radius_secret>
</authserver>
</system>
</opnsense>
"""
        c = OPNsenseCodec()
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert first.radius_servers[0].host == second.radius_servers[0].host
        assert first.radius_servers[0].key == second.radius_servers[0].key


# ---------------------------------------------------------------------------
# MikroTik RouterOS
# ---------------------------------------------------------------------------


class TestMikroTikRADIUSParseRender:
    def test_parse_radius_section(self):
        raw = """\
/radius
add address=10.0.0.4 secret=shared-secret service=login
add address=10.0.0.5 secret=other-secret authentication-port=1645 service=login
"""
        intent = MikroTikRouterOSCodec().parse(raw)
        assert len(intent.radius_servers) == 2
        by_host = {s.host: s for s in intent.radius_servers}
        assert by_host["10.0.0.4"].key == "shared-secret"
        assert by_host["10.0.0.4"].auth_port == 1812
        assert by_host["10.0.0.5"].auth_port == 1645

    def test_render_emits_radius_section(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            radius_servers=[CanonicalRADIUSServer(
                host="10.0.0.4", key="secret", auth_port=1645,
            )],
        )
        out = MikroTikRouterOSCodec().render(intent)
        assert "/radius" in out
        assert "address=10.0.0.4" in out
        assert "secret=secret" in out
        assert "authentication-port=1645" in out

    def test_round_trip(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            radius_servers=[CanonicalRADIUSServer(
                host="10.0.0.4", key="k1",
            )],
        )
        c = MikroTikRouterOSCodec()
        reparsed = c.parse(c.render(intent))
        assert reparsed.radius_servers[0].host == "10.0.0.4"
        assert reparsed.radius_servers[0].key == "k1"


# ---------------------------------------------------------------------------
# FortiGate
# ---------------------------------------------------------------------------


class TestFortiGateRADIUSParseRender:
    def test_parse_user_radius(self):
        raw = """\
config user radius
    edit "MyRadius"
        set server "10.0.0.4"
        set secret ENC fakeHash==
        set radius-port 1812
    next
end
"""
        intent = FortiGateCLICodec().parse(raw)
        s = intent.radius_servers[0]
        assert s.host == "10.0.0.4"
        assert s.key == "fortios:ENC fakeHash=="

    def test_render_emits_user_radius(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            radius_servers=[CanonicalRADIUSServer(
                host="10.0.0.4",
                key="fortios:ENC abc==",
            )],
        )
        out = FortiGateCLICodec().render(intent)
        assert "config user radius" in out
        assert 'set server "10.0.0.4"' in out
        assert "set secret ENC abc==" in out

    def test_round_trip(self):
        raw = """\
config user radius
    edit "r1"
        set server "10.0.0.4"
        set secret ENC hash==
    next
end
"""
        c = FortiGateCLICodec()
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert first.radius_servers[0].host == second.radius_servers[0].host
        assert first.radius_servers[0].key == second.radius_servers[0].key


# ---------------------------------------------------------------------------
# Cross-codec: Cisco -> OPNsense RADIUS flow
# ---------------------------------------------------------------------------


class TestCiscoToOPNsenseRADIUS:
    def test_cisco_radius_survives_to_opnsense(self):
        raw = """\
radius server Corp
 address ipv4 10.0.0.4 auth-port 1812 acct-port 1813
 key plaintext
!
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        out = OPNsenseCodec().render(intent)
        assert "<authserver>" in out
        assert "<type>radius</type>" in out
        assert "<host>10.0.0.4</host>" in out
