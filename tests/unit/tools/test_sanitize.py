"""Unit tests for ``netcanon.tools.sanitize``.

Covers:

1. The pure :func:`sanitize_intent` walk against synthetic
   :class:`CanonicalIntent` instances — every category of redaction.
2. The end-to-end :func:`sanitize_text` against real-capture fixtures —
   parse + sanitize + render all wire correctly through the codec
   registry.
3. Counter-per-session stability — same input always maps to same
   output across the whole config.
4. Format-preserving hash redaction across the major hash prefixes
   (Junos $9$, crypt $5$/$6$, bcrypt $2y$, FortiGate ENC, Cisco
   type-7, Aruba SHA-1).
5. ``--dry-run`` semantics — substitutions populated, sanitized_text
   empty.
6. Round-trip property: parsing the sanitized output yields a
   CanonicalIntent with no real-IP / hash / secret strings remaining.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalEvpnType5Route,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalLocalUser,
    CanonicalRADIUSServer,
    CanonicalRoutingInstance,
    CanonicalSNMP,
    CanonicalSNMPv3User,
    CanonicalStaticRoute,
    CanonicalVlan,
    CanonicalVRRPGroup,
    CanonicalVxlan,
)
from netcanon.migration.codecs.base import ParseError
from netcanon.tools.sanitize import (
    SanitizationResult,
    Substitution,
    _SubstitutionTable,
    sanitize_intent,
    sanitize_text,
)
from tests.support.canonical_reflection import (
    flatten_annotation as _flatten_annotation,
)
from tests.support.canonical_reflection import (
    reachable_models as _reachable_canonical_models,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Field-typed redactions on synthetic CanonicalIntent
# ---------------------------------------------------------------------------


class TestHostnameRedaction:
    def test_hostname_redacted_to_device_n(self):
        intent = CanonicalIntent(hostname="my-real-router")
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.hostname == "device-1"
        assert any(
            s.category == "hostname" and s.original == "my-real-router"
            for s in subs
        )

    def test_empty_hostname_no_substitution(self):
        intent = CanonicalIntent(hostname="")
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.hostname == ""
        assert not any(s.category == "hostname" for s in subs)


class TestDomainRedaction:
    def test_domain_redacted(self):
        intent = CanonicalIntent(domain="company-internal.lan")
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.domain == "example-1.test"
        assert any(s.category == "domain" for s in subs)


class TestIPv4Redaction:
    def test_public_ipv4_redacted_to_docs_range(self):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="ge-0/0/0",
                    ipv4_addresses=[CanonicalIPv4Address(ip="8.8.8.8", prefix_length=32)],
                )
            ]
        )
        sanitized, subs = sanitize_intent(intent)
        new_ip = sanitized.interfaces[0].ipv4_addresses[0].ip
        # Should be replaced with a docs-range IP
        assert new_ip != "8.8.8.8"
        assert new_ip.startswith(("192.0.2.", "198.51.100.", "203.0.113."))

    def test_rfc1918_preserved(self):
        for private in ("10.0.0.1", "172.16.0.1", "192.168.1.1"):
            intent = CanonicalIntent(
                interfaces=[
                    CanonicalInterface(
                        name="x",
                        ipv4_addresses=[CanonicalIPv4Address(ip=private, prefix_length=24)],
                    )
                ]
            )
            sanitized, _ = sanitize_intent(intent)
            assert sanitized.interfaces[0].ipv4_addresses[0].ip == private

    def test_loopback_preserved(self):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="lo",
                    ipv4_addresses=[CanonicalIPv4Address(ip="127.0.0.1", prefix_length=32)],
                )
            ]
        )
        sanitized, _ = sanitize_intent(intent)
        assert sanitized.interfaces[0].ipv4_addresses[0].ip == "127.0.0.1"

    def test_already_in_docs_range_preserved(self):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="x",
                    ipv4_addresses=[CanonicalIPv4Address(ip="192.0.2.50", prefix_length=32)],
                )
            ]
        )
        sanitized, _ = sanitize_intent(intent)
        assert sanitized.interfaces[0].ipv4_addresses[0].ip == "192.0.2.50"

    def test_cgnat_preserved(self):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="x",
                    ipv4_addresses=[CanonicalIPv4Address(ip="100.64.5.1", prefix_length=32)],
                )
            ]
        )
        sanitized, _ = sanitize_intent(intent)
        assert sanitized.interfaces[0].ipv4_addresses[0].ip == "100.64.5.1"

    def test_dns_servers_public_redacted_private_preserved(self):
        intent = CanonicalIntent(
            dns_servers=["8.8.8.8", "192.168.1.1", "1.1.1.1"],
        )
        sanitized, subs = sanitize_intent(intent)
        # Public ones got redacted
        assert sanitized.dns_servers[0] != "8.8.8.8"
        assert sanitized.dns_servers[2] != "1.1.1.1"
        # Private one preserved
        assert sanitized.dns_servers[1] == "192.168.1.1"
        # Two substitutions logged
        ipv4_subs = [s for s in subs if s.category == "ipv4-public"]
        assert len(ipv4_subs) == 2


class TestInterfaceDescriptionRedaction:
    def test_description_replaced(self):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="ge-0/0/0", description="Uplink to ISP-PRD")
            ]
        )
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.interfaces[0].description == "description redacted"
        assert any(
            s.category == "interface-description"
            and s.original == "Uplink to ISP-PRD"
            for s in subs
        )

    def test_empty_description_no_substitution(self):
        intent = CanonicalIntent(
            interfaces=[CanonicalInterface(name="ge-0/0/0", description="")]
        )
        sanitized, subs = sanitize_intent(intent)
        assert not any(s.category == "interface-description" for s in subs)


class TestLocalUserHashRedaction:
    def test_junos_dollar9_format_preserved(self):
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(name="admin", hashed_password="$9$realJunosHashHere")
            ]
        )
        sanitized, _ = sanitize_intent(intent)
        # Format prefix preserved
        assert sanitized.local_users[0].hashed_password.startswith("$9$")

    def test_crypt_dollar5_format_preserved(self):
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(name="admin", hashed_password="$5$salt$hash")
            ]
        )
        sanitized, _ = sanitize_intent(intent)
        assert sanitized.local_users[0].hashed_password.startswith("$5$")

    def test_bcrypt_format_preserved(self):
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(
                    name="admin",
                    hashed_password="$2y$11$abcdefghijklmnopqrstuv",
                )
            ]
        )
        sanitized, _ = sanitize_intent(intent)
        assert sanitized.local_users[0].hashed_password.startswith("$2y$11$")

    def test_fortigate_enc_format_preserved(self):
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(name="admin", hashed_password="ENC realFortiHashB64==")
            ]
        )
        sanitized, _ = sanitize_intent(intent)
        assert sanitized.local_users[0].hashed_password.startswith("ENC ")


class TestLocalUserNameRedaction:
    """Phase-3 Round-6.1 — username redaction with iterative
    per-class numbering and cross-reference stability.

    Operator-chosen usernames (`alice`, `john.smith`, the Windows-
    login-mirror case `user12`) are operator-PII when shared in
    public bug reports — leaking them enables correlation attacks.
    The hashed-password redaction alone wasn't enough.
    """

    def test_single_user_name_redacted_to_localuser1(self):
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(name="alice", hashed_password="$9$realHash"),
            ]
        )
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.local_users[0].name == "localuser1"
        assert any(
            s.category == "local-user-name" and s.original == "alice"
            and s.redacted == "localuser1"
            for s in subs
        )

    def test_multiple_users_iteratively_numbered(self):
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(name="alice"),
                CanonicalLocalUser(name="bob"),
                CanonicalLocalUser(name="charlie"),
            ]
        )
        sanitized, _ = sanitize_intent(intent)
        assert sanitized.local_users[0].name == "localuser1"
        assert sanitized.local_users[1].name == "localuser2"
        assert sanitized.local_users[2].name == "localuser3"

    def test_duplicate_input_names_collapse_to_same_placeholder(self):
        """Cross-reference stability: same input → same output across
        the whole config so any reference to the user from another
        stanza (AAA, sudo, role assignment) resolves to the same
        placeholder.  Test exercises the dict-keyed cache."""
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(name="alice"),
                CanonicalLocalUser(name="alice"),  # duplicate (rare but legal)
                CanonicalLocalUser(name="bob"),
            ]
        )
        sanitized, _ = sanitize_intent(intent)
        assert sanitized.local_users[0].name == "localuser1"
        assert sanitized.local_users[1].name == "localuser1"  # same placeholder
        assert sanitized.local_users[2].name == "localuser2"  # next number

    def test_empty_name_not_redacted(self):
        """Pydantic allows empty name (= field never set); don't
        produce a substitution row for the no-op."""
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(name="", hashed_password="$9$h"),
            ]
        )
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.local_users[0].name == ""
        assert not any(s.category == "local-user-name" for s in subs)

    def test_name_and_hash_substitutions_independent(self):
        """The local-user-name and local-user-hash entries are
        emitted independently — operator can see both in the audit."""
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(name="user12", hashed_password="$9$realHash"),
            ]
        )
        _, subs = sanitize_intent(intent)
        cats = {s.category for s in subs}
        assert "local-user-name" in cats
        assert "local-user-hash" in cats


class TestSNMPv3UserNameRedaction:
    """Phase-3 Round-6.1 — SNMPv3 USM securityName redaction with
    iterative per-class numbering, independent counter from
    local-user-name (so a config with 1 local user + 1 v3 user
    produces ``localuser1`` and ``snmpv3user1``, NOT ``localuser1``
    and ``snmpv3user2``)."""

    def test_v3_user_name_redacted_to_snmpv3user1(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(
                community="",
                v3_users=[CanonicalSNMPv3User(name="ops")],
            )
        )
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.snmp.v3_users[0].name == "snmpv3user1"
        assert any(
            s.category == "snmpv3-user-name" and s.original == "ops"
            for s in subs
        )

    def test_multiple_v3_users_iteratively_numbered(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(
                community="",
                v3_users=[
                    CanonicalSNMPv3User(name="alice"),
                    CanonicalSNMPv3User(name="bob"),
                ],
            )
        )
        sanitized, _ = sanitize_intent(intent)
        assert sanitized.snmp.v3_users[0].name == "snmpv3user1"
        assert sanitized.snmp.v3_users[1].name == "snmpv3user2"

    def test_per_class_counters_are_independent(self):
        """A config with 1 local user + 1 v3 user must produce
        ``localuser1`` + ``snmpv3user1`` (each starts at 1) — NOT a
        session-wide counter that would have given ``snmpv3user2``."""
        intent = CanonicalIntent(
            local_users=[CanonicalLocalUser(name="root")],
            snmp=CanonicalSNMP(
                community="",
                v3_users=[CanonicalSNMPv3User(name="monitor")],
            ),
        )
        sanitized, _ = sanitize_intent(intent)
        assert sanitized.local_users[0].name == "localuser1"
        assert sanitized.snmp.v3_users[0].name == "snmpv3user1"


class TestSNMPRedaction:
    def test_community_redacted(self):
        intent = CanonicalIntent(snmp=CanonicalSNMP(community="SuperSecret"))
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.snmp.community == "public_redacted_1"
        assert any(s.category == "snmp-community" for s in subs)

    def test_v3_passphrases_redacted(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(
                community="",
                v3_users=[
                    CanonicalSNMPv3User(
                        name="ops",
                        auth_protocol="sha",
                        priv_protocol="aes",
                        auth_passphrase="real-auth-passphrase-here",
                        priv_passphrase="real-priv-passphrase-here",
                    )
                ],
            )
        )
        sanitized, subs = sanitize_intent(intent)
        v3 = sanitized.snmp.v3_users[0]
        assert v3.auth_passphrase == "REDACTED-AUTH-1"
        assert v3.priv_passphrase == "REDACTED-PRIV-1"


class TestRADIUSRedaction:
    def test_shared_secret_redacted(self):
        intent = CanonicalIntent(
            radius_servers=[
                CanonicalRADIUSServer(
                    host="10.0.0.5",
                    key="my-real-radius-secret",
                )
            ]
        )
        sanitized, subs = sanitize_intent(intent)
        # Canonical field name is ``key`` (RADIUS shared secret)
        assert sanitized.radius_servers[0].key == "REDACTED-RADIUS-1"


class TestVRRPAuthenticationRedaction:
    """Regression guard for the VRRP/CARP auth secret-leak (project
    review 2026-06-06, finding R-01 / CF-01).

    ``vrrp_groups[].authentication`` is cleartext-bearing: ``plain:``
    and ``carp-key:`` hold the literal secret and the renderers emit it
    back verbatim.  The sanitiser must replace the secret value while
    preserving the ``<scheme>:`` prefix (each renderer slices a
    scheme-width prefix and branches on ``startswith`` — the prefix
    must survive or render output becomes malformed).
    """

    @staticmethod
    def _iface_with_auth(auth: str) -> CanonicalIntent:
        return CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="Vlan10",
                    vrrp_groups=[
                        CanonicalVRRPGroup(group_id=10, authentication=auth)
                    ],
                )
            ]
        )

    def test_plain_scheme_value_redacted_prefix_preserved(self):
        sanitized, subs = sanitize_intent(self._iface_with_auth("plain:SuperSecret123"))
        out = sanitized.interfaces[0].vrrp_groups[0].authentication
        assert out.startswith("plain:")          # scheme survives for the renderer
        assert "SuperSecret123" not in out         # secret value gone
        assert out == "plain:REDACTED-VRRP-AUTH-1"
        assert any(
            s.category == "vrrp-authentication"
            and s.original == "plain:SuperSecret123"
            for s in subs
        )

    def test_carp_key_scheme_value_redacted_prefix_preserved(self):
        sanitized, _ = sanitize_intent(self._iface_with_auth("carp-key:b1nary-CARP-pw"))
        out = sanitized.interfaces[0].vrrp_groups[0].authentication
        assert out.startswith("carp-key:")
        assert "b1nary-CARP-pw" not in out
        assert out == "carp-key:REDACTED-VRRP-AUTH-1"

    def test_md5_scheme_value_redacted_prefix_preserved(self):
        sanitized, _ = sanitize_intent(self._iface_with_auth("md5:keystring-or-hash"))
        out = sanitized.interfaces[0].vrrp_groups[0].authentication
        assert out.startswith("md5:")
        assert "keystring-or-hash" not in out

    def test_empty_authentication_no_substitution(self):
        sanitized, subs = sanitize_intent(self._iface_with_auth(""))
        assert sanitized.interfaces[0].vrrp_groups[0].authentication == ""
        assert not any(s.category == "vrrp-authentication" for s in subs)

    def test_multiple_groups_each_redacted(self):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="Vlan10",
                    vrrp_groups=[
                        CanonicalVRRPGroup(group_id=10, authentication="plain:secret-a"),
                        CanonicalVRRPGroup(group_id=20, authentication="plain:secret-b"),
                    ],
                )
            ]
        )
        sanitized, subs = sanitize_intent(intent)
        joined = "".join(g.authentication for g in sanitized.interfaces[0].vrrp_groups)
        assert "secret-a" not in joined
        assert "secret-b" not in joined
        assert len([s for s in subs if s.category == "vrrp-authentication"]) == 2

    def test_rendered_output_omits_secret(self):
        """The real attack scenario: sanitize_intent → render must not
        emit the cleartext secret.  Exercises the cisco_iosxe_cli render
        path that previously leaked it (`authentication text <secret>`)."""
        from netcanon.migration.codecs.registry import get_codec

        intent = CanonicalIntent(
            hostname="r1",
            interfaces=[
                CanonicalInterface(
                    name="Vlan10",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="192.168.1.2", prefix_length=24)
                    ],
                    vrrp_groups=[
                        CanonicalVRRPGroup(
                            group_id=10,
                            virtual_ips=["192.168.1.254"],
                            authentication="plain:MyVrrpSecret",
                        )
                    ],
                )
            ],
        )
        sanitized, _ = sanitize_intent(intent)
        rendered = get_codec("cisco_iosxe_cli").render(sanitized)
        assert "MyVrrpSecret" not in rendered          # the leak is closed
        assert "REDACTED-VRRP-AUTH-1" in rendered        # render path was exercised


class TestStaticRouteRedaction:
    def test_public_gateway_redacted_private_preserved(self):
        intent = CanonicalIntent(
            static_routes=[
                CanonicalStaticRoute(destination="0.0.0.0/0", gateway="8.8.8.8"),
                CanonicalStaticRoute(destination="10.0.0.0/8", gateway="192.168.1.1"),
            ]
        )
        sanitized, _ = sanitize_intent(intent)
        # Public gateway redacted
        assert sanitized.static_routes[0].gateway != "8.8.8.8"
        # Private gateway preserved
        assert sanitized.static_routes[1].gateway == "192.168.1.1"

    def test_public_destination_redacted_prefix_preserved(self):
        """A public destination CIDR (a route to a provider / peer block) is
        redacted to a docs range with its prefix length preserved; the
        default route and private aggregates are preserved (audit 65f9c01 #20)."""
        intent = CanonicalIntent(
            static_routes=[
                # 44.21.0.0/16 is clearly public (44/8 is allocated + routable,
                # and NOT one of the RFC 5737 docs ranges the redactor skips).
                CanonicalStaticRoute(destination="44.21.0.0/16", gateway="44.21.0.1"),
                # default route — 0.0.0.0 is unspecified, left as-is.
                CanonicalStaticRoute(destination="0.0.0.0/0", gateway="192.0.2.1"),
                # private aggregate preserved (the common LAN case).
                CanonicalStaticRoute(destination="10.20.0.0/16", gateway="10.0.0.1"),
            ]
        )
        sanitized, subs = sanitize_intent(intent)
        public_dest = sanitized.static_routes[0].destination
        assert public_dest != "44.21.0.0/16"      # public dest redacted
        assert public_dest.endswith("/16")         # prefix length preserved
        assert sanitized.static_routes[1].destination == "0.0.0.0/0"
        assert sanitized.static_routes[2].destination == "10.20.0.0/16"
        assert any(
            s.field == "static_routes[0].destination" for s in subs
        ), "destination redaction must be recorded in the substitution log"


class TestDnsNameHostFieldRedaction:
    """DNS-name host fields (NTP / syslog / SNMP-trap / RADIUS targets) must
    not re-leak the org domain (audit 65f9c01 #20)."""

    def test_fqdn_maps_to_stable_opaque_placeholder(self):
        table = _SubstitutionTable()
        out = table.redact_host("syslog.corp.example.com")
        assert out == "host-1.example.test"
        assert "corp.example.com" not in out and "example.com" not in out
        # stable: same FQDN -> same placeholder (cross-reference survives)
        assert table.redact_host("syslog.corp.example.com") == "host-1.example.test"
        # distinct FQDN -> distinct placeholder
        assert table.redact_host("ntp.corp.example.com") == "host-2.example.test"

    def test_two_label_org_domain_not_leaked_in_first_label(self):
        """The org name lives in the FIRST label of a bare registered domain
        (``acmecorp.com``); preserving the first label would leak it, so the
        whole name is replaced."""
        out = _SubstitutionTable().redact_host("acmecorp.com")
        assert "acmecorp" not in out
        assert out == "host-1.example.test"

    def test_ip_behaviour_unchanged(self):
        table = _SubstitutionTable()
        # public IP -> docs range (as before)
        assert table.redact_host("8.8.8.8").startswith(
            ("192.0.2.", "198.51.100.", "203.0.113.")
        )
        # private IP preserved
        assert table.redact_host("10.0.0.5") == "10.0.0.5"

    def test_bare_single_label_preserved(self):
        table = _SubstitutionTable()
        assert table.redact_host("localhost") == "localhost"
        assert table.redact_host("nms") == "nms"

    def test_trailing_dot_fqdn_redacted(self):
        """A rooted FQDN with a trailing dot (``nms.corp.example.``) is still
        an org-domain leak and must be redacted, not passed through verbatim
        (audit e5b77d7 #12)."""
        out = _SubstitutionTable().redact_host("nms.corp.example.")
        assert out == "host-1.example.test"
        assert "corp" not in out

    def test_underscore_label_fqdn_redacted(self):
        """A host label containing an underscore (``srv_01.corp.example`` —
        common in AD / SRV / operator-named hosts) must be redacted, not
        leaked (audit e5b77d7 #12)."""
        out = _SubstitutionTable().redact_host("srv_01.corp.example")
        assert out == "host-1.example.test"
        assert "srv_01" not in out and "corp" not in out

    def test_bare_underscore_label_preserved(self):
        """A bare single label with an underscore but no dot has no domain to
        leak — the widened FQDN regex must not over-match it."""
        assert _SubstitutionTable().redact_host("srv_01") == "srv_01"

    def test_fqdn_servers_redacted_through_sanitize_intent(self):
        intent = CanonicalIntent(
            ntp_servers=["ntp.corp.example.com", "10.0.0.1"],
            syslog_servers=["logs.corp.example.com"],
            snmp=CanonicalSNMP(trap_hosts=["nms.corp.example.com"]),
            radius_servers=[
                CanonicalRADIUSServer(
                    host="radius.corp.example.com", key="s3cret"
                )
            ],
        )
        sanitized, _ = sanitize_intent(intent)
        # The org domain must not survive in ANY host field.
        assert all("corp.example.com" not in h for h in sanitized.ntp_servers)
        assert all("corp.example.com" not in h for h in sanitized.syslog_servers)
        assert all(
            "corp.example.com" not in h for h in sanitized.snmp.trap_hosts
        )
        assert "corp.example.com" not in sanitized.radius_servers[0].host
        # FQDN entry became a host placeholder; the private IP is preserved.
        assert sanitized.ntp_servers[0].endswith(".example.test")
        assert sanitized.ntp_servers[1] == "10.0.0.1"


class TestTier3Stripped:
    def test_dropped_tier3_sections_emptied(self):
        intent = CanonicalIntent(
            dropped_tier3_sections=["firewall-policy: 47 lines", "vpn ipsec: 22 lines"]
        )
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.dropped_tier3_sections == []
        assert any(s.category == "tier3-stripped" for s in subs)


# ---------------------------------------------------------------------------
# Counter-per-session stability — same input → same output
# ---------------------------------------------------------------------------


class TestCounterStability:
    def test_same_hostname_used_twice_gets_same_redaction(self):
        # Note: there's only ONE hostname field on CanonicalIntent.
        # The cross-reference stability test goes via _SubstitutionTable directly.
        table = _SubstitutionTable()
        first = table.redact_hostname("rtr-edge-01")
        second = table.redact_hostname("rtr-edge-01")
        assert first == second

    def test_distinct_hostnames_get_distinct_redactions(self):
        table = _SubstitutionTable()
        a = table.redact_hostname("rtr-a")
        b = table.redact_hostname("rtr-b")
        assert a != b
        assert a == "device-1"
        assert b == "device-2"

    def test_same_public_ip_referenced_twice_same_redaction(self):
        intent = CanonicalIntent(
            dns_servers=["8.8.8.8"],
            ntp_servers=["8.8.8.8"],
        )
        sanitized, _ = sanitize_intent(intent)
        # Both got the same docs-range substitute
        assert sanitized.dns_servers[0] == sanitized.ntp_servers[0]


# ---------------------------------------------------------------------------
# sanitize_intent purity — original is not mutated
# ---------------------------------------------------------------------------


class TestSanitizePurity:
    def test_input_intent_not_mutated(self):
        intent = CanonicalIntent(hostname="real-router")
        _, _ = sanitize_intent(intent)
        # Original intent is untouched
        assert intent.hostname == "real-router"


# ---------------------------------------------------------------------------
# sanitize_text — end-to-end against real-capture fixtures
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[3]
ARUBA_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "real" / "aruba_aoss"
    / "hpe_community_2920_wb1608_dhcp_snooping.cfg"
)


