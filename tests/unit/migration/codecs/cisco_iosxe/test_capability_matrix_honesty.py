"""
Regression-guard: cisco_iosxe NETCONF codec's CapabilityMatrix must
honestly reflect its render coverage.

The cisco_iosxe codec is a Phase 0.5 stub whose ``_render_canonical()``
emits ONLY the ``openconfig-interfaces`` subtree.  Every other canonical
surface (system / vlans / static-routes / snmp / lags / local_users /
radius / dhcp / vrf / vxlan / evpn) lands on the canonical tree but is
silently dropped on render.

Wave 10β-A flagged the previous matrix as artifactual: it declared
those surfaces ``supported`` to keep cross-mesh translations from
classifying them as unsupported on the target side, but the actual
emit path was narrow.  Wave 10γ-2 lifted those un-rendered surfaces to
``unsupported`` so cross-mesh expectation YAMLs and the
:func:`netcanon.services.migration_validate.validate_against`
classifier reason against accurate capability data.

This module is the regression guard against a future render expansion
silently outpacing the matrix (or vice versa — a matrix loosening
without the render to back it up).  The pattern: build a
``CanonicalIntent`` populated with each top-level field, call
``codec.render(...)``, and assert that any field absent from the
rendered XML is declared ``unsupported`` in the codec's
:class:`CapabilityMatrix`.

When the cisco_iosxe render is genuinely expanded to walk e.g.
``intent.hostname`` and emit ``<system><config><hostname>``, this
test will fail loudly — at which point the operator should:

1. Move the corresponding ``UnsupportedPath`` to ``supported``.
2. Update :func:`netcanon.migration.codecs.cisco_iosxe_cli.codec._walk_canonical`
   if the new emission needs new xpath shapes.
3. Update the relevant per-pair YAMLs under
   ``tests/fixtures/cross_vendor_expectations/*__cisco_iosxe.yaml``
   to flip the disposition from ``unsupported`` to ``good`` / ``lossy``.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalEvpnType5Route,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalLAG,
    CanonicalLocalUser,
    CanonicalRADIUSServer,
    CanonicalRoutingInstance,
    CanonicalSNMP,
    CanonicalSNMPv3User,
    CanonicalStaticRoute,
    CanonicalVlan,
    CanonicalVxlan,
)
from netcanon.migration.codecs.cisco_iosxe import CiscoIOSXECodec

pytestmark = pytest.mark.unit


def _populate_kitchen_sink_intent() -> CanonicalIntent:
    """Build a CanonicalIntent that exercises every top-level field.

    Used to drive the render and observe what survives to the wire.
    Each field carries a sentinel value chosen to be readily-grep-able
    in the rendered output (e.g. distinctive names / IPs / hashes).
    """
    return CanonicalIntent(
        # ── Tier 1 scalars / lists ──
        hostname="iosxe-honest-stub",
        domain="example.test",
        dns_servers=["10.255.0.53", "10.255.0.54"],
        ntp_servers=["10.255.0.123"],
        timezone="UTC",
        syslog_servers=["10.255.0.514"],
        interfaces=[
            CanonicalInterface(
                name="GigabitEthernet0/0/0",
                description="WAN uplink — render guard",
                enabled=True,
                interface_type="ianaift:ethernetCsmacd",
                ipv4_addresses=[
                    CanonicalIPv4Address(ip="198.51.100.1", prefix_length=30),
                ],
                # The honest matrix declares ``/system/hostname`` etc.
                # unsupported but does NOT yet declare the per-interface
                # switchport sub-fields (no top-level field for them in
                # CanonicalIntent — they live on CanonicalInterface).
                # These attributes are populated to verify the render
                # observably ignores them; the matrix-level honesty
                # check below focuses on top-level fields.
                switchport_mode="access",
                access_vlan=10,
            ),
        ],
        vlans=[
            CanonicalVlan(
                id=10,
                name="USERS",
                tagged_ports=[],
                untagged_ports=["GigabitEthernet0/0/0"],
            ),
        ],
        static_routes=[
            CanonicalStaticRoute(
                destination="0.0.0.0/0",
                gateway="198.51.100.2",
            ),
        ],
        # ── Tier 2 ──
        dhcp_servers=[
            CanonicalDHCPPool(
                interface="GigabitEthernet0/0/0",
                network="192.0.2.0/24",
                start_ip="192.0.2.10",
                end_ip="192.0.2.100",
            ),
        ],
        snmp=CanonicalSNMP(
            community="readonly-guard",
            location="lab",
            contact="netops@example.test",
            trap_hosts=["10.255.0.10"],
            v3_users=[
                CanonicalSNMPv3User(
                    name="snmpv3-guard",
                    group="ro-group",
                    auth_protocol="sha",
                    auth_passphrase="$9$fake$auth",
                    priv_protocol="aes",
                    priv_passphrase="$9$fake$priv",
                ),
            ],
        ),
        lags=[
            CanonicalLAG(
                name="Port-Channel1",
                members=["GigabitEthernet0/0/1", "GigabitEthernet0/0/2"],
                mode="active",
            ),
        ],
        local_users=[
            CanonicalLocalUser(
                name="admin-guard",
                privilege_level=15,
                hashed_password="$9$fake$hash",
                role="admin",
            ),
        ],
        radius_servers=[
            CanonicalRADIUSServer(host="10.255.0.1812", key="$9$fake$radius"),
        ],
        # ── Tier 2 (ship-before-wire) ──
        vxlan_vnis=[
            CanonicalVxlan(
                vlan_id=10,
                vni=10010,
                source_interface="Loopback0",
            ),
        ],
        evpn_type5_routes=[
            CanonicalEvpnType5Route(
                vrf="TENANT-A",
                prefix="10.10.0.0/16",
            ),
        ],
        routing_instances=[
            CanonicalRoutingInstance(
                name="TENANT-A",
                instance_type="vrf",
                route_distinguisher="65000:100",
                rt_imports=["65000:100"],
                rt_exports=["65000:100"],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Top-level fields the render path is observed to walk.  Driven by
# inspection of ``CiscoIOSXECodec._render_canonical``.  Update in lockstep
# whenever the render is genuinely expanded.
# ---------------------------------------------------------------------------

#: Top-level CanonicalIntent fields the cisco_iosxe NETCONF render
#: walks to XML.  Anything outside this set is dropped on render.
_RENDERED_TOP_LEVEL_FIELDS: frozenset[str] = frozenset({
    "interfaces",
})


#: Top-level CanonicalIntent fields the render path observably DROPS.
#: Every entry here MUST appear in the codec's
#: :class:`CapabilityMatrix.unsupported` list as ``f\"/{field}\"`` so
#: ``run_full_mesh.py``'s field-disposition matrix can flip
#: ``unsupported_in_target=True`` for these cells.  Mirror of the
#: positive ``_RENDERED_TOP_LEVEL_FIELDS`` set above.
_DROPPED_TOP_LEVEL_FIELDS: frozenset[str] = frozenset({
    "hostname",
    "domain",
    "dns_servers",
    "ntp_servers",
    "timezone",
    "syslog_servers",
    "vlans",
    "static_routes",
    "dhcp_servers",
    "snmp",
    "lags",
    "local_users",
    "radius_servers",
    "vxlan_vnis",
    "evpn_type5_routes",
    "routing_instances",
})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRenderCoverageHonesty:
    """The matrix's `unsupported` set must mirror what render observably
    drops; the matrix's `supported` set must mirror what render emits.
    """

    def test_render_emits_only_interfaces_subtree(self):
        """Walk a kitchen-sink CanonicalIntent through the render and
        confirm every non-``interfaces`` sentinel is absent from the
        output.  Regression guard against a partial render expansion
        landing without a matrix update."""
        intent = _populate_kitchen_sink_intent()
        rendered = CiscoIOSXECodec().render(intent)

        # Hostname / domain / DNS / NTP / timezone / syslog sentinels.
        assert "iosxe-honest-stub" not in rendered, (
            "intent.hostname leaked into rendered output — render path "
            "expanded; update matrix to move /system/hostname + /hostname "
            "from `unsupported` to `supported`."
        )
        assert "example.test" not in rendered
        assert "10.255.0.53" not in rendered
        assert "10.255.0.123" not in rendered
        assert "10.255.0.514" not in rendered
        # VLAN sentinel name.
        assert "USERS" not in rendered
        # Static-route sentinel.
        assert "198.51.100.2" not in rendered
        # DHCP sentinel.
        assert "192.0.2." not in rendered
        # SNMP sentinels.
        assert "readonly-guard" not in rendered
        assert "snmpv3-guard" not in rendered
        # LAG sentinel.
        assert "Port-Channel1" not in rendered
        # Local-user sentinel.
        assert "admin-guard" not in rendered
        # RADIUS sentinel.
        assert "10.255.0.1812" not in rendered
        # VXLAN / EVPN sentinels.
        assert "Loopback0" not in rendered
        assert "TENANT-A" not in rendered
        # Interface sentinel SHOULD appear (positive control).
        assert "GigabitEthernet0/0/0" in rendered

    def test_dropped_fields_declared_unsupported_at_top_level(self):
        """Every field in :data:`_DROPPED_TOP_LEVEL_FIELDS` must appear
        in the codec's :class:`CapabilityMatrix.unsupported` list with
        the top-level ``f\"/{field}\"`` xpath shape (or under a documented
        prefix mapping in :mod:`tools.run_full_mesh`).  The matrix tool
        consumes either shape to flag the field as
        ``unsupported_in_target=True``."""
        caps = CiscoIOSXECodec().capabilities
        unsupported_paths = {up.path for up in caps.unsupported}

        # Mirrors tools/run_full_mesh.py::_FIELD_TO_XPATH_PREFIX.
        # Fields covered by a prefix get `unsupported_in_target` from
        # any xpath under the prefix; other fields need exact
        # `/<field>`.
        prefix_covered = {
            "vxlan_vnis": "/vxlan-vnis/",
            "evpn_type5_routes": "/evpn-type5/",
            "routing_instances": "/routing-instances/",
        }

        for field in _DROPPED_TOP_LEVEL_FIELDS:
            prefix = prefix_covered.get(field)
            if prefix:
                # Either prefix-match OR exact `/<field>` works.
                ok = (
                    any(p.startswith(prefix) for p in unsupported_paths)
                    or f"/{field}" in unsupported_paths
                )
                assert ok, (
                    f"render drops intent.{field} but no /{field}-family "
                    f"xpath (prefix {prefix!r} or exact /{field}) is "
                    f"declared unsupported.  Add an UnsupportedPath."
                )
            else:
                assert f"/{field}" in unsupported_paths, (
                    f"render drops intent.{field} but the matrix's "
                    f"unsupported list contains no exact /{field} "
                    f"declaration.  Add UnsupportedPath(path='/{field}', "
                    f"reason=...) so run_full_mesh.py recognises this "
                    f"field as unsupported-in-target."
                )

    def test_rendered_fields_not_in_unsupported(self):
        """The render-emitted top-level field MUST NOT appear in
        ``unsupported`` (otherwise the matrix lies in the OTHER
        direction).  Self-consistency check between the positive and
        negative coverage sets."""
        caps = CiscoIOSXECodec().capabilities
        unsupported_paths = {up.path for up in caps.unsupported}
        for field in _RENDERED_TOP_LEVEL_FIELDS:
            assert f"/{field}" not in unsupported_paths, (
                f"render emits intent.{field} but the matrix declares "
                f"/{field} as unsupported — contradiction.  Remove the "
                f"UnsupportedPath or add the field to "
                f"_RENDERED_TOP_LEVEL_FIELDS guard set."
            )

    def test_no_overlap_between_supported_and_unsupported(self):
        """Strictness: no xpath should appear in BOTH the supported
        and unsupported lists.  Catches drift from copy-paste."""
        caps = CiscoIOSXECodec().capabilities
        sup = set(caps.supported)
        unsup = {up.path for up in caps.unsupported}
        overlap = sup & unsup
        assert not overlap, (
            f"xpath(s) declared as both supported AND unsupported: {overlap}"
        )


class TestGranularXpathDeclarations:
    """The granular xpaths emitted by ``_walk_canonical`` for un-rendered
    surfaces must classify as ``unsupported`` so
    :func:`validate_against` correctly flags them on cross-codec runs.
    """

    def test_walker_xpaths_for_unrendered_surfaces_classify_unsupported(self):
        """For each canonical-walker xpath that corresponds to an
        un-rendered surface, the matrix's ``classify`` method must
        return ``"unsupported"``."""
        caps = CiscoIOSXECodec().capabilities
        # Granular xpath shapes from _walk_canonical that target
        # un-rendered surfaces.  Mirrors the canonical walker's emit
        # shapes — see netcanon.migration.codecs.cisco_iosxe_cli.codec
        # ._walk_canonical.
        unrendered_walker_xpaths = [
            "/system/hostname",
            "/system/dns-server",
            "/system/ntp-server",
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/routing/static-route",
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/trap-host",
            "/snmp/v3-user",
        ]
        for xp in unrendered_walker_xpaths:
            assert caps.classify(xp) == "unsupported", (
                f"{xp!r} classifies as {caps.classify(xp)!r}; expected "
                f"`unsupported` because the cisco_iosxe NETCONF render "
                f"does not emit this surface."
            )

    def test_interface_subtree_xpaths_classify_supported(self):
        """Positive control: the interface subtree xpaths the render
        DOES emit must classify as ``supported``."""
        caps = CiscoIOSXECodec().capabilities
        rendered_walker_xpaths = [
            "/interfaces/interface/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/config/type",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/interfaces/interface/ipv6/address/ip",
            "/interfaces/interface/ipv6/address/prefix-length",
        ]
        for xp in rendered_walker_xpaths:
            assert caps.classify(xp) == "supported", (
                f"{xp!r} classifies as {caps.classify(xp)!r}; expected "
                f"`supported` — this xpath is emitted by "
                f"_render_canonical()."
            )
