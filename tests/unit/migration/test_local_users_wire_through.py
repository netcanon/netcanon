"""
Unit tests for :class:`CanonicalLocalUser` wire-through across all 5 codecs.
Covers the Tier 2 local_users work from translator-plans.txt.

Structure mirrors test_lag_wire_through.py — one class per codec
covering parse, render (where applicable), round-trip stability.  An
end-to-end cross-codec class covers the canonical-bridge shape.

CRITICAL: No real credentials here.  All hashes in test inputs are
synthetic strings that LOOK like hashes (keep the shape right) but
are not derived from any actual password.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalLocalUser,
)
from netcanon.migration.codecs.aruba_aoss import ArubaAOSSCodec
from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netcanon.migration.codecs.fortigate_cli import FortiGateCLICodec
from netcanon.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netcanon.migration.codecs.opnsense import OPNsenseCodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Cisco IOS-XE CLI (parse-only)
# ---------------------------------------------------------------------------


class TestCiscoLocalUsersParse:
    def test_secret_type_9_priv_15_becomes_admin(self):
        raw = "username admin privilege 15 secret 9 $9$fake$hash\n"
        intent = CiscoIOSXECLICodec().parse(raw)
        assert len(intent.local_users) == 1
        u = intent.local_users[0]
        assert u.name == "admin"
        assert u.privilege_level == 15
        assert u.role == "admin"
        assert u.hashed_password == "9 $9$fake$hash"

    def test_secret_type_5_priv_1_becomes_operator(self):
        raw = "username readonly privilege 1 secret 5 $1$fake$md5hash\n"
        intent = CiscoIOSXECLICodec().parse(raw)
        u = intent.local_users[0]
        assert u.privilege_level == 1
        assert u.role == "operator"

    def test_password_legacy_type_7(self):
        """Legacy ``password 7 <reversible>`` form still parses (and
        ideally triggers a warning downstream — not asserted here)."""
        raw = "username weak password 7 091C08\n"
        intent = CiscoIOSXECLICodec().parse(raw)
        u = intent.local_users[0]
        assert u.name == "weak"
        assert u.hashed_password == "7 091C08"

    def test_missing_privilege_defaults_to_1(self):
        raw = "username nopriv secret 5 $1$fake$hash\n"
        intent = CiscoIOSXECLICodec().parse(raw)
        assert intent.local_users[0].privilege_level == 1

    def test_duplicate_username_lines_dedupe(self):
        """Real Cisco configs can emit multiple lines per user (ssh
        pubkey attach etc.).  First wins."""
        raw = (
            "username admin privilege 15 secret 9 $9$first$hash\n"
            "username admin privilege 15 secret 9 $9$second$hash\n"
        )
        intent = CiscoIOSXECLICodec().parse(raw)
        assert len(intent.local_users) == 1
        assert intent.local_users[0].hashed_password == "9 $9$first$hash"

    def test_case_insensitive(self):
        raw = "USERNAME admin PRIVILEGE 15 SECRET 9 $9$fake$hash\n"
        intent = CiscoIOSXECLICodec().parse(raw)
        assert intent.local_users[0].name == "admin"


# ---------------------------------------------------------------------------
# Aruba AOS-S (parse + render)
# ---------------------------------------------------------------------------


class TestArubaLocalUsersParseRender:
    def test_parse_manager_and_operator(self):
        raw = (
            'hostname "sw1"\n'
            'password manager user-name "admin" sha1 "abc123def456"\n'
            'password operator user-name "viewer" sha1 "fff888ccc"\n'
        )
        intent = ArubaAOSSCodec().parse(raw)
        assert len(intent.local_users) == 2
        by_name = {u.name: u for u in intent.local_users}
        assert by_name["admin"].role == "manager"
        assert by_name["admin"].privilege_level == 15
        assert by_name["admin"].hashed_password == "sha1:abc123def456"
        assert by_name["viewer"].role == "operator"
        assert by_name["viewer"].privilege_level == 1

    def test_render_emits_password_lines(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            local_users=[
                CanonicalLocalUser(
                    name="admin",
                    privilege_level=15,
                    hashed_password="sha1:abc123",
                    role="manager",
                ),
                CanonicalLocalUser(
                    name="viewer",
                    privilege_level=1,
                    hashed_password="sha1:fff888",
                    role="operator",
                ),
            ],
        )
        out = ArubaAOSSCodec().render(intent)
        assert 'password manager user-name "admin" sha1 "abc123"' in out
        assert 'password operator user-name "viewer" sha1 "fff888"' in out

    def test_round_trip(self):
        raw = (
            'hostname "sw1"\n'
            'password manager user-name "admin" sha1 "abc123"\n'
            'password operator user-name "viewer" sha1 "fff888"\n'
        )
        c = ArubaAOSSCodec()
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert [(u.name, u.role, u.privilege_level) for u in first.local_users] \
               == [(u.name, u.role, u.privilege_level) for u in second.local_users]

    def test_unmigratable_hash_emits_comment_review_line(self):
        """AOS-S only accepts plaintext / sha1 / sha256.  Bcrypt
        (OPNsense / FortiGate), sha512 (Arista / Junos $6$), Cisco
        type-5 / type-9 / type-7 etc. cannot be consumed.  Render
        emits a comment-form `; password manager ... -- review:`
        line carrying the source hash format name, so the operator
        gets an explicit reset-this-password reminder rather than
        a `plaintext "bcrypt:..."` line that AOS-S could either
        reject (best case) or accept as a literal plaintext
        password equal to the hash text (severe security bug)."""
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            local_users=[CanonicalLocalUser(
                name="imported",
                privilege_level=15,
                hashed_password="bcrypt:$2y$10$somehash",
            )],
        )
        out = ArubaAOSSCodec().render(intent)
        # Comment marker (leading ";") so the line is inert.
        assert '; password manager user-name "imported"' in out
        # Carries the source-vendor hash algorithm name in the review
        # text so the operator knows what to reset from.
        assert "bcrypt" in out
        assert "review" in out
        # The original hash MUST NOT leak into the rendered config
        # (would-be plaintext security bug).
        assert "$2y$10$somehash" not in out


# ---------------------------------------------------------------------------
# OPNsense (parse + render)
# ---------------------------------------------------------------------------


class TestOPNsenseLocalUsersParseRender:
    def test_parse_admin_and_regular_user(self):
        raw = """\