class TestSanitizeTextEndToEnd:
    def test_aruba_real_capture_round_trips(self):
        raw = ARUBA_FIXTURE.read_text(encoding="utf-8")
        result = sanitize_text(raw, "aruba_aoss")
        assert result.sanitized_text  # non-empty render
        assert len(result.substitutions) > 0  # at least one redaction

    def test_aruba_dry_run_returns_audit_no_render(self):
        raw = ARUBA_FIXTURE.read_text(encoding="utf-8")
        result = sanitize_text(raw, "aruba_aoss", dry_run=True)
        assert result.sanitized_text == ""
        assert len(result.substitutions) > 0

    def test_unknown_codec_raises(self):
        with pytest.raises(ValueError, match="[Uu]nknown source codec"):
            sanitize_text("", "no_such_codec")

    def test_out_of_range_input_raises_parse_error_not_validation_error(self):
        # An NX-OS HSRP group-id of 301 exceeds the VRRP 0-255 range that
        # CanonicalVRRPGroup.group_id enforces, so parse constructs an
        # invalid model and pydantic raises ValidationError.  sanitize_text
        # must convert that to a ParseError (contract) so the HTTP route
        # returns a clean 400 rather than leaking a 500.  (Surfaced by the
        # live /sanitize dogfood on a real NX-OS capture.)
        raw = (
            "feature hsrp\n"
            "interface Vlan10\n"
            "  no shutdown\n"
            "  ip address 10.0.0.2/24\n"
            "  hsrp 301\n"
            "    ip 10.0.0.1\n"
        )
        with pytest.raises(ParseError, match="could not be represented"):
            sanitize_text(raw, "cisco_nxos")


