"""
``CiscoIOSXRCodec`` — bidirectional codec for Cisco IOS-XR
``show running-config`` text.

Targets the ASR 9000, NCS 5500 / 540 / 560 / 5700 / 8000, and CRS
series — Cisco's service-provider routing NOS.  Distinct vendor identity
from ``cisco_iosxe`` / ``cisco_nxos``: a different CLI grammar (4-segment
port names, top-level ``vrf`` stanzas, ``route-policy`` instead of
``route-map``, ``ipv4 address`` inside interfaces), a different
``CapabilityMatrix``, and a different render path.

Module layout mirrors the ``cisco_iosxe_cli`` / ``cisco_nxos`` post-split
shape:

* ``codec.py`` (this file) — the class with metadata / capabilities /
  probe / port-name delegates.  ``parse()`` / ``render()`` are one-line
  delegators to the sibling modules.
* ``parse.py`` — line-scan + per-stanza dispatch over IOS-XR text.
* ``render.py`` — canonical tree → IOS-XR running-config text.
* ``port_names.py`` — cross-vendor 4-segment port-name bridge.

``iter_xpaths`` reuses ``_walk_canonical`` from
:mod:`netcanon.migration.codecs.cisco_iosxe_cli.codec` — IOS-XR
introduces no new canonical xpaths, so the shared walker yields exactly
the right set.

This codec lands in four phases (see
``docs/v0.2.0-planning/04-iosxr-codec/``).  **Phases 1-2 are complete.**
Phase 1: hostname, domain, interfaces (4-segment physical / Loopback /
MgmtEth / Bundle-Ether / sub-interfaces, with IPv4 dotted-mask + IPv6
CIDR + description / admin-state / mtu), and default-VRF ``router
static`` routes.  Phase 2 adds: top-level ``vrf <name>`` stanzas + ``import|export route-target`` blocks → routing-instances; the
route-distinguisher harvested from / rendered to ``router bgp <asn> /
vrf <name> / rd`` (IOS-XR keeps the RD in the BGP process, not the
``vrf`` stanza — declared lossy); per-interface ``vrf <name>``
membership; ``Bundle-Ether`` LAGs (``bundle id <N> mode <m>``); local
users (``username`` block → group + secret); per-VRF ``router static``
routes; and sub-interface ``encapsulation dot1q`` → synthesised VLAN
records.  Shipped ``bidirectional`` (not the dossier's transient
``parse_only``) because the repo forbids a ``parse_only`` + ``cli-*``
codec (``TestNoOrphanedParseOnlyCliCodec``) — same call the NX-OS codec
made.  SNMP (out of v1 XR scope) plus the SP-routing / ``route-policy``
/ MPLS / ``l2vpn`` Tier-3 stanzas remain ``unsupported`` in the matrix
below — Phase 3 surfaces them on ``dropped_tier3_sections`` (the
``detect_tier3_sections_iosxr`` notification banner) rather than
translating them.  ``certainty`` is ``certified`` (Phase 4) — the
real-capture corpus in ``tests/fixtures/real/cisco_iosxr/`` spans 10
configs from two independent sources (7 ``batfish/lab-validation`` +
3 ``ios-xr/xrd-tools`` covering IS-IS / SR-MPLS / SRv6-L3VPN grammar
batfish lacks), all parsing + round-tripping cleanly — well past the
``base.py`` "≥3 real captures" bar.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, ClassVar

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


@register
class CiscoIOSXRCodec(CodecBase):
    """Bidirectional codec for Cisco IOS-XR ``show running-config`` output."""

    name: ClassVar[str] = "cisco_iosxr"
    version_hint: ClassVar[str | None] = "6.x / 7.x"
    input_format: ClassVar[str] = "cli-iosxr"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "certified"
    canonical_model: ClassVar[str] = "openconfig-lite"
    description: ClassVar[str] = (
        "Paste the output of `show running-config` from a Cisco IOS-XR "
        "device (ASR 9000 / NCS 5500 / 8000 / 540 series).  XR uses "
        "4-segment port names (GigabitEthernet0/0/0/0), `vrf` as a "
        "top-level stanza, and `route-policy` instead of `route-map` — "
        "use the `cisco_iosxe_cli` codec for Catalyst / ASR1k / ISR "
        "captures."
    )
    sample_input: ClassVar[str] = (
        "!! IOS XR Configuration 6.6.2\n"
        "!\n"
        "hostname Router\n"
        "domain name example.com\n"
        "!\n"
        "interface Loopback0\n"
        " ipv4 address 10.255.0.1 255.255.255.255\n"
        "!\n"
        "interface GigabitEthernet0/0/0/0\n"
        " description WAN uplink\n"
        " ipv4 address 198.51.100.1 255.255.255.252\n"
        "!\n"
        "interface MgmtEth0/RP0/CPU0/0\n"
        " ipv4 address 192.168.1.1 255.255.255.0\n"
        "!\n"
        "router static\n"
        " address-family ipv4 unicast\n"
        "  0.0.0.0/0 198.51.100.2\n"
        " !\n"
        "!\n"
        "end\n"
    )
    output_extension: ClassVar[str] = "cfg"

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="cisco_iosxr",
        vendor_id="cisco_iosxr",
        version_range="6.x / 7.x",
        device_classes=[DeviceClass.router],
        supported=[
            # System
            "/system/hostname",
            # Interfaces — name + basic L3
            "/interfaces/interface/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/config/mtu",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/interfaces/interface/ipv6/address/ip",
            "/interfaces/interface/ipv6/address/prefix-length",
            # Phase 2 — per-interface VRF membership (bare `vrf <name>`)
            "/interfaces/interface/config/vrf",
            # Phase 2 — sub-interface `encapsulation dot1q` → synthesised
            # VLAN id-list (no port membership; name always empty)
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            # Static routes — default VRF + per-VRF (`router static / vrf`)
            "/routing/static-route",
            "/routing/static-route/vrf",
            # Phase 2 — VRF declarations.  Also declared lossy below (the
            # route-distinguisher must be read from / rendered to the
            # `router bgp` block) → the path classifies lossy.  Name /
            # description / route-target import+export round-trip cleanly.
            "/routing-instances/instance",
            # Phase 2 — Bundle-Ether LAGs (`bundle id <N> mode <m>`)
            "/lags/lag/name",
            "/lags/lag/members",
            "/lags/lag/mode",
            # Phase 2 — local users (`username` block → group + secret)
            "/local-users/user/name",
            "/local-users/user/hashed-password",
            "/local-users/user/role",
        ],
        lossy=[
            LossyPath(
                path="/interfaces/interface/config/type",
                reason=(
                    "CLI parser infers interface type from the name "
                    "prefix (GigabitEthernet -> ethernetCsmacd, Loopback "
                    "-> softwareLoopback, Bundle-Ether -> ieee8023adLag, "
                    "MgmtEth -> ethernetCsmacd, tunnel-ip/te -> tunnel) "
                    "but cannot detect every IANA type — sub-interfaces "
                    "with vendor-specific encapsulation classify as "
                    "'other'."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/4th-port-segment",
                reason=(
                    "IOS-XR port names use 4 segments (rack/slot/"
                    "instance/port) while the cross-vendor PortIdentity "
                    "supports only 3 (stack/module/port).  The 4th "
                    "segment is preserved via "
                    "PortIdentity.meta['iosxr_port_index'] for the "
                    "same-vendor round-trip but DROPS to '0' when "
                    "renaming to a 3-segment target (IOS-XE / Arista). "
                    "Operators must verify port mappings via the rename "
                    "modal."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/routing-instances/instance",
                reason=(
                    "VRF declarations (`vrf <name>` + `address-family "
                    "ipv4 unicast` / `import|export route-target`) and "
                    "per-interface `vrf <name>` membership parse + render "
                    "cleanly, but `route_distinguisher` must be read from "
                    "/ rendered to the BGP block (`router bgp <asn> / vrf "
                    "<name> / rd <rd>`) — IOS-XR keeps the RD there, not "
                    "in the `vrf` stanza.  Phase 2 wires a minimal "
                    "BGP-RD harvest + a minimal `router bgp` RD-carrier "
                    "on render whose ASN is derived from the RD's "
                    "administrator field (the `<asn>:<nn>` convention); a "
                    "config whose BGP ASN differs from the RD "
                    "administrator re-emits the normalised ASN (cosmetic "
                    "— the RD itself round-trips).  An XR source with no "
                    "`router bgp` stanza keeps route_distinguisher='' on "
                    "round-trip.  `l3_vni` (EVPN Type-5) is not modelled "
                    "— IOS-XR EVPN is a Tier-3 `l2vpn` / `evpn` surface."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            # ── Tier-1/2 surfaces this codec drops on render — declared so the
            #    live validation report flags the loss instead of reporting
            #    `severity: ok` (2026-06 adversarial review #9). ──
            UnsupportedPath(path="/system/timezone", reason="Render emits no clock/timezone stanza; intent.timezone is dropped on migration."),
            UnsupportedPath(path="/system/dns-server", reason="Render emits no name-server config; intent.dns_servers are dropped on migration."),
            UnsupportedPath(path="/system/ntp-server", reason="Render emits no NTP config; intent.ntp_servers are dropped on migration."),
            UnsupportedPath(path="/system/syslog-server", reason="Render emits no logging/syslog config; intent.syslog_servers are dropped on migration."),
            UnsupportedPath(path="/dhcp-servers/pool", reason="Render emits no DHCP server pool; intent.dhcp_servers are dropped on migration."),
            UnsupportedPath(path="/radius-servers/server/host", reason="Render emits no AAA radius-server config; RADIUS host is dropped on migration."),
            UnsupportedPath(path="/radius-servers/server/key", reason="Render emits no AAA radius-server config; the RADIUS shared secret is dropped on migration."),
            # ── SNMP — out of the v1 XR scope ──
            UnsupportedPath(
                path="/snmp/community",
                reason="SNMP parse + render is out of the v1 XR scope.",
            ),
            # ── Routing protocols — Tier 3 ──
            UnsupportedPath(
                path="/routing/bgp",
                reason=(
                    "IOS-XR `router bgp <asn>` is Tier-3.  Phase 3 adds a "
                    "minimal per-VRF RD harvest; full BGP modeling stays "
                    "unsupported (per-VRF address-family + neighbor-group "
                    "templates diverge from IOS-XE)."
                ),
            ),
            UnsupportedPath(
                path="/routing/ospf",
                reason="`router ospf <pid>` parse-and-ignore (Tier-3).",
            ),
            UnsupportedPath(
                path="/routing/isis",
                reason="`router isis <name>` parse-and-ignore (Tier-3).",
            ),
            UnsupportedPath(
                path="/mpls",
                reason=(
                    "`mpls ldp` / `mpls traffic-eng` / `mpls oam` are "
                    "SP-platform fundamentals with no canonical model; "
                    "Tier-3 banner notes the dropped surface."
                ),
            ),
            # ── Policy primitives — Tier 3 ──
            UnsupportedPath(
                path="/policy/route-policy",
                reason=(
                    "IOS-XR `route-policy NAME ... end-policy` is a "
                    "structured if/elseif/else/endif DSL distinct from "
                    "IOS-XE `route-map` sequence form.  Tier-3 by design "
                    "— parity with Junos `policy-options`."
                ),
            ),
            UnsupportedPath(
                path="/policy/prefix-set",
                reason="`prefix-set NAME ... end-set` set-form list (Tier-3).",
            ),
            UnsupportedPath(
                path="/policy/community-set",
                reason="`community-set NAME ... end-set` set-form list (Tier-3).",
            ),
            UnsupportedPath(
                path="/policy/as-path-set",
                reason="`as-path-set NAME ... end-set` set-form filter (Tier-3).",
            ),
            # ── EVPN / VXLAN — out of v1 scope ──
            UnsupportedPath(
                path="/vxlan-vnis/vni",
                reason=(
                    "IOS-XR VXLAN (NCS 5500 / 540 `nve` interfaces) is "
                    "rare in the SP corpus; no canonical demand surfaced. "
                    "Parse-and-ignore in v1."
                ),
            ),
            UnsupportedPath(
                path="/vxlan-vnis/source-interface",
                reason="See /vxlan-vnis/vni — same scope.",
            ),
            UnsupportedPath(
                path="/vxlan-vnis/udp-port",
                reason="See /vxlan-vnis/vni — same scope.",
            ),
            UnsupportedPath(
                path="/evpn-type5-routes/route",
                reason=(
                    "IOS-XR EVPN runs under top-level `l2vpn` + `evpn` + "
                    "`bridge group` stanzas — grammatically distant from "
                    "the IOS-XE / Arista / NX-OS EVPN model.  No canonical "
                    "mapping in v1."
                ),
            ),
            # ── Firewall / NAT / ACL — Tier 3 ──
            UnsupportedPath(
                path="/access-list/extended",
                reason=(
                    "IOS-XR `ipv4 access-list NAME / N permit ...` is "
                    "Tier-3 — auto-translating ACL semantics across "
                    "vendors risks shipping subtly-permissive rules.  "
                    "Operator authors firewall policy manually.  Parity "
                    "with the IOS-XE codec."
                ),
            ),
            UnsupportedPath(
                path="/access-list/ipv6",
                reason="See /access-list/extended — IPv6 variant.",
            ),
            UnsupportedPath(
                path="/firewall",
                reason=(
                    "IOS-XR firewall features are Tier-3 stateful "
                    "surfaces — never auto-translatable.  Parity with "
                    "IOS-XE codec."
                ),
            ),
            UnsupportedPath(
                path="/nat",
                reason=(
                    "IOS-XR NAT (`nat64` / `cgnat`) is Tier-3.  Operator "
                    "authors NAT manually.  Parity with IOS-XE codec."
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
        from ..._tier3_detection import detect_tier3_sections_iosxr

        intent = parse_intent(raw)
        # Surface Tier-3 stanza headers the parser deliberately drops
        # (BGP / OSPF / IS-IS / MPLS / route-policy / prefix-set / ACLs /
        # l2vpn / evpn).  Notification-only — never read by render.
        intent.dropped_tier3_sections = detect_tier3_sections_iosxr(raw)
        return intent

    def render(self, tree: Any) -> str:
        return render_intent(tree)

    # -----------------------------------------------------------------
    # iter_xpaths — reuse the shared canonical walker
    # -----------------------------------------------------------------

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        """Yield schema xpaths from a :class:`CanonicalIntent`."""
        if isinstance(tree, CanonicalIntent):
            from ..cisco_iosxe_cli.codec import _walk_canonical
            yield from _walk_canonical(tree)

    # -----------------------------------------------------------------
    # Cross-vendor port-name translation (delegated to .port_names)
    # -----------------------------------------------------------------

    def classify_port_name(self, name: str):
        return _port_names.classify_port_name(name)

    def format_port_identity(self, identity) -> str | None:
        return _port_names.format_port_identity(identity)

    # -----------------------------------------------------------------
    # Auto-detection probe
    # -----------------------------------------------------------------

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Detect Cisco IOS-XR ``show running-config`` text.

        Primary marker: the ``!! IOS XR Configuration <version>`` banner
        is unambiguous — no other vendor emits this exact form.

        Without the banner we score IOS-XR-SPECIFIC structural markers:
        4-segment port names + the ``ipv4 address`` keyword (vs IOS-XE
        ``ip address`` / NX-OS ``ip address X/N``), ``MgmtEth`` (XR-only),
        ``Bundle-Ether``, and the ``route-policy`` / ``prefix-set`` DSL
        signatures.  These don't appear in IOS-XE / NX-OS captures, so
        the probe doesn't steal their configs.
        """
        # Reject XML / JSON early (shared shape helper).
        if detect_input_shape(raw_prefix) is not None:
            return None

        if re.search(r"^!!\s+IOS XR Configuration", raw_prefix, re.MULTILINE):
            return (98, "IOS XR Configuration banner present")

        hits = 0
        if re.search(
            r"^interface\s+(?:GigabitEthernet|TenGigE|HundredGigE|FortyGigE|"
            r"TwentyFiveGigE|TwoHundredGigE|FourHundredGigE|FastEthernet)"
            r"\d+/\d+/\d+/\d+\b",
            raw_prefix, re.IGNORECASE | re.MULTILINE,
        ):
            hits += 2  # 4-segment physical port — strong XR signal
        if re.search(r"^\s+ipv4\s+address\s+\d", raw_prefix, re.MULTILINE):
            hits += 1
        if re.search(
            r"^interface\s+MgmtEth\d+/(?:RP|RSP)\d+/CPU\d+/\d+",
            raw_prefix, re.IGNORECASE | re.MULTILINE,
        ):
            hits += 2  # MgmtEth — XR-only
        if re.search(r"^interface\s+Bundle-Ether\d+",
                     raw_prefix, re.IGNORECASE | re.MULTILINE):
            hits += 1
        if re.search(r"^route-policy\s+\S+", raw_prefix, re.MULTILINE):
            hits += 1
        if re.search(r"^end-policy\s*$", raw_prefix, re.MULTILINE):
            hits += 1
        if re.search(r"^prefix-set\s+\S+", raw_prefix, re.MULTILINE):
            hits += 1

        if hits >= 4:
            return (92, f"{hits} IOS-XR grammar markers (banner absent)")
        if hits >= 2:
            return (75, f"{hits} IOS-XR grammar markers")
        return None
