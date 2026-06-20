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
import typing
from pathlib import Path

import pytest
from pydantic import BaseModel

from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
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


def _flatten_annotation(ann):
    """Yield ``ann`` and every nested type argument (unwraps
    ``list[...]`` / ``Optional[...]`` / ``dict[...]`` / unions)."""
    args = typing.get_args(ann)
    if not args:
        yield ann
        return
    for a in args:
        yield from _flatten_annotation(a)


def _reachable_canonical_models(root_cls, acc=None):
    """All ``BaseModel`` subclasses reachable from ``root_cls`` via its
    (possibly nested) field annotations."""
    if acc is None:
        acc = set()
    if root_cls in acc:
        return acc
    acc.add(root_cls)
    for fld in root_cls.model_fields.values():
        for t in _flatten_annotation(fld.annotation):
            if isinstance(t, type) and issubclass(t, BaseModel):
                _reachable_canonical_models(t, acc)
    return acc


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
    preserved, hostname preserved."""

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

    def test_hostname_trap_target_preserved(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(community="", trap_hosts=["nms.corp.example"])
        )
        sanitized, _ = sanitize_intent(intent)
        # Documented residual: name-form hosts pass through.
        assert sanitized.snmp.trap_hosts[0] == "nms.corp.example"


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