# ---------------------------------------------------------------------------
# Sanitization result contract
# ---------------------------------------------------------------------------


class TestResultContract:
    def test_substitution_dataclass_fields(self):
        s = Substitution(
            category="hostname",
            field="hostname",
            original="real",
            redacted="device-1",
        )
        assert s.category == "hostname"
        assert s.original == "real"

    def test_result_default_substitutions_empty(self):
        r = SanitizationResult(sanitized_text="x")
        assert r.substitutions == []


# ---------------------------------------------------------------------------
# Structural guard — every secret-bearing canonical field is redacted
#
# Turns the documented invariant ("the sanitiser redacts every secret")
# into a mechanical, two-sided check (mirrors the ``_WIRED_UP_BY_CODEC``
# matrix-honesty pattern).  Recommended by the 2026-06-06 project review
# as the durable fix for the CF-01 class: a future secret field cannot
# be added to the canonical model without either a redaction rule or a
# conscious update here.
# ---------------------------------------------------------------------------


# (ClassName, field_name) for every canonical field that carries a
# secret/credential and MUST be redacted by ``sanitize_intent``.  Keep
# in lockstep with the sanitiser — both directions are enforced below.
_REGISTERED_SECRET_FIELDS = {
    ("CanonicalLocalUser", "hashed_password"),
    ("CanonicalSNMP", "community"),
    ("CanonicalSNMPv3User", "auth_passphrase"),
    ("CanonicalSNMPv3User", "priv_passphrase"),
    ("CanonicalRADIUSServer", "key"),
    ("CanonicalVRRPGroup", "authentication"),
}

