"""Regression-guard: Cisco IOS-XE CLI codec must declare ACL /
firewall / NAT xpaths ``unsupported`` so operators pasting Cisco
configs with ``ip access-list`` / ``zone-pair security`` / ``ip nat
inside source`` blocks are NOT silently dropped without a
notification.

Wave 11-A — closes a silent-drop gap surfaced during the doc audit
follow-up.  Five sibling codecs (``aruba_aoss``, ``fortigate_cli``,
``mikrotik_routeros``, ``opnsense``, ``juniper_junos``) already
declare their firewall / ACL surfaces unsupported; this test
guarantees ``cisco_iosxe_cli`` follows suit.

cisco_iosxe_cli has the richest firewall surface among Cisco
codecs because it parses ``show running-config`` text directly —
hence it gets ACL (extended / standard / ipv6) plus zone-based
firewall plus NAT declarations.

See also:
- netcanon/migration/codecs/cisco_iosxe_cli/codec.py — declaration
  site
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec

pytestmark = pytest.mark.unit


_EXPECTED_FIREWALL_XPATHS = (
    "/access-list/extended",
    "/access-list/standard",
    "/access-list/ipv6",
    "/firewall",
    "/nat",
)


class TestACLFirewallNATDeclaredUnsupported:
    """Each ACL / firewall / NAT xpath the IOS-XE CLI grammar accepts
    must be declared ``unsupported`` so cross-vendor migrations
    surface a notification instead of silently dropping these
    stanzas."""

    def test_extended_acl_declared_unsupported(self) -> None:
        caps = CiscoIOSXECLICodec().capabilities
        unsupported_paths = {up.path for up in caps.unsupported}
        assert "/access-list/extended" in unsupported_paths

    def test_standard_acl_declared_unsupported(self) -> None:
        caps = CiscoIOSXECLICodec().capabilities
        unsupported_paths = {up.path for up in caps.unsupported}
        assert "/access-list/standard" in unsupported_paths

    def test_ipv6_acl_declared_unsupported(self) -> None:
        caps = CiscoIOSXECLICodec().capabilities
        unsupported_paths = {up.path for up in caps.unsupported}
        assert "/access-list/ipv6" in unsupported_paths

    def test_firewall_declared_unsupported(self) -> None:
        caps = CiscoIOSXECLICodec().capabilities
        unsupported_paths = {up.path for up in caps.unsupported}
        assert "/firewall" in unsupported_paths

    def test_nat_declared_unsupported(self) -> None:
        caps = CiscoIOSXECLICodec().capabilities
        unsupported_paths = {up.path for up in caps.unsupported}
        assert "/nat" in unsupported_paths

    def test_firewall_reasons_cite_tier_3(self) -> None:
        caps = CiscoIOSXECLICodec().capabilities
        for up in caps.unsupported:
            if up.path in _EXPECTED_FIREWALL_XPATHS:
                assert up.reason is not None
                assert "Tier 3" in up.reason, (
                    f"{up.path!r} reason must cite 'Tier 3' to "
                    f"explain the auto-translation hazard; got: "
                    f"{up.reason!r}"
                )

    def test_firewall_xpaths_classify_unsupported(self) -> None:
        caps = CiscoIOSXECLICodec().capabilities
        for xp in _EXPECTED_FIREWALL_XPATHS:
            assert caps.classify(xp) == "unsupported", (
                f"{xp!r} classifies as {caps.classify(xp)!r}; expected "
                f"'unsupported'."
            )


class TestExistingDeclarationsPreserved:
    """Regression guard — adding ACL / firewall / NAT declarations
    must NOT drop any pre-existing ``unsupported`` xpaths."""

    def test_existing_unsupported_paths_preserved(self) -> None:
        # NOTE: ``/routing-instances/instance`` was historically in
        # this list with reason "wire-up deferred" but the declaration
        # was always stale — parse._parse_routing_instances + render
        # VRF emission have shipped since the early codec.  Wave 10β-B
        # (commit `40de39c`) re-flipped the per-pair YAML disposition.
        # The post-validation cleanup (commit following `170a2c2`)
        # moved the declaration from ``unsupported`` to ``lossy`` to
        # match reality.  See
        # ``test_capability_matrix_vrf_lossy.py`` for the corrected
        # invariant.
        caps = CiscoIOSXECLICodec().capabilities
        unsupported_paths = {up.path for up in caps.unsupported}
        for required in (
            "/interfaces/interface/subinterfaces/subinterface/ipv6",
            "/vxlan-vnis/vni",
            "/vxlan-vnis/source-interface",
            "/vxlan-vnis/udp-port",
        ):
            assert required in unsupported_paths, (
                f"existing UnsupportedPath {required!r} dropped — "
                f"Wave 11-A must only ADD ACL/firewall/NAT "
                f"declarations, not remove pre-existing ones."
            )
