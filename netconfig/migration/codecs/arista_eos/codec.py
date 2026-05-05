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
from typing import Any, ClassVar, Iterable

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
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/routing/static-route",
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/trap-host",
            "/snmp/v3-user",
            "/aaa/authentication/users/user/config/username",
            "/aaa/authentication/users/user/config/password",
            "/aaa/authentication/users/user/config/role",
            "/vxlan-vnis/vni",                   # GAP 6 demoted
            "/vxlan-vnis/source-interface",      # GAP-EVPN-2
            "/vxlan-vnis/udp-port",              # GAP-EVPN-2
            "/routing-instances/instance",       # GAP 6 demoted
            "/dhcp_servers/pool",                # Cluster E.1-A
        ],
        lossy=[
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
        # netconfig/migration/_tier3_detection.py.  Notification-only.
        intent.dropped_tier3_sections = detect_tier3_sections_iosxe_cli(raw)
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
        stripped = raw_prefix.lstrip()
        if stripped.startswith("<") or stripped.startswith("{"):
            return None
        if re.search(r"^!\s*device:.*EOS-", raw_prefix, re.MULTILINE):
            return (98, "Arista EOS '! device: ... EOS-' banner present")
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