# A field name that looks like it holds a credential.
_SECRET_NAME_RE = re.compile(
    r"passphrase|password|secret|community|^authentication$|(^|_)key$",
    re.IGNORECASE,
)


class TestSecretRedactionCoverage:
    """Two-sided structural guard for sanitiser secret coverage."""

    def test_forward_no_registered_secret_survives(self):
        """Populate every registered secret field with a unique
        sentinel, sanitise, and assert no sentinel survives into the
        canonical output.  Fails on the CF-01 class — a secret field
        present on the model but skipped by the sanitiser walk."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="Vlan10",
                    vrrp_groups=[
                        CanonicalVRRPGroup(
                            group_id=10,
                            authentication="plain:SENTINEL-vrrp-auth",
                        )
                    ],
                )
            ],
            local_users=[
                CanonicalLocalUser(
                    name="admin", hashed_password="$9$SENTINEL-hash"
                )
            ],
            snmp=CanonicalSNMP(
                community="SENTINEL-community",
                v3_users=[
                    CanonicalSNMPv3User(
                        name="ops",
                        auth_passphrase="SENTINEL-auth-pass",
                        priv_passphrase="SENTINEL-priv-pass",
                    )
                ],
            ),
            radius_servers=[
                CanonicalRADIUSServer(host="10.0.0.9", key="SENTINEL-radius-key")
            ],
        )
        sanitized, _ = sanitize_intent(intent)
        blob = sanitized.model_dump_json()
        leaked = [
            tok
            for tok in (
                "SENTINEL-vrrp-auth",
                "SENTINEL-hash",
                "SENTINEL-community",
                "SENTINEL-auth-pass",
                "SENTINEL-priv-pass",
                "SENTINEL-radius-key",
            )
            if tok in blob
        ]
        assert not leaked, f"secret sentinels survived sanitisation: {leaked}"

    def test_reverse_no_unregistered_secret_field(self):
        """Introspect every secret-named string field reachable from
        ``CanonicalIntent`` and assert it is registered above.  A NEW
        secret field added to the model without a redaction rule (and
        registration) fails here, forcing the author to wire the
        sanitiser."""
        found = set()
        for model in _reachable_canonical_models(CanonicalIntent):
            for fname, fld in model.model_fields.items():
                if not _SECRET_NAME_RE.search(fname):
                    continue
                if str in _flatten_annotation(fld.annotation):
                    found.add((model.__name__, fname))

        unregistered = found - _REGISTERED_SECRET_FIELDS
        stale = _REGISTERED_SECRET_FIELDS - found
        assert not unregistered, (
            "Secret-bearing canonical field(s) with no known redaction "
            "rule — add redaction in sanitize_intent AND register in "
            f"_REGISTERED_SECRET_FIELDS: {sorted(unregistered)}"
        )
        assert not stale, (
            "Registered secret field(s) no longer on the model — remove "
            f"from _REGISTERED_SECRET_FIELDS: {sorted(stale)}"
        )


# ---------------------------------------------------------------------------
# R-16 / CF-04 — PII / network tail redaction
#
# Non-secret-but-identifying fields the sanitiser previously left
# untouched: SNMP contact/location (operator PII), SNMP trap-target +
# RADIUS server + DHCP-gateway hosts (public IPv4), and VLAN-SVI IPv4
# (a SEPARATE canonical field from interfaces[].ipv4_addresses).
#
# These are PII/network, not secrets, so they are intentionally NOT in
# _REGISTERED_SECRET_FIELDS and do NOT trip TestSecretRedactionCoverage
# (that guard introspects secret-NAMED fields only).  This forward
# block is the durable "these PII fields don't survive" check.
# ---------------------------------------------------------------------------


class TestSNMPContactLocationRedaction:
    """SNMP contact (email/name) + location (site/address) are operator
    PII.  Free-text → opaque placeholder, not an IP redaction."""

    def test_contact_redacted_to_placeholder(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(community="", contact="admin@corp.example")
        )
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.snmp.contact == "<contact redacted>"
        assert "admin@corp.example" not in sanitized.snmp.contact
        assert any(
            s.category == "snmp-contact" and s.original == "admin@corp.example"
            for s in subs
        )

    def test_location_redacted_to_placeholder(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(community="", location="Rack 7, 12 Real Street")
        )
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.snmp.location == "<location redacted>"
        assert any(s.category == "snmp-location" for s in subs)

    def test_empty_contact_and_location_no_substitution(self):
        intent = CanonicalIntent(snmp=CanonicalSNMP(community="x"))
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.snmp.contact == ""
        assert sanitized.snmp.location == ""
        assert not any(s.category == "snmp-contact" for s in subs)
        assert not any(s.category == "snmp-location" for s in subs)


class TestSNMPTrapHostRedaction:
    """SNMP trap-target hosts: public IPv4 → docs range, private
    preserved, FQDN → host placeholder (audit 65f9c01 #20)."""

    def test_public_trap_host_redacted_private_preserved(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(
                community="",
                trap_hosts=["8.8.8.8", "192.168.50.5"],
            )
        )
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.snmp.trap_hosts[0] != "8.8.8.8"
        assert sanitized.snmp.trap_hosts[0].startswith(
            ("192.0.2.", "198.51.100.", "203.0.113.")
        )
        assert sanitized.snmp.trap_hosts[1] == "192.168.50.5"  # private kept
        assert len([s for s in subs if s.category == "ipv4-public"]) == 1

    def test_fqdn_trap_target_redacted(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(community="", trap_hosts=["nms.corp.example"])
        )
        sanitized, _ = sanitize_intent(intent)
        # An FQDN trap target re-leaks the org domain — now redacted to a
        # stable host placeholder (audit 65f9c01 #20, was a documented
        # residual passthrough before).
        assert sanitized.snmp.trap_hosts[0] != "nms.corp.example"
        assert "corp.example" not in sanitized.snmp.trap_hosts[0]
        assert sanitized.snmp.trap_hosts[0].endswith(".example.test")


class TestRADIUSHostRedaction:
    """RADIUS server host: public IPv4 → docs range, private preserved.
    Complements the existing key-redaction test."""

    def test_public_host_redacted(self):
        intent = CanonicalIntent(
            radius_servers=[
                CanonicalRADIUSServer(host="203.0.113.200", key="s"),
                CanonicalRADIUSServer(host="9.9.9.9", key="s2"),
            ]
        )
        sanitized, subs = sanitize_intent(intent)
        # 203.0.113.x is already a docs range -> preserved as-is.
        assert sanitized.radius_servers[0].host == "203.0.113.200"
        # 9.9.9.9 is public -> redacted.
        assert sanitized.radius_servers[1].host != "9.9.9.9"
        assert sanitized.radius_servers[1].host.startswith(
            ("192.0.2.", "198.51.100.", "203.0.113.")
        )
        assert any(
            s.category == "ipv4-public"
            and s.field == "radius_servers[1].host"
            for s in subs
        )

    def test_private_host_preserved(self):
        intent = CanonicalIntent(
            radius_servers=[CanonicalRADIUSServer(host="10.0.0.5", key="s")]
        )
        sanitized, _ = sanitize_intent(intent)
        assert sanitized.radius_servers[0].host == "10.0.0.5"


class TestDHCPGatewayRedaction:
    """DHCP pool gateway: sibling of the already-redacted static-route
    gateway.  Public IPv4 → docs range; private (the common case)
    preserved."""

    def test_public_gateway_redacted_private_preserved(self):
        intent = CanonicalIntent(
            dhcp_servers=[
                CanonicalDHCPPool(network="10.0.0.0/24", gateway="1.1.1.1"),
                CanonicalDHCPPool(network="10.1.0.0/24", gateway="10.1.0.1"),
            ]
        )
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.dhcp_servers[0].gateway != "1.1.1.1"
        assert sanitized.dhcp_servers[1].gateway == "10.1.0.1"  # private kept
        assert any(
            s.field == "dhcp_servers[0].gateway" for s in subs
        )


class TestVlanSviIPv4Redaction:
    """The material R-16 leak: SVI L3 addresses live on
    CanonicalVlan.ipv4_addresses — a SEPARATE field the interface walk
    never reaches.  On Aruba / Junos these render straight off the VLAN
    record, so a public SVI IP previously survived sanitisation."""

    def test_public_svi_ip_redacted_private_preserved(self):
        intent = CanonicalIntent(
            vlans=[
                CanonicalVlan(
                    id=10,
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="8.8.4.4", prefix_length=24),
                        CanonicalIPv4Address(ip="192.168.10.1", prefix_length=24),
                    ],
                )
            ]
        )
        sanitized, subs = sanitize_intent(intent)
        svi = sanitized.vlans[0].ipv4_addresses
        assert svi[0].ip != "8.8.4.4"
        assert svi[0].ip.startswith(("192.0.2.", "198.51.100.", "203.0.113."))
        assert svi[1].ip == "192.168.10.1"  # private SVI gateway preserved
        assert any(
            s.category == "ipv4-public"
            and s.field == "vlans[0].ipv4_addresses[0].ip"
            for s in subs
        )

    def test_svi_copy_matches_interface_copy_cross_reference(self):
        """Cisco/Arista keep an independent synthesised vlan copy of the
        SVI interface address.  Because redact_ipv4 is cache-keyed by IP
        string, the same public IP on both the interface and the vlan
        record resolves to the SAME docs-range substitute."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="Vlan10",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="11.22.33.44", prefix_length=24)
                    ],
                )
            ],
            vlans=[
                CanonicalVlan(
                    id=10,
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="11.22.33.44", prefix_length=24)
                    ],
                )
            ],
        )
        sanitized, _ = sanitize_intent(intent)
        iface_ip = sanitized.interfaces[0].ipv4_addresses[0].ip
        vlan_ip = sanitized.vlans[0].ipv4_addresses[0].ip
        assert iface_ip != "11.22.33.44"
        assert vlan_ip == iface_ip  # cross-reference stable


class TestPiiTailRenderedOutputClean:
    """End-to-end: sanitize_intent -> render must not emit the original
    PII.  Exercises the Aruba SVI-on-VLAN render path (the field that
    leaked) plus SNMP contact."""

    def test_aruba_svi_and_contact_absent_from_render(self):
        from netcanon.migration.codecs.registry import get_codec

        intent = CanonicalIntent(
            hostname="r1",
            vlans=[
                CanonicalVlan(
                    id=10,
                    name="USERS",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="9.9.9.9", prefix_length=24)
                    ],
                )
            ],
            snmp=CanonicalSNMP(community="", contact="admin@corp.example"),
        )
        sanitized, _ = sanitize_intent(intent)
        rendered = get_codec("aruba_aoss").render(sanitized)
        assert "9.9.9.9" not in rendered            # SVI leak closed
        assert "admin@corp.example" not in rendered   # contact leak closed


class TestVirtualGatewayAddressRedaction:
    """Regression guard for the anycast / VARP virtual-gateway-address leak
    (blind audit ``3ec11f3`` #6).  ``virtual_gateway_address`` is a sibling
    of ``.ip`` on both address models, rendered verbatim by 5 codecs
    (Arista ``ip address virtual``, Aruba ``active-gateway ip``, Junos,
    NX-OS DAG, IOS-XE SD-Access).  A public one bypassed sanitisation while
    its primary-IP sibling was redacted — the identical leak class the
    VRRP/CARP VIP fix (#134) closed for ``CanonicalVRRPGroup.virtual_ips``."""

    def test_public_vga_redacted_on_interface_ipv4(self):
        intent = CanonicalIntent(
            hostname="sw",
            interfaces=[CanonicalInterface(
                name="Vlan10", default_name="Vlan10",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="8.8.8.2", prefix_length=24,
                    virtual_gateway_address="9.9.9.1")])],
        )
        sanitized, subs = sanitize_intent(intent)
        addr = sanitized.interfaces[0].ipv4_addresses[0]
        assert addr.ip != "8.8.8.2"                       # primary redacted (baseline)
        assert addr.virtual_gateway_address != "9.9.9.1"  # VGA redacted (the fix)
        assert any(
            s.field.endswith("ipv4_addresses[0].virtual_gateway_address")
            for s in subs
        )

    def test_public_vga_redacted_on_interface_ipv6(self):
        intent = CanonicalIntent(
            hostname="sw",
            interfaces=[CanonicalInterface(
                name="Vlan10", default_name="Vlan10",
                ipv6_addresses=[CanonicalIPv6Address(
                    ip="2001:4860::2", prefix_length=64,
                    virtual_gateway_address="2001:4860::1")])],
        )
        sanitized, _ = sanitize_intent(intent)
        addr = sanitized.interfaces[0].ipv6_addresses[0]
        assert addr.ip != "2001:4860::2"
        assert addr.virtual_gateway_address != "2001:4860::1"

    def test_public_vga_redacted_on_vlan_svi(self):
        intent = CanonicalIntent(
            hostname="sw",
            vlans=[CanonicalVlan(
                id=10, name="V10",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="8.8.8.2", prefix_length=24,
                    virtual_gateway_address="9.9.9.1")])],
        )
        sanitized, _ = sanitize_intent(intent)
        addr = sanitized.vlans[0].ipv4_addresses[0]
        assert addr.virtual_gateway_address != "9.9.9.1"

    def test_private_vga_preserved(self):
        """A private VGA (the LAN-gateway common case) is preserved, like any
        private IP — redaction targets public/routable addresses only."""
        intent = CanonicalIntent(
            hostname="sw",
            interfaces=[CanonicalInterface(
                name="Vlan10", default_name="Vlan10",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="10.0.0.2", prefix_length=24,
                    virtual_gateway_address="10.0.0.1")])],
        )
        sanitized, _ = sanitize_intent(intent)
        assert sanitized.interfaces[0].ipv4_addresses[0].virtual_gateway_address == "10.0.0.1"

    def test_public_vga_absent_from_render(self):
        """End-to-end: the Aruba AOS-CX ``active-gateway ip`` line must not
        emit the public VGA after sanitisation.  Precondition-asserts the
        codec DOES emit it first, so the test can't pass vacuously."""
        from netcanon.migration.codecs.registry import get_codec

        intent = CanonicalIntent(
            hostname="sw",
            vlans=[CanonicalVlan(id=10, name="V10")],
            interfaces=[CanonicalInterface(
                name="Vlan10", default_name="Vlan10",
                interface_type="ianaift:l3ipvlan",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="8.8.8.2", prefix_length=24,
                    virtual_gateway_address="9.9.9.1")])],
        )
        codec = get_codec("aruba_aoscx")
        assert "9.9.9.1" in codec.render(intent)            # precondition: codec emits VGA
        sanitized, _ = sanitize_intent(intent)
        assert "9.9.9.1" not in codec.render(sanitized)     # leak closed end-to-end


