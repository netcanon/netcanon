"""
``MikroTikRouterOSCodec`` — third real codec, Session 2 of the
vendor-config-research plan.

Module layout (post-split per the codecs/README.md split-codec
convention):

* ``codec.py`` (this file) — the ``MikroTikRouterOSCodec`` class
  with metadata (capabilities / classvars / probe / iter_xpaths /
  port-name delegates).  ``parse()`` and ``render()`` are two-line
  delegators to the corresponding functions in the sibling modules.
* ``parse.py`` — line-walker + per-section dispatchers that consume
  RouterOS ``/export`` text and produce :class:`CanonicalIntent`.
  Also hosts the shared name/type helpers (``_is_ethernet_name``,
  ``_is_vlan_name``, ``_infer_iface_type_from_name``,
  ``_sort_interfaces``) re-imported by render.py.
* ``render.py`` — canonical tree to RouterOS ``/export`` text.
* ``port_names.py`` — cross-vendor port-name identity bridge.

Input format
------------
RouterOS ``/export verbose`` output.  Line-oriented, section-oriented
grammar::

    # leading comment banner

    /system identity
    set name=router1

    /interface ethernet
    set [ find default-name=ether1 ] comment="WAN uplink" disabled=no
    set [ find default-name=ether2 ] comment="LAN trunk"  disabled=no

    /interface vlan
    add comment="Users" interface=bridge1 name=vlan10 vlan-id=10

    /ip address
    add address=192.168.10.1/24 interface=vlan10 network=192.168.10.0

    /ip route
    add dst-address=0.0.0.0/0 gateway=198.51.100.1

    /system dns
    set servers=1.1.1.1,8.8.8.8

    /system ntp client
    set enabled=yes servers=pool.ntp.org

Tree shape
----------
Every ``parse()`` returns a :class:`CanonicalIntent`; every
``render()`` consumes one.  Same contract as every other canonical-
bridged codec.

Round-trip invariant
--------------------
``parse(render(tree)) == tree`` for the supported canonical subset
(hostname, interfaces, VLANs, static_routes, DNS/NTP servers).
RouterOS defaults that we don't model (auto-mac, distance, etc.) are
either omitted on render or stamped with the MikroTik-conventional
default, so repeated parse/render cycles stabilise after one pass.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar, Iterable

from ....models.migration import (
    CapabilityMatrix,
    DeviceClass,
    LossyPath,
    UnsupportedPath,
)
from ...canonical.intent import CanonicalIntent
from .._input_shape import detect_input_shape
from ..base import CodecBase
from ..registry import register
from . import port_names as _port_names
from .parse import parse_intent
from .render import render_intent

__all__ = ["MikroTikRouterOSCodec"]


@register
class MikroTikRouterOSCodec(CodecBase):
    """Codec for MikroTik RouterOS ``/export verbose`` text.

    Declares ``device_classes=[router, firewall]`` — RouterOS runs the
    gamut from SOHO routers to carrier-grade firewalls; translation
    against anything that shares ``router`` (IOS-XE, OPNsense) is
    permitted by the class guard.
    """

    name: ClassVar[str] = "mikrotik_routeros"
    version_hint: ClassVar[str | None] = "7.x"
    input_format: ClassVar[str] = "cli-mikrotik"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "certified"
    canonical_model: ClassVar[str] = "openconfig-lite"
    description: ClassVar[str] = (
        "Paste the output of `/export verbose` on RouterOS.  The codec "
        "parses the section/add/set grammar (/system identity, "
        "/interface ethernet, /ip address, etc)."
    )
    sample_input: ClassVar[str] = (
        '# by RouterOS 7.13\n'
        '/system identity\n'
        'set name=router1\n'
        '\n'
        '/interface ethernet\n'
        'set [ find default-name=ether1 ] comment="WAN uplink" disabled=no\n'
        '\n'
        '/ip address\n'
        'add address=198.51.100.2/30 interface=ether1\n'
        '\n'
        '/ip route\n'
        'add dst-address=0.0.0.0/0 gateway=198.51.100.1\n'
    )
    output_extension: ClassVar[str] = "rsc"

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="mikrotik_routeros",
        vendor_id="mikrotik_routeros",
        version_range="7.x",
        device_classes=[DeviceClass.router, DeviceClass.firewall],
        supported=[
            "/system/hostname",
            "/system/dns-server",
            "/system/ntp-server",
            "/interfaces/interface/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/interfaces/interface/ipv6/address/ip",         # GAP-EVPN-3
            "/interfaces/interface/ipv6/address/prefix-length",  # GAP-EVPN-3
            "/interfaces/interface/tunnel-type",             # /interface gre vs eoip vs ipip discriminator
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/routing/static-route",
            # Tier 2 — SNMP
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/trap-host",
            "/snmp/v3-user",
            # v0.2.0 Wave B — VRRP wire-up.  RouterOS exposes the
            # classic IETF VRRP primitive natively under top-level
            # ``/interface vrrp``; the codec parses + renders the
            # full canonical surface (group_id, priority, preempt,
            # advertisement_interval, IPv4/IPv6 virtual IPs, auth via
            # the ``authentication=simple|ah`` + ``password=`` pair).
            # HSRP / CARP / anycast modes have no native RouterOS
            # equivalent — the renderer surfaces them as review
            # comments instead of dropping silently.
            "/interfaces/interface/vrrp-groups/group",
        ],
        lossy=[
            LossyPath(
                path="/interfaces/interface/config/type",
                reason=(
                    "RouterOS does not expose IANA ifType; the codec "
                    "infers it from the interface-name prefix "
                    "(etherN → ethernetCsmacd, vlanN → l3ipvlan)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vlans/vlan/name",
                reason=(
                    "MikroTik stores a VLAN's name as the L3 interface "
                    "name (e.g. vlan10), NOT a separate descriptive "
                    "name field.  Cross-vendor rendering may conflate "
                    "the two."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/dhcp-client-v6",
                reason=(
                    "RouterOS exposes IPv6 DHCPv6 client config under "
                    "the separate /ipv6 dhcp-client section rather than "
                    "an interface-attribute, so dhcp_client_v6 does not "
                    "round-trip through MikroTik's interface stanzas."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            UnsupportedPath(
                path="/filter/rule",
                reason=(
                    "Firewall filter rules are Tier 3 (informational) "
                    "and not auto-rendered by the canonical bridge."
                ),
            ),
            UnsupportedPath(
                path="/nat/rule",
                reason="NAT rules are Tier 3 — informational only.",
            ),
            UnsupportedPath(
                path="/vxlan-vnis/vni",
                reason=(
                    "RouterOS VXLAN exists but is rare in canonical "
                    "scope and not modelled in v1."
                ),
            ),
            UnsupportedPath(
                path="/vxlan-vnis/source-interface",
                reason="VXLAN not modelled (see /vxlan-vnis/vni).",
            ),
            UnsupportedPath(
                path="/vxlan-vnis/udp-port",
                reason="VXLAN not modelled (see /vxlan-vnis/vni).",
            ),
            # -- Ship-before-wire (v0.2.0) -- anycast / per-VRF static routes --
            # VRRP wired in Wave B; anycast (Wave C) + per-VRF static
            # routes remain unsupported until their respective waves.
            UnsupportedPath(
                path="/interfaces/interface/ipv4/address/virtual-gateway-address",
                reason=(
                    "Anycast-gateway virtual IPv4 companion parses-and-"
                    "ignores in v1.  Schema exists on "
                    "CanonicalIPv4Address; wire-up scheduled for v0.2.0 "
                    "Wave C (see docs/v0.2.0-planning/02-anycast-gateway/)."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/ipv6/address/virtual-gateway-address",
                reason=(
                    "IPv6 anycast-gateway virtual IP companion parses-"
                    "and-ignores in v1.  Schema exists on "
                    "CanonicalIPv6Address; wire-up scheduled for v0.2.0 "
                    "Wave C."
                ),
            ),
            UnsupportedPath(
                path="/anycast-gateway-mac",
                reason=(
                    "System-wide anycast-gateway MAC parses-and-ignores "
                    "in v1.  Schema exists on CanonicalIntent; wire-up "
                    "scheduled for v0.2.0 Wave C."
                ),
            ),
            UnsupportedPath(
                path="/routing/static-route/vrf",
                reason=(
                    "Per-VRF static-route binding parses-and-ignores in "
                    "v1.  Schema exists on CanonicalStaticRoute.vrf; "
                    "wire-up scheduled for v0.2.0 (closes existing "
                    "per-VRF static-route lossy declaration)."
                ),
            ),
        ],
    )

    @property
    def capabilities(self) -> CapabilityMatrix:
        return self._CAPS

    # -----------------------------------------------------------------
    # Parse / Render — delegate to sibling modules
    # -----------------------------------------------------------------

    def parse(self, raw: str) -> CanonicalIntent:
        from ..._tier3_detection import detect_tier3_sections_routeros

        intent = parse_intent(raw)
        # Surface Tier-3 `/path` blocks the parser drops (`/ip firewall`,
        # `/queue`, `/ip ipsec`, `/routing bgp/ospf/filter`).
        # Notification-only.
        intent.dropped_tier3_sections = detect_tier3_sections_routeros(raw)
        return intent

    def render(self, tree: Any) -> str:
        return render_intent(tree)

    # -----------------------------------------------------------------
    # iter_xpaths
    # -----------------------------------------------------------------

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        """Yield schema xpaths from a :class:`CanonicalIntent`."""
        if isinstance(tree, CanonicalIntent):
            # Reuse the shared canonical walker so every codec emits
            # the same set of xpaths for the same tree.
            from ..cisco_iosxe_cli.codec import _walk_canonical
            yield from _walk_canonical(tree)

    # -----------------------------------------------------------------
    # Cross-vendor port-name translation
    # -----------------------------------------------------------------
    # Implementation extracted to :mod:`.port_names` — these methods
    # delegate so the codec class stays focused on parse/render.

    def classify_port_name(self, name: str):
        return _port_names.classify_port_name(name)

    def format_port_identity(self, identity) -> str | None:
        return _port_names.format_port_identity(identity)

    # -----------------------------------------------------------------
    # Auto-detection probe (R5)
    # -----------------------------------------------------------------

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Detect MikroTik RouterOS ``/export`` text.

        Unique markers: ``/system identity``, ``/interface ethernet``
        section headers, RouterOS banner ``# ... by RouterOS``, or
        the ``set [ find default-name=`` idiom.
        """
        # XML / JSON shape — shared helper tolerates leading shell-echo
        # / banner framing so real captures don't bypass the guard.
        if detect_input_shape(raw_prefix) is not None:
            return None
        # Banner comment from /export is the single strongest signal.
        if re.search(r"^#\s*.*by RouterOS", raw_prefix, re.MULTILINE):
            return (98, "'# ... by RouterOS' banner header present")

        # Gather all weaker signals, pick the strongest.  Two+ section
        # headers AND the find-default-name idiom together is a very
        # strong signal; either alone is medium-strong.
        section_hits = 0
        if re.search(r"^/system identity", raw_prefix, re.MULTILINE):
            section_hits += 1
        if re.search(r"^/interface (ethernet|vlan|bridge|wireless)",
                     raw_prefix, re.MULTILINE):
            section_hits += 1
        if re.search(r"^/ip (address|route|dns)",
                     raw_prefix, re.MULTILINE):
            section_hits += 1
        has_find_idiom = "[ find default-name=" in raw_prefix

        if section_hits >= 2 and has_find_idiom:
            return (97, "multiple RouterOS sections + find-default-name idiom")
        if section_hits >= 2:
            return (95, f"{section_hits} RouterOS section headers present")
        if has_find_idiom:
            return (90, "RouterOS 'set [ find default-name=...]' idiom present")
        if section_hits == 1:
            return (80, "one RouterOS section header present")
        return None
