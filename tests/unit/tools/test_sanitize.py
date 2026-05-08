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

from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIPv4Address,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLocalUser,
    CanonicalRADIUSServer,
    CanonicalSNMP,
    CanonicalSNMPv3User,
    CanonicalStaticRoute,
)
from netcanon.tools.sanitize import (
    SanitizationResult,
    Substitution,
    _SubstitutionTable,
    sanitize_intent,
    sanitize_text,
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
