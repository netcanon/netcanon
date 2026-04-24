"""
Per-codec SNMPv3 USM user parse + render wire-through tests.

Layer-A coverage: every codec that participates in the SNMPv3
cross-mesh (six out of eight shipped codecs — OPNsense and the
Cisco IOS-XE NETCONF stub declare ``/snmp/v3-user`` as unsupported)
must parse v3 users from its native grammar and emit equivalent
v3 stanzas on render.  Round-trip idempotency is the primary
invariant for bidirectional codecs.

The cross-mesh smoke tests live in
``tests/unit/migration/test_cross_mesh_overrides.py`` under the
``@pytest.mark.cross_mesh`` marker — this file is the Layer-A
per-codec correctness layer for the SNMPv3 surface.

What IS tested here:
    * Parse extracts every declared v3 user with correct auth/priv
      protocol normalisation (aes → aes128, aes 128 → aes128,
      authentication-sha → sha, etc.)
    * Render emits a grammar-compliant v3 stanza for every user.
    * Round-trip (parse → render → parse) is idempotent for every
      bidirectional codec.
    * Parse tolerates noAuthNoPriv / authNoPriv / authPriv modes.

What IS NOT tested here:
    * Cross-vendor key re-encoding (not modelled — keys pass through
      verbatim and operators re-key on the target device).
    * Wire-grammar edge cases with localised / pre-hashed keys
      (``snmp-server user ... v3 localized 0 <hex>`` form is
      out-of-scope for v1 — rendered in plain form after parse).
"""
from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalSNMP,
    CanonicalSNMPv3User,
)
from netconfig.migration.codecs.arista_eos import AristaEOSCodec
from netconfig.migration.codecs.aruba_aoss import ArubaAOSSCodec
from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netconfig.migration.codecs.fortigate_cli import FortiGateCLICodec
from netconfig.migration.codecs.juniper_junos.codec import JunosCodec
from netconfig.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec

pytestmark = pytest.mark.unit


