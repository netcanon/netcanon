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

``_walk_canonical`` (the canonical-tree xpath walker reused by
several other codecs' ``iter_xpaths`` implementations) is kept here
at module level rather than in :mod:`.parse` or :mod:`.render` to
preserve the
``from netconfig.migration.codecs.cisco_iosxe_cli.codec import _walk_canonical``
import surface every cross-codec consumer relies on.

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
    * ``secondary`` IP addresses are ignored on parse (first
      address only).
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
            "/interfaces/interface/config/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/interfaces/interface/ipv6/address/ip",         # GAP-EVPN-3
            "/interfaces/interface/ipv6/address/prefix-length",  # GAP-EVPN-3
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/routing/static-route",
            # Tier 2 — SNMP
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/trap-host",
            "/snmp/v3-user",
        ],
        lossy=[
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
        ],
        unsupported=[
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
            UnsupportedPath(
                path="/routing-instances/instance",
                reason=(
                    "VRF declarations (`vrf definition <name>` with "
                    "`rd` + `address-family ipv4` + "
                    "`route-target import/export`) and per-interface "
                    "`vrf forwarding <name>` parse-and-ignore in "
                    "v1.  CanonicalRoutingInstance + "
                    "CanonicalInterface.vrf schema exists; IOS-XE "
                    "wire-up deferred."
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
        ],
    )

    @property
    def capabilities(self) -> CapabilityMatrix:
        return self._CAPS

    # -----------------------------------------------------------------
    # Parse / Render — delegate to sibling modules
    # -----------------------------------------------------------------

    def parse(self, raw: str) -> CanonicalIntent:
        return parse_intent(raw)

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
        # XML or JSON - not IOS CLI.
        stripped = raw_prefix.lstrip()
        if stripped.startswith("<") or stripped.startswith("{"):
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


def _walk_canonical(intent: CanonicalIntent) -> Iterable[str]:
    """Yield schema xpaths from a CanonicalIntent for validation.

    Kept at module level (rather than relocating to :mod:`.parse` or
    :mod:`.render`) so that the
    ``from netconfig.migration.codecs.cisco_iosxe_cli.codec import _walk_canonical``
    import surface every cross-codec ``iter_xpaths`` consumer relies
    on stays intact.  Used by the OPNsense / Aruba / FortiGate / Arista /
    Juniper / MikroTik / Cisco-NETCONF codecs.
    """
    if intent.hostname:
        yield "/system/hostname"
    for _ in intent.dns_servers:
        yield "/system/dns-server"
    for _ in intent.ntp_servers:
        yield "/system/ntp-server"
    for iface in intent.interfaces:
        yield "/interfaces/interface/name"
        if iface.description:
            yield "/interfaces/interface/config/description"
        yield "/interfaces/interface/config/enabled"
        if iface.interface_type:
            yield "/interfaces/interface/config/type"
        for _ in iface.ipv4_addresses:
            yield "/interfaces/interface/ipv4/address/ip"
            yield "/interfaces/interface/ipv4/address/prefix-length"
        for _ in iface.ipv6_addresses:                # GAP-EVPN-3
            yield "/interfaces/interface/ipv6/address/ip"
            yield "/interfaces/interface/ipv6/address/prefix-length"
    for _ in intent.vlans:
        yield "/vlans/vlan/id"
        yield "/vlans/vlan/name"
    for _ in intent.static_routes:
        yield "/routing/static-route"
    # Tier 2 — emit only what's populated
    if intent.snmp is not None:
        if intent.snmp.community:
            yield "/snmp/community"
        if intent.snmp.location:
            yield "/snmp/location"
        if intent.snmp.contact:
            yield "/snmp/contact"
        for _ in intent.snmp.trap_hosts:
            yield "/snmp/trap-host"
        for _ in intent.snmp.v3_users:
            yield "/snmp/v3-user"