class TestVirtualMacRedaction:
    """Regression guard for the burned-in / operator MAC leak (blind audit
    ``f92e97a`` T0-3).  The anycast virtual-gateway MAC and a VRRP virtual MAC
    are rendered verbatim by the codecs; a burned-in MAC's OUI leaks the
    hardware vendor and the full address is device-unique.  Redacted to the
    RFC 7042 documentation range (``00:00:5e:00:53:NN``); protocol-standard
    VRRP/HSRP vMACs (derived from the group ID) are preserved -- they identify
    nothing about the operator."""

    #: Arista OUI 00:1c:73 -> identifying (hardware vendor + device-unique).
    _BURNED_IN = "00:1c:73:0a:0b:0c"

    def test_interface_ipv4_vgmac_redacted(self):
        intent = CanonicalIntent(
            hostname="sw",
            interfaces=[CanonicalInterface(
                name="Vlan10", default_name="Vlan10",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="10.0.0.2", prefix_length=24,
                    virtual_gateway_mac=self._BURNED_IN)])],
        )
        sanitized, subs = sanitize_intent(intent)
        vgm = sanitized.interfaces[0].ipv4_addresses[0].virtual_gateway_mac
        assert vgm != self._BURNED_IN
        assert vgm.startswith("00:00:5e:00:53:")            # RFC 7042 docs range
        assert any(
            s.field.endswith("ipv4_addresses[0].virtual_gateway_mac") for s in subs
        )

    def test_interface_ipv6_vgmac_redacted(self):
        intent = CanonicalIntent(
            hostname="sw",
            interfaces=[CanonicalInterface(
                name="Vlan10", default_name="Vlan10",
                ipv6_addresses=[CanonicalIPv6Address(
                    ip="2001:db8::2", prefix_length=64,
                    virtual_gateway_mac=self._BURNED_IN)])],
        )
        sanitized, _ = sanitize_intent(intent)
        assert (
            sanitized.interfaces[0].ipv6_addresses[0].virtual_gateway_mac
            != self._BURNED_IN
        )

    def test_vlan_svi_vgmac_redacted(self):
        intent = CanonicalIntent(
            hostname="sw",
            vlans=[CanonicalVlan(
                id=10, name="V10",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="10.0.0.2", prefix_length=24,
                    virtual_gateway_mac=self._BURNED_IN)])],
        )
        sanitized, _ = sanitize_intent(intent)
        assert (
            sanitized.vlans[0].ipv4_addresses[0].virtual_gateway_mac
            != self._BURNED_IN
        )

    def test_vrrp_virtual_mac_redacted(self):
        intent = CanonicalIntent(
            hostname="sw",
            interfaces=[CanonicalInterface(
                name="Vlan10", default_name="Vlan10",
                vrrp_groups=[CanonicalVRRPGroup(
                    group_id=10, virtual_ips=["10.0.0.254"],
                    virtual_mac=self._BURNED_IN)])],
        )
        sanitized, subs = sanitize_intent(intent)
        assert (
            sanitized.interfaces[0].vrrp_groups[0].virtual_mac != self._BURNED_IN
        )
        assert any(s.field.endswith("vrrp_groups[0].virtual_mac") for s in subs)

    def test_anycast_gateway_mac_redacted(self):
        intent = CanonicalIntent(hostname="sw", anycast_gateway_mac=self._BURNED_IN)
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.anycast_gateway_mac != self._BURNED_IN
        assert any(s.field == "anycast_gateway_mac" for s in subs)

    def test_wellknown_vrrp_mac_preserved(self):
        """The protocol-standard VRRP virtual MAC (00:00:5e:00:01:NN, derived
        from the VRID) identifies nothing and is preserved."""
        vrrp_mac = "00:00:5e:00:01:0a"
        intent = CanonicalIntent(
            hostname="sw",
            interfaces=[CanonicalInterface(
                name="Vlan10", default_name="Vlan10",
                vrrp_groups=[CanonicalVRRPGroup(
                    group_id=10, virtual_ips=["10.0.0.254"],
                    virtual_mac=vrrp_mac)])],
        )
        sanitized, _ = sanitize_intent(intent)
        assert sanitized.interfaces[0].vrrp_groups[0].virtual_mac == vrrp_mac

    def test_cisco_dotted_format_preserved(self):
        """A Cisco dotted-form MAC (aaaa.bbbb.cccc) is redacted in the same
        format so the renderer still emits valid syntax."""
        intent = CanonicalIntent(hostname="sw", anycast_gateway_mac="001c.730a.0b0c")
        sanitized, _ = sanitize_intent(intent)
        out = sanitized.anycast_gateway_mac
        assert out != "001c.730a.0b0c"
        assert out.startswith("0000.5e00.53")              # dotted RFC 7042 form

    def test_burned_in_mac_absent_from_render(self):
        """End-to-end: the NX-OS ``fabric forwarding anycast-gateway-mac`` line
        must not emit the burned-in OUI after sanitisation.  Precondition-asserts
        the codec DOES emit it first, so the test can't pass vacuously."""
        from netcanon.migration.codecs.registry import get_codec

        intent = CanonicalIntent(
            hostname="sw",
            anycast_gateway_mac=self._BURNED_IN,
            vlans=[CanonicalVlan(id=10, name="V10")],
        )
        codec = get_codec("cisco_nxos")
        assert "001c.730a.0b0c" in codec.render(intent)     # precondition: codec emits the MAC
        sanitized, _ = sanitize_intent(intent)
        rendered = codec.render(sanitized)
        assert "001c.73" not in rendered                    # burned-in OUI gone (dotted form)
        assert "00:1c:73" not in rendered                   # ...and colon form


