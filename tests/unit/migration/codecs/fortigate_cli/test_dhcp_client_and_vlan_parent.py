"""
FortiGate CLI render-side tests for the canonical-layer wave
follow-up findings 20 and 21 (``user_smoke_findings.md``).

* **Finding 20** -- ``CanonicalInterface.dhcp_client=True`` (set by
  OPNsense parser commit ``c16d2c0`` from ``<ipaddr>dhcp</ipaddr>``)
  must emit ``set mode dhcp`` inside the ``config system interface``
  edit block.  Mirrors Junos commit ``5edf800`` (``family inet
  dhcp``), Cisco IOS-XE ``ip address dhcp``, and MikroTik DHCP-client
  consumers.  Reference: docs.fortinet.com/document/fortigate/
  7.6.6/cli-reference/190194324/config-system-interface ``set mode
  {static | dhcp}``.

* **Finding 21** -- ``_parent_for_vlan_iface`` previously walked the
  deduped iface list and picked the first non-VLAN candidate.  With
  OPNsense source where ``igc0`` (WAN, dhcp_client) and ``port1``
  (LAN, static RFC1918) both survive elision, this picked WAN —
  wrong.  New deterministic LAN-preference scorer: +10 for private
  IPv4, +5 for trunk-allowed-vlans, -5 for dhcp_client, +1 per
  port-index.  Falls back to legacy first-non-VLAN behaviour when no
  candidate has signals (preserves backward compat).
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalIPv4Address,
    CanonicalInterface,
    CanonicalVlan,
)
from netconfig.migration.canonical.port_names import translate_port_names
from netconfig.migration.codecs.fortigate_cli import FortiGateCLICodec
from netconfig.migration.codecs.fortigate_cli.render import (
    _parent_for_vlan_iface,
)
from netconfig.migration.codecs.opnsense import OPNsenseCodec


pytestmark = pytest.mark.unit


def _slice_block(out: str, marker: str) -> str:
    """Slice a single ``edit "X" ... next`` block out of FortiGate
    render output for inspection.  Mirrors the helper in
    ``test_render_opnsense_smoke.py``."""
    lines = out.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if marker in ln),
        None,
    )
    if start is None:
        return ""
    end = next(
        (i for i, ln in enumerate(lines[start:], start)
         if ln.strip() == "next"),
        len(lines) - 1,
    )
    return "\n".join(lines[start:end + 1])


# ---------------------------------------------------------------------------
# Finding 20 -- set mode dhcp for DHCP-client interfaces
# ---------------------------------------------------------------------------


class TestFinding20DhcpClientEmitsSetModeDhcp:
    """``iface.dhcp_client=True`` (with no static IPv4) must emit
    ``set mode dhcp`` and skip the ``set ip`` / ``set mode static``
    branch."""

    def test_fortigate_dhcp_client_emits_set_mode_dhcp(self) -> None:
        """Synthetic ``CanonicalInterface(name="port1", dhcp_client=
        True)`` -> output contains ``set mode dhcp`` AND no ``set ip``
        line in the port1 block."""
        tree = CanonicalIntent(
            hostname="fw01",
            interfaces=[
                CanonicalInterface(
                    name="port1",
                    dhcp_client=True,
                    enabled=True,
                ),
            ],
        )
        out = FortiGateCLICodec().render(tree)
        block = _slice_block(out, 'edit "port1"')
        assert "set mode dhcp" in block
        # No static-IP leaks into the DHCP-client block.
        assert "set ip " not in block
        assert "set mode static" not in block

    def test_fortigate_dhcp_client_with_static_ip_prefers_static(
        self,
    ) -> None:
        """Defensive guard: a contradictory canonical state with both
        ``dhcp_client=True`` and a static IPv4 address picks the
        static path (FortiOS treats the explicit ``set ip`` as the
        dominant source, so the safe-deploy choice is to honour it)."""
        tree = CanonicalIntent(
            hostname="fw01",
            interfaces=[
                CanonicalInterface(
                    name="port1",
                    dhcp_client=True,
                    ipv4_addresses=[
                        CanonicalIPv4Address(
                            ip="10.0.0.1", prefix_length=24,
                        ),
                    ],
                    enabled=True,
                ),
            ],
        )
        out = FortiGateCLICodec().render(tree)
        block = _slice_block(out, 'edit "port1"')
        # Static-IP path wins: explicit IP + ``set mode static``.
        assert "set ip 10.0.0.1 255.255.255.0" in block
        assert "set mode static" in block
        # And no ``set mode dhcp`` competing line.
        assert "set mode dhcp" not in block

    def test_fortigate_static_ip_unchanged(self) -> None:
        """Regression guard: ``dhcp_client=False`` (default) + static
        IP renders exactly as before (``set ip A.B.C.D M.M.M.M`` and
        ``set mode static``).  No accidental drift from the new
        branch."""
        tree = CanonicalIntent(
            hostname="fw01",
            interfaces=[
                CanonicalInterface(
                    name="port1",
                    ipv4_addresses=[
                        CanonicalIPv4Address(
                            ip="192.168.88.2", prefix_length=24,
                        ),
                    ],
                    enabled=True,
                ),
            ],
        )
        out = FortiGateCLICodec().render(tree)
        block = _slice_block(out, 'edit "port1"')
        assert "set ip 192.168.88.2 255.255.255.0" in block
        assert "set mode static" in block
        assert "set mode dhcp" not in block

    def test_opnsense_wan_dhcp_cascades_to_fortigate_set_mode_dhcp(
        self,
    ) -> None:
        """End-to-end (canonical-layer cascade): synthetic OPNsense
        source XML with ``<ipaddr>dhcp</ipaddr>`` now produces
        ``CanonicalInterface.dhcp_client=True`` (commit ``c16d2c0``),
        which the FortiGate render must surface as ``set mode dhcp``.

        Skip if the OPNsense parser hasn't been exercised by import
        (the canonical-layer cascade is the cross-codec contract this
        test pins)."""
        opnsense_xml = """<?xml version="1.0"?>