<opnsense>
<system>
<user>
<name>root</name>
<password>$2y$10$fake</password>
<scope>system</scope>
<groupname>admins</groupname>
</user>
<user>
<name>guest</name>
<password>$2y$10$other</password>
<groupname>users</groupname>
</user>
</system>
</opnsense>
"""
        intent = OPNsenseCodec().parse(raw)
        assert len(intent.local_users) == 2
        by_name = {u.name: u for u in intent.local_users}
        assert by_name["root"].privilege_level == 15
        assert by_name["root"].role == "admin"
        assert by_name["root"].hashed_password == "bcrypt:$2y$10$fake"
        assert by_name["guest"].privilege_level == 1
        assert by_name["guest"].role == "user"

    def test_scope_does_not_determine_privilege(self):
        """<scope>system</scope> is a user-type distinction, not a
        privilege one.  Admin-ness comes ONLY from groupname=admins.
        Surfaced during development: my initial implementation
        treated scope=system as admin, which mis-classified every
        non-admin system user on round-trip."""
        raw = """\
<opnsense>
<system>
<user>
<name>sysuser</name>
<scope>system</scope>
<groupname>users</groupname>
</user>
</system>
</opnsense>
"""
        intent = OPNsenseCodec().parse(raw)
        assert intent.local_users[0].privilege_level == 1
        assert intent.local_users[0].role == "user"

    def test_render_emits_user_elements(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            local_users=[CanonicalLocalUser(
                name="admin",
                privilege_level=15,
                hashed_password="bcrypt:$2y$10$fake",
            )],
        )
        out = OPNsenseCodec().render(intent)
        assert "<user>" in out
        assert "<name>admin</name>" in out
        assert "<password>$2y$10$fake</password>" in out
        assert "<groupname>admins</groupname>" in out

    def test_round_trip(self):
        raw = """\
<opnsense>
<system>
<user><name>root</name><password>$2y$10$x</password><groupname>admins</groupname></user>
<user><name>viewer</name><password>$2y$10$y</password><groupname>users</groupname></user>
</system>
</opnsense>
"""
        c = OPNsenseCodec()
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert [(u.name, u.privilege_level) for u in first.local_users] \
               == [(u.name, u.privilege_level) for u in second.local_users]


# ---------------------------------------------------------------------------
# MikroTik RouterOS (parse + render)
# ---------------------------------------------------------------------------


class TestMikroTikLocalUsersParseRender:
    def test_parse_full_write_read_groups(self):
        raw = """\
