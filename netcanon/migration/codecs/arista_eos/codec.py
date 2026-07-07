"""
``AristaEOSCodec`` — 6th shipped codec.

See package ``__init__`` for scope + grammar-departure notes.

Module layout (post-split):

* ``codec.py`` (this file) — the ``AristaEOSCodec`` class with
  metadata (capabilities / classvars / probe / port-name delegates).
  ``parse()`` and ``render()`` are two-line delegators to the
  corresponding functions in the sibling modules.
* ``parse.py`` — line-scan + per-stanza dispatch over EOS
  ``show running-config`` text.  Hosts the regex constants, the
  router-bgp + interface walkers, and helpers like
  ``_infer_iface_type`` / ``_expand_vlan_list``.
* ``render.py`` — canonical tree → EOS CLI text.

Structural strategy: EOS CLI is line-oriented with ``!`` delimiters,
nearly identical to Cisco IOS syntax for the subset we model.  The
parser therefore leans on the Cisco IOS-XE CLI patterns but diverges
where the grammar does:

  * ``ip address <ip>/<prefix>`` (CIDR) not ``ip address A.B.C.D MASK``.
  * ``username X role <name>`` replaces Cisco's ``privilege <N>``.
  * ``no switchport`` explicit L2→L3 flip.
  * Port-channel / LAG stanzas use ``channel-group N mode active``
    identical to Cisco, but the resulting LAG is ``Port-Channel<N>``
    (capital C) per EOS convention.

Tier-3 / silently-ignored top-level stanzas: ``router bgp``,
``router ospf``, ``mlag configuration``, ``vxlan``, ``management api
http-commands``, ``spanning-tree ...``, ``aaa ...``, ``daemon ...``.
Parse-and-ignore is load-bearing — the real-capture fixture exercises
all of these and the codec must tolerate them.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from ....models.migration import (
    CapabilityMatrix,
    DeviceClass,
    LossyPath,
    UnsupportedPath,
)
from ...canonical.intent import (
    CanonicalEvpnType5Route,  # noqa: F401 — reserved for GAP 6+ follow-up
    CanonicalIntent,
)
from .._input_shape import detect_input_shape
from ..base import CodecBase
from ..registry import register
from . import port_names as _port_names
from .parse import parse_intent
from .render import render_intent


@register
class AristaEOSCodec(CodecBase):
    """Bidirectional codec for Arista EOS ``show running-config``."""

    name: ClassVar[str] = "arista_eos"
    version_hint: ClassVar[str | None] = "EOS 4.20+"
    input_format: ClassVar[str] = "cli-arista"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "certified"
    canonical_model: ClassVar[str] = "openconfig-lite"
    description: ClassVar[str] = (
        "Paste the output of `show running-config` from an Arista EOS "
        "device.  The codec parses hostname, interfaces, VLANs, static "
        "routes, SNMP, and local-user grammar; BGP / OSPF / MLAG / VXLAN "
        "stanzas pass through as Tier-3 parse-and-ignore blocks."
    )
    sample_input: ClassVar[str] = (
        "! Command: show running-config\n"
        "! device: sw1 (DCS-7050SX-64, EOS-4.27.0F)\n"
        "!\n"
        "hostname sw1\n"
        "!\n"
        "vlan 10\n"
        "   name USERS\n"
        "!\n"
        "interface Ethernet1\n"
        "   description uplink\n"
        "   no switchport\n"
        "   ip address 10.0.0.1/31\n"
        "!\n"
        "interface Loopback0\n"
        "   ip address 172.16.0.1/32\n"
        "!\n"
        "ip routing\n"
        "ip route 0.0.0.0/0 10.0.0.2\n"
        "end\n"
    )
    output_extension: ClassVar[str] = "cfg"

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="arista_eos",
        vendor_id="arista_eos",
        version_range="4.20+",
        device_classes=[DeviceClass.switch, DeviceClass.router],
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
            "/interfaces/interface/dhcp-client-v6",          # IPv6 DHCPv6 / SLAAC
            "/interfaces/interface/tunnel-type",             # GRE / IPIP / IPSEC / VXLAN discriminator
            "/interfaces/interface/config/vrf",   # GAP 6
            "/interfaces/interface/dot1q-vlan",   # GAP 7: routed-subif `encapsulation dot1q vlan N`
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/routing/static-route",
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/trap-host",
            "/snmp/v3-user",
            "/local-users/user/name",
            "/local-users/user/hashed-password",
            "/local-users/user/role",
            "/vxlan-vnis/vni",                   # GAP 6 demoted
            "/vxlan-vnis/source-interface",      # GAP-EVPN-2
            "/vxlan-vnis/udp-port",              # GAP-EVPN-2
            "/routing-instances/instance",       # GAP 6 demoted
            "/dhcp-servers/pool",                # Cluster E.1-A
            # -- v0.2.0 Wave B (VRRP) -- per-codec wire-up landed --
            "/interfaces/interface/vrrp-groups/group",
            # -- v0.2.0 Wave C (VARP / anycast-gateway) --
            "/interfaces/interface/ipv4/address/virtual-gateway-address",
            "/interfaces/interface/ipv6/address/virtual-gateway-address",
            "/anycast-gateway-mac",
        ],
        lossy=[
            LossyPath(
                path="/routing-instances/instance/description",
                reason=(
                    "The VRF/routing-instance is harvested with its rd + "
                    "route-targets (which render under `router bgp / vrf`), "
                    "but EOS render has no `vrf instance <name> / description` "
                    "emit path, so a description parsed from a legacy "
                    "`vrf definition` stanza is dropped on render (#21)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/mode",
                reason=(
                    "Arista EOS renders only IETF VRRP; a cross-family source "
                    "mode (HSRP / CARP) drops to a review comment on render, so "
                    "the FHRP protocol silently changes -- verify the "
                    "redundancy intent survived."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vlans/vlan/ipv4/address/secondary-ip",
                reason=(
                    "VLAN-SVI mount render gap: this codec renders a VLAN's L3 "
                    "by synthesizing an `interface Vlan<N>` "
                    "(synthesize_svis_from_vlan_l3), which copies only "
                    "ip+prefix_length, so the is_secondary flag on a VLAN-"
                    "record address is dropped. The SVI L3 itself round-trips, "
                    "so declared lossy (blind-audit f92e97a T0-2)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vlans/vlan/ipv4/address/virtual-gateway-address",
                reason=(
                    "VLAN-SVI mount render gap: the synthesized `interface "
                    "Vlan<N>` carries only ip+prefix_length, so an anycast/VARP "
                    "virtual-gateway IP on a VLAN-record address never reaches "
                    "the `ip address virtual` emit. Declared lossy "
                    "(blind-audit f92e97a T0-2)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vlans/vlan/ipv4/address/virtual-gateway-mac",
                reason=(
                    "VLAN-SVI mount render gap: the synthesized SVI carries "
                    "only ip+prefix_length, and EOS has no per-IP virtual-MAC "
                    "grammar anyway (only the system-wide `ip virtual-router "
                    "mac-address` rides /anycast-gateway-mac). Declared lossy "
                    "(blind-audit f92e97a T0-2)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vlans/vlan/description",
                reason=(
                    "Render emits the VLAN name but not a separate "
                    "description line, so the canonical VLAN description "
                    "(distinct from the name) drops on render (silent-loss "
                    "guard, Bucket-C stage 2)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/engine-id",
                reason=(
                    "The SNMPv3 USM user round-trips but a per-user "
                    "engineID is not emitted on render (engineIDs are "
                    "device-assigned / global), so the canonical engine_id "
                    "drops (silent-loss guard, Bucket-C stage 2)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/routing/static-route/metric",
                reason=(
                    "Render emits destination + next-hop only; the static-"
                    "route administrative distance (metric) is dropped (run3)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/routing/static-route/description",
                reason=(
                    "Render emits destination + next-hop only; the static-"
                    "route name / description is dropped (run3)."
                ),
                severity="warn",
            ),
            # -- v0.2.0 Wave C (VARP) -- per-IP MAC overrides --
            # EOS only supports a system-wide virtual-router MAC
            # (``ip virtual-router mac-address`` — see the
            # ``/anycast-gateway-mac`` supported entry above).
            # Per-IP MAC overrides (Junos-style ``virtual-gateway-v4-
            # mac`` / ``-v6-mac`` per-address) have no Arista
            # equivalent — cross-vendor renders from Junos surface a
            # review banner on the migrate page.
            LossyPath(
                path="/interfaces/interface/ipv4/address/virtual-gateway-mac",
                reason=(
                    "EOS only supports a system-wide virtual-router "
                    "MAC (``ip virtual-router mac-address``).  Per-IP "
                    "MAC overrides (Junos-style ``virtual-gateway-"
                    "v4-mac``) drop on render — cross-vendor sources "
                    "carrying per-IP MACs surface a review banner so "
                    "the operator can either consolidate to a single "
                    "system-wide MAC or pick a vendor target that "
                    "preserves per-IP overrides."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/ipv6/address/virtual-gateway-mac",
                reason=(
                    "Mirror of the IPv4 case.  EOS shares one "
                    "system-wide virtual-router MAC across IPv4 and "
                    "IPv6 anycast — no per-IP override grammar."
                ),
                severity="warn",
            ),
            # -- VXLAN BUM-replication underlay (silent-loss guard) --
            # Render emits the ``interface Vxlan1`` VLAN<->VNI bindings
            # (+ source-interface + udp-port) but not the flood/multicast
            # underlay, so those sub-details drop while the VNI binding
            # (declared supported above) survives — declared here so the
            # validation report warns instead of reporting ``severity: ok``.
            LossyPath(
                path="/vxlan-vnis/mcast-group",
                reason=(
                    "Render emits the per-VNI VLAN<->VNI bindings "
                    "(``vxlan vlan <V> vni <N>``) + source-interface + "
                    "udp-port, but not the multicast underlay "
                    "(``vxlan vlan <V> multicast-group <ip>``): the BUM "
                    "multicast group drops on render while the VLAN<->VNI "
                    "binding survives.  Cross-vendor sources carrying a "
                    "multicast underlay surface a review banner so the "
                    "operator can re-apply flood/multicast on the target."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vxlan-vnis/flood-list",
                reason=(
                    "Companion to /vxlan-vnis/mcast-group: the ingress-"
                    "replication (head-end) flood list "
                    "(``vxlan flood vtep <ip> …``) is not emitted, so a "
                    "source using static VTEP flood-lists loses them on "
                    "render while the VLAN<->VNI binding survives."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/config/type",
                reason=(
                    "EOS interface names don't encode speed; the parser "
                    "defaults to 'gig' speed-hint for all Ethernet<N> "
                    "ports.  Target codecs that care about speed "
                    "(Cisco's GigabitEthernet / TenGigabitEthernet "
                    "distinction) may emit less-specific prefixes."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/evpn-type5-routes/route",
                reason=(
                    "EVPN Type-5 IP-prefix advertisements use a "
                    "VRF-property canonical model: "
                    "CanonicalRoutingInstance.l3_vni captures the "
                    "L3 VNI; Type-5 announcements are IMPLICIT — "
                    "any subnet carried by a VRF-assigned interface "
                    "(CanonicalInterface.vrf) whose VRF has a "
                    "non-None l3_vni gets announced.  The "
                    "CanonicalEvpnType5Route per-prefix record is "
                    "a lossy-by-default extension point: no codec "
                    "populates it today (would require route-map / "
                    "policy-statement parsing to derive which "
                    "prefixes specific policies export); consumers "
                    "that need explicit per-prefix semantics should "
                    "infer from VRF membership + l3_vni rather than "
                    "relying on this list.  Operators porting "
                    "route-map-based prefix selection across "
                    "vendors will see a review-required banner."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            UnsupportedPath(
                path="/interfaces/interface/voice-vlan",
                reason=(
                    "This codec does not model EOS per-port voice VLAN "
                    "(``switchport phone``); dropped on render (blind-audit "
                    "65f9c01 #11)."
                ),
            ),
            UnsupportedPath(
                path="/routing/static-route/interface",
                reason=(
                    "No interface-nexthop (connected) static-route form; a "
                    "gateway-less / interface-only route is dropped (run3)."
                ),
            ),
            # ── Tier-1 surfaces this codec drops on render — declared so the
            #    live validation report flags the loss instead of reporting
            #    `severity: ok` (2026-06 adversarial review #9). ──
            UnsupportedPath(
                path="/system/timezone",
                reason="Render emits no clock/timezone stanza; intent.timezone is dropped on migration.",
            ),
            UnsupportedPath(
                path="/system/syslog-server",
                reason="Render emits no logging/syslog config; intent.syslog_servers are dropped on migration.",
            ),
            UnsupportedPath(
                path="/routing/bgp",
                reason=(
                    "BGP stanzas parse-and-ignore in v1 — neighbor "
                    "tables, redistribution, address-families are "
                    "silently dropped."
                ),
            ),
            UnsupportedPath(
                path="/routing/ospf",
                reason=(
                    "OSPF areas / redistribution / interface-level "
                    "cost tuning parse-and-ignore in v1."
                ),
            ),
            UnsupportedPath(
                path="/access-list/extended",
                reason=(
                    "Arista EOS extended ACLs (`ip access-list <name>` "
                    "with `permit/deny tcp/udp/ip ...` ACEs) are Tier 3 "
                    "— auto-translation across vendors risks shipping "
                    "subtly-permissive rules.  Operator must author "
                    "firewall policy manually."
                ),
            ),
            UnsupportedPath(
                path="/access-list/standard",
                reason=(
                    "Standard ACLs (numbered 1-99 / 1300-1999, or "
                    "named `ip access-list standard <name>`) are "
                    "Tier 3 — see `/access-list/extended`."
                ),
            ),
            UnsupportedPath(
                path="/access-list/ipv6",
                reason=(
                    "IPv6 access-lists (`ipv6 access-list <name>`) "
                    "are Tier 3 — see `/access-list/extended`."
                ),
            ),
            # -- Ship-before-wire (v0.2.0) -- per-VRF static routes --
            # (VRRP + anycast-gateway flipped to ``supported`` in
            # Wave B/C — see the supported list above.)
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
        from ..._tier3_detection import detect_tier3_sections_iosxe_cli

        intent = parse_intent(raw)
        # Surface Tier-3 stanza headers (ACLs, route-maps, crypto, QoS)
        # the parser deliberately drops — see
        # netcanon/migration/_tier3_detection.py.  Notification-only.
        intent.dropped_tier3_sections = detect_tier3_sections_iosxe_cli(raw)
        return intent

    def render(self, tree: Any) -> str:
        return render_intent(tree)

    # -----------------------------------------------------------------
    # Cross-vendor port-name translation
    # -----------------------------------------------------------------

    def classify_port_name(self, name: str):
        return _port_names.classify_port_name(name)

    def format_port_identity(self, identity) -> str | None:
        return _port_names.format_port_identity(identity)

    # -----------------------------------------------------------------
    # Auto-detection probe (R5)
    # -----------------------------------------------------------------

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Detect Arista EOS running-config.

        Signals:
          * ``! device: ... EOS-`` banner in the header (strongest —
            EOS is the only vendor that stamps this line on `show
            running-config` output).
          * ``transceiver qsfp default-mode 4x10G`` / ``Arista`` /
            ``daemon TerminAttr`` — EOS-native stanzas.
          * ``Port-Channel`` (capital C) distinct from Cisco's ``Port-
            channel`` (lower c).
        """
        # XML / JSON shape — shared helper tolerates leading shell-echo
        # / banner framing so real captures don't bypass the guard.
        if detect_input_shape(raw_prefix) is not None:
            return None
        if re.search(r"^!\s*device:.*EOS-", raw_prefix, re.MULTILINE):
            return (98, "Arista EOS '! device: ... EOS-' banner present")
        # EOS software image: the ``.swi`` (SWitch Image) extension on a
        # ``boot system`` line is Arista-unique (Cisco boots ``.bin``), and
        # real captures carry it even without the ``! device:`` banner.
        # Tolerate a leading ``! `` (the boot line is often a header comment).
        # Without this, marker-light EOS configs (mlag/BGP topologies) fell
        # through to cisco_iosxe_cli — surfaced by the dogfood detection
        # label-noise sweep (batfish eos_mlag / arista-originator detected as
        # cisco_iosxe_cli at margin 70-90).
        if re.search(r"^!?\s*boot system\b.*\.swi\b", raw_prefix, re.MULTILINE):
            return (95, "Arista EOS boot image (.swi)")
        # RANCID / oxidized collection header — an explicit, operator-tool
        # vendor declaration (real config repos carry it).  Zero false-positive
        # (it names the vendor) and higher-signal than IOS-lookalike content,
        # so marker-light EOS (dhcp-relay / interface / misc feature snippets)
        # stops falling through to cisco_iosxe_cli.  Same dogfood label-noise
        # finding as the .swi marker above.
        if re.search(r"^!\s*RANCID-CONTENT-TYPE:\s*arista\b",
                     raw_prefix, re.MULTILINE | re.IGNORECASE):
            return (97, "RANCID-CONTENT-TYPE: arista header")
        hits = 0
        if re.search(r"^daemon TerminAttr", raw_prefix, re.MULTILINE):
            hits += 1
        if re.search(
            r"^transceiver qsfp default-mode", raw_prefix, re.MULTILINE,
        ):
            hits += 1
        if re.search(
            r"^interface Ethernet\d+(?:/\d+)?\s*$",
            raw_prefix, re.MULTILINE,
        ):
            hits += 1
        if re.search(
            r"^interface Port-Channel\d+\s*$",
            raw_prefix, re.MULTILINE,
        ):
            hits += 1
        if re.search(
            r"^management api http-commands\s*$",
            raw_prefix, re.MULTILINE,
        ):
            hits += 1
        if hits >= 3:
            return (92, f"{hits} Arista EOS grammar markers present")
        if hits == 2:
            return (72, "partial Arista EOS grammar match")
        return None
