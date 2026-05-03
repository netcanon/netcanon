"""
FortiGate CLI render-side regression tests for Phase 4 user-smoke fixes.

Covers three issues surfaced by manual cross-vendor smoke-testing of a
real Cisco c9300 ``show running-config`` paste against the FortiGate
target -- see ``tests/fixtures/real/user_smoke_findings.md`` issues
1, 2, 6 for the original report:

* **Issue 1a** -- type-9 / sha512 / bcrypt source hashes were leaking
  through ``set password ENC <foreign-blob>`` lines, accepted by
  FortiOS as garbage instead of being flagged for operator reset.
* **Issue 2** -- Cisco multi-module sources (Te1/0/1 + Gi1/1/1 +
  Te1/1/1 + ...) collapsed to a single ``port1``, producing duplicate
  ``edit "port1"`` blocks that FortiOS rejects on commit.
* **Issue 6** -- canonical VLANs with SVI IPs were silently dropped on
  the way to FortiOS -- output had no ``edit "vlan<id>"`` blocks at
  all, so VLAN-routed networks vanished in translation.

The shared user-secret policy lives in
``netconfig/migration/_user_secrets.py`` (commit ``da8883f``); we
exercise it transitively through the FortiGate render path here so
the codec-level wiring is covered.
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalIPv4Address,
    CanonicalInterface,
    CanonicalLAG,
    CanonicalLocalUser,
    CanonicalVlan,
)
from netconfig.migration.canonical.port_names import translate_port_names
from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netconfig.migration.codecs.fortigate_cli import FortiGateCLICodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Issue 1a -- unmigratable hash policy
# ---------------------------------------------------------------------------


class TestIssue1aHashPolicy:
    """``set password ENC <foreign-blob>`` must not leak Cisco
    type-9 / Arista sha512 / OPNsense bcrypt hashes to FortiOS -- the
    ENC envelope is FortiOS-internal and accepting it would be a
    silent security failure."""

    def _render_with_user(self, hashed: str, name: str = "netadmin") -> str:
        tree = CanonicalIntent(
            hostname="fw01",
            local_users=[
                CanonicalLocalUser(
                    name=name,
                    privilege_level=15,
                    hashed_password=hashed,
                ),
            ],
        )
        return FortiGateCLICodec().render(tree)

    def test_unmigratable_hash_emits_review_comment(self) -> None:
        """Cisco type-9 (``9 $9$..``) must produce a ``# password
        manager`` review comment naming the source algorithm."""
        out = self._render_with_user("9 $9$fakeSaltAdmin1$realisticPayload")
        assert '# password manager user-name "netadmin"' in out
        assert "review:" in out
        assert "9 hash from source vendor" in out
        # The literal ENC + payload form must NOT appear.
        assert "set password ENC 9 $9$" not in out
        assert "set password 9 $9$" not in out

    def test_unmigratable_hash_does_not_leak_payload(self) -> None:
        """Even the review comment must not embed the actual hash
        payload -- operators paste rendered configs into tickets and
        chat, and the comment line is the easy place to accidentally
        re-ship the secret."""
        payload = "$9$fakeSaltAdmin1$reallySensitivePayload"
        out = self._render_with_user(f"9 {payload}")
        assert payload not in out
        assert "fakeSaltAdmin1" not in out
        assert "reallySensitivePayload" not in out

    def test_arista_sha512_hash_unmigratable(self) -> None:
        """Vendor-tagged ``arista:sha512:$6$...`` form is also
        unmigratable to FortiGate -- same review path."""
        out = self._render_with_user(
            "arista:sha512:$6$abcsalt$ariaPayload"
        )
        assert "review:" in out
        assert "sha512 hash from source vendor" in out
        assert "$6$abcsalt$ariaPayload" not in out

    def test_opnsense_bcrypt_hash_unmigratable(self) -> None:
        """OPNsense bcrypt (``bcrypt:$2y$..``) is unmigratable too."""
        out = self._render_with_user("bcrypt:$2y$10$opnsalty.payload")
        assert "review:" in out
        assert "bcrypt hash from source vendor" in out
        assert "$2y$10$opnsalty.payload" not in out

    def test_native_fortios_hash_passes_through(self) -> None:
        """Same-vendor round-trip: ``fortios:<blob>`` hashes are the
        FortiOS-native ENC form and must be emitted unchanged via
        ``set password <blob>`` (no ``ENC`` re-prefix needed because
        the blob already carries the FortiOS-internal envelope)."""
        out = self._render_with_user(
            "fortios:ENCfakeFortiosEncryptedBlob123==",
        )
        assert "set password ENCfakeFortiosEncryptedBlob123==" in out
        # No review comment should appear for native hashes.
        assert "review:" not in out

    def test_plaintext_password_not_flagged(self) -> None:
        """Plaintext passwords (no algorithm tag) are migratable to
        every target -- no review comment, plain ENC emit."""
        out = self._render_with_user("plain-text-password")
        assert "review:" not in out
        # Plaintext goes through the ``elif raw:`` branch as ENC + value.
        assert "set password ENC" in out


# ---------------------------------------------------------------------------
# Issue 2 -- multi-module port-name collision
# ---------------------------------------------------------------------------


class TestIssue2PortCollision:
    """Cisco's stack/module/port encoding must round-trip through the
    FortiGate target without collapsing distinct ports onto a single
    ``edit "port1"`` block.  Rule of the fix: when ``module > 0`` or
    ``stack > 1`` the formatter switches to ``port-<stack>-<module>-
    <port>``; the renderer also dedups by emission order as a
    belt-and-braces guard against any residual collision."""

    def test_multi_module_ports_no_duplicate_edits(self) -> None:
        """Cisco c9300 has Te1/0/1 (module=0) and Gi1/1/1 (module=1)
        sharing port=1.  The disambiguator splits them: Te1/0/1 ->
        port1, Gi1/1/1 -> port-1-1-1.  The output must contain
        ``edit "port1"`` at most once."""
        ios_cli = (
            "hostname c9300-test\n"
            "!\n"
            "interface TenGigabitEthernet1/0/1\n"
            " description base-mod0\n"
            " no shutdown\n"
            "!\n"
            "interface GigabitEthernet1/1/1\n"
            " description uplink-mod1\n"
            " no shutdown\n"
            "!\n"
            "end\n"
        )
        src = CiscoIOSXECLICodec()
        tgt = FortiGateCLICodec()
        intent = src.parse(ios_cli)
        translate_port_names(intent, src, tgt)
        out = tgt.render(intent)
        assert out.count('edit "port1"') <= 1
        # The mod-1 port must have its own disambiguated name.
        assert 'edit "port-1-1-1"' in out

    def test_collision_emits_review_comment(self) -> None:
        """Two source ports that BOTH classify with stack=1, module=1,
        port=1 (Gi1/1/1 + Te1/1/1 -- they differ only in
        name_speed_hint, which the formatter ignores in v1) hit the
        render-time dedup and produce a ``# port collision`` comment
        for the second one."""
        ios_cli = (
            "hostname c9300-test\n"
            "!\n"
            "interface GigabitEthernet1/1/1\n"
            " description gig-uplink\n"
            "!\n"
            "interface TenGigabitEthernet1/1/1\n"
            " description ten-uplink\n"
            "!\n"
            "end\n"
        )
        src = CiscoIOSXECLICodec()
        tgt = FortiGateCLICodec()
        intent = src.parse(ios_cli)
        translate_port_names(intent, src, tgt)
        out = tgt.render(intent)
        assert out.count('edit "port-1-1-1"') == 1
        assert "# port collision: port-1-1-1" in out

    def test_single_axis_source_keeps_simple_portn(self) -> None:
        """Same-vendor and other single-axis sources (FortiGate's own
        ``port1``, MikroTik ``ether1``, OPNsense ``igb0``) leave
        stack/module unset -- the formatter takes the simple ``portN``
        path so existing translations stay unchanged."""
        from netconfig.migration.codecs.fortigate_cli.port_names import (
            classify_port_name,
            format_port_identity,
        )
        ident = classify_port_name("port1")
        assert ident.kind == "physical"
        assert ident.stack is None
        assert ident.module is None
        assert format_port_identity(ident) == "port1"

    def test_module_zero_keeps_simple_portn(self) -> None:
        """Cisco Te1/0/24 (module=0) must still render as port24 --
        the disambiguator only kicks in when module > 0 (or stack >
        1) so single-stack/base-module Cisco sources don't see a
        breaking change."""
        from netconfig.migration.codecs.fortigate_cli.port_names import (
            format_port_identity,
        )
        from netconfig.migration.codecs.cisco_iosxe_cli.port_names import (
            classify_port_name as cisco_classify,
        )
        ident = cisco_classify("TenGigabitEthernet1/0/24")
        assert ident.stack == 1 and ident.module == 0 and ident.port == 24
        assert format_port_identity(ident) == "port24"

    def test_module_one_uses_disambiguated_name(self) -> None:
        """Cisco Gi1/1/1 (module=1) must produce port-1-1-1."""
        from netconfig.migration.codecs.fortigate_cli.port_names import (
            format_port_identity,
        )
        from netconfig.migration.codecs.cisco_iosxe_cli.port_names import (
            classify_port_name as cisco_classify,
        )
        ident = cisco_classify("GigabitEthernet1/1/1")
        assert ident.module == 1
        assert format_port_identity(ident) == "port-1-1-1"


# ---------------------------------------------------------------------------
# Issue 6 -- VLAN child interface emit
# ---------------------------------------------------------------------------


class TestIssue6VlanChildEmit:
    """Canonical VLANs with SVI L3 addresses must materialise as
    FortiOS ``edit "vlan<id>"`` child blocks under ``config system
    interface``, with ``set type vlan / set vlanid N / set interface
    "<parent>"`` plus optional ``set ip <addr> <mask>`` for the SVI
    routing.  The parent prefers the first canonical LAG (operators
    almost always trunk VLANs over a LAG) and falls back to the
    first non-VLAN physical interface."""

    def test_vlan_child_interface_emit_with_svi_ip(self) -> None:
        """VLAN 11 with SVI IP 192.168.11.252/24 -> child block named
        ``vlan11`` carrying type=vlan, vlanid=11, and the SVI IP
        copied across in the FortiOS dotted-decimal mask form."""
        tree = CanonicalIntent(
            hostname="c9300",
            interfaces=[
                CanonicalInterface(
                    name="port1",
                    interface_type="ianaift:ethernetCsmacd",
                ),
            ],
            vlans=[
                CanonicalVlan(
                    id=11,
                    name="data",
                    ipv4_addresses=[
                        CanonicalIPv4Address(
                            ip="192.168.11.252", prefix_length=24,
                        ),
                    ],
                ),
            ],
        )
        out = FortiGateCLICodec().render(tree)
        assert 'edit "vlan11"' in out
        assert "set type vlan" in out
        assert "set vlanid 11" in out
        # FortiOS uses dotted-decimal mask form, not CIDR -- match
        # the rest of the renderer's IP emit style.
        assert "set ip 192.168.11.252 255.255.255.0" in out

    def test_vlan_child_interface_emit_with_lag_parent(self) -> None:
        """When the canonical tree has a LAG, the synthetic VLAN
        child binds to the first LAG via ``set interface "LAG1"``
        rather than a physical port -- operators almost always trunk
        VLANs over the LAG."""
        tree = CanonicalIntent(
            hostname="c9300",
            interfaces=[
                CanonicalInterface(
                    name="port1",
                    interface_type="ianaift:ethernetCsmacd",
                ),
            ],
            lags=[
                CanonicalLAG(name="LAG1", members=["port1"], mode="active"),
            ],
            vlans=[
                CanonicalVlan(id=20, name="prod"),
            ],
        )
        out = FortiGateCLICodec().render(tree)
        assert 'edit "vlan20"' in out
        assert 'set interface "LAG1"' in out

    def test_vlan_child_falls_back_to_first_physical(self) -> None:
        """No LAG -> first non-VLAN interface becomes the parent."""
        tree = CanonicalIntent(
            hostname="c9300",
            interfaces=[
                CanonicalInterface(
                    name="port1",
                    interface_type="ianaift:ethernetCsmacd",
                ),
                CanonicalInterface(
                    name="port2",
                    interface_type="ianaift:ethernetCsmacd",
                ),
            ],
            vlans=[CanonicalVlan(id=100)],
        )
        out = FortiGateCLICodec().render(tree)
        assert 'edit "vlan100"' in out
        assert 'set interface "port1"' in out

    def test_vlan_child_skipped_when_existing_vlan_iface_present(self) -> None:
        """Intra-vendor round-trip: a FortiGate-source ``VL_100``
        interface with vlanid 100 already covers the VLAN -- the
        renderer must NOT also emit a synthetic ``vlan100`` child
        (would produce two blocks for the same vlanid)."""
        tree = CanonicalIntent(
            hostname="fw",
            interfaces=[
                CanonicalInterface(
                    name="port1",
                    interface_type="ianaift:ethernetCsmacd",
                ),
                CanonicalInterface(
                    name="VL_100",
                    interface_type="ianaift:l3ipvlan",
                ),
            ],
            vlans=[
                CanonicalVlan(id=100, name="VL_100"),
            ],
        )
        out = FortiGateCLICodec().render(tree)
        # The original VL_100 must be present, the synthetic vlan100
        # must NOT.
        assert 'edit "VL_100"' in out
        assert 'edit "vlan100"' not in out

    def test_vlan_child_svi_ip_directly_via_helper(self) -> None:
        """Direct unit test for the SVI-absorption fallback in
        :func:`_build_vlan_children`: when a canonical VLAN has no
        ``ipv4_addresses`` but a sibling ``Vlan<id>`` interface does
        (Cisco-style separate SVI stub), the helper copies the IP
        from that interface across to the synthetic vlan child.

        Tested via the helper directly because at the renderer level
        the existing ``Vlan<id>`` interface short-circuits the
        synthetic emit (its name matches ``_looks_like_vlan_iface``
        + ``vlanid`` so the dedup guard suppresses the duplicate)."""
        from netconfig.migration.codecs.fortigate_cli.render import (
            _build_vlan_children,
        )
        vlan = CanonicalVlan(id=50, name="mgmt")
        svi_iface = CanonicalInterface(
            name="Vlan50",
            interface_type="ianaift:l3ipvlan",
            ipv4_addresses=[
                CanonicalIPv4Address(ip="10.50.0.1", prefix_length=24),
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
        assert c["name"] == "vlan50"
        assert c["vlanid"] == 50
        assert c["ip"] == "10.50.0.1"
        assert c["mask"] == "255.255.255.0"
        # Parent fallback to first non-VLAN interface.
        assert c["parent"] == "port1"

    def test_no_vlan_block_when_tree_has_no_vlans(self) -> None:
        """Negative case: trees without VLANs must not produce any
        synthetic vlan child entries."""
        tree = CanonicalIntent(
            hostname="fw",
            interfaces=[
                CanonicalInterface(
                    name="port1",
                    interface_type="ianaift:ethernetCsmacd",
                ),
            ],
        )
        out = FortiGateCLICodec().render(tree)
        assert "set type vlan" not in out

    def test_full_pipeline_cisco_to_fortigate_vlan_emit(self) -> None:
        """End-to-end smoke: a Cisco source with a Vlan11 SVI +
        Port-channel1 trunk landing as fortigate output -- must
        contain the ``edit "vlan11"`` child bound to LAG1 with the
        SVI IP attached."""
        ios_cli = (
            "hostname c9300\n"
            "!\n"
            "interface Port-channel1\n"
            " switchport mode trunk\n"
            " switchport trunk allowed vlan 10,11,20\n"
            "!\n"
            "interface TenGigabitEthernet1/0/1\n"
            " channel-group 1 mode active\n"
            "!\n"
            "interface Vlan11\n"
            " ip address 192.168.11.252 255.255.255.0\n"
            "!\n"
            "vlan 11\n"
            "!\n"
            "end\n"
        )
        src = CiscoIOSXECLICodec()
        tgt = FortiGateCLICodec()
        intent = src.parse(ios_cli)
        translate_port_names(intent, src, tgt)
        out = tgt.render(intent)
        assert 'edit "vlan11"' in out
        assert "set vlanid 11" in out
        assert 'set interface "LAG1"' in out
        assert "set ip 192.168.11.252 255.255.255.0" in out