/user
add group=full name=admin
add group=write name=netops
add group=read name=viewer
"""
        intent = MikroTikRouterOSCodec().parse(raw)
        by_name = {u.name: u for u in intent.local_users}
        assert by_name["admin"].privilege_level == 15
        assert by_name["netops"].privilege_level == 10
        assert by_name["viewer"].privilege_level == 1

    def test_no_password_hash_in_export(self):
        """RouterOS /export intentionally omits password hashes —
        they live in a separate protected store.  Canonical
        hashed_password must be empty for users from /user section."""
        raw = "/user\nadd group=full name=admin\n"
        intent = MikroTikRouterOSCodec().parse(raw)
        assert intent.local_users[0].hashed_password == ""

    def test_unknown_group_defaults_to_least_privilege(self):
        """Safe-default principle: custom/unknown groups -> 1."""
        raw = "/user\nadd group=custom_readonly name=someuser\n"
        intent = MikroTikRouterOSCodec().parse(raw)
        assert intent.local_users[0].privilege_level == 1

    def test_render_emits_user_section(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            local_users=[
                CanonicalLocalUser(name="admin", privilege_level=15),
                CanonicalLocalUser(name="viewer", privilege_level=1),
            ],
        )
        out = MikroTikRouterOSCodec().render(intent)
        assert "/user" in out
        assert "add group=full name=admin" in out
        assert "add group=read name=viewer" in out

    def test_round_trip(self):
        raw = (
            "/system identity\n"
            "set name=r1\n\n"
            "/user\n"
            "add group=full name=admin\n"
            "add group=read name=viewer\n"
        )
        c = MikroTikRouterOSCodec()
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert [(u.name, u.privilege_level) for u in first.local_users] \
               == [(u.name, u.privilege_level) for u in second.local_users]


# ---------------------------------------------------------------------------
# FortiGate (parse + render)
# ---------------------------------------------------------------------------


class TestFortiGateLocalUsersParseRender:
    def test_super_admin_accprofile_maps_to_priv_15(self):
        raw = """\
config system admin
    edit "admin"
        set password ENC fakeEncodedHash==
        set accprofile "super_admin"
    next
end
"""
        intent = FortiGateCLICodec().parse(raw)
        assert intent.local_users[0].name == "admin"
        assert intent.local_users[0].privilege_level == 15
        assert intent.local_users[0].role == "super_admin"
        assert intent.local_users[0].hashed_password == "fortios:ENC fakeEncodedHash=="

    def test_custom_accprofile_treated_as_non_admin(self):
        raw = """\
config system admin
    edit "auditor"
        set password ENC abc==
        set accprofile "prof_admin"
    next
end
"""
        intent = FortiGateCLICodec().parse(raw)
        assert intent.local_users[0].privilege_level == 1
        assert intent.local_users[0].role == "prof_admin"

    def test_old_password_used_as_fallback(self):
        """Real FortiGate exports sometimes carry `set old-password
        ENC ...` when the current password field isn't exported.
        Use it as the canonical hash so nothing is silently dropped."""
        raw = """\
config system admin
    edit "admin"
        set old-password ENC oldEncodedHash==
        set accprofile "super_admin"
    next
end
"""
        intent = FortiGateCLICodec().parse(raw)
        assert "oldEncodedHash" in intent.local_users[0].hashed_password

    def test_render_emits_admin_block(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            local_users=[CanonicalLocalUser(
                name="admin",
                privilege_level=15,
                hashed_password="fortios:ENC abc==",
                role="super_admin",
            )],
        )
        out = FortiGateCLICodec().render(intent)
        assert "config system admin" in out
        assert 'edit "admin"' in out
        assert "set password ENC abc==" in out
        assert 'set accprofile "super_admin"' in out

    def test_round_trip(self):
        raw = """\
config system admin
    edit "admin"
        set password ENC hash1==
        set accprofile "super_admin"
    next
    edit "auditor"
        set password ENC hash2==
        set accprofile "prof_admin"
    next
end
"""
        c = FortiGateCLICodec()
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert [(u.name, u.privilege_level, u.role) for u in first.local_users] \
               == [(u.name, u.privilege_level, u.role) for u in second.local_users]


# ---------------------------------------------------------------------------
# Cross-codec: Cisco -> Aruba users flow
# ---------------------------------------------------------------------------


class TestCiscoToArubaUsersFlow:
    """A common real scenario: admin exports a Cisco config with
    `username admin secret 9 $9$...`, migrates to an Aruba switch.
    The user identity + privilege should survive; the hash format
    won't (AOS-S expects sha1 or plaintext, not Cisco type-9 scrypt)
    but the line should still render."""

    def test_admin_name_and_privilege_survive_translation(self):
        raw = "hostname sw1\nusername alice privilege 15 secret 9 $9$fake$hash\n"
        intent = CiscoIOSXECLICodec().parse(raw)
        out = ArubaAOSSCodec().render(intent)
        # Name survives.
        assert '"alice"' in out
        # Privilege 15 -> manager role.
        assert "password manager user-name" in out

    def test_operator_privilege_survives(self):
        raw = "hostname sw1\nusername bob privilege 1 secret 5 $1$fake$hash\n"
        intent = CiscoIOSXECLICodec().parse(raw)
        out = ArubaAOSSCodec().render(intent)
        assert '"bob"' in out
        assert "password operator user-name" in out
