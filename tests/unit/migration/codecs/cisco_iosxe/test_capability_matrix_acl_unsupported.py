"""Regression-guard: Cisco IOS-XE NETCONF codec must declare ACL /
firewall xpaths ``unsupported`` so operators sending OpenConfig ACL
or zone-based-firewall payloads are NOT silently dropped without a
notification.

Wave 11-A — closes a silent-drop gap surfaced during the doc audit
follow-up.  Five sibling codecs (``aruba_aoss``, ``fortigate_cli``,
``mikrotik_routeros``, ``opnsense``, ``juniper_junos``) already
declare their firewall / ACL surfaces unsupported; this test
guarantees ``cisco_iosxe`` follows suit.

The codec is a Phase 0.5 stub — render emits only the
``openconfig-interfaces`` subtree.  ACL / ZBF subtrees were
previously absent from the matrix at all, so cross-mesh validation
classified them as ``unknown`` rather than ``unsupported``.  This
declaration makes the silent-drop honest.

See also:
- netconfig/migration/codecs/cisco_iosxe/codec.py — declaration site
- tests/unit/migration/codecs/cisco_iosxe/test_capability_matrix_honesty.py
  — sibling regression guard for render-vs-matrix coverage
"""

from __future__ import annotations

import pytest

from netconfig.migration.codecs.cisco_iosxe import CiscoIOSXECodec

pytestmark = pytest.mark.unit


_EXPECTED_ACL_FIREWALL_XPATHS = (
    "/access-list",
    "/firewall",
)


class TestACLFirewallDeclaredUnsupported:
    """Each ACL / firewall xpath must be declared ``unsupported`` so
    cross-vendor migrations surface a notification instead of silently
    dropping these stanzas."""

    def test_access_list_declared_unsupported(self) -> None:
        caps = CiscoIOSXECodec().capabilities
        unsupported_paths = {up.path for up in caps.unsupported}
        assert "/access-list" in unsupported_paths, (
            "OpenConfig `acl` / IETF `ietf-access-control-list` "
            "subtrees must be declared unsupported to honour the "
            "silent-drop gap surfaced in Wave 11-A."
        )

    def test_firewall_declared_unsupported(self) -> None:
        caps = CiscoIOSXECodec().capabilities
        unsupported_paths = {up.path for up in caps.unsupported}
        assert "/firewall" in unsupported_paths, (
            "Zone-based firewall / CBAC subtrees must be declared "
            "unsupported to honour the silent-drop gap surfaced in "
            "Wave 11-A."
        )

    def test_acl_firewall_reasons_cite_tier_3(self) -> None:
        caps = CiscoIOSXECodec().capabilities
        for up in caps.unsupported:
            if up.path in _EXPECTED_ACL_FIREWALL_XPATHS:
                assert up.reason is not None
                assert "Tier 3" in up.reason, (
                    f"{up.path!r} reason must cite 'Tier 3' to "
                    f"explain the auto-translation hazard; got: "
                    f"{up.reason!r}"
                )

    def test_acl_firewall_xpaths_classify_unsupported(self) -> None:
        caps = CiscoIOSXECodec().capabilities
        for xp in _EXPECTED_ACL_FIREWALL_XPATHS:
            assert caps.classify(xp) == "unsupported", (
                f"{xp!r} classifies as {caps.classify(xp)!r}; expected "
                f"'unsupported'."
            )


class TestExistingDeclarationsPreserved:
    """Regression guard — adding ACL / firewall declarations must NOT
    drop any pre-existing ``unsupported`` xpaths."""

    def test_top_level_field_markers_preserved(self) -> None:
        caps = CiscoIOSXECodec().capabilities
        unsupported_paths = {up.path for up in caps.unsupported}
        # Spot-check a representative slice of the Phase 0.5 stub
        # markers — the broader honesty sweep lives in
        # test_capability_matrix_honesty.py.
        for required in (
            "/system/hostname",
            "/snmp/community",
            "/vxlan-vnis/vni",
            "/routing-instances/instance",
            "/hostname",
            "/snmp",
            "/vlans",
        ):
            assert required in unsupported_paths, (
                f"existing UnsupportedPath {required!r} dropped — "
                f"Wave 11-A must only ADD ACL/firewall declarations, "
                f"not remove pre-existing ones."
            )