class TestCiscoIOSXECLISNMPv3:
    """Cisco IOS-XE CLI codec — parse_only on v3 users."""

    def test_parses_full_auth_priv_user(self):
        raw = (
            "hostname Test\n!\n"
            "snmp-server user netadmin adminGroup v3 "
            "auth sha SHApass priv aes 128 AESpass\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        assert tree.snmp is not None
        assert len(tree.snmp.v3_users) == 1
        u = tree.snmp.v3_users[0]
        assert u.name == "netadmin"
        assert u.group == "adminGroup"
        assert u.auth_protocol == "sha"
        assert u.auth_passphrase == "SHApass"
        # ``priv aes 128`` Cisco-style two-token form → canonical aes128.
        assert u.priv_protocol == "aes128"
        assert u.priv_passphrase == "AESpass"

    def test_parses_auth_no_priv_user(self):
        raw = (
            "snmp-server user monitor roGroup v3 "
            "auth md5 MDpass\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        u = tree.snmp.v3_users[0]
        assert u.auth_protocol == "md5"
        assert u.priv_protocol == ""

    def test_parses_no_auth_no_priv_user(self):
        raw = "snmp-server user reader roGroup v3\n"
        tree = CiscoIOSXECLICodec().parse(raw)
        u = tree.snmp.v3_users[0]
        assert u.auth_protocol == ""
        assert u.priv_protocol == ""

    def test_multiple_users_parse(self):
        raw = (
            "snmp-server user a g1 v3 auth sha aaa priv aes 128 bbb\n"
            "snmp-server user b g2 v3 auth md5 ccc\n"
            "snmp-server user c g3 v3\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        assert [u.name for u in tree.snmp.v3_users] == ["a", "b", "c"]


class TestAristaEOSSNMPv3:
    """Arista EOS — bidirectional; round-trip invariant applies."""

    def _round_trip(self, raw: str) -> tuple[CanonicalIntent, str, CanonicalIntent]:
        c = AristaEOSCodec()
        tree = c.parse(raw)
        rendered = c.render(tree)
        retree = c.parse(rendered)
        return tree, rendered, retree

    def test_parses_native_single_token_priv(self):
        raw = (
            "hostname TestEOS\n!\n"
            "snmp-server user a g1 v3 auth sha pw1 priv aes pw2\n"
        )
        tree = AristaEOSCodec().parse(raw)
        u = tree.snmp.v3_users[0]
        assert u.priv_protocol == "aes128"      # bare ``aes`` → aes128

    def test_parses_aes256_single_token(self):
        raw = (
            "snmp-server user a g1 v3 auth sha p priv aes256 q\n"
        )
        tree = AristaEOSCodec().parse(raw)
        assert tree.snmp.v3_users[0].priv_protocol == "aes256"

    def test_parses_cisco_pasted_two_token_priv(self):
        """EOS tolerates Cisco-style ``aes 128`` when pasted."""
        raw = (
            "snmp-server user a g1 v3 auth sha p priv aes 128 q\n"
        )
        tree = AristaEOSCodec().parse(raw)
        assert tree.snmp.v3_users[0].priv_protocol == "aes128"

    def test_round_trip_idempotent(self):
        raw = (
            "hostname TestEOS\n!\n"
            "snmp-server user netadmin adminGroup v3 "
            "auth sha SHApass priv aes256 AESpass\n"
            "snmp-server user monitor roGroup v3 auth md5 MDpass\n"
            "snmp-server user reader roGroup v3\n"
        )
        tree, rendered, retree = self._round_trip(raw)
        assert len(tree.snmp.v3_users) == 3
        # Every field survives the round-trip.
        for u1, u2 in zip(tree.snmp.v3_users, retree.snmp.v3_users):
            assert u1.model_dump() == u2.model_dump()


class TestArubaAOSSSNMPv3:
    """Aruba AOS-S — bidirectional.  Grammar has the unusual
    two-line structure: user declaration + separate group binding."""

    def test_parses_user_with_separate_group_binding(self):
        raw = (
            'hostname "AOS"\n'
            'snmpv3 user "netadmin" auth sha "SHApass" priv aes "AESpass"\n'
            'snmpv3 group "AdminGroup" user "netadmin" sec-model ver3\n'
        )
        tree = ArubaAOSSCodec().parse(raw)
        assert len(tree.snmp.v3_users) == 1
        u = tree.snmp.v3_users[0]
        assert u.name == "netadmin"
        assert u.group == "AdminGroup"
        assert u.auth_protocol == "sha"
        assert u.priv_protocol == "aes128"      # bare ``aes`` on AOS-S

    def test_parses_group_bind_before_user(self):
        """Group binding can appear before user declaration —
        merged by name, not position."""
        raw = (
            'hostname "AOS"\n'
            'snmpv3 group "ROGroup" user "monitor" sec-model ver3\n'
            'snmpv3 user "monitor" auth md5 "MDpass"\n'
        )
        tree = ArubaAOSSCodec().parse(raw)
        assert len(tree.snmp.v3_users) == 1     # merged
        u = tree.snmp.v3_users[0]
        assert u.group == "ROGroup"
        assert u.auth_protocol == "md5"

    def test_round_trip_idempotent(self):
        raw = (
            'hostname "AOS"\n'
            'snmpv3 user "a" auth sha "pw1" priv aes "pw2"\n'
            'snmpv3 group "G1" user "a" sec-model ver3\n'
            'snmpv3 user "b"\n'
        )
        c = ArubaAOSSCodec()
        tree = c.parse(raw)
        retree = c.parse(c.render(tree))
        assert len(retree.snmp.v3_users) == 2
        by_name = {u.name: u for u in retree.snmp.v3_users}
        assert by_name["a"].group == "G1"
        assert by_name["a"].priv_protocol == "aes128"
        assert by_name["b"].auth_protocol == ""


class TestJuniperJunosSNMPv3:
    """Juniper Junos — bidirectional.  Grammar splits USM + VACM
    across multiple set-lines that merge by user name."""

    def test_parses_multi_line_v3_user(self):
        raw = (
            "set system host-name fw1\n"
            "set snmp v3 usm local-engine user netadmin "
            'authentication-sha authentication-key "sha_hash"\n'
            "set snmp v3 usm local-engine user netadmin "
            'privacy-aes128 privacy-key "aes_hash"\n'
            "set snmp v3 vacm security-to-group security-model usm "
            "security-name netadmin group Admins\n"
        )
        tree = JunosCodec().parse(raw)
        assert len(tree.snmp.v3_users) == 1
        u = tree.snmp.v3_users[0]
        assert u.name == "netadmin"
        assert u.group == "Admins"
        assert u.auth_protocol == "sha"
        assert u.auth_passphrase == "sha_hash"
        assert u.priv_protocol == "aes128"
        assert u.priv_passphrase == "aes_hash"

    def test_parses_user_without_privacy(self):
        raw = (
            "set snmp v3 usm local-engine user monitor "
            'authentication-md5 authentication-key "md5_pass"\n'
        )
        tree = JunosCodec().parse(raw)
        u = tree.snmp.v3_users[0]
        assert u.auth_protocol == "md5"
        assert u.priv_protocol == ""

    def test_round_trip_idempotent(self):
        raw = (
            "set system host-name fw1\n"
            "set snmp v3 usm local-engine user a "
            'authentication-sha authentication-key "h1"\n'
            "set snmp v3 usm local-engine user a "
            'privacy-aes128 privacy-key "h2"\n'
            "set snmp v3 vacm security-to-group security-model usm "
            "security-name a group G1\n"
            "set snmp v3 usm local-engine user b "
            'authentication-md5 authentication-key "h3"\n'
            "set snmp v3 vacm security-to-group security-model usm "
            "security-name b group G2\n"
        )
        c = JunosCodec()
        tree = c.parse(raw)
        retree = c.parse(c.render(tree))
        assert len(retree.snmp.v3_users) == 2
        by_name = {u.name: u for u in retree.snmp.v3_users}
        assert by_name["a"].model_dump() == {
            "name": "a", "group": "G1", "auth_protocol": "sha",
            "auth_passphrase": "h1", "priv_protocol": "aes128",
            "priv_passphrase": "h2", "engine_id": "",
        }
        assert by_name["b"].model_dump() == {
            "name": "b", "group": "G2", "auth_protocol": "md5",
            "auth_passphrase": "h3", "priv_protocol": "",
            "priv_passphrase": "", "engine_id": "",
        }


class TestFortiGateCLISNMPv3:
    """FortiGate CLI — bidirectional.  Grammar uses nested
    ``config system snmp user / edit <name>`` blocks with
    ``auth-proto`` / ``auth-pwd`` + ``priv-proto`` / ``priv-pwd``."""

    def test_parses_auth_priv_user(self):
        raw = (
            '#config-version=FG100E-7.2.0:opmode=1\n'
            "config system global\n"
            '    set hostname "fg1"\n'
            "end\n"
            "config system snmp user\n"
            '    edit "netadmin"\n'
            "        set security-level auth-priv\n"
            "        set auth-proto sha256\n"
            "        set auth-pwd ENC someSHAhash==\n"
            "        set priv-proto aes256\n"
            "        set priv-pwd ENC someAEShash==\n"
            "    next\n"
            "end\n"
        )
        tree = FortiGateCLICodec().parse(raw)
        assert tree.snmp is not None
        u = tree.snmp.v3_users[0]
        assert u.name == "netadmin"
        assert u.auth_protocol == "sha256"
        assert u.priv_protocol == "aes256"
        # ENC prefix joined into the passphrase verbatim.
        assert u.auth_passphrase == "ENC someSHAhash=="
        assert u.priv_passphrase == "ENC someAEShash=="

    def test_parses_auth_no_priv_user(self):
        raw = (
            "config system snmp user\n"
            '    edit "monitor"\n'
            "        set security-level auth-no-priv\n"
            "        set auth-proto sha\n"
            "        set auth-pwd ENC md5hash==\n"
            "    next\n"
            "end\n"
        )
        tree = FortiGateCLICodec().parse(raw)
        u = tree.snmp.v3_users[0]
        assert u.priv_protocol == ""

    def test_round_trip_idempotent(self):
        raw = (
            "config system snmp user\n"
            '    edit "a"\n'
            "        set security-level auth-priv\n"
            "        set auth-proto sha256\n"
            "        set auth-pwd ENC h1==\n"
            "        set priv-proto aes256\n"
            "        set priv-pwd ENC h2==\n"
            "    next\n"
            "end\n"
        )
        c = FortiGateCLICodec()
        tree = c.parse(raw)
        retree = c.parse(c.render(tree))
        assert tree.snmp.v3_users == retree.snmp.v3_users


class TestMikroTikRouterOSSNMPv3:
    """MikroTik RouterOS — bidirectional.  Grammar overloads the
    ``/snmp community`` section for both v1/v2c communities and
    v3 USM users, disambiguated by presence of
    ``authentication-protocol=``."""

    def test_parses_v3_user_in_snmp_community_section(self):
        raw = (
            "# 2026-01-01 by RouterOS 7.18\n"
            "/snmp\n"
            "set enabled=yes\n"
            "/snmp community\n"
            'add name=netadmin authentication-protocol=SHA1 '
            'authentication-password="SHApass" '
            'encryption-protocol=aes-256-cfb '
            'encryption-password="AESpass"\n'
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        u = tree.snmp.v3_users[0]
        assert u.name == "netadmin"
        assert u.auth_protocol == "sha"         # SHA1 → canonical sha
        assert u.priv_protocol == "aes256"

    def test_v2c_community_and_v3_user_coexist(self):
        """``set [ find default=yes ] name=X`` is v2c; the ``add name=Y
        authentication-protocol=...`` line is v3.  Both populate the
        canonical tree without stepping on each other."""
        raw = (
            "/snmp community\n"
            "set [ find default=yes ] name=public\n"
            'add name=netadmin authentication-protocol=SHA1 '
            'authentication-password="pw1"\n'
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.snmp.community == "public"
        assert len(tree.snmp.v3_users) == 1
        assert tree.snmp.v3_users[0].name == "netadmin"

    def test_round_trip_idempotent(self):
        raw = (
            "/snmp\n"
            "set enabled=yes\n"
            "/snmp community\n"
            "set [ find default=yes ] name=public\n"
            'add name=a authentication-protocol=SHA1 '
            'authentication-password="p1" '
            'encryption-protocol=aes-128-cfb '
            'encryption-password="p2"\n'
            'add name=b authentication-protocol=MD5 '
            'authentication-password="p3"\n'
        )
        c = MikroTikRouterOSCodec()
        tree = c.parse(raw)
        retree = c.parse(c.render(tree))
        assert tree.snmp.community == retree.snmp.community
        assert tree.snmp.v3_users == retree.snmp.v3_users


class TestCrossVendorSNMPv3Render:
    """Build a canonical tree with v3 users + render on every
    bidirectional codec.  Doesn't assert byte-equality (grammar
    differs wildly) — just that no codec crashes and the rendered
    output contains the user's name."""

    @pytest.fixture
    def intent_with_v3(self) -> CanonicalIntent:
        intent = CanonicalIntent()
        intent.snmp = CanonicalSNMP()
        intent.snmp.v3_users.append(CanonicalSNMPv3User(
            name="netadmin",
            group="AdminGrp",
            auth_protocol="sha",
            auth_passphrase="authhash",
            priv_protocol="aes128",
            priv_passphrase="privhash",
        ))
        return intent

    @pytest.mark.parametrize("codec_cls", [
        AristaEOSCodec,
        ArubaAOSSCodec,
        JunosCodec,
        FortiGateCLICodec,
        MikroTikRouterOSCodec,
    ])
    def test_render_every_bidir_codec_emits_v3_user(
        self, intent_with_v3: CanonicalIntent, codec_cls: type,
    ):
        c = codec_cls()
        rendered = c.render(intent_with_v3)
        assert "netadmin" in rendered, (
            f"{codec_cls.__name__} render dropped v3 user name"
        )
