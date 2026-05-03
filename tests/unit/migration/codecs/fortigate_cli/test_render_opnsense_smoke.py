"""
FortiGate CLI render-side regression tests for OPNsense supergate
user-smoke findings -- ``tests/fixtures/real/user_smoke_findings.md``
issues 5, 6, 8, 12.

* **Finding 5** -- VLAN child interfaces had ``set type vlan`` /
  ``set vlanid`` / ``set interface`` but NO ``set ip`` line, because
  the ``_build_vlan_children`` helper looked up SVI IPs only on
  ``CanonicalVlan.ipv4_addresses``.  OPNsense source stores VLAN SVI
  IPs on the corresponding ``<optN>`` zone (parsed as a
  :class:`CanonicalInterface` named ``vlan0.<id>``), not on the
  ``<vlans><vlan>`` record itself.  Five OPNsense L3 networks
  vanished from FortiGate output.

* **Finding 6** -- VLAN child ``set interface`` line bound every
  VLAN to ``igc0`` (the WAN), not the LAN port.  The parent-port
  lookup walked the FULL canonical interface list which still
  contained the WAN stub; the renderer now passes the elided list
  (post-Finding-8 stub-removal) so the fallback lands on the LAN.

* **Finding 8** -- ``edit "igc0"`` empty-stub literal stayed in the
  rendered output.  OPNsense's ``<wan><if>igc0</if><ipaddr>dhcp
  </ipaddr></wan>`` parses to a content-free CanonicalInterface
  (FortiGate has no DHCP-client representation in canonical), and
  the foreign-shaped name (``igc0`` is OPNsense's igc(4) driver
  name) leaks through verbatim because port-name classification
  hits ``unknown``.  Mirror Junos's tiered elision policy
  (``juniper_junos/render.py``, commit ``0fdf7e9``): elide empty
  stubs whose name doesn't match a FortiGate-native physical-port
  shape.

* **Finding 12** -- ``<domain>example.test</domain>`` from OPNsense
  ``<system>`` was dropped on the FortiGate side because the
  renderer never emitted ``set domain`` inside ``config system
  dns``.  Per FortiOS 7.x CLI reference (docs.fortinet.com/document/
  fortigate/7.6.6/cli-reference/190194324/config-system-dns) the
  ``set domain "<value>"`` field belongs inside the ``config system
  dns`` block.

Approach for Finding 5+6 also exercises a port_names.py change:
``format_port_identity`` now returns ``vlan<id>`` for SVI identities
(was None), so the cross-vendor SVI iface and its
``ipv4_addresses`` survive the ``translate_port_names`` rename pass
and reach ``_build_vlan_children``'s sibling-iface walk where the
IP gets absorbed into the synthetic vlan child entry.
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalIPv4Address,
    CanonicalInterface,
    CanonicalLAG,
    CanonicalVlan,
)
from netconfig.migration.canonical.port_names import (
    PortIdentity,
    translate_port_names,
)
from netconfig.migration.codecs.fortigate_cli import FortiGateCLICodec
from netconfig.migration.codecs.fortigate_cli.port_names import (
    format_port_identity,
)
from netconfig.migration.codecs.fortigate_cli.render import (
    _build_vlan_children,
    _iface_is_empty_stub,
    _is_fortigate_native_name,
)
from netconfig.migration.codecs.opnsense import OPNsenseCodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Finding 5 -- SVI IP lookup walks tree.interfaces by vlan_id
# ---------------------------------------------------------------------------


class TestFinding5SviIpFromInterfaceList:
    """``_build_vlan_children`` previously read SVI IP only from
    ``CanonicalVlan.ipv4_addresses``.  Cisco-source paths pre-merge
    ``interface Vlan<N>`` IPs into the VLAN record so the lookup
    succeeded; OPNsense-source paths leave the IP on the canonical
    interface ``vlan0.<id>`` only.  Extended lookup walks all
    interfaces by ``_vlan_id_for(name, vlans)`` and copies the IP
    from the first match."""

    def test_svi_ip_resolved_via_dotted_iface_name(self) -> None:
        """OPNsense-style: SVI iface named ``vlan0.10`` carries the
        IP; canonical VLAN id 10 has empty ipv4.  The vlan-id walk
        in ``_build_vlan_children`` matches ``vlan0.10`` -> id 10
        and copies the address."""
        vlan = CanonicalVlan(id=10, name="USERVLAN")
        svi_iface = CanonicalInterface(
            name="vlan0.10",
            interface_type="ianaift:l3ipvlan",
            ipv4_addresses=[
                CanonicalIPv4Address(ip="192.168.10.1", prefix_length=24),
            ],
        )
        physical = CanonicalInterface(
            name="port1",
            interface_type="ianaift:ethernetCsmacd",
        )
        tree = CanonicalIntent(vlans=[vlan], interfaces=[physical, svi_iface])
        children = _build_vlan_children(tree, tree.interfaces)
        assert len(children) == 1
        c = children[0]
        assert c["vlanid"] == 10
        assert c["ip"] == "192.168.10.1"
        assert c["mask"] == "255.255.255.0"
        assert c["parent"] == "port1"

    def test_svi_ip_resolved_via_native_vlanN_iface_name(self) -> None:
        """Cross-vendor SVI iface arriving with FortiGate-native
        ``vlan<id>`` naming (post-rename through the new
        ``format_port_identity`` SVI branch) is also picked up by
        the vlan-id walk."""
        vlan = CanonicalVlan(id=11, name="mgmt")
        svi_iface = CanonicalInterface(
            name="vlan11",
            interface_type="ianaift:l3ipvlan",
            ipv4_addresses=[
                CanonicalIPv4Address(ip="10.11.0.1", prefix_length=24),
            ],
        )
        physical = CanonicalInterface(
            name="port1",
            interface_type="ianaift:ethernetCsmacd",
        )
        tree = CanonicalIntent(vlans=[vlan], interfaces=[physical, svi_iface])
        children = _build_vlan_children(tree, tree.interfaces)
        # The native-named SVI iface shares its name with the synth
        # child, so the renderer's existing dedup will use the iface
        # emit path; the helper still computes the metadata.
        assert children[0]["ip"] == "10.11.0.1"

    def test_canonical_vlan_ipv4_takes_precedence(self) -> None:
        """When BOTH the VLAN record and a sibling iface carry IPs,
        the VLAN's record wins -- the legacy fast path stays."""
        vlan = CanonicalVlan(
            id=20,
            name="prod",
            ipv4_addresses=[
                CanonicalIPv4Address(ip="10.20.0.1", prefix_length=24),
            ],
        )
        svi_iface = CanonicalInterface(
            name="vlan0.20",
            interface_type="ianaift:l3ipvlan",
            ipv4_addresses=[
                CanonicalIPv4Address(ip="172.20.0.1", prefix_length=24),
            ],
        )
        physical = CanonicalInterface(
            name="port1",
            interface_type="ianaift:ethernetCsmacd",
        )
        tree = CanonicalIntent(vlans=[vlan], interfaces=[physical, svi_iface])
        children = _build_vlan_children(tree, tree.interfaces)
        assert children[0]["ip"] == "10.20.0.1"