class TestVRFNameRedaction:
    """VRF / routing-instance names are redacted cross-reference-stable
    (blind audit ``81d9740`` #5).  A VRF name can encode customer / tenant
    identity (``Tenant_A``) — the same risk class as a VLAN name, which IS
    redacted.  The rename must apply to the routing-instance definition AND
    every interface / static-route / EVPN-Type5 record that references it, or
    a ``ip route vrf <name>`` reference would dangle off its definition."""

    def test_vrf_names_redacted_across_all_four_sites(self):
        intent = CanonicalIntent(
            hostname="r1",
            routing_instances=[CanonicalRoutingInstance(name="Tenant_A")],
            interfaces=[CanonicalInterface(
                name="Gi0/1", default_name="Gi0/1", vrf="Tenant_A")],
            static_routes=[CanonicalStaticRoute(
                destination="10.0.0.0/24", gateway="10.0.0.1", vrf="Tenant_A")],
            evpn_type5_routes=[CanonicalEvpnType5Route(
                vrf="Tenant_A", prefix="10.1.0.0/24")],
        )
        sanitized, subs = sanitize_intent(intent)
        # The operator-chosen name is gone from every site...
        assert sanitized.routing_instances[0].name != "Tenant_A"
        assert sanitized.interfaces[0].vrf != "Tenant_A"
        assert sanitized.static_routes[0].vrf != "Tenant_A"
        assert sanitized.evpn_type5_routes[0].vrf != "Tenant_A"
        # ...replaced by a vrf-N placeholder...
        placeholder = sanitized.routing_instances[0].name
        assert placeholder.startswith("vrf-")
        # ...the SAME placeholder everywhere (cross-reference stable).
        assert sanitized.interfaces[0].vrf == placeholder
        assert sanitized.static_routes[0].vrf == placeholder
        assert sanitized.evpn_type5_routes[0].vrf == placeholder
        assert any(s.category == "vrf-name" for s in subs)

    def test_distinct_vrf_names_get_distinct_placeholders(self):
        intent = CanonicalIntent(
            hostname="r1",
            routing_instances=[
                CanonicalRoutingInstance(name="Tenant_A"),
                CanonicalRoutingInstance(name="Tenant_B"),
            ],
        )
        sanitized, _ = sanitize_intent(intent)
        names = {ri.name for ri in sanitized.routing_instances}
        assert len(names) == 2                      # distinct in -> distinct out
        assert "Tenant_A" not in names and "Tenant_B" not in names


def test_raw_sections_stripped_by_sanitiser():
    """DATA-02: Tier-3 ``raw_sections`` (verbatim vendor text) is cleared.

    No production parser populates ``raw_sections`` today, but the IOS-XE
    renderer emits any entries verbatim, so the sanitiser must fail closed
    and strip it (mirrors the ``dropped_tier3_sections`` strip) — otherwise
    a future parser that fills it could round-trip unredacted secrets.
    """
    intent = CanonicalIntent(
        hostname="r1",
        raw_sections={
            "router bgp 65000": "neighbor 203.0.113.7 password SENTINEL-raw",
        },
    )
    sanitized, subs = sanitize_intent(intent)
    assert sanitized.raw_sections == {}
    assert any(s.field == "raw_sections" for s in subs)
    # The verbatim secret must not survive anywhere in the output.
    assert "SENTINEL-raw" not in sanitized.model_dump_json()


# ---------------------------------------------------------------------------
# v0.4.0 self-audit — verbatim apply-group carry-through + free-text PII
# ---------------------------------------------------------------------------


class TestJunosApplyGroupsStripped:
    """v0.4.0 self-audit (HIGH): secrets inside a Junos ``apply-group``
    are carried verbatim in ``group_content`` and re-emitted by the
    renderer, bypassing every field-typed redaction.  They must be
    stripped fail-closed (like ``raw_sections``)."""

    def test_group_content_and_apply_groups_emptied(self):
        intent = CanonicalIntent(
            hostname="r1",
            group_content={
                "GLOBAL": [
                    ["system", "login", "user", "backdoor",
                     "authentication", "encrypted-password",
                     "$6$RealSalt$RealHashSENTINEL"],
                    ["snmp", "community", "SuperSecretSENTINEL",
                     "authorization", "read-only"],
                ]
            },
            apply_groups=["GLOBAL"],
        )
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.group_content == {}
        assert sanitized.apply_groups == []
        assert {s.field for s in subs} >= {"group_content", "apply_groups"}
        assert "SENTINEL" not in sanitized.model_dump_json()

    def test_end_to_end_junos_apply_group_secret_not_rendered(self):
        raw = (
            "set system host-name real-edge-rtr\n"
            "set groups GLOBAL system login user backdoor authentication "
            'encrypted-password "$6$RealSaltHere$RealHashSecretXYZ"\n'
            "set groups GLOBAL snmp community SuperSecretCommunity "
            "authorization read-only\n"
            "set apply-groups GLOBAL\n"
        )
        out = sanitize_text(raw, "juniper_junos").sanitized_text
        assert "$6$RealSaltHere$RealHashSecretXYZ" not in out
        assert "SuperSecretCommunity" not in out
        assert "backdoor" not in out