<opnsense>
  <system>
    <hostname>edgegw</hostname>
    <domain>example.test</domain>
  </system>
  <interfaces>
    <wan>
      <if>igc0</if>
      <ipaddr>dhcp</ipaddr>
      <enable>1</enable>
    </wan>
    <lan>
      <if>igc1</if>
      <ipaddr>192.168.88.2</ipaddr>
      <subnet>24</subnet>
      <enable>1</enable>
    </lan>
  </interfaces>
</opnsense>
"""
        src = OPNsenseCodec()
        tgt = FortiGateCLICodec()
        intent = src.parse(opnsense_xml)
        translate_port_names(intent, src, tgt)
        out = tgt.render(intent)
        # The WAN igc0 ends up as ``edit "igc0"`` (no FortiGate role
        # rename for OPNsense BSD-driver names) — what matters is
        # the DHCP-mode emit on the WAN block.
        wan_block = _slice_block(out, 'edit "igc0"')
        assert "set mode dhcp" in wan_block


# ---------------------------------------------------------------------------
# Finding 21 -- _parent_for_vlan_iface prefers LAN over WAN
# ---------------------------------------------------------------------------


class TestFinding21VlanParentPrefersLan:
    """The VLAN-parent scorer assigns +10 for private IPv4, +5 for
    trunk-allowed-vlans, -5 for dhcp_client, +1 per port-index.  When
    no candidate has any signal, falls back to the legacy
    first-non-VLAN behaviour for backward compat."""

    def test_fortigate_vlan_parent_prefers_lan_over_wan(self) -> None:
        """Synthetic ``port1`` with static ``192.168.88.2/24`` (LAN)
        and ``port2`` with ``dhcp_client=True`` (WAN) -> VLAN child
        anchors on ``port1``."""
        port1 = CanonicalInterface(
            name="port1",
            ipv4_addresses=[
                CanonicalIPv4Address(
                    ip="192.168.88.2", prefix_length=24,
                ),
            ],
            enabled=True,
        )
        port2 = CanonicalInterface(
            name="port2",
            dhcp_client=True,
            enabled=True,
        )
        # Pass port2 (WAN) FIRST so the legacy first-iface fallback
        # would have picked it; the scorer must overrule that.
        chosen = _parent_for_vlan_iface(
            "vlan10", [port2, port1],
        )
        assert chosen == "port1"

    def test_fortigate_vlan_parent_prefers_trunk_allowed_vlans(
        self,
    ) -> None:
        """``port1`` with ``trunk_allowed_vlans=[10, 20]`` (+5)
        outranks ``port2`` with no signals (+port-index=2 only)."""
        port1 = CanonicalInterface(
            name="port1",
            trunk_allowed_vlans=[10, 20],
            enabled=True,
        )
        port2 = CanonicalInterface(
            name="port2",
            ipv4_addresses=[
                CanonicalIPv4Address(
                    ip="203.0.113.1", prefix_length=24,
                ),
            ],
            enabled=True,
        )
        # port2 has a public IP (no +10 bonus for RFC1918) plus
        # port-index=2.  port1 has trunk-allowed (+5) plus
        # port-index=1.  port1 should win on +5 trunk signal.
        chosen = _parent_for_vlan_iface(
            "vlan10", [port2, port1],
        )
        assert chosen == "port1"

    def test_fortigate_vlan_parent_falls_back_to_first_when_no_signals(
        self,
    ) -> None:
        """Two ports with no IP, no trunk, no dhcp -> all candidates
        score 0 plus port-index.  Legacy fallback fires (first
        non-VLAN-shaped iface wins)."""
        port_a = CanonicalInterface(name="port_a", enabled=True)
        port_b = CanonicalInterface(name="port_b", enabled=True)
        chosen = _parent_for_vlan_iface(
            "vlan10", [port_a, port_b],
        )
        # Legacy fallback returns the first non-VLAN iface — port_a
        # (no trailing digit -> port-index=0, same as port_b).
        assert chosen == "port_a"

    def test_fortigate_vlan_parent_dhcp_client_demoted_below_lan(
        self,
    ) -> None:
        """Explicit DHCP client (``-5``) + private IPv4 LAN (``+10``):
        LAN wins by +15."""
        wan = CanonicalInterface(
            name="igc0",
            dhcp_client=True,
            enabled=True,
        )
        lan = CanonicalInterface(
            name="port1",
            ipv4_addresses=[
                CanonicalIPv4Address(
                    ip="10.0.0.1", prefix_length=24,
                ),
            ],
            enabled=True,
        )
        chosen = _parent_for_vlan_iface("vlan10", [wan, lan])
        assert chosen == "port1"

    def test_fortigate_vlan_parent_dotted_form_still_works(
        self,
    ) -> None:
        """Dotted-form names (``port1.10`` -> parent ``port1``) bypass
        the scorer and use the legacy parent-by-substring lookup so
        explicit operator-encoded parents take precedence over any
        scoring heuristic."""
        port1 = CanonicalInterface(
            name="port1",
            ipv4_addresses=[
                CanonicalIPv4Address(
                    ip="10.0.0.1", prefix_length=24,
                ),
            ],
            enabled=True,
        )
        port2 = CanonicalInterface(
            name="port2",
            ipv4_addresses=[
                CanonicalIPv4Address(
                    ip="172.16.0.1", prefix_length=24,
                ),
            ],
            enabled=True,
        )
        chosen = _parent_for_vlan_iface(
            "port2.20", [port1, port2],
        )
        # Dotted-form parent wins regardless of scoring.
        assert chosen == "port2"

    def test_fortigate_vlan_parent_end_to_end_via_render(self) -> None:
        """End-to-end: render a tree where ``port1`` is LAN and
        ``port2`` is WAN-DHCP -> the rendered VLAN child block shows
        ``set interface "port1"``, NOT ``set interface "port2"``."""
        tree = CanonicalIntent(
            hostname="fw01",
            interfaces=[
                # WAN first so legacy ordering would have picked it.
                CanonicalInterface(
                    name="port2",
                    dhcp_client=True,
                    enabled=True,
                ),
                CanonicalInterface(
                    name="port1",
                    ipv4_addresses=[
                        CanonicalIPv4Address(
                            ip="192.168.88.2", prefix_length=24,
                        ),
                    ],
                    enabled=True,
                ),
            ],
            vlans=[CanonicalVlan(id=10, name="users")],
        )
        out = FortiGateCLICodec().render(tree)
        # VLAN child binds to LAN.
        assert 'set interface "port1"' in out
        assert 'set interface "port2"' not in out