# ---------------------------------------------------------------------------
# Finding 6 -- VLAN parent prefers LAN over WAN-stub
# ---------------------------------------------------------------------------


class TestFinding6VlanParentNotWanStub:
    """When the canonical tree has a content-free WAN stub (OPNsense
    ``igc0`` with ``<ipaddr>dhcp</ipaddr>`` -- no static IP, no
    description) sitting before the LAN port in the iface list, the
    naive "first non-VLAN" parent fallback picks the WAN.  After
    Finding 8's stub elision, the WAN stub is removed BEFORE the
    parent lookup runs, so the fallback naturally lands on the LAN."""

    def test_vlan_parent_skips_wan_stub_and_picks_lan(self) -> None:
        """Two physicals: ``igc0`` (no IP, no description) +
        ``port1`` (LAN with IP).  Both are non-VLAN-shaped, so the
        legacy fallback picked ``igc0``.  After elision ``port1``
        wins."""
        tree = CanonicalIntent(
            hostname="supergate",
            interfaces=[
                CanonicalInterface(
                    name="igc0",
                    enabled=True,
                ),
                CanonicalInterface(
                    name="port1",
                    interface_type="ianaift:ethernetCsmacd",
                    enabled=True,
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="192.168.88.2", prefix_length=24),
                    ],
                ),
            ],
            vlans=[CanonicalVlan(id=10, name="users")],
        )
        out = FortiGateCLICodec().render(tree)
        assert 'set interface "port1"' in out
        assert 'set interface "igc0"' not in out


# ---------------------------------------------------------------------------
# Finding 8 -- empty-stub elision via tiered policy
# ---------------------------------------------------------------------------