class TestFreeTextPiiRedaction:
    """v0.4.0 self-audit: free-text fields besides interface.description
    (VLAN name/description, static-route / routing-instance / VRRP
    description, DHCP domain-name) are operator/org PII and must not
    survive sanitisation."""

    def test_modelled_free_text_fields_redacted(self):
        intent = CanonicalIntent(
            vlans=[CanonicalVlan(
                id=10, name="CEO-OFFICE", description="Jane Doe x4012")],
            static_routes=[CanonicalStaticRoute(
                destination="0.0.0.0/0", gateway="10.0.0.1",
                description="to-DC-NYC-rack42")],
            routing_instances=[CanonicalRoutingInstance(
                name="MGMT", description="customer ACME tenant")],
            dhcp_servers=[CanonicalDHCPPool(
                network="10.0.0.0/24",
                domain_name="internal.acmecorp.example")],
            interfaces=[CanonicalInterface(
                name="ge-0/0/0", default_name="ge-0/0/0",
                vrrp_groups=[CanonicalVRRPGroup(
                    group_id=1, description="HQ gateway - John")])],
        )
        sanitized, _ = sanitize_intent(intent)
        blob = sanitized.model_dump_json()
        for leaked in (
            "CEO-OFFICE", "Jane Doe x4012", "to-DC-NYC-rack42",
            "customer ACME tenant", "internal.acmecorp.example",
            "HQ gateway - John",
        ):
            assert leaked not in blob, f"PII survived: {leaked!r}"

    def test_vlan_name_redaction_is_cross_reference_stable(self):
        """Same VLAN name → same placeholder, so ``vlan members <name>``
        cross-references stay consistent in the rendered output."""
        intent = CanonicalIntent(
            vlans=[
                CanonicalVlan(id=10, name="SECRET-VLAN"),
                CanonicalVlan(id=20, name="SECRET-VLAN"),
                CanonicalVlan(id=30, name="OTHER"),
            ],
        )
        sanitized, _ = sanitize_intent(intent)
        names = [v.name for v in sanitized.vlans]
        assert "SECRET-VLAN" not in names and "OTHER" not in names
        assert names[0] == names[1]      # same source name → same redaction
        assert names[0] != names[2]      # distinct names stay distinct


# ---------------------------------------------------------------------------
# v0.4.1 run3 audit — IP-typed redaction gaps (extends the IPv4-only tail)
#
# Three "same class, new surface" leaks the IPv4-only redaction missed:
#   * interface / DNS / NTP / syslog IPv6 (ipv6-sanitizer-leak)
#   * VRRP / CARP virtual IPs, v4 and v6 (vrrp-vip-leak)
#   * DHCP pool range bounds + served subnet (dhcp-range-leak)
# These are network-location PII, not secrets, so they live here as a
# forward "must not survive" block rather than in the secret-coverage
# guard.
# ---------------------------------------------------------------------------


class TestIPv6Redaction:
    """Global/public IPv6 is redacted to the RFC 3849 docs range; ULA,
    link-local, loopback, unspecified, multicast, and the docs range
    itself are preserved (mirrors the IPv4 policy)."""

    def test_public_interface_ipv6_redacted(self):
        intent = CanonicalIntent(
            interfaces=[CanonicalInterface(
                name="Vlan10",
                ipv6_addresses=[
                    CanonicalIPv6Address(ip="2606:4700:4700::1111",
                                         prefix_length=64),
                ],
            )],
        )
        sanitized, subs = sanitize_intent(intent)
        new_ip = sanitized.interfaces[0].ipv6_addresses[0].ip
        assert new_ip != "2606:4700:4700::1111"
        assert new_ip.startswith("2001:db8::")
        assert any(
            s.category == "ipv6-public"
            and s.original == "2606:4700:4700::1111"
            for s in subs
        )

    @pytest.mark.parametrize(
        "preserved",
        ["fe80::1", "fd00::dead:beef", "::1", "ff02::1", "2001:db8::5"],
    )
    def test_non_global_ipv6_preserved(self, preserved):
        intent = CanonicalIntent(
            interfaces=[CanonicalInterface(
                name="Vlan10",
                ipv6_addresses=[
                    CanonicalIPv6Address(ip=preserved, prefix_length=64),
                ],
            )],
        )
        sanitized, _ = sanitize_intent(intent)
        assert sanitized.interfaces[0].ipv6_addresses[0].ip == preserved

    def test_ipv6_in_dns_ntp_syslog_lists_redacted(self):
        intent = CanonicalIntent(
            dns_servers=["2001:4860:4860::8888"],
            ntp_servers=["2606:4700:4700::64"],
            syslog_servers=["2620:fe::fe"],
        )
        sanitized, _ = sanitize_intent(intent)
        blob = sanitized.model_dump_json()
        for leaked in (
            "2001:4860:4860::8888", "2606:4700:4700::64", "2620:fe::fe",
        ):
            assert leaked not in blob, f"public IPv6 survived: {leaked!r}"

    def test_ipv6_redaction_is_cross_reference_stable(self):
        """Same source IPv6 → same docs substitute everywhere."""
        table = _SubstitutionTable()
        a = table.redact_ipv6("2606:4700:4700::1111")
        b = table.redact_ipv6("2606:4700:4700::1111")
        c = table.redact_ipv6("2001:4860:4860::8888")
        assert a == b           # stable
        assert a != c           # distinct sources stay distinct


class TestIPv6TransitionAddressRedaction:
    """audit 276eaeb T0-4: IPv6 *transition* formats (6to4, IPv4-mapped,
    IPv4-compatible, NAT64, Teredo) embed a routable IPv4 in their low
    bits, yet classify as ``is_private`` / ``is_reserved`` at the v6
    layer — so ``redact_ipv6`` used to emit them verbatim and leak the
    embedded public IPv4.  They are now redacted iff the embedded IPv4
    is public; transition addresses wrapping a *private* IPv4 are still
    preserved (the wrapper carries no public information)."""

    # Each embeds the public 8.8.8.8 (Teredo embeds public 65.54.227.120
    # as its server) and must NOT survive verbatim, and must NOT leak the
    # embedded v4 anywhere in the substitute.
    @pytest.mark.parametrize(
        "addr, leaked_v4",
        [
            ("2002:0808:0808::1", "8.8.8.8"),                 # 6to4
            ("64:ff9b::8.8.8.8", "8.8.8.8"),                  # NAT64 well-known
            ("64:ff9b:1::8.8.8.8", "8.8.8.8"),                # NAT64 RFC 8215
            ("::ffff:8.8.8.8", "8.8.8.8"),                    # IPv4-mapped
            ("::8.8.8.8", "8.8.8.8"),                         # IPv4-compatible
            ("2001:0000:4136:e378:8000:63bf:3fff:fdd2",       # Teredo
             "65.54.227.120"),
        ],
    )
    def test_transition_with_public_v4_is_redacted(self, addr, leaked_v4):
        table = _SubstitutionTable()
        out = table.redact_ipv6(addr)
        assert out != addr, f"transition address survived verbatim: {addr}"
        assert out.startswith("2001:db8::")
        assert leaked_v4 not in out, f"embedded public IPv4 leaked: {leaked_v4}"

    @pytest.mark.parametrize(
        "addr",
        [
            "2002:c0a8:0101::1",     # 6to4 wrapping 192.168.1.1 (private)
            "::ffff:192.168.1.1",    # IPv4-mapped wrapping a private v4
            "::ffff:10.0.0.1",       # IPv4-mapped wrapping RFC 1918
            "2002:c633:6401::1",     # 6to4 wrapping 198.51.100.1 (docs)
        ],
    )
    def test_transition_with_nonpublic_v4_is_preserved(self, addr):
        """No public information to leak → preserve verbatim (don't
        manufacture a false redaction that would corrupt a real config)."""
        table = _SubstitutionTable()
        assert table.redact_ipv6(addr) == addr

    def test_end_to_end_transition_leak_closed_on_interface(self):
        """Full pipeline: a 6to4 + a NAT64 address on an interface must
        not appear anywhere in the sanitized dump."""
        intent = CanonicalIntent(
            interfaces=[CanonicalInterface(
                name="Vlan10",
                ipv6_addresses=[
                    CanonicalIPv6Address(ip="2002:0808:0808::1",
                                         prefix_length=64),
                    CanonicalIPv6Address(ip="64:ff9b::8.8.8.8",
                                         prefix_length=96),
                ],
            )],
        )
        sanitized, _ = sanitize_intent(intent)
        blob = sanitized.model_dump_json()
        for leaked in ("2002:0808:0808::1", "64:ff9b::8.8.8.8", "8.8.8.8"):
            assert leaked not in blob, f"transition leak survived: {leaked!r}"


class TestVRRPVirtualIPRedaction:
    """v0.4.1: the VRRP / CARP virtual IP — frequently the public HA
    gateway — was passed through verbatim while its sibling auth secret
    was redacted.  Both v4 and v6 VIPs are now redacted."""

    def test_public_virtual_ips_redacted_private_preserved(self):
        intent = CanonicalIntent(
            interfaces=[CanonicalInterface(
                name="Vlan10",
                vrrp_groups=[CanonicalVRRPGroup(
                    group_id=10,
                    virtual_ips=["8.8.4.4", "10.0.0.254"],
                    virtual_ipv6s=["2606:4700:4700::64", "fd00::64"],
                )],
            )],
        )
        sanitized, subs = sanitize_intent(intent)
        g = sanitized.interfaces[0].vrrp_groups[0]
        assert "8.8.4.4" not in g.virtual_ips          # public v4 gone
        assert "10.0.0.254" in g.virtual_ips           # private preserved
        assert "2606:4700:4700::64" not in g.virtual_ipv6s  # public v6 gone
        assert "fd00::64" in g.virtual_ipv6s           # ULA preserved
        assert any("virtual_ips" in s.field for s in subs)
        assert any("virtual_ipv6s" in s.field for s in subs)

    def test_rendered_output_omits_public_vip(self):
        """End-to-end via a codec that renders VRRP: a genuinely public
        VIP must not appear in the sanitised render output."""
        from netcanon.migration.codecs.registry import get_codec

        intent = CanonicalIntent(
            hostname="r1",
            interfaces=[CanonicalInterface(
                name="Vlan10",
                ipv4_addresses=[
                    CanonicalIPv4Address(ip="10.0.0.2", prefix_length=24)],
                vrrp_groups=[CanonicalVRRPGroup(
                    group_id=10, virtual_ips=["8.8.4.4"])],
            )],
        )
        sanitized, _ = sanitize_intent(intent)
        rendered = get_codec("cisco_iosxe_cli").render(sanitized)
        assert "8.8.4.4" not in rendered


