"""
``JunosCodec`` — 7th shipped vendor.

See package ``__init__`` for scope + grammar notes.

Module layout (post-split per the codecs/README.md split-codec
convention):

* ``codec.py`` (this file) — the ``JunosCodec`` class with
  metadata (capabilities / classvars / probe / iter_xpaths /
  port-name delegates).  ``parse()`` and ``render()`` are two-
  line delegators to the corresponding functions in the sibling
  modules.
* ``parse.py`` — set-form + block-form parser.  Owns the two-pass
  groups-then-top-level dispatch (GAP 8 apply-groups
  inheritance), the block-form-to-set-form conversion (GAP 9a),
  the per-stanza ``_apply_*`` dispatchers, and the VXLAN switch-
  options back-patch post-pass (GAP-EVPN-2).
* ``render.py`` — canonical tree → Junos ``set``-form text.
  Owns the interface-range structural-collapse auto-synthesis,
  sub-interface unit splitting (GAP 4), VLAN-to-VNI mapping,
  routing-instances emission, and apply-groups round-trip
  re-emission (GAP 9b).
* ``port_names.py`` — cross-vendor port-name identity bridge
  (shared with the rename-modal orchestrator).

Parse strategy (set-form + block-form):

Junos ``set``-form is a flat sequence of ``set <space-separated
hierarchy path>`` commands.  The codec tokenises each line against a
small regex table keyed on the leading path segments (e.g.
``set interfaces``, ``set system host-name``).  Each matcher extracts
the payload and applies it to the CanonicalIntent.  Unrecognised
paths are silently ignored (Tier-3 parse-tolerance).

Block-form (curly-brace hierarchical) input is auto-detected and
converted to set-form before the normal set-form parser runs, so the
dispatch surface is identical for both grammars.

Render strategy (flat set-form, with apply-groups round-trip):

The codec emits flat Junos ``set``-form commands in a deterministic
order (system / login / interfaces / vlans / routing-options / snmp)
that round-trips through the parser.  Strings containing spaces
or shell-special characters are double-quoted per Junos convention.
Hashes stored under the ``junos:<hash>`` vendor tag get their prefix
stripped on render so parse(render(tree)) is a true round-trip.

Apply-groups inheritance (``set groups <name> ... / set apply-groups
<name>``) round-trips: parse buckets group content separately and
replays it via two-pass dispatch; render re-emits the captured group
bodies + the ``set apply-groups`` statements.
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


@register
class JunosCodec(CodecBase):
    """Bidirectional codec for Juniper Junos ``set``-form configuration."""

    name: ClassVar[str] = "juniper_junos"
    version_hint: ClassVar[str | None] = "Junos 18.x+"
    input_format: ClassVar[str] = "cli-junos-set"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "certified"
    canonical_model: ClassVar[str] = "openconfig-lite"
    description: ClassVar[str] = (
        "Paste Junos configuration text — either `set`-form (output of "
        "`show configuration | display set` on any Junos EX/QFX/MX/SRX "
        "device) or block-form (hierarchical curly-brace) directly.  "
        "Block-form is auto-detected and converted to set-form ahead "
        "of the normal parser, so operators with block-form exports "
        "from `show configuration` need no preprocessing."
    )
    sample_input: ClassVar[str] = (
        "set version 23.2R1.14\n"
        "set system host-name sw-edge-01\n"
        "set system root-authentication encrypted-password "
        '"$6$abcd$fake"\n'
        "set system login user netadmin class super-user\n"
        "set system login user netadmin authentication "
        'encrypted-password "$6$efgh$fake"\n'
        "set interfaces em0 unit 0 family inet address "
        "192.0.2.1/24\n"
        "set interfaces ge-0/0/0 description \"uplink to core\"\n"
        "set interfaces ge-0/0/0 unit 0 family inet address "
        "10.0.0.1/31\n"
        "set interfaces lo0 unit 0 family inet address "
        "172.16.0.1/32\n"
        "set vlans USERS vlan-id 10\n"
        "set vlans VOICE vlan-id 20\n"
        "set routing-options static route 0.0.0.0/0 next-hop "
        "10.0.0.2\n"
        "set snmp community public authorization read-only\n"
        'set snmp location "Rack 4 DC1"\n'
    )
    output_extension: ClassVar[str] = "conf"

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="juniper_junos",
        vendor_id="juniper_junos",
        version_range="18.x+",
        device_classes=[DeviceClass.switch, DeviceClass.router],
        supported=[
            "/system/hostname",
            "/interfaces/interface/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/interfaces/interface/ipv6/address/ip",         # GAP-EVPN-3
            "/interfaces/interface/ipv6/address/prefix-length",  # GAP-EVPN-3
            "/interfaces/interface/dhcp-client-v6",          # IPv6 dhcpv6-client (no SLAAC keyword on Junos)
            "/interfaces/interface/tunnel-type",             # gr- / ip- / st0 prefix discriminator
            "/interfaces/interface/config/vrf",   # GAP 6
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/routing/static-route",
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/v3-user",
            "/aaa/authentication/users/user/config/username",
            "/aaa/authentication/users/user/config/password",
            "/aaa/authentication/users/user/config/role",
            "/vxlan-vnis/vni",                   # GAP 6
            "/vxlan-vnis/source-interface",      # GAP-EVPN-2
            "/vxlan-vnis/udp-port",              # GAP-EVPN-2
            "/routing-instances/instance",       # GAP 6
            "/dhcp-servers/pool",                # Cluster E.1-B
            # -- v0.2.0 Wave B: classic FHRP redundancy groups --
            "/interfaces/interface/vrrp-groups/group",
            # -- v0.2.0 Wave C: anycast-gateway companions --
            "/interfaces/interface/ipv4/address/virtual-gateway-address",
            "/interfaces/interface/ipv4/address/virtual-gateway-mac",
            "/interfaces/interface/ipv6/address/virtual-gateway-address",
            "/interfaces/interface/ipv6/address/virtual-gateway-mac",
        ],
        lossy=[
            LossyPath(
                path="/interfaces/interface/subinterfaces/subinterface",
                reason=(
                    "Unit 0 collapses into the parent (common case "
                    "— most Junos interfaces have exactly one unit).  "
                    "GAP 4 materialises units 1+ as distinct "
                    "CanonicalInterface entries named "
                    "``<parent>.<unit>``; per-unit VLAN tagging "
                    "(``unit N vlan-id 100``) still parses-and-"
                    "ignores pending a canonical tagged-subinterface "
                    "model."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/groups",
                reason=(
                    "Apply-groups inheritance is wired for the full "
                    "dispatch surface via GAP 8's two-pass parse "
                    "(system / login / interfaces / protocols / "
                    "SNMP / routing-options / routing-instances / "
                    "vlans).  Unsupported surfaces under ``set "
                    "groups <g>`` (policy-options, firewall filters, "
                    "RADIUS server options beyond host) still "
                    "parse-and-ignore."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/evpn-type5-routes/route",
                reason=(
                    "EVPN Type-5 IP-prefix advertisements use a "
                    "VRF-property canonical model: "
                    "CanonicalRoutingInstance.l3_vni captures the "
                    "L3 VNI (populated from ``set routing-instances "
                    "<vrf> protocols evpn ip-prefix-routes vni "
                    "<N>``); Type-5 announcements are IMPLICIT for "
                    "any interface bound to the VRF via "
                    "CanonicalInterface.vrf.  The per-prefix "
                    "CanonicalEvpnType5Route list is a lossy-by-"
                    "default extension point: no codec populates it "
                    "today (would require ``set policy-options "
                    "policy-statement`` parsing to derive which "
                    "prefixes specific export policies select).  "
                    "Consumers needing explicit per-prefix semantics "
                    "should infer from VRF membership + l3_vni "
                    "rather than relying on this list."
                ),
                severity="warn",
            ),
            # -- v0.2.0 Wave A: per-VRF static-route binding --
            LossyPath(
                path="/routing/static-route/vrf",
                reason=(
                    "CanonicalStaticRoute.vrf is parseable from ``set "
                    "routing-instances <NAME> routing-options static "
                    "route <dest>/<prefix> next-hop <gw>`` but the "
                    "current Junos routing-instances dispatcher "
                    "(``_apply_routing_instances``) only harvests RD "
                    "/ RT / interface-binding / L3 VNI sub-paths; "
                    "static routes inside the VRF block parse-and-"
                    "ignore.  Top-level ``set routing-options static "
                    "route`` lines round-trip cleanly with vrf=''.  "
                    "Cross-vendor migration from a source carrying "
                    "per-VRF static routes (Cisco IOS-XE ``ip route "
                    "vrf <NAME> ...``, NX-OS ``vrf context <NAME> / "
                    "ip route ...``) into Junos surfaces these "
                    "routes at the global level today — operators "
                    "must manually move them under the matching "
                    "routing-instance until the dispatcher is "
                    "widened (follow-up commit)."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            UnsupportedPath(
                path="/routing/bgp",
                reason=(
                    "BGP / IS-IS / OSPF / MPLS stanzas parse-and-"
                    "ignore in v1.  Junos routing-options are "
                    "syntactically rich (policy-options, policy-"
                    "statement, BFD) and warrant a dedicated "
                    "follow-up commit."
                ),
            ),
            UnsupportedPath(
                path="/firewall/filter",
                reason=(
                    "Junos firewall filters are Tier-3 — the grammar "
                    "(family / term / from / then) is distinct from "
                    "ACL models in other codecs and defers."
                ),
            ),
            # -- v0.2.0 Wave C: anycast-gateway system MAC --
            UnsupportedPath(
                path="/anycast-gateway-mac",
                reason=(
                    "Junos has no system-wide anycast-gateway MAC: "
                    "per-IRB-unit overrides live on "
                    "CanonicalIPv4Address.virtual_gateway_mac (the "
                    "``set interfaces irb unit <vid> virtual-gateway-"
                    "v4-mac`` / ``-v6-mac`` grammar) and round-trip "
                    "through the supported per-address surface "
                    "instead.  The top-level CanonicalIntent."
                    "anycast_gateway_mac field is silently dropped "
                    "on render — cross-vendor migration from a "
                    "source carrying the system-wide MAC (Arista "
                    "``ip virtual-router mac-address``, NX-OS "
                    "``fabric forwarding anycast-gateway-mac``) "
                    "must distribute the value across every IRB "
                    "unit's per-address MAC on the receiving Junos "
                    "side."
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
        from ..._tier3_detection import detect_tier3_sections_junos

        intent = parse_intent(raw)
        # Surface Tier-3 `set` lines the parser drops (`set firewall`,
        # `set security policies`, `set policy-options`, `set
        # class-of-service`).  Notification-only.
        intent.dropped_tier3_sections = detect_tier3_sections_junos(raw)
        return intent

    def render(self, tree: Any) -> str:
        return render_intent(tree)

    # -----------------------------------------------------------------
    # iter_xpaths — reuse the shared canonical walker.
    # -----------------------------------------------------------------

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        if isinstance(tree, CanonicalIntent):
            from ..cisco_iosxe_cli.codec import _walk_canonical
            yield from _walk_canonical(tree)

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
        """Detect Junos set-form config.

        Signals:
          * ``set version <X>`` banner on the first non-comment line.
          * ``set system host-name`` — universal Junos line shape.
          * ``set interfaces <media>-<fpc>/<pic>/<port>`` —
            Junos-specific port naming.
        """
        # XML / JSON shape — shared helper tolerates leading shell-echo
        # / banner framing so real captures don't bypass the guard.
        if detect_input_shape(raw_prefix) is not None:
            return None
        if re.search(
            r"^set version \d",
            raw_prefix, re.MULTILINE,
        ):
            return (90, "Junos 'set version X' banner present")
        hits = 0
        if re.search(
            r"^set system host-name\s+\S+",
            raw_prefix, re.MULTILINE,
        ):
            hits += 1
        if re.search(
            r"^set interfaces (?:ge|xe|et|fe|em|me|fxp|ae|lo|irb)",
            raw_prefix, re.MULTILINE,
        ):
            hits += 1
        if re.search(
            r"^set (?:routing-options|protocols|policy-options|firewall)",
            raw_prefix, re.MULTILINE,
        ):
            hits += 1
        if re.search(
            r"^set vlans \S+ vlan-id \d+",
            raw_prefix, re.MULTILINE,
        ):
            hits += 1
        if hits >= 3:
            return (88, f"{hits} Junos set-form grammar markers")
        if hits == 2:
            return (68, "partial Junos set-form grammar match")
        return None