class TestFinding8EmptyStubElision:
    """Mirror the Junos tiered elision policy (commit ``0fdf7e9``):
    skip empty stubs whose name doesn't match a FortiGate-native
    physical-port shape (``port<N>``, ``mgmt<N>``, ``wan<N>``,
    ``lan<N>``, ``vlan<N>``, ``loopback<N>``, ``fortilink<N>``,
    ``[ab]``, ``ssl.root``, ``gre<N>``, ``port-<s>-<m>-<p>``).
    FortiGate-native names are kept for round-trip stability."""

    def test_foreign_empty_stub_elided(self) -> None:
        """OPNsense ``igc0`` arriving as content-free stub should
        not appear as ``edit "igc0"`` in the rendered output."""
        tree = CanonicalIntent(
            hostname="x",
            interfaces=[
                CanonicalInterface(name="igc0", enabled=True),
                CanonicalInterface(
                    name="port1",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.0.0.1", prefix_length=24),
                    ],
                ),
            ],
        )
        out = FortiGateCLICodec().render(tree)
        assert 'edit "igc0"' not in out
        assert 'edit "port1"' in out

    def test_fortigate_native_empty_stub_preserved(self) -> None:
        """Same-vendor round-trip: FortiGate's own ``port5`` may
        appear in source config with no body (operator-disabled or
        unconfigured but explicitly named).  Keep the bare ``edit
        "port5" / set status up`` block so reparse round-trips."""
        tree = CanonicalIntent(
            hostname="x",
            interfaces=[
                CanonicalInterface(name="port5", enabled=True),
            ],
        )
        out = FortiGateCLICodec().render(tree)
        assert 'edit "port5"' in out

    def test_native_shapes_match_predicate(self) -> None:
        """Spot-check: every FortiGate-native shape from the
        per-chassis port catalogue resolves as native."""
        for name in (
            "port1", "port24", "port-1-1-1",
            "mgmt", "mgmt1", "mgmt2",
            "wan1", "wan2",
            "lan", "lan1",
            "dmz", "dmz1",
            "internal", "internal1",
            "vlan10", "vlan100",
            "loopback0", "loopback7",
            "fortilink", "fortilink1",
            "a", "b",
            "ssl.root",
            "gre1",
        ):
            assert _is_fortigate_native_name(name), name

    def test_foreign_shapes_do_not_match_predicate(self) -> None:
        """Negative coverage: foreign-vendor port names are not
        recognised as FortiGate-native.  ``Vlan100`` (Cisco SVI) is
        DELIBERATELY excluded -- the case-insensitive ``vlan<N>``
        match catches both Cisco-style ``Vlan100`` and FortiGate-
        native ``vlan100``, which is the desired behaviour for
        Finding 5: a Cisco source ``Vlan100`` carrying an IP should
        be treated as a vlan child, not elided as a foreign stub."""
        for name in (
            "igc0", "ixl0", "lo0",          # OPNsense / FreeBSD
            "ge-0/0/0", "xe-0/0/24",       # Junos
            "ether1", "sfp-sfpplus1",       # MikroTik
            "GigabitEthernet1/0/1",         # Cisco IOS-XE
            "Ethernet1",                    # Arista
            "VL_100", "DATA",               # FortiGate user-named
                                            # (intentionally not
                                            # in the native shape;
                                            # kept via interface_type
                                            # check, not name)
        ):
            assert not _is_fortigate_native_name(name), name

    def test_iface_with_description_not_empty(self) -> None:
        """An interface carrying a description is meaningful even
        without an IP -- elide guard must not remove it."""
        iface = CanonicalInterface(
            name="igc0",
            description="Uplink to ISP",
            enabled=True,
        )
        assert _iface_is_empty_stub(iface) is False

    def test_iface_with_interface_type_set_not_empty(self) -> None:
        """FortiGate-source virtual ifaces (``ssl.root``,
        ``l2t.root``, ``naf.root``, ``default-mesh``, SD-WAN
        ``HUB1-O1``) parse with ``interface_type=
        "ianaift:ethernetCsmacd"`` and zero per-iface attrs.  Their
        intra-vendor round-trip stability requires preserving them
        even though ``_is_fortigate_native_name`` doesn't recognise
        the user-chosen name -- the non-empty interface_type is the
        load-bearing signal."""
        iface = CanonicalInterface(
            name="HUB1-O1",
            interface_type="ianaift:ethernetCsmacd",
            enabled=True,
        )
        assert _iface_is_empty_stub(iface) is False

    def test_iface_with_lag_member_not_empty(self) -> None:
        """LAG-member ifaces (``lag_member_of`` set) carry the
        bundling intent and must survive elision."""
        iface = CanonicalInterface(
            name="igc0",
            lag_member_of="LAG1",
            enabled=True,
        )
        assert _iface_is_empty_stub(iface) is False


# ---------------------------------------------------------------------------
# Finding 12 -- domain name emit
# ---------------------------------------------------------------------------


