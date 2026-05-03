"""
Regression tests for Wave 3 OPNsense-supergate findings against the
``cisco_iosxe_cli`` render path.

Two issues from
``tests/fixtures/real/user_smoke_findings.md`` (OPEN OPNsense
section):

* Finding #2 — bcrypt hash leak under ``secret 5 bcrypt:$2y$11$...``
  (security disclosure + wrong type tag).  Cross-vendor hashes that
  IOS-XE cannot consume must emit a ``! password manager user-name
  ...`` review-comment line, not the literal payload.
* Finding #8 — ``interface igc0`` empty stub leaking through from the
  OPNsense canonical tree.  The render path now mirrors the Junos
  tiered-elision pattern (commit ``0fdf7e9``) and skips empty stubs
  unless the name matches an IOS-XE physical-port shape OR the iface
  is referenced from a VLAN port list.
* Finding #12 — ``ip domain name`` regression guard (already-emitted
  behaviour pinned so a future refactor can't silently drop it).

See also:

* :mod:`netconfig.migration._user_secrets` — shared hash-policy helper
* :mod:`netconfig.migration.codecs.cisco_iosxe_cli.render` — the
  render path under test
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalLocalUser,
    CanonicalRoutingInstance,
    CanonicalVlan,
)
from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Finding #2 — hash-portability gate
# ---------------------------------------------------------------------------


class TestHashGate:
    def test_cisco_bcrypt_hash_emits_review_comment(self) -> None:
        """OPNsense-source bcrypt hash → IOS-XE comment line, no
        ``$2y$`` payload anywhere on the wire."""
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(
                    name="root",
                    privilege_level=15,
                    hashed_password="bcrypt:$2y$11$fakeBcryptHashForRoot",
                ),
            ],
        )
        out = CiscoIOSXECLICodec().render(intent)
        # Critical: no payload leak.
        assert "$2y$" not in out
        assert "bcrypt:" not in out
        # No ``secret 5`` line for this user (bcrypt would have leaked
        # under that tag pre-fix).
        assert "username root secret 5" not in out
        # Review comment present, IOS-XE syntax (``! ``).
        assert (
            '! password manager user-name "root" -- review: bcrypt'
            in out
        )

    def test_cisco_md5crypt_passes_through(self) -> None:
        """``5 $1$..`` (Cisco md5crypt round-trip form) → ``secret 5
        $1$..``."""
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(
                    name="admin",
                    privilege_level=15,
                    hashed_password="5 $1$abc$xyz",
                ),
            ],
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "username admin privilege 15 secret 5 $1$abc$xyz" in out
        # No review comment for migratable hashes.
        assert "review:" not in out

    def test_cisco_type9_native_passes_through(self) -> None:
        """``9 $9$..`` (Cisco type-9 / scrypt) → ``secret 9 $9$..``."""
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(
                    name="netadmin",
                    privilege_level=15,
                    hashed_password="9 $9$fakeScryptHashHere",
                ),
            ],
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert (
            "username netadmin privilege 15 secret 9 "
            "$9$fakeScryptHashHere"
        ) in out

    def test_cisco_sha512_emits_review_comment(self) -> None:
        """Arista-source ``sha512:$6$..`` is NOT consumable on IOS-XE
        (sha512 isn't in the type 0/5/8/9 set).  Should emit comment."""
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(
                    name="alice",
                    hashed_password="arista:sha512:$6$saltSalt$hashHash",
                ),
            ],
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "$6$" not in out
        assert "sha512" in out  # algorithm name in the comment body
        assert "review:" in out

    def test_cisco_fortios_enc_emits_review_comment(self) -> None:
        """FortiGate-source ENC blob → not migratable; comment line."""
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(
                    name="bob",
                    hashed_password="fortios:AK1abc==",
                ),
            ],
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "AK1abc" not in out
        assert "fortios" in out
        assert (
            '! password manager user-name "bob"' in out
        )


# ---------------------------------------------------------------------------
# Finding #8 — empty interface stub elision
# ---------------------------------------------------------------------------


class TestStubElision:
    def test_cisco_foreign_port_stub_elided(self) -> None:
        """``igc0`` empty (no body, no VLAN ref) → not in output."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="igc0"),
            ],
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "interface igc0" not in out

    def test_cisco_native_port_no_body_kept(self) -> None:
        """``GigabitEthernet0/0`` empty → kept (round-trip stability
        for same-vendor source captures)."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="GigabitEthernet0/0"),
            ],
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "interface GigabitEthernet0/0" in out

    def test_cisco_native_loopback_no_body_kept(self) -> None:
        """``Loopback0`` empty → kept (matches the physical-port shape
        regex)."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="Loopback0"),
            ],
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "interface Loopback0" in out

    def test_cisco_native_port_channel_no_body_kept(self) -> None:
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="Port-channel10"),
            ],
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "interface Port-channel10" in out

    def test_cisco_vrf_referenced_foreign_port_kept(self) -> None:
        """A foreign port bound by a VRF → kept (vrf forwarding body
        keeps the body-content gate satisfied)."""
        intent = CanonicalIntent(
            routing_instances=[
                CanonicalRoutingInstance(name="MGMT"),
            ],
            interfaces=[
                CanonicalInterface(name="igc0", vrf="MGMT"),
            ],
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "interface igc0" in out
        assert "vrf forwarding MGMT" in out

    def test_cisco_vlan_referenced_foreign_port_kept(self) -> None:
        """A foreign port referenced from a VLAN port list → kept;
        the VLAN-projection transform synthesises ``switchport mode``
        body which makes it a normal-content render."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="igc0"),
            ],
            vlans=[
                CanonicalVlan(id=10, name="USER", untagged_ports=["igc0"]),
            ],
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "interface igc0" in out
        # The synthesised switchport body is what keeps it from being
        # elided (rather than the VLAN-membership reference branch).
        assert "switchport access vlan 10" in out

    def test_cisco_foreign_port_with_ip_kept(self) -> None:
        """Foreign port name with a body → kept (content gate)."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="igc0",
                    ipv4_addresses=[
                        CanonicalIPv4Address(
                            ip="10.0.0.1", prefix_length=24,
                        ),
                    ],
                ),
            ],
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "interface igc0" in out
        assert "ip address 10.0.0.1 255.255.255.0" in out

    def test_cisco_foreign_port_with_description_kept(self) -> None:
        """Description alone is enough body to keep the stub."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="igc0", description="WAN uplink",
                ),
            ],
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "interface igc0" in out
        assert "description WAN uplink" in out

    def test_cisco_disabled_foreign_port_kept(self) -> None:
        """``enabled=False`` is body content."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="igc0", enabled=False),
            ],
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "interface igc0" in out
        assert "shutdown" in out


# ---------------------------------------------------------------------------
# Finding #12 — domain emit regression guard
# ---------------------------------------------------------------------------


class TestDomainEmit:
    def test_cisco_domain_name_emitted(self) -> None:
        """``ip domain name <fqdn>`` already lands in the rendered
        config — pin the behaviour so a refactor can't drop it."""
        intent = CanonicalIntent(
            hostname="r1",
            domain="example.test",
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "ip domain name example.test" in out

    def test_cisco_no_domain_no_emit(self) -> None:
        """Empty ``domain`` → no ``ip domain name`` line (avoids
        emitting bare ``ip domain name`` syntax errors)."""
        intent = CanonicalIntent(hostname="r1")
        out = CiscoIOSXECLICodec().render(intent)
        assert "ip domain name" not in out