class TestDHCPRangeRedaction:
    """v0.4.1: DHCP pool range bounds (start_ip/end_ip) and the served
    subnet (network) leaked while the same record's gateway / dns_servers
    were redacted — the trust-asymmetry trap.  Public → docs range,
    network prefix length preserved, private LAN ranges untouched."""

    def test_public_range_and_network_redacted(self):
        intent = CanonicalIntent(
            dhcp_servers=[CanonicalDHCPPool(
                network="9.9.9.0/24",
                start_ip="9.9.9.10",
                end_ip="9.9.9.20",
                gateway="9.9.9.1",
            )],
        )
        sanitized, subs = sanitize_intent(intent)
        p = sanitized.dhcp_servers[0]
        assert "9.9.9.10" not in p.start_ip
        assert "9.9.9.20" not in p.end_ip
        assert "9.9.9.0" not in p.network
        assert p.network.endswith("/24")   # prefix length preserved
        for fld in ("start_ip", "end_ip", "network"):
            assert any(s.field.endswith(fld) for s in subs)

    def test_private_lan_range_preserved(self):
        intent = CanonicalIntent(
            dhcp_servers=[CanonicalDHCPPool(
                network="192.168.10.0/24",
                start_ip="192.168.10.100",
                end_ip="192.168.10.200",
            )],
        )
        sanitized, _ = sanitize_intent(intent)
        p = sanitized.dhcp_servers[0]
        assert p.network == "192.168.10.0/24"
        assert p.start_ip == "192.168.10.100"
        assert p.end_ip == "192.168.10.200"


# ---------------------------------------------------------------------------
# Overlay (EVPN / VXLAN / VRF) identifiers — non-secret but network-
# identifying fields the sanitiser previously left untouched: VRF
# route-distinguisher + route-targets, VXLAN BUM multicast group + VTEP
# flood-list, EVPN Type-5 RTs + advertised prefix, and the SNMPv3
# engineID.  A verifier leaked the trio `65501:100` / `239.7.7.7` /
# `9.9.9.9` through these.  Like the PII-tail block above, these are NOT
# secret-NAMED so they intentionally don't register in
# _REGISTERED_SECRET_FIELDS; this is their forward "must not survive"
# guard.
# ---------------------------------------------------------------------------


class TestOverlayFieldRedaction:
    def test_route_distinguisher_redacted(self):
        intent = CanonicalIntent(
            routing_instances=[
                CanonicalRoutingInstance(name="TENANT-A", route_distinguisher="65501:100"),
            ],
        )
        sanitized, subs = sanitize_intent(intent)
        rd = sanitized.routing_instances[0].route_distinguisher
        assert rd != "65501:100"
        assert rd.startswith("64496:")  # RFC 5398 documentation ASN
        assert any(s.category == "route-distinguisher" for s in subs)

    def test_route_targets_redacted(self):
        intent = CanonicalIntent(
            routing_instances=[
                CanonicalRoutingInstance(
                    name="TENANT-A",
                    rt_imports=["65501:100", "65001:200"],
                    rt_exports=["65501:100"],
                ),
            ],
        )
        sanitized, subs = sanitize_intent(intent)
        ri = sanitized.routing_instances[0]
        assert "65501:100" not in ri.rt_imports and "65001:200" not in ri.rt_imports
        assert "65501:100" not in ri.rt_exports
        assert all(rt.startswith("64496:") for rt in ri.rt_imports + ri.rt_exports)
        assert any(s.category == "route-target" for s in subs)

    def test_rd_rt_cross_reference_stable(self):
        """An RD that recurs as a route-target (and across sibling VRFs)
        maps to the SAME placeholder, so the VPN-correlation structure
        survives sanitisation while the real ASN/index is hidden."""
        intent = CanonicalIntent(
            routing_instances=[
                CanonicalRoutingInstance(
                    name="A", route_distinguisher="65501:100",
                    rt_imports=["65501:100"], rt_exports=["65501:100"],
                ),
                CanonicalRoutingInstance(
                    name="B", route_distinguisher="65501:200",
                    rt_imports=["65501:100"],  # imports A's RT
                ),
            ],
        )
        sanitized, _ = sanitize_intent(intent)
        a, b = sanitized.routing_instances
        # 65501:100 everywhere → one placeholder; 65501:200 → a distinct one.
        assert a.route_distinguisher == a.rt_imports[0] == a.rt_exports[0]
        assert b.rt_imports[0] == a.route_distinguisher
        assert b.route_distinguisher != a.route_distinguisher

    def test_vxlan_mcast_group_redacted_to_doc_range(self):
        intent = CanonicalIntent(
            vxlan_vnis=[
                CanonicalVxlan(vlan_id=100, vni=10100, mcast_group="239.7.7.7"),
                CanonicalVxlan(vlan_id=200, vni=10200, mcast_group="239.7.7.7"),
            ],
        )
        sanitized, subs = sanitize_intent(intent)
        g0 = sanitized.vxlan_vnis[0].mcast_group
        g1 = sanitized.vxlan_vnis[1].mcast_group
        assert g0 != "239.7.7.7"
        assert g0.startswith("233.252.0.")   # RFC 5771 MCAST-TEST-NET
        assert g0 == g1                       # same group → stable placeholder
        assert any(s.category == "mcast-group" for s in subs)

    def test_vxlan_flood_list_public_redacted_private_preserved(self):
        intent = CanonicalIntent(
            vxlan_vnis=[
                CanonicalVxlan(
                    vlan_id=100, vni=10100,
                    flood_list=["9.9.9.9", "10.0.0.1"],
                ),
            ],
        )
        sanitized, _ = sanitize_intent(intent)
        flood = sanitized.vxlan_vnis[0].flood_list
        assert flood[0] != "9.9.9.9"
        assert flood[0].startswith(("192.0.2.", "198.51.100.", "203.0.113."))
        assert flood[1] == "10.0.0.1"  # private VTEP preserved

    def test_evpn_type5_rt_and_public_prefix_redacted(self):
        intent = CanonicalIntent(
            evpn_type5_routes=[
                CanonicalEvpnType5Route(
                    vrf="TENANT-A",
                    prefix="8.8.0.0/16",   # public — address redacted
                    rt_imports=["65001:100"],
                    rt_exports=["65001:100"],
                ),
                CanonicalEvpnType5Route(
                    vrf="TENANT-B",
                    prefix="10.1.0.0/16",   # private — preserved
                    rt_imports=["65001:200"],
                ),
            ],
        )
        sanitized, _ = sanitize_intent(intent)
        r0, r1 = sanitized.evpn_type5_routes
        assert all(rt.startswith("64496:") for rt in r0.rt_imports + r0.rt_exports)
        # Public prefix address redacted, /16 preserved; private kept whole.
        assert r0.prefix.endswith("/16")
        assert r0.prefix.split("/")[0].startswith(
            ("192.0.2.", "198.51.100.", "203.0.113.")
        )
        assert r1.prefix == "10.1.0.0/16"

    def test_snmpv3_engine_id_redacted(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(
                community="",
                v3_users=[
                    CanonicalSNMPv3User(name="ops", engine_id="80001f8880e5817264"),
                ],
            ),
        )
        sanitized, subs = sanitize_intent(intent)
        eid = sanitized.snmp.v3_users[0].engine_id
        assert eid != "80001f8880e5817264"
        assert "REDACTED" in eid
        assert any(s.category == "snmpv3-engine-id" for s in subs)

    def test_leaked_overlay_trio_does_not_survive(self):
        """End-to-end: the exact values an audit verifier leaked through
        the overlay surfaces (`65501:100`, `239.7.7.7`, `9.9.9.9`) must
        not appear anywhere in the sanitised canonical output."""
        intent = CanonicalIntent(
            routing_instances=[
                CanonicalRoutingInstance(
                    name="A", route_distinguisher="65501:100",
                    rt_imports=["65501:100"],
                ),
            ],
            vxlan_vnis=[
                CanonicalVxlan(
                    vlan_id=100, vni=10100,
                    mcast_group="239.7.7.7", flood_list=["9.9.9.9"],
                ),
            ],
        )
        sanitized, _ = sanitize_intent(intent)
        blob = sanitized.model_dump_json()
        leaked = [t for t in ("65501:100", "239.7.7.7", "9.9.9.9") if t in blob]
        assert not leaked, f"overlay identifiers survived sanitisation: {leaked}"