class TestFinding12DomainEmit:
    """``CanonicalIntent.domain`` (set by OPNsense parse from
    ``<system><domain>``) must surface inside ``config system dns``
    as ``set domain "<value>"`` -- the FortiOS-native form."""

    def test_domain_emitted_inside_system_dns(self) -> None:
        tree = CanonicalIntent(
            hostname="supergate",
            domain="example.test",
        )
        out = FortiGateCLICodec().render(tree)
        assert "config system dns" in out
        assert 'set domain "example.test"' in out

    def test_domain_alongside_dns_servers(self) -> None:
        """Domain emit doesn't disturb the existing DNS-resolver
        emit -- both lines appear in the same block."""
        tree = CanonicalIntent(
            hostname="supergate",
            domain="example.test",
            dns_servers=["1.1.1.1", "8.8.8.8"],
        )
        out = FortiGateCLICodec().render(tree)
        assert "set primary 1.1.1.1" in out
        assert "set secondary 8.8.8.8" in out
        assert 'set domain "example.test"' in out

    def test_no_domain_no_dns_block_when_empty(self) -> None:
        """Negative case: empty canonical -> no system dns block."""
        tree = CanonicalIntent(hostname="x")
        out = FortiGateCLICodec().render(tree)
        assert "config system dns" not in out

    def test_domain_only_emits_dns_block(self) -> None:
        """Domain-only canonical (no resolver IPs -- WAN gets DNS
        from upstream DHCP) still emits the system dns block so the
        FQDN suffix survives the migration."""
        tree = CanonicalIntent(hostname="x", domain="example.test")
        out = FortiGateCLICodec().render(tree)
        assert "config system dns" in out
        assert 'set domain "example.test"' in out
        # No primary/secondary because no resolver IPs.
        assert "set primary" not in out
        assert "set secondary" not in out


# ---------------------------------------------------------------------------
# port_names.py SVI branch supports Findings 5 + 6
# ---------------------------------------------------------------------------


class TestSviIdentityFormatsAsVlanN:
    """Cross-vendor SVI identities (``kind="svi"``) now format to
    ``vlan<index>`` rather than None.  This means the SVI iface
    (carrying ``ipv4_addresses``) survives ``translate_port_names``
    rather than being auto-dropped, so ``_build_vlan_children``'s
    sibling-iface walk can absorb the IP."""

    def test_svi_identity_returns_vlanN(self) -> None:
        ident = PortIdentity(kind="svi", index=10, original="vlan0.10")
        assert format_port_identity(ident) == "vlan10"

    def test_svi_without_index_returns_none(self) -> None:
        """No index -> no deterministic name (defensive: an SVI
        identity without an index is malformed; return None to fall
        through the orchestrator's auto-drop / warn path)."""
        ident = PortIdentity(kind="svi", original="weird-svi")
        assert format_port_identity(ident) is None


# ---------------------------------------------------------------------------
# End-to-end: OPNsense supergate fixture exercises Findings 5/6/8/12
# ---------------------------------------------------------------------------


class TestOpnsenseSupergateEndToEnd:
    """Full pipeline: real OPNsense supergate fixture parse ->
    rename -> FortiGate render.  Acts as a smoke regression for the
    full Phase 4 OPNsense -> FortiGate path."""

    def _render_supergate(self) -> str:
        from pathlib import Path
        xml_path = (
            Path(__file__).resolve().parents[4]
            / "fixtures" / "real" / "opnsense"
            / "user_contrib_supergate_opn25.xml"
        )
        if not xml_path.exists():
            pytest.skip(f"fixture missing: {xml_path}")
        xml = xml_path.read_text()
        src = OPNsenseCodec()
        tgt = FortiGateCLICodec()
        intent = src.parse(xml)
        translate_port_names(intent, src, tgt)
        return tgt.render(intent)

    def test_no_igc0_stub(self) -> None:
        """Finding 8: WAN stub elided."""
        out = self._render_supergate()
        assert 'edit "igc0"' not in out

    def test_vlan_children_have_ip(self) -> None:
        """Finding 5: each of the 5 OPNsense VLANs gets an IP."""
        out = self._render_supergate()
        # All 5 source VLANs have SVI IPs that must round-trip.
        assert "set ip 192.168.10.1 255.255.255.0" in out
        assert "set ip 192.168.11.1 255.255.255.0" in out
        assert "set ip 192.168.20.1 255.255.255.0" in out
        assert "set ip 10.10.10.100 255.255.255.0" in out
        assert "set ip 192.168.150.1 255.255.255.0" in out

    def test_vlan_children_anchored_on_lan(self) -> None:
        """Finding 6: VLAN parent is the LAN (port1, which is the
        renamed ixl0), not the WAN."""
        out = self._render_supergate()
        # No vlan child should anchor on the WAN.
        assert 'set interface "igc0"' not in out
        # All vlan children should anchor on port1 (the renamed LAN).
        assert out.count('set interface "port1"') >= 5

    def test_domain_emitted(self) -> None:
        """Finding 12: domain example.test surfaces."""
        out = self._render_supergate()
        assert 'set domain "example.test"' in out
