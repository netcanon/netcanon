"""Aruba AOS-S render: OPNsense supergate smoke-test findings.

Three regressions surfaced by the OPNsense-supergate user-contrib
fixture (see ``tests/fixtures/real/user_smoke_findings.md``, OPEN
section, findings 4 / 8 / 12):

* **Finding 4** — L3 SVI IPs dropped entirely.  OPNsense source
  carries SVI L3 on ``CanonicalInterface(name="vlan0.10")``-style
  records (the ``<if>`` element from each ``<optN>`` zone), not on
  the ``CanonicalVlan`` itself.  The Aruba renderer was only
  walking ``vlan.ipv4_addresses`` and ``Vlan<N>``-style sibling
  interfaces, so 5 networks (vlan 10, 11, 20, 100, 150) became
  unreachable with declared-but-IP-less VLANs.

* **Finding 8** — Foreign-vendor source-port stubs (``igc0``,
  ``ixl0``, ``eth0``) were emitting as ``interface igc0 / enable /
  exit`` literal blocks.  AOS-S would reject any of those names at
  deploy.  Mirror the Junos tiered-elision policy: drop foreign-
  shaped names that have no body content beyond the default
  ``enabled=True``.

* **Finding 12** — ``CanonicalIntent.domain`` (e.g. ``example.test``
  from OPNsense's ``<domain>`` element) was being silently dropped.
  AOS-S syntax ``ip dns domain-name <name>`` (verified against
  Aruba AOS-S 16.11 KB ``ip-dns-dom-nam.htm``) was missing entirely.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalVlan,
)
from netcanon.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Finding 4 — SVI IP emission
# ---------------------------------------------------------------------------


def test_aruba_svi_ip_emitted_when_canonical_has_vlan_ipv4() -> None:
    """When ``CanonicalVlan.ipv4_addresses`` is populated, the SVI L3
    line emits inside the ``vlan N`` block."""
    intent = CanonicalIntent(
        vlans=[CanonicalVlan(
            id=10,
            name="USER VLAN",
            ipv4_addresses=[CanonicalIPv4Address(
                ip="192.168.10.1", prefix_length=24,
            )],
        )],
    )
    out = ArubaAOSSCodec().render(intent)
    assert "vlan 10" in out
    assert 'name "USER VLAN"' in out
    # AOS-S form: `ip address X/N` inside the vlan block (verified
    # against `tests/fixtures/real/aruba_aoss/aruba_central_5memberstack_rendered.cfg`).
    assert "ip address 192.168.10.1/24" in out


def test_aruba_svi_ip_emitted_from_interface_vlan_id_match() -> None:
    """OPNsense pattern: VLAN has no ipv4 itself but a sibling
    ``CanonicalInterface`` whose name encodes the same VLAN id
    (``vlan0.10`` from OPNsense's ``<if>`` element on ``<opt1>``)
    carries the SVI L3.  Renderer walks both shapes and finds it."""
    intent = CanonicalIntent(
        vlans=[
            CanonicalVlan(id=10, name="USER VLAN"),
            CanonicalVlan(id=150, name="IOT VLAN"),
        ],
        interfaces=[
            # OPNsense-style SVI interface name (`<if>vlan0.10</if>`
            # from the supergate fixture).
            CanonicalInterface(
                name="vlan0.10",
                description="USERVLAN",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="192.168.10.1", prefix_length=24,
                )],
            ),
            CanonicalInterface(
                name="vlan0.150",
                description="IOTVLAN",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="192.168.150.1", prefix_length=24,
                )],
            ),
        ],
    )
    out = ArubaAOSSCodec().render(intent)
    # Both SVI IPs land inside their respective vlan blocks.
    assert "vlan 10" in out
    assert "ip address 192.168.10.1/24" in out
    assert "vlan 150" in out
    assert "ip address 192.168.150.1/24" in out
    # And neither sibling iface emits its own `interface vlan0.10`
    # stanza — the L3 was absorbed.  (The lname.startswith("vlan")
    # filter would already drop these; this guards against future
    # regressions where someone widens the filter.)
    assert "interface vlan0.10" not in out
    assert "interface vlan0.150" not in out


def test_aruba_svi_ip_emitted_from_cisco_style_vlan_iface() -> None:
    """Cisco-style cross-vendor input: ``Vlan10`` interface carries
    SVI L3.  This is the original codepath the renderer already
    supported; the Finding 4 fix must not regress it."""
    intent = CanonicalIntent(
        vlans=[CanonicalVlan(id=10, name="DATA")],
        interfaces=[CanonicalInterface(
            name="Vlan10",
            ipv4_addresses=[CanonicalIPv4Address(
                ip="10.0.10.1", prefix_length=24,
            )],
        )],
    )
    out = ArubaAOSSCodec().render(intent)
    assert "vlan 10" in out
    assert "ip address 10.0.10.1/24" in out


def test_aruba_vlan_with_no_svi_does_not_emit_empty_ip_line() -> None:
    """Regression guard: a VLAN with NO SVI IP source must not emit
    a spurious ``ip address`` line."""
    intent = CanonicalIntent(
        vlans=[CanonicalVlan(id=99, name="UNUSED")],
    )
    out = ArubaAOSSCodec().render(intent)
    assert "vlan 99" in out
    assert 'name "UNUSED"' in out
    # No SVI source data → no ip address line in the vlan 99 block.
    # We assert on the section between `vlan 99` and the next `exit`.
    vlan_section_start = out.index("vlan 99")
    vlan_section = out[vlan_section_start:].split("   exit", 1)[0]
    assert "ip address" not in vlan_section


def test_aruba_svi_lookup_prefers_canonical_vlan_over_interface() -> None:
    """When BOTH ``CanonicalVlan.ipv4_addresses`` and a sibling
    interface carry an IP, the canonical VLAN wins (existing
    same-vendor round-trip path takes precedence)."""
    intent = CanonicalIntent(
        vlans=[CanonicalVlan(
            id=10,
            ipv4_addresses=[CanonicalIPv4Address(
                ip="192.168.10.1", prefix_length=24,
            )],
        )],
        interfaces=[CanonicalInterface(
            name="vlan0.10",
            ipv4_addresses=[CanonicalIPv4Address(
                ip="10.99.99.99", prefix_length=24,
            )],
        )],
    )
    out = ArubaAOSSCodec().render(intent)
    assert "ip address 192.168.10.1/24" in out
    # The conflicting sibling-iface IP is not emitted as the SVI.
    assert "ip address 10.99.99.99/24" not in out


# ---------------------------------------------------------------------------
# Finding 8 — foreign-port stub elision
# ---------------------------------------------------------------------------


def test_aruba_foreign_port_with_only_enable_elided() -> None:
    """OPNsense ``igc0`` arriving with no body content beyond the
    default ``enabled=True`` is elided — emitting
    ``interface igc0 / enable / exit`` would be rejected by AOS-S
    (``igc0`` isn't an Aruba port name)."""
    intent = CanonicalIntent(
        interfaces=[CanonicalInterface(name="igc0", enabled=True)],
    )
    out = ArubaAOSSCodec().render(intent)
    assert "interface igc0" not in out
    # Sanity: the bogus stub didn't somehow become an "interface 0"
    # via name parsing fallback either.
    assert "igc0" not in out


def test_aruba_foreign_port_with_description_kept() -> None:
    """Foreign-shape names with real body content (description, IPs,
    MTU non-default) are KEPT — operators see the source content
    even though the port name will need post-deploy editing."""
    intent = CanonicalIntent(
        interfaces=[CanonicalInterface(
            name="igc0",
            description="WAN uplink (review: rename for AOS-S)",
            enabled=True,
        )],
    )
    out = ArubaAOSSCodec().render(intent)
    assert "interface igc0" in out
    # The description was emitted (description renders as `name "X"`
    # on AOS-S — that's the renderer's existing convention).
    assert "WAN uplink" in out


def test_aruba_foreign_port_with_ipv4_kept() -> None:
    """Foreign-shape name with an IPv4 address is KEPT — IP carries
    real operator-visible state."""
    intent = CanonicalIntent(
        interfaces=[CanonicalInterface(
            name="ixl0",
            ipv4_addresses=[CanonicalIPv4Address(
                ip="192.168.88.2", prefix_length=24,
            )],
        )],
    )
    out = ArubaAOSSCodec().render(intent)
    assert "interface ixl0" in out
    assert "ip address 192.168.88.2/24" in out


def test_aruba_native_port_no_body_kept() -> None:
    """AOS-S-shape port names (``1/1``, ``24``, ``1/A1``) are KEPT
    even with empty bodies — round-trip stability for native source."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(name="1/1", enabled=True),
            CanonicalInterface(name="24", enabled=True),
            CanonicalInterface(name="1/A1", enabled=True),
        ],
    )
    out = ArubaAOSSCodec().render(intent)
    assert "interface 1/1" in out
    assert "interface 24" in out
    assert "interface 1/A1" in out


def test_aruba_disabled_foreign_port_kept() -> None:
    """A foreign-shape port with ``enabled=False`` is KEPT — explicit
    admin-down state is body content the operator wrote."""
    intent = CanonicalIntent(
        interfaces=[CanonicalInterface(name="eth0", enabled=False)],
    )
    out = ArubaAOSSCodec().render(intent)
    assert "interface eth0" in out
    assert "   disable" in out


# ---------------------------------------------------------------------------
# Finding 12 — domain emit
# ---------------------------------------------------------------------------


def test_aruba_domain_emits_dns_command() -> None:
    """``CanonicalIntent.domain`` emits ``ip dns domain-name <name>``.

    AOS-S syntax verified against Aruba AOS-S 16.10/16.11 KB
    ``ip-dns-dom-nam.htm`` (https://arubanetworking.hpe.com/techdocs/
    AOS-S/16.11/IPV6/KB/content/kb/ip-dns-dom-nam.htm).
    """
    intent = CanonicalIntent(domain="example.test")
    out = ArubaAOSSCodec().render(intent)
    assert "ip dns domain-name example.test" in out


def test_aruba_domain_absent_emits_nothing() -> None:
    """No domain in the canonical → no ``ip dns domain-name`` line.

    Regression guard: empty-string default must not leak as
    ``ip dns domain-name `` (trailing space) or similar.
    """
    intent = CanonicalIntent()
    out = ArubaAOSSCodec().render(intent)
    assert "ip dns domain-name" not in out


# ---------------------------------------------------------------------------
# Finding 15 — Aruba LAN IP drop (port-mapping gap)
# ---------------------------------------------------------------------------


def test_aruba_opnsense_lan_ip_survives_port_rename() -> None:
    """End-to-end: an OPNsense-source ``ixl0`` LAN interface
    (``CanonicalInterface(name="ixl0", ipv4_addresses=...)``) must
    survive ``translate_port_names`` and reach Aruba's render path
    with its IP intact.

    Finding #15 root cause: Aruba's ``format_port_identity`` had
    a ``port == 0 -> None`` short-circuit that fired for every
    OPNsense BSD device name (every NIC's first instance has
    port=0: ``ixl0`` / ``igb0`` / ``em0`` / ``ix0``).  Combined
    with the orchestrator's ``strip_unmappable=True`` default,
    every foreign-source LAN interface was stripped from the
    canonical tree before render was called — its IP went with it.

    The fix removes the ``port == 0`` guard in the kind=physical
    branch.  ``ixl0`` now maps to AOS-S ``"1"``; LAN IP appears
    in the rendered config.  Mgmt-vrf-bound Cisco interfaces
    still route through the kind=mgmt branch (returns ``"oobm"``)
    via the wave-2 cascade (commit ``56a4cde``).
    """
    from netcanon.migration.canonical.port_names import (
        translate_port_names,
    )
    from netcanon.migration.codecs.opnsense.codec import (
        OPNsenseCodec,
    )

    intent = CanonicalIntent(
        hostname="supergate",
        interfaces=[
            CanonicalInterface(
                name="ixl0",  # OPNsense LAN device
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="192.168.88.2", prefix_length=24,
                )],
            ),
        ],
    )

    src_codec = OPNsenseCodec()
    tgt_codec = ArubaAOSSCodec()
    translate_port_names(intent, src_codec, tgt_codec, rename_map=None)

    # After rename, the canonical interface's name is the
    # AOS-S native form ``"1"`` (port=0 collapsed to port 1).
    iface_names = {iface.name for iface in intent.interfaces}
    assert "1" in iface_names, (
        f"Expected ixl0 to rename to '1', got {iface_names!r}"
    )

    # And the LAN IP survives into the rendered config.
    out = tgt_codec.render(intent)
    assert "interface 1" in out
    assert "ip address 192.168.88.2/24" in out


def test_aruba_opnsense_igb_lan_ip_survives_port_rename() -> None:
    """Same shape as the ixl0 test but exercises the Intel igb
    driver name (1G NIC, the dominant case on home-lab supergate
    deployments).  Confirms the ``port=0`` fix is driver-agnostic
    — any BSD ``<driver>0`` name behaves the same way.
    """
    from netcanon.migration.canonical.port_names import (
        translate_port_names,
    )
    from netcanon.migration.codecs.opnsense.codec import (
        OPNsenseCodec,
    )

    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="igb0",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="10.0.0.1", prefix_length=24,
                )],
            ),
        ],
    )
    src = OPNsenseCodec()
    tgt = ArubaAOSSCodec()
    translate_port_names(intent, src, tgt, rename_map=None)
    iface_names = {iface.name for iface in intent.interfaces}
    assert "1" in iface_names

    out = tgt.render(intent)
    assert "ip address 10.0.0.1/24" in out
