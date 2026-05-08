"""Regression-guard: Arista EOS codec must declare ACL xpaths
``unsupported`` so operators pasting EOS configs with
``ip access-list extended`` / ``ip access-list standard`` / ``ipv6
access-list`` blocks are NOT silently dropped without a notification.

Wave 11-A — closes a silent-drop gap surfaced during the doc audit
follow-up.  Five sibling codecs (``aruba_aoss``, ``fortigate_cli``,
``mikrotik_routeros``, ``opnsense``, ``juniper_junos``) already
declare their firewall / ACL surfaces unsupported; this test
guarantees ``arista_eos`` follows suit.

The parser does NOT (yet) populate ``firewall_rules`` on
``CanonicalIntent``; the declarations are honest about Tier 3
status — ACL grammar is rich, vendor-specific, and auto-translation
risks shipping subtly-permissive rules.

See also:
- netcanon/migration/codecs/arista_eos/codec.py — where the
  declarations live
- tests/unit/migration/codecs/cisco_iosxe/test_capability_matrix_honesty.py
  — the canonical pattern for codec-honesty regression guards
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.arista_eos import AristaEOSCodec

pytestmark = pytest.mark.unit


_EXPECTED_ACL_XPATHS = (
    "/access-list/extended",
    "/access-list/standard",
    "/access-list/ipv6",
)


class TestACLDeclaredUnsupported:
    """Each ACL xpath the EOS grammar accepts must be declared
    ``unsupported`` so cross-vendor migrations surface a notification
    instead of silently dropping ACL stanzas."""

    def test_extended_acl_declared_unsupported(self) -> None:
        caps = AristaEOSCodec().capabilities
        unsupported_paths = {up.path for up in caps.unsupported}
        assert "/access-list/extended" in unsupported_paths, (
            "Arista EOS extended ACLs must be declared unsupported "
            "to honour the silent-drop gap surfaced in Wave 11-A."
        )

    def test_standard_acl_declared_unsupported(self) -> None:
        caps = AristaEOSCodec().capabilities
        unsupported_paths = {up.path for up in caps.unsupported}
        assert "/access-list/standard" in unsupported_paths

    def test_ipv6_acl_declared_unsupported(self) -> None:
        caps = AristaEOSCodec().capabilities
        unsupported_paths = {up.path for up in caps.unsupported}
        assert "/access-list/ipv6" in unsupported_paths

    def test_acl_reasons_cite_tier_3(self) -> None:
        """The ``reason`` field must explain WHY (Tier 3) so operators
        reading the unsupported-paths panel understand it's intentional,
        not a bug."""
        caps = AristaEOSCodec().capabilities
        for up in caps.unsupported:
            if up.path in _EXPECTED_ACL_XPATHS:
                assert up.reason is not None
                assert "Tier 3" in up.reason, (
                    f"{up.path!r} reason must cite 'Tier 3' to "
                    f"explain the auto-translation hazard; got: "
                    f"{up.reason!r}"
                )

    def test_acl_xpaths_classify_unsupported(self) -> None:
        """``CapabilityMatrix.classify`` must return ``'unsupported'``
        for these xpaths so :func:`validate_against` reports them in
        the unsupported-paths panel."""
        caps = AristaEOSCodec().capabilities
        for xp in _EXPECTED_ACL_XPATHS:
            assert caps.classify(xp) == "unsupported", (
                f"{xp!r} classifies as {caps.classify(xp)!r}; expected "
                f"'unsupported' so operators see a notification "
                f"instead of a silent drop."
            )


class TestExistingDeclarationsPreserved:
    """Regression guard — adding ACL declarations must NOT drop any
    pre-existing ``unsupported`` xpaths."""

    def test_routing_bgp_still_declared(self) -> None:
        caps = AristaEOSCodec().capabilities
        unsupported_paths = {up.path for up in caps.unsupported}
        assert "/routing/bgp" in unsupported_paths

    def test_routing_ospf_still_declared(self) -> None:
        caps = AristaEOSCodec().capabilities
        unsupported_paths = {up.path for up in caps.unsupported}
        assert "/routing/ospf" in unsupported_paths
