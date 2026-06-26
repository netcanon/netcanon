"""
``CiscoIOSXECLICodec`` — bidirectional codec for Cisco IOS-XE
``show running-config`` text.

Direction: ``bidirectional``.  Certified.

Module layout (post-split):

* ``codec.py`` (this file) — the ``CiscoIOSXECLICodec`` class with
  metadata (capabilities / classvars / probe / port-name delegates).
  ``parse()`` and ``render()`` are one-line delegators to the
  corresponding functions in the sibling modules.
* ``parse.py`` — line-scan + per-stanza dispatch over IOS-XE
  ``show running-config`` text.  Hosts the regex constants, the
  per-block parsers (interfaces / VLANs / SVIs / LAGs / static
  routes / SNMP / DHCP / RADIUS / local users), and helpers like
  ``_infer_type`` / ``_mask_to_prefix``.
* ``render.py`` — canonical tree → IOS-XE running-config text.
  Hosts the render-only helpers (``_prefix_to_mask`` /
  ``_cidr_to_dest_mask`` / ``_extract_lag_number`` /
  ``_split_cisco_hash``).
* ``port_names.py`` — cross-vendor port-name bridge.

``_walk_canonical`` (the canonical-tree xpath walker reused by every
other codec's ``iter_xpaths`` implementation) now lives in
:mod:`netcanon.migration.canonical.xpath_walker` and is **re-exported**
here, so the historical
``from netcanon.migration.codecs.cisco_iosxe_cli.codec import _walk_canonical``
import surface every cross-codec consumer relies on stays intact.

Parser strategy
---------------
IOS ``show running-config`` is a line-oriented, indentation-significant
format.  Interfaces are delimited by ``interface <name>`` lines and
terminated by ``!`` comment lines.  See :mod:`.parse` for the full
walk.  The render path emits the same ``!``-delimited stanzas an
operator would paste back into a console.

Limitations:
    * Routing protocols (BGP/OSPF), ACLs, crypto, AAA-policy,
      QoS, and route-maps are silently skipped on parse and not
      emitted on render — out of canonical scope.
    * Subnet mask → prefix-length conversion handles standard
      contiguous masks only (``255.255.255.0`` → ``/24``).
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
from ...canonical.xpath_walker import _walk_canonical
from .._input_shape import detect_input_shape
from ..base import CodecBase
from ..registry import register
from . import port_names as _port_names
from .parse import parse_intent
from .render import render_intent


@register
class CiscoIOSXECLICodec(CodecBase):
    """Bidirectional codec for Cisco IOS-XE ``show running-config`` output.

    Shares ``vendor_id=cisco_iosxe`` with the NETCONF codec — both
    target the same vendor YAML.
    """

    name: ClassVar[str] = "cisco_iosxe_cli"
    version_hint: ClassVar[str | None] = "15.x / 16.x / 17.x"
    input_format: ClassVar[str] = "cli-ios"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "certified"
    canonical_model: ClassVar[str] = "openconfig-lite"
    description: ClassVar[str] = (
        "Paste the output of `show running-config`.  This is the text "
        "your existing backup collector already captures — you can also "
        "pick a stored Cisco config from the dropdown."
    )
    sample_input: ClassVar[str] = (
        '!\n'
        'version 17.9\n'
        'hostname Router\n'
        '!\n'
        'interface GigabitEthernet0/0/0\n'
        ' description WAN uplink\n'
        ' ip address 198.51.100.1 255.255.255.252\n'
        ' no shutdown\n'
        '!\n'
        'interface Loopback0\n'
        ' description Router-ID\n'
        ' ip address 10.255.0.1 255.255.255.255\n'
        '!\n'
        'end\n'
    )
    output_extension: ClassVar[str] = "cfg"

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="cisco_iosxe_cli",
        vendor_id="cisco_iosxe",
        version_range="15.x+",
        device_classes=[DeviceClass.router, DeviceClass.switch],
        supported=[
            "/system/hostname",
            "/interfaces/interface/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/interfaces/interface/ipv6/address/ip",         # GAP-EVPN-3
            "/interfaces/interface/ipv6/address/prefix-length",  # GAP-EVPN-3
            "/interfaces/interface/dhcp-client-v6",          # IPv6 DHCPv6 / SLAAC
            "/interfaces/interface/tunnel-type",             # GRE / IPIP / IPSEC / VXLAN discriminator
            # ``switchport voice vlan <N>`` — parsed (_SWITCHPORT_VOICE_RE)
            # and rendered, so it fully round-trips same-vendor (blind-audit
            # 65f9c01 #11; targets that can't carry it declare it unsupported).
            # The sibling L2 surfaces (switchport-mode / access-vlan / trunk-*)
            # also round-trip but ride the classify() default; declared here
            # because the audit named voice-vlan specifically.
            "/interfaces/interface/voice-vlan",
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/routing/static-route",
            "/routing/static-route/vrf",          # v0.2.0 — per-VRF binding (ip route vrf <NAME>)
            # Tier 2 — SNMP
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/trap-host",
            "/snmp/v3-user",
            # Wave B (v0.2.0) — classic VRRP groups.  Parses the
            # ``vrrp <vrid> ip|ipv6|priority|preempt|description|
            # authentication|track|timers`` family inside ``interface``
            # stanzas; renders the classic single-line per-attribute
            # form (broadest IOS-XE compatibility, 15.x onward).
            "/interfaces/interface/vrrp-groups/group",
            # NB: ``/interfaces/interface/ipv4/address/virtual-gateway-address``
            # is declared LOSSY below — SD-Access anycast only round-trips the
            # primary-IP-as-gateway shape (vga == ip); a separate cross-vendor
            # VARP VIP (vga != ip) drops on render.
            # Wave C (v0.2.0) — top-level ``fabric forwarding
            # anycast-gateway-mac <MAC>`` declares the chassis-wide
            # anycast MAC.  Round-trips between Cisco dotted-triplet
            # wire form and canonical colon-hex.
            "/anycast-gateway-mac",
        ],
        lossy=[
            LossyPath(
                path="/vlans/vlan/ipv4/address/virtual-gateway-address",
                reason=(
                    "VLAN-SVI mount render gap: the synthesized `interface "
                    "Vlan<N>` (synthesize_svis_from_vlan_l3) carries only "
                    "ip+prefix_length, so an anycast virtual-gateway IP on a "
                    "VLAN-record address is stripped before the anycast-mode "
                    "emit fires — even the vga==ip SD-Access partial that "
                    "round-trips on the interface mount. The secondary-IP flag "
                    "DOES survive (positional ` secondary` token) so it stays "
                    "supported. Declared lossy (blind-audit f92e97a T0-2)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vlans/vlan/ipv4/address/virtual-gateway-mac",
                reason=(
                    "VLAN-SVI mount render gap: the synthesized SVI carries "
                    "only ip+prefix_length, and IOS-XE has no per-SVI virtual-"
                    "MAC line (the chassis-wide anycast MAC rides "
                    "/anycast-gateway-mac). Declared lossy "
                    "(blind-audit f92e97a T0-2)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/ipv4/address/virtual-gateway-address",
                reason=(
                    "SD-Access anycast (virtual_gateway_address == the "
                    "interface's primary IP) round-trips via `fabric "
                    "forwarding mode anycast-gateway`, but a SEPARATE "
                    "cross-vendor VARP virtual IP (virtual_gateway_address "
                    "!= the interface IP, the Arista/Junos shape) has no "
                    "IOS-XE equivalent and drops on render (emitted as a "
                    "review comment only).  Demoted from supported to lossy "
                    "so the separate-VIP loss is surfaced instead of "
                    "reported severity:ok (silent-loss guard, Bucket-C "
                    "stage 3)."
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
                path="/routing/static-route/description",
                reason=(
                    "Parse/render round-trip a single-token ``ip route ... "
                    "name <X>`` route label, but an IOS-XE route name is a "
                    "single whitespace-free token — a multi-word description "
                    "(e.g. a Junos free-text route description) cannot be "
                    "represented and is dropped (run3)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/config/type",
                reason=(
                    "CLI parser infers interface type from the name prefix "
                    "(GigabitEthernet → ethernetCsmacd, Loopback → "
                    "softwareLoopback) but cannot detect all IANA types."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/evpn-type5-routes/route",
                reason=(
                    "EVPN Type-5 per-prefix records are a VRF-"
                    "property canonical model via "
                    "CanonicalRoutingInstance.l3_vni; IOS-XE would "
                    "derive Type-5 intent from ``router bgp / "
                    "address-family l2vpn evpn`` + per-VRF route-"
                    "target configuration.  No codec populates per-"
                    "prefix records today — lossy-by-default "
                    "extension point pending future route-map "
                    "parsing."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/address-family",
                reason=(
                    "IOS-XE 17.12+ supports the modern multi-line "
                    "``vrrp <VRID> address-family ipv4`` nested block "
                    "with indented ``address`` / ``priority`` / "
                    "``preempt`` sub-commands.  The parser detects the "
                    "surface (so the lossiness is visible) but does "
                    "not deep-populate the nested attributes.  Render "
                    "always emits the classic single-line per-"
                    "attribute form, which is accepted by every IOS-"
                    "XE release from 15.x onward and is the form real "
                    "captures emit.  A config that uses ONLY the "
                    "modern AF form round-trips as an empty group "
                    "shell — the lossiness is intentional and "
                    "operator-visible."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/routing-instances/instance",
                reason=(
                    "VRF declarations (``vrf definition <name>`` "
                    "with ``rd`` + ``address-family ipv4`` + "
                    "``route-target import/export``) and per-"
                    "interface ``vrf forwarding <name>`` are parsed "
                    "into ``CanonicalIntent.routing_instances`` "
                    "(see ``parse._parse_routing_instances``) and "
                    "rendered back to ``vrf definition`` blocks "
                    "(see ``render`` VRF emission loop).  Cross-"
                    "vendor render to Junos ``set routing-instances "
                    "<name> instance-type vrf`` confirmed bidir-"
                    "ectional via Wave 10β-B (commit `40de39c`).  "
                    "Lossy rather than supported because per-VRF "
                    "static routes carry no ``vrf`` discriminator "
                    "on ``CanonicalStaticRoute`` (route table "
                    "membership drops on round-trip), and "
                    "``address-family ipv6`` / EVPN ``l2vpn evpn`` "
                    "sub-stanzas inside ``vrf definition`` are "
                    "parse-and-ignore in v1.  Basic VRF + "
                    "RD + RT_imports/exports + description "
                    "round-trip cleanly."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
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
                path="/interfaces/interface/subinterfaces/subinterface/ipv6",
                reason="Phase 0.5 scope — IPv4 only.",
            ),
            UnsupportedPath(
                path="/vxlan-vnis/vni",
                reason=(
                    "IOS-XE VXLAN mappings (`interface nve1 / member "
                    "vni <N> associate vrf <name>`) parse-and-ignore "
                    "in v1.  CanonicalVxlan schema exists; wire-up "
                    "deferred until demand arrives for Catalyst-to-"
                    "Arista migrations."
                ),
            ),
            UnsupportedPath(
                path="/vxlan-vnis/source-interface",
                reason=(
                    "IOS-XE VXLAN source-interface (`interface nve1 / "
                    "source-interface Loopback<N>`) parse-and-ignore "
                    "in v1.  Same scope as /vxlan-vnis/vni — both "
                    "land when Catalyst VXLAN demand arrives."
                ),
            ),
            UnsupportedPath(
                path="/vxlan-vnis/udp-port",
                reason=(
                    "IOS-XE VXLAN UDP port (`interface nve1 / vxlan "
                    "udp-port <N>`) parse-and-ignore in v1.  Same "
                    "scope as /vxlan-vnis/vni."
                ),
            ),
            # ── ACL / firewall / NAT (Tier 3 — not auto-translatable) ──
            UnsupportedPath(
                path="/access-list/extended",
                reason=(
                    "Cisco IOS-XE extended ACLs "
                    "(`ip access-list extended <name>` or numbered "
                    "100-199 / 2000-2699) are Tier 3 — auto-"
                    "translating ACL semantics across vendors risks "
                    "shipping subtly-permissive rules.  Operator must "
                    "author firewall policy manually."
                ),
            ),
            UnsupportedPath(
                path="/access-list/standard",
                reason=(
                    "Standard ACLs (numbered 1-99 / 1300-1999, or "
                    "named) are Tier 3 — see `/access-list/extended`."
                ),
            ),
            UnsupportedPath(
                path="/access-list/ipv6",
                reason=(
                    "IPv6 access-lists (`ipv6 access-list <name>`) "
                    "are Tier 3 — see `/access-list/extended`."
                ),
            ),
            UnsupportedPath(
                path="/firewall",
                reason=(
                    "Zone-based firewall (`zone-pair security` / "
                    "`policy-map type inspect`) is Tier 3 — stateful "
                    "zone-pair semantics don't translate cleanly "
                    "across vendors.  Operator must author firewall "
                    "policy manually."
                ),
            ),
            UnsupportedPath(
                path="/nat",
                reason=(
                    "NAT configuration (`ip nat inside source` / "
                    "`ip nat outside source` / `ip nat pool`) is "
                    "Tier 3 — NAT semantics are tightly coupled to "
                    "interface zone designations and don't translate "
                    "cleanly cross-vendor.  Operator must author NAT "
                    "policy manually."
                ),
            ),
            # -- Ship-before-wire (v0.2.0) -- IPv6 anycast --
            # (per-VRF static routes graduated to ``supported`` in
            # v0.2.0 — see ``/routing/static-route/vrf`` above.)
            UnsupportedPath(
                path="/interfaces/interface/ipv6/address/virtual-gateway-address",
                reason=(
                    "IPv6 anycast-gateway virtual IP companion parses-"
                    "and-ignores in v1.  IOS-XE SD-Access IPv6 anycast "
                    "is rare in production captures (the corpus has "
                    "zero fixtures exercising it); wire-up deferred "
                    "until demand arrives.  IPv4 SD-Access anycast IS "
                    "supported (see ``/interfaces/interface/ipv4/"
                    "address/virtual-gateway-address`` in the "
                    "``supported`` list)."
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
        # Surface Tier-3 stanza headers the parser deliberately drops
        # (ACLs, NAT, QoS, route-maps, crypto).  Notification-only —
        # never read by any render-side code.
        intent.dropped_tier3_sections = detect_tier3_sections_iosxe_cli(raw)
        return intent

    def render(self, tree: Any) -> str:
        return render_intent(tree)

    # -----------------------------------------------------------------
    # iter_xpaths — same shape as the NETCONF codec
    # -----------------------------------------------------------------

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        """Yield schema xpaths from a :class:`CanonicalIntent`."""
        if isinstance(tree, CanonicalIntent):
            yield from _walk_canonical(tree)
        elif isinstance(tree, dict):
            # Back-compat fallback for old-shape trees.
            from ..cisco_iosxe.codec import _walk
            yield from _walk(tree, "")

    # -----------------------------------------------------------------
    # Cross-vendor port-name translation
    # -----------------------------------------------------------------
    # Implementation extracted to :mod:`.port_names` (see that
    # module's docstring for the full form-by-form reference).
    # These methods delegate so the codec class stays focused on
    # parse/render.

    def classify_port_name(self, name: str):
        return _port_names.classify_port_name(name)

    def format_port_identity(self, identity) -> str | None:
        return _port_names.format_port_identity(identity)

    # -----------------------------------------------------------------
    # Auto-detection probe (R5)
    # -----------------------------------------------------------------

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Detect Cisco IOS CLI ``show running-config`` text.

        Strong signals (all Cisco-specific; ``show running-config`` is
        intentionally NOT one of them — that phrase is the command
        operators run on Aruba, Arista, and others, so its presence in
        a paste means "this is some vendor's running-config" rather
        than "this is Cisco's running-config"):

          * ``Building configuration...`` banner
          * ``Current configuration : <N> bytes`` banner
          * ``! Last configuration change at ...`` banner line
          * ``service timestamps`` directive (Cisco-specific syntax)
          * ``interface GigabitEthernet`` / ``TenGigabitEthernet`` /
            etc. — Cisco interface naming
          * ``ip address X.X.X.X Y.Y.Y.Y`` (dotted-decimal mask form;
            Aruba uses CIDR ``/24`` form)
          * ``switchport`` mode keyword (Cisco specific)
          * ``no shutdown`` form

        Weaker signals: ``!`` stanza delimiter, leading ``hostname``.
        """
        lowered = raw_prefix.lower()
        # XML or JSON - not IOS CLI.  Uses the shared shape helper so
        # captures with leading shell echo / banner / motd framing
        # don't bypass the guard (Round 4.2 fix).
        if detect_input_shape(raw_prefix) is not None:
            return None

        # If the input carries a recognisable Aruba banner anywhere in
        # the first few KiB, defer to Aruba's probe.  This guards the
        # common paste case where the operator copies a full session
        # transcript including the prompt + `show running-config` echo
        # — the string "show running-config" is the OPERATOR'S
        # COMMAND, not an IOS-specific banner, so reasoning from its
        # presence alone produced false positives.  Aruba's own probe
        # will still claim the input via its own banner match.
        if re.search(
            r"^;\s*(J[A-Z]?\d+[A-Z]*|hpStack_\w+)\s+Configuration",
            raw_prefix, re.MULTILINE,
        ):
            return None

        # Defer to IOS-XR when an XR-EXCLUSIVE marker is present.  None of
        # these appear in genuine IOS-XE running-config — the `!! IOS XR
        # Configuration` banner, 4-segment physical ports
        # (`GigabitEthernet0/0/0/0`; IOS-XE tops out at 3 segments),
        # `MgmtEth` management ports, and the `route-policy` /
        # `end-policy` / `prefix-set` routing DSL are all XR-only.
        # Batfish-extracted XR captures otherwise share enough generic
        # Cisco banners / interface shapes to tie IOS-XE here and lose
        # the alphabetical tie-break, silently mis-detecting XR as XE
        # (2026-06 review #21).  (The bare `ipv4 address` keyword is
        # deliberately NOT in this list: Batfish's IOS-XE interface
        # coverage fixture mixes it in, so it isn't reliably exclusive.)
        if re.search(
            r"^!!\s+IOS XR Configuration"
            r"|^interface\s+(?:GigabitEthernet|TenGigE|HundredGigE|"
            r"FortyGigE|TwentyFiveGigE|TwoHundredGigE|FourHundredGigE|"
            r"FastEthernet)\d+/\d+/\d+/\d+\b"
            r"|^interface\s+MgmtEth\d"
            r"|^route-policy\s+\S+"
            r"|^end-policy\s*$"
            r"|^prefix-set\s+\S+",
            raw_prefix, re.IGNORECASE | re.MULTILINE,
        ):
            return None

        # Same alphabetical-tie-break hazard as the XR block above, but for
        # NX-OS and AOS-CX: a bannerless containerlab / golden-config
        # capture (no ``!Command: show running-config`` NX-OS banner, no
        # ``!Version ArubaOS-CX`` banner) caps its own vendor's structural
        # probe at 90 and TIES IOS-XE's generic ``no shutdown`` /
        # ``interface loopback`` / ``switchport`` markers at 90 — then
        # loses the alphabetical tie-break (``cisco_iosxe_cli`` <
        # ``cisco_nxos``) and silently mis-detects as IOS-XE.  Each marker
        # below is exclusive to the other vendor and never appears in
        # genuine IOS-XE running-config, so deferring (return None) cannot
        # regress IOS-XE detection:
        #   NX-OS  — ``feature nv overlay`` / ``feature vn-segment-vlan-
        #            based`` (IOS-XE has no ``feature`` command at all),
        #            ``nv overlay evpn`` (IOS-XE uses ``l2vpn evpn``), and
        #            the ``vn-segment <vni>`` VLAN→VNI binding (IOS-XE uses
        #            ``vlan configuration N / member vni``).
        #   AOS-CX — ``interface lag <N>`` (IOS-XE uses ``Port-channel``) and
        #            the per-interface ``vrf attach`` (IOS-XE uses ``vrf
        #            forwarding``).
        # ``interface nve1`` is deliberately NOT in this list: IOS-XE
        # Catalyst VXLAN-EVPN also uses ``interface nve1`` + ``member vni``,
        # so it is shared, not NX-OS-exclusive (a real IOS-XE EVPN leaf
        # fixture carries it).
        if re.search(
            r"^feature\s+nv\s+overlay\b"
            r"|^feature\s+vn-segment-vlan-based\b"
            r"|^nv\s+overlay\s+evpn\b"
            r"|^\s+vn-segment\s+\d+"
            r"|^interface\s+lag\s+\d"
            r"|^\s+vrf\s+attach\b",
            raw_prefix, re.IGNORECASE | re.MULTILINE,
        ):
            return None

        # Cisco-specific banners — each unambiguous on its own.  The
        # ``show running-config`` echo is now ONLY a confidence
        # multiplier alongside one of these; on its own it's not
        # diagnostic.  See _IOS_BANNER_HITS for the full list.
        cisco_banner_hits = 0
        for pattern, weight in _IOS_BANNER_HITS:
            if pattern in lowered:
                cisco_banner_hits += weight
        if cisco_banner_hits >= 4:
            return (
                98,
                "multiple IOS-specific banners "
                "(Building / Current / Last change / service timestamps)",
            )
        if cisco_banner_hits >= 2:
            return (
                95,
                "IOS-specific banner sequence detected",
            )
        # Strong IOS-shape markers (one enough for medium confidence).
        strong_hits = 0
        if re.search(r"^interface\s+(gigabit|fastether|tengigabit|"
                     r"loopback|vlan|port-channel|tunnel|serial)",
                     raw_prefix, re.IGNORECASE | re.MULTILINE):
            strong_hits += 1
        if re.search(r"^\s+ip\s+address\s+\d+\.\d+\.\d+\.\d+\s+\d+\.",
                     raw_prefix, re.IGNORECASE | re.MULTILINE):
            strong_hits += 1
        if re.search(r"^\s+(no\s+)?shutdown\s*$",
                     raw_prefix, re.IGNORECASE | re.MULTILINE):
            strong_hits += 1
        if re.search(r"^\s+switchport\s+",
                     raw_prefix, re.IGNORECASE | re.MULTILINE):
            strong_hits += 1
        # If the operator's prompt-echo carries ``show running-config``
        # AND we see at least one Cisco-shape structural marker, we
        # have stronger evidence than structure alone.  This is the
        # path that previously fired at 95 on bare ``show running-
        # config`` text.
        if "show running-config" in lowered and strong_hits >= 1:
            return (
                90,
                f"'show running-config' header + "
                f"{strong_hits} IOS structural marker(s)",
            )
        if strong_hits >= 2:
            return (90, f"{strong_hits} strong IOS CLI markers present")
        if strong_hits == 1:
            return (70, "one IOS CLI marker present")
        # Weakest fallback — `hostname` + `!` is plausible IOS but also
        # plausible many other CLI dialects.  Keep the score low.
        if (re.search(r"^hostname\s+\S+", raw_prefix, re.IGNORECASE | re.MULTILINE)
                and "!" in raw_prefix):
            return (45, "leading 'hostname' + '!' delimiters — possible IOS")
        return None


#: Cisco-specific IOS banner / directive substrings used by the
#: detection probe.  Each entry is ``(lowered_substring, weight)``.
#: When the cumulative weight reaches a threshold the probe returns a
#: high-confidence detection.  Curated to be Cisco-unique (Aruba /
#: Arista / Junos do NOT emit any of these strings):
#:
#:   * ``Building configuration...`` — Cisco IOS / IOS-XE banner
#:     emitted by the device when ``show running-config`` runs
#:   * ``Current configuration : <N> bytes`` — second-line Cisco
#:     banner companion to ``Building configuration...``
#:   * ``! Last configuration change at`` — Cisco's commit-history
#:     comment (Aruba uses ``;`` for comments, not ``!``)
#:   * ``service timestamps`` — Cisco-specific top-of-config
#:     directive controlling logging/debug message formatting
#:
#: Each contributes weight 2.  The 95 threshold is "two banners
#: present"; 98 is "all four / kitchen sink".
_IOS_BANNER_HITS: tuple[tuple[str, int], ...] = (
    ("building configuration", 2),
    ("current configuration :", 2),
    ("! last configuration change at", 2),
    ("service timestamps", 2),
)


# ``_walk_canonical`` was relocated to
# ``netcanon/migration/canonical/xpath_walker.py`` (run3
# ``walk-canonical-vendor-leaf``) so the shared canonical-tree walker
# no longer lives inside a vendor codec.  It is imported at module top
# and re-exported from here, keeping the historical
# ``from ...cisco_iosxe_cli.codec import _walk_canonical`` path that the
# cross-codec ``iter_xpaths`` consumers + honesty tests rely on intact.
