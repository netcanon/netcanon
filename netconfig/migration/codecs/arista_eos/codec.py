"""
``AristaEOSCodec`` — 6th shipped codec.

See package ``__init__`` for scope + grammar-departure notes.

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

import ipaddress
import logging
import re
from typing import Any, ClassVar, Iterable

from ....models.migration import (
    CapabilityMatrix,
    DeviceClass,
    LossyPath,
    UnsupportedPath,
)
from ...canonical.intent import (
    CanonicalIPv4Address,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalEvpnType5Route,  # noqa: F401 — reserved for GAP 6+ follow-up
    CanonicalLAG,
    CanonicalRoutingInstance,
    CanonicalVxlan,
    CanonicalLocalUser,
    CanonicalSNMP,
    CanonicalSNMPv3User,
    CanonicalStaticRoute,
    CanonicalVlan,
)
from ..base import CodecBase, ParseError, RenderError
from ..registry import register
from . import port_names as _port_names

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex patterns — module-level so they compile once per import.
# ---------------------------------------------------------------------------

_HOSTNAME_RE = re.compile(r"^hostname\s+(\S+)\s*$", re.MULTILINE)
_DNS_SERVER_RE = re.compile(
    r"^ip name-server\s+(?:vrf\s+\S+\s+)?(\S+)\s*$",
    re.MULTILINE,
)
_DNS_DOMAIN_RE = re.compile(r"^dns domain\s+(\S+)\s*$", re.MULTILINE)
_NTP_SERVER_RE = re.compile(
    r"^ntp server\s+(?:vrf\s+\S+\s+)?(\S+)",
    re.MULTILINE,
)
_IP_ROUTE_RE = re.compile(
    # ``ip route 0.0.0.0/0 10.0.0.1`` or ``ip route 10.0.0.0/8 Null0``.
    r"^ip route\s+(\d+\.\d+\.\d+\.\d+)/(\d+)\s+(\S+)",
    re.MULTILINE,
)
_SNMP_COMMUNITY_RE = re.compile(
    # ``snmp-server community public ro`` / ``... rw``.
    r"^snmp-server community\s+(\S+)\s+(ro|rw)",
    re.MULTILINE | re.IGNORECASE,
)
_SNMP_LOCATION_RE = re.compile(
    r"^snmp-server location\s+(.+)$",
    re.MULTILINE,
)
_SNMP_CONTACT_RE = re.compile(
    r"^snmp-server contact\s+(.+)$",
    re.MULTILINE,
)
_SNMP_HOST_RE = re.compile(
    r"^snmp-server host\s+(\d+\.\d+\.\d+\.\d+)",
    re.MULTILINE,
)
# SNMPv3 user on Arista EOS.  Canonical grammar accepts both native
# EOS forms and Cisco-ish pasted forms:
#
#   snmp-server user <name> <group> v3 [auth {md5|sha|...} <pass>]
#                                     [priv {des|aes|aes128|aes192|
#                                     aes256} [keybits?] <pass>]
#
# EOS natively uses ``aes`` (AES-128 default) / ``aes192`` /
# ``aes256`` as single tokens but tolerates the Cisco-style
# ``aes 128`` two-token form on ingest.  The keybits group is
# optional to match both.  The pre-hashed ``localized <engineID>
# <hex>`` form is out of scope for v1 — parse-and-ignore, rendered
# back from canonical in plain form.
_SNMP_V3_USER_RE = re.compile(
    r"^snmp-server\s+user\s+(\S+)\s+(\S+)\s+v3"
    r"(?:\s+auth\s+(md5|sha|sha224|sha256|sha384|sha512)\s+(\S+))?"
    r"(?:\s+priv\s+(des|3des|aes|aes128|aes192|aes256)"
    r"(?:\s+(128|192|256))?\s+(\S+))?"
    r"\s*$",
    re.IGNORECASE | re.MULTILINE,
)

#: Username grammar (EOS flavour).  Three observed forms:
#:   username admin privilege 15 role network-admin nopassword
#:   username X privilege 15 secret sha512 $6$...
#:   username X secret 5 $1$...
#: ``role`` and ``secret``/``nopassword`` are optional; ``privilege``
#: defaults to 1 when absent.
#:
#: All intra-line whitespace matchers use ``[^\S\n]`` (any whitespace
#: except newline) rather than ``\s``.  Critical: the plain ``\s``
#: form bleeds across line boundaries on multi-user blocks — a
#: trailing optional group would consume ``\nusername`` from the next
#: line, making that line's entry disappear from finditer.
_WS = r"[^\S\n]"
_USERNAME_RE = re.compile(
    rf"^username{_WS}+(?P<name>\S+)"
    rf"(?:{_WS}+privilege{_WS}+(?P<priv>\d+))?"
    rf"(?:{_WS}+role{_WS}+(?P<role>\S+))?"
    rf"(?:{_WS}+(?P<pwmode>nopassword|secret{_WS}+\S+{_WS}+\S+))?",
    re.MULTILINE,
)

_VRF_INSTANCE_RE = re.compile(r"^vrf\s+instance\s+(\S+)\s*$", re.MULTILINE)
_INTERFACE_HEADER_RE = re.compile(r"^interface\s+(\S+)\s*$")

# VLAN stanza: ``vlan <id>`` optionally followed by ``   name <name>``.
_VLAN_HEADER_RE = re.compile(r"^vlan\s+(\d+)\s*$")


# ---------------------------------------------------------------------------
# Codec class
# ---------------------------------------------------------------------------


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
            "/routing-instances/instance",       # GAP 6 demoted
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
        ],
    )

    @property
    def capabilities(self) -> CapabilityMatrix:
        return self._CAPS

    # -----------------------------------------------------------------
    # Parse
    # -----------------------------------------------------------------

    def parse(self, raw: str) -> CanonicalIntent:
        if not raw.strip():
            raise ParseError(
                "arista_eos: empty input", snippet="",
            )
        stripped = raw.lstrip()
        if stripped.startswith("<"):
            raise ParseError(
                "arista_eos: input looks like XML, not EOS CLI.",
                snippet=stripped[:120],
            )
        if stripped.startswith("{"):
            raise ParseError(
                "arista_eos: input looks like JSON, not EOS CLI.",
                snippet=stripped[:120],
            )

        intent = CanonicalIntent(
            source_vendor="arista_eos",
            source_format="cli-arista",
        )

        # --- Top-level scalar fields (regex-based, single-pass) ---
        m = _HOSTNAME_RE.search(raw)
        if m:
            intent.hostname = m.group(1)
        for dns_m in _DNS_SERVER_RE.finditer(raw):
            intent.dns_servers.append(dns_m.group(1))
        m = _DNS_DOMAIN_RE.search(raw)
        if m:
            intent.domain = m.group(1)
        for ntp_m in _NTP_SERVER_RE.finditer(raw):
            intent.ntp_servers.append(ntp_m.group(1))
        for route_m in _IP_ROUTE_RE.finditer(raw):
            ip, prefix, next_hop = route_m.groups()
            # Skip interface-form next hops (``Null0``, ``Ethernet1``) —
            # treat as non-routable for canonical; parse-ignore keeps
            # the canonical tree clean while preserving round-trip for
            # IP-form routes.
            try:
                ipaddress.IPv4Address(next_hop)
            except ipaddress.AddressValueError:
                continue
            intent.static_routes.append(CanonicalStaticRoute(
                destination=f"{ip}/{prefix}",
                gateway=next_hop,
                interface="",
            ))

        # --- SNMP block (single CanonicalSNMP assembled from lines) ---
        snmp = CanonicalSNMP()
        snmp_hit = False
        m = _SNMP_COMMUNITY_RE.search(raw)
        if m:
            snmp.community = m.group(1)
            snmp_hit = True
        m = _SNMP_LOCATION_RE.search(raw)
        if m:
            snmp.location = m.group(1).strip().strip('"')
            snmp_hit = True
        m = _SNMP_CONTACT_RE.search(raw)
        if m:
            snmp.contact = m.group(1).strip().strip('"')
            snmp_hit = True
        for host_m in _SNMP_HOST_RE.finditer(raw):
            snmp.trap_hosts.append(host_m.group(1))
            snmp_hit = True
        # SNMPv3 users — seven-group regex.  priv token normalises
        # via the (priv_proto, priv_bits) pair: ``aes`` + ``None`` →
        # aes128 (EOS default); ``aes`` + ``128`` → aes128 (Cisco-
        # style paste); ``aes128`` → aes128 (EOS native single-token);
        # ``aes192`` / ``aes256`` preserve bits.  ``des`` / ``3des``
        # ignore the bits group if present (unusual but tolerated).
        for v3_m in _SNMP_V3_USER_RE.finditer(raw):
            name, group, auth_p, auth_pw, priv_p, priv_bits, priv_pw = (
                v3_m.groups()
            )
            priv_norm = ""
            if priv_p:
                priv_low = priv_p.lower()
                if priv_low == "aes":
                    priv_norm = f"aes{priv_bits}" if priv_bits else "aes128"
                else:
                    priv_norm = priv_low
            snmp.v3_users.append(CanonicalSNMPv3User(
                name=name,
                group=group,
                auth_protocol=(auth_p or "").lower(),
                auth_passphrase=auth_pw or "",
                priv_protocol=priv_norm,
                priv_passphrase=priv_pw or "",
            ))
            snmp_hit = True
        if snmp_hit:
            intent.snmp = snmp

        # --- Usernames ---
        for u_m in _USERNAME_RE.finditer(raw):
            name = u_m.group("name")
            priv_str = u_m.group("priv")
            role = u_m.group("role") or ""
            pwmode = u_m.group("pwmode") or ""
            priv = int(priv_str) if priv_str else 1
            hashed = ""
            if pwmode.startswith("secret"):
                # ``secret sha512 $6$...`` or ``secret 5 $1$...``.
                # Use a single-split so the hash blob (which contains
                # ``$`` / ``/`` / ``.`` internally) stays intact.
                parts = pwmode.split(None, 2)
                if len(parts) == 3:
                    alg = parts[1]
                    # Store as ``arista:<alg>:<hash>`` with COLON
                    # separation — the colon is our canonical
                    # interior delimiter and doesn't appear in any
                    # real EOS hash (they're base64-ish: alnum + .
                    # + / + $).
                    hashed = f"arista:{alg}:{parts[2]}"
            intent.local_users.append(CanonicalLocalUser(
                name=name,
                privilege_level=priv,
                hashed_password=hashed,
                role=role,
            ))

        # --- VRF declarations (GAP 6) — ``vrf instance <name>`` top-
        #     level lines create CanonicalRoutingInstance records.
        #     RD + RTs get populated later from the router-bgp pass.
        for vrf_m in _VRF_INSTANCE_RE.finditer(raw):
            intent.routing_instances.append(
                CanonicalRoutingInstance(name=vrf_m.group(1))
            )

        # --- Interface + VLAN + Vxlan stanzas (line-scan with
        #     current-stanza tracking, same pattern as cisco_iosxe_cli) ---
        self._parse_stanzas(raw, intent)

        # --- router bgp <asn> / vrf <name> / rd + route-target (GAP 6) ---
        self._parse_router_bgp(raw, intent)

        logger.debug(
            "arista_eos parsed: hostname=%r ifaces=%d vlans=%d "
            "vxlan_vnis=%d vrfs=%d routes=%d lags=%d users=%d "
            "snmp=%s (input=%d chars)",
            intent.hostname,
            len(intent.interfaces),
            len(intent.vlans),
            len(intent.vxlan_vnis),
            len(intent.routing_instances),
            len(intent.static_routes),
            len(intent.lags),
            len(intent.local_users),
            "yes" if intent.snmp else "no",
            len(raw),
        )
        return intent

    def _parse_stanzas(self, raw: str, intent: CanonicalIntent) -> None:
        """Line-scanner for interface + vlan stanzas.

        Both stanza types are delimited by ``!`` or by the next top-
        level keyword (``interface ``, ``vlan ``, ``router ``, etc.).
        EOS indents sub-commands with 3 spaces (not Cisco's 1 or
        tab); matching is whitespace-tolerant.
        """
        iface_by_name: dict[str, CanonicalInterface] = {}
        # Track pending LAG member ↔ channel-group bindings so we
        # can reverse-link after interfaces are materialised.
        lag_members: dict[int, list[str]] = {}

        current_iface: CanonicalInterface | None = None
        current_iface_is_l3 = False   # set via ``no switchport``
        current_vlan: CanonicalVlan | None = None

        lines = raw.splitlines()
        for raw_line in lines:
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("!"):
                # End-of-stanza delimiter.  Close whichever is open.
                current_iface = None
                current_iface_is_l3 = False
                current_vlan = None
                continue

            # Header matches only at column 0 (no leading whitespace)
            # — EOS sub-commands are all indented.
            if not line.startswith((" ", "\t")):
                # Possible new top-level stanza.  Close anything open
                # from the previous stanza first.
                iface_m = _INTERFACE_HEADER_RE.match(line)
                vlan_m = _VLAN_HEADER_RE.match(line)
                if iface_m:
                    name = iface_m.group(1)
                    # GAP 6: Vxlan<N> is a VXLAN config container, not
                    # a real interface.  Its sub-commands populate
                    # CanonicalVxlan records via _apply_iface_subcommand,
                    # but we don't materialise a CanonicalInterface for
                    # it — render rebuilds the stanza from
                    # tree.vxlan_vnis + tree.routing_instances[].l3_vni.
                    if name.lower().startswith("vxlan"):
                        # Still track as current_iface so indented
                        # ``vxlan ...`` sub-lines dispatch correctly,
                        # but use a throwaway sentinel interface that
                        # never joins tree.interfaces.
                        sentinel = CanonicalInterface(name=name, enabled=True)
                        sentinel.interface_type = _infer_iface_type(name)
                        current_iface = sentinel
                        current_iface_is_l3 = False
                        current_vlan = None
                        continue
                    iface = iface_by_name.get(name)
                    if iface is None:
                        iface = CanonicalInterface(
                            name=name, enabled=True,
                        )
                        iface.interface_type = _infer_iface_type(name)
                        iface_by_name[name] = iface
                        intent.interfaces.append(iface)
                    current_iface = iface
                    current_iface_is_l3 = False
                    current_vlan = None
                    continue
                if vlan_m:
                    vid = int(vlan_m.group(1))
                    vlan = CanonicalVlan(id=vid, name="")
                    intent.vlans.append(vlan)
                    current_vlan = vlan
                    current_iface = None
                    continue
                # Any other top-level stanza closes context.  The
                # scanner continues so regex-based top-level lines
                # (``ip route`` etc.) are ignored here — they were
                # picked up by the earlier regex pass.
                current_iface = None
                current_vlan = None
                continue

            # Indented = sub-command of the currently-open stanza.
            if current_iface is not None:
                self._apply_iface_subcommand(
                    current_iface, stripped, lag_members, intent,
                )
                # Track L3 flip so subsequent ``ip address`` lines are
                # understood as routed rather than SVI-like.
                if stripped == "no switchport":
                    current_iface_is_l3 = True
            elif current_vlan is not None:
                if stripped.startswith("name "):
                    current_vlan.name = stripped.split(None, 1)[1].strip()

        # Reverse-link LAG members.  For each channel-group binding
        # captured during the pass, synthesise the LAG if the child
        # interfaces named it — EOS doesn't require a standalone
        # ``interface Port-ChannelN`` stanza.
        for chan_id, members in lag_members.items():
            lag_name = f"Port-Channel{chan_id}"
            existing = next(
                (l for l in intent.lags if l.name == lag_name), None,
            )
            if existing is None:
                intent.lags.append(CanonicalLAG(
                    name=lag_name,
                    members=sorted(set(members)),
                    mode="active",
                ))
            else:
                existing.members = sorted(set(existing.members + members))
            # Reverse-link on each member interface.
            for member in members:
                m_iface = iface_by_name.get(member)
                if m_iface is not None and m_iface.lag_member_of is None:
                    m_iface.lag_member_of = lag_name

    def _parse_router_bgp(
        self, raw: str, intent: CanonicalIntent,
    ) -> None:
        """Parse ``router bgp <asn> / vrf <name> / rd <rd> /
        route-target import|export|both <rt>`` — the pieces we care
        about for VRF metadata.  BGP neighbor/address-family details
        stay parse-and-ignore.

        Lines in EOS `router bgp` are indented; `vrf <name>` nests
        3-spaces deeper than the router-bgp stanza.  We track stanza
        depth via leading-whitespace count.
        """
        in_bgp = False
        current_vrf: CanonicalRoutingInstance | None = None
        for raw_line in raw.splitlines():
            stripped = raw_line.strip()
            # Blank line: end of file / section.
            if not stripped:
                in_bgp = False
                current_vrf = None
                continue
            # Top-level ``router bgp <asn>`` opens the section.
            if raw_line.startswith("router bgp "):
                in_bgp = True
                current_vrf = None
                continue
            # ``!`` alone (possibly indented) is a sub-stanza separator
            # inside router-bgp; close the per-vrf context but KEEP
            # in_bgp active so the next ``vrf <name>`` block parses.
            if stripped == "!":
                current_vrf = None
                continue
            # Another top-level stanza (non-indented, non-comment)
            # closes router-bgp.
            if not raw_line.startswith((" ", "\t")):
                in_bgp = False
                current_vrf = None
                continue
            if not in_bgp:
                continue
            # Inside router-bgp: 3-space indent for top-level router
            # subs, 6-space indent for per-vrf subs.  Count leading
            # spaces to distinguish.
            leading_spaces = len(raw_line) - len(raw_line.lstrip(" "))
            if stripped.startswith("vrf "):
                vrf_name = stripped.split(None, 1)[1].strip()
                current_vrf = next(
                    (r for r in intent.routing_instances if r.name == vrf_name),
                    None,
                )
                if current_vrf is None:
                    # ``router bgp X / vrf Y`` declares a VRF context
                    # even if no standalone ``vrf instance Y`` was
                    # seen upstream — create one so RD/RTs don't get
                    # dropped.
                    current_vrf = CanonicalRoutingInstance(name=vrf_name)
                    intent.routing_instances.append(current_vrf)
                continue
            if current_vrf is None:
                continue
            # Deeper indent = sub-command of ``vrf <name>``.
            if leading_spaces < 6:
                # Back up to router-bgp top-level — close vrf context.
                current_vrf = None
                continue
            if stripped.startswith("rd "):
                parts = stripped.split(None, 1)
                if len(parts) >= 2:
                    current_vrf.route_distinguisher = parts[1].strip()
                continue
            if stripped.startswith("route-target both "):
                rt = stripped.split(None, 2)[2].strip()
                if rt not in current_vrf.rt_imports:
                    current_vrf.rt_imports.append(rt)
                if rt not in current_vrf.rt_exports:
                    current_vrf.rt_exports.append(rt)
                continue
            if stripped.startswith("route-target import "):
                rt = stripped.split(None, 2)[2].strip()
                # EOS also has ``route-target import evpn <rt>`` inside
                # ``router bgp / vrf <name>`` stanzas — the ``evpn``
                # keyword is just marking the address-family; the
                # actual RT follows.  Strip the ``evpn `` prefix.
                if rt.startswith("evpn "):
                    rt = rt[len("evpn "):].strip()
                if rt and rt not in current_vrf.rt_imports:
                    current_vrf.rt_imports.append(rt)
                continue
            if stripped.startswith("route-target export "):
                rt = stripped.split(None, 2)[2].strip()
                if rt.startswith("evpn "):
                    rt = rt[len("evpn "):].strip()
                if rt and rt not in current_vrf.rt_exports:
                    current_vrf.rt_exports.append(rt)
                continue

    def _apply_iface_subcommand(
        self,
        iface: CanonicalInterface,
        line: str,
        lag_members: dict[int, list[str]],
        intent: CanonicalIntent,
    ) -> None:
        """Apply one indented sub-command to *iface*."""
        if line == "shutdown":
            iface.enabled = False
            return
        if line == "no shutdown":
            iface.enabled = True
            return
        if line.startswith("description "):
            desc = line.split(None, 1)[1].strip()
            # EOS often quotes descriptions; strip bracketing quotes.
            if len(desc) >= 2 and desc[0] == desc[-1] and desc[0] in "\"'":
                desc = desc[1:-1]
            iface.description = desc
            return
        if line.startswith("ip address "):
            # ``ip address 10.0.0.1/31`` — CIDR form only (EOS).
            rest = line.split(None, 2)[2].strip()
            # Some ``ip address`` lines have ``secondary`` trailer —
            # ignore the trailer, first address wins.
            addr = rest.split()[0]
            if "/" in addr:
                ip, prefix = addr.split("/", 1)
                try:
                    iface.ipv4_addresses.append(CanonicalIPv4Address(
                        ip=ip,
                        prefix_length=int(prefix),
                    ))
                except ValueError:
                    pass
            return
        if line.startswith("mtu "):
            try:
                iface.mtu = int(line.split()[1])
            except (ValueError, IndexError):
                pass
            return
        if line.startswith("channel-group "):
            # ``channel-group 1 mode active`` — LAG membership.
            parts = line.split()
            if len(parts) >= 2:
                try:
                    chan_id = int(parts[1])
                    lag_members.setdefault(chan_id, []).append(iface.name)
                except ValueError:
                    pass
            return
        # ``switchport mode access`` / ``switchport access vlan N`` /
        # ``switchport trunk allowed vlan L`` — parse-and-record.
        if line.startswith("switchport access vlan "):
            try:
                iface.access_vlan = int(line.split()[-1])
                iface.switchport_mode = "access"
            except ValueError:
                pass
            return
        if line.startswith("switchport trunk allowed vlan "):
            # ``switchport trunk allowed vlan 10,20,30-35``
            iface.switchport_mode = "trunk"
            tail = line.split(None, 4)[-1]
            iface.trunk_allowed_vlans = _expand_vlan_list(tail)
            return
        if line == "switchport mode trunk":
            iface.switchport_mode = "trunk"
            return
        if line == "switchport mode access":
            iface.switchport_mode = "access"
            return
        if line == "no switchport":
            # Explicit L2→L3.  We don't model L2/L3 state on
            # CanonicalInterface (beyond ip addresses); record nothing
            # but keep the branch to avoid falling through to
            # "unrecognised" tolerance.
            return
        # GAP 6: ``vrf <name>`` on an Ethernet / Port-Channel / Loopback /
        # Vlan interface sets per-interface VRF membership.
        # NOT ``vrf definition`` (that's a top-level stanza already
        # caught by _VRF_INSTANCE_RE); we just match bare ``vrf X``.
        if line.startswith("vrf ") and not line.startswith((
            "vrf instance", "vrf definition",
        )):
            parts = line.split(None, 1)
            if len(parts) >= 2:
                iface.vrf = parts[1].strip()
            return
        # GAP 6: Vxlan interface sub-commands — VLAN↔VNI mappings and
        # VRF↔L3-VNI mappings live here.  ``iface.name`` starts with
        # ``Vxlan`` (``Vxlan1`` / ``Vxlan2``).
        if iface.name.lower().startswith("vxlan"):
            # ``vxlan vlan <vid> vni <vni>``
            m = re.match(r"^vxlan\s+vlan\s+(\d+)\s+vni\s+(\d+)\s*$", line)
            if m:
                try:
                    vid = int(m.group(1))
                    vni = int(m.group(2))
                    intent.vxlan_vnis.append(
                        CanonicalVxlan(vlan_id=vid, vni=vni)
                    )
                except ValueError:
                    pass
                return
            # ``vxlan vrf <name> vni <vni>`` — L3 VNI for Type-5.
            m = re.match(r"^vxlan\s+vrf\s+(\S+)\s+vni\s+(\d+)\s*$", line)
            if m:
                vrf_name = m.group(1)
                try:
                    l3_vni = int(m.group(2))
                except ValueError:
                    return
                ri = next(
                    (r for r in intent.routing_instances if r.name == vrf_name),
                    None,
                )
                if ri is None:
                    ri = CanonicalRoutingInstance(
                        name=vrf_name, l3_vni=l3_vni,
                    )
                    intent.routing_instances.append(ri)
                else:
                    ri.l3_vni = l3_vni
                return
            # Other ``vxlan source-interface`` / ``vxlan udp-port`` /
            # ``vxlan virtual-router`` lines fall through to parse-
            # and-ignore — vendor-native details we don't model.
        # Unrecognised sub-command — parse-and-ignore.

    # -----------------------------------------------------------------
    # Render
    # -----------------------------------------------------------------

    def render(self, tree: Any) -> str:
        if not isinstance(tree, CanonicalIntent):
            raise RenderError(
                "arista_eos: tree must be a CanonicalIntent.",
                yang_path="/",
            )

        out: list[str] = []
        out.append("! Generated by netconfig-translator (arista_eos target)")
        out.append("!")
        if tree.hostname:
            out.append(f"hostname {tree.hostname}")
            out.append("!")

        if tree.dns_servers:
            for dns in tree.dns_servers:
                out.append(f"ip name-server vrf default {dns}")
            out.append("!")
        if tree.domain:
            out.append(f"dns domain {tree.domain}")
            out.append("!")
        if tree.ntp_servers:
            for ntp in tree.ntp_servers:
                out.append(f"ntp server {ntp}")
            out.append("!")

        if tree.snmp is not None:
            if tree.snmp.community:
                out.append(f"snmp-server community {tree.snmp.community} ro")
            if tree.snmp.location:
                out.append(f"snmp-server location {tree.snmp.location}")
            if tree.snmp.contact:
                out.append(f"snmp-server contact {tree.snmp.contact}")
            for host in tree.snmp.trap_hosts:
                out.append(f"snmp-server host {host}")
            # SNMPv3 users.  ``aes128`` canonical → ``aes`` on EOS wire
            # (Arista accepts both but the bare form is the
            # platform-natural default); ``aes192`` / ``aes256`` emit
            # one-token form.  Users with no auth / no priv emit the
            # bare ``v3`` line — noAuthNoPriv is a valid USM mode.
            for u in tree.snmp.v3_users:
                parts = [f"snmp-server user {u.name} {u.group or 'v3group'} v3"]
                if u.auth_protocol:
                    parts.append(
                        f"auth {u.auth_protocol} {u.auth_passphrase}"
                    )
                if u.priv_protocol:
                    wire_priv = (
                        "aes" if u.priv_protocol == "aes128"
                        else u.priv_protocol
                    )
                    parts.append(f"priv {wire_priv} {u.priv_passphrase}")
                out.append(" ".join(parts))
            if (
                tree.snmp.community or tree.snmp.location
                or tree.snmp.contact or tree.snmp.trap_hosts
                or tree.snmp.v3_users
            ):
                out.append("!")

        # --- Local users ---
        if tree.local_users:
            for user in tree.local_users:
                parts = [f"username {user.name}"]
                if user.privilege_level and user.privilege_level != 1:
                    parts.append(f"privilege {user.privilege_level}")
                if user.role:
                    parts.append(f"role {user.role}")
                if user.hashed_password:
                    vendor, _, tail = user.hashed_password.partition(":")
                    if vendor == "arista" and ":" in tail:
                        # Round-trip: ``arista:<alg>:<hash>`` →
                        # ``secret <alg> <hash>``.
                        alg, _, hsh = tail.partition(":")
                        parts.append(f"secret {alg} {hsh}")
                    else:
                        # Foreign hash — emit as opaque secret 5.
                        parts.append(f"secret 5 {user.hashed_password}")
                else:
                    parts.append("nopassword")
                out.append(" ".join(parts))
            out.append("!")

        # --- VRF instances (GAP 6) — declare every canonical VRF via
        #     ``vrf instance <name>``.  RD + RTs emit later under
        #     router-bgp / vrf <name>. ---
        if tree.routing_instances:
            for ri in tree.routing_instances:
                out.append(f"vrf instance {ri.name}")
            out.append("!")

        # --- VLANs ---
        if tree.vlans:
            for vlan in tree.vlans:
                out.append(f"vlan {vlan.id}")
                if vlan.name:
                    out.append(f"   name {vlan.name}")
            out.append("!")

        # --- Interfaces ---
        # Build LAG mode lookup so member interfaces can emit the
        # matching ``channel-group N mode <mode>`` line.  Arista LAGs
        # live on the member side — the canonical tree carries
        # `lag_member_of` on each member + a `CanonicalLAG` record in
        # `tree.lags`; render needs both.
        lag_mode_by_name = {lag.name: (lag.mode or "active") for lag in tree.lags}
        for iface in tree.interfaces:
            out.append(f"interface {iface.name}")
            if iface.description:
                out.append(f"   description {iface.description}")
            # L3 flip needed when we emit an IP address on a port that
            # doesn't already indicate L3 (Ethernet<N> physical).
            if iface.ipv4_addresses and iface.name.lower().startswith(
                "ethernet"
            ):
                out.append("   no switchport")
            # GAP 6: per-interface VRF membership.  Must emit BEFORE
            # ``ip address`` so EOS correctly binds the IP into the
            # VRF's routing table.
            if iface.vrf:
                out.append(f"   vrf {iface.vrf}")
            if iface.switchport_mode == "access":
                out.append("   switchport mode access")
                if iface.access_vlan is not None:
                    out.append(
                        f"   switchport access vlan {iface.access_vlan}"
                    )
            elif iface.switchport_mode == "trunk":
                out.append("   switchport mode trunk")
                if iface.trunk_allowed_vlans:
                    vlist = ",".join(str(v) for v in iface.trunk_allowed_vlans)
                    out.append(
                        f"   switchport trunk allowed vlan {vlist}"
                    )
            for addr in iface.ipv4_addresses:
                out.append(
                    f"   ip address {addr.ip}/{addr.prefix_length}"
                )
            # LAG membership: ``channel-group N mode <mode>`` on member
            # Ethernet interfaces.  Arista (like Cisco IOS) puts this
            # on the child side, not the Port-Channel stanza.
            if iface.lag_member_of:
                m = re.match(r"^Port-Channel(\d+)$", iface.lag_member_of)
                if m is not None:
                    chan_id = m.group(1)
                    mode = lag_mode_by_name.get(
                        iface.lag_member_of, "active",
                    )
                    # Normalise canonical mode strings to EOS CLI tokens.
                    if mode == "static":
                        mode_token = "on"
                    elif mode == "passive":
                        mode_token = "passive"
                    else:
                        mode_token = "active"
                    out.append(
                        f"   channel-group {chan_id} mode {mode_token}"
                    )
            if iface.mtu is not None:
                out.append(f"   mtu {iface.mtu}")
            if not iface.enabled:
                out.append("   shutdown")
            out.append("!")

        # --- LAGs (channel-group lines live on member interfaces; we
        #     also emit ``interface Port-ChannelN`` stubs so the
        #     config is self-consistent) ---
        existing_names = {i.name for i in tree.interfaces}
        for lag in tree.lags:
            if lag.name not in existing_names:
                out.append(f"interface {lag.name}")
                out.append("!")

        # --- Vxlan1 (GAP 6) — EOS carries VLAN-to-VNI + VRF-to-L3-VNI
        #     mappings inside a single ``interface Vxlan1`` stanza.
        #     Source-interface defaults to Loopback0; real configs
        #     often use a dedicated VTEP loopback but we don't model
        #     that choice — operators can re-emit as needed.
        has_l3_vnis = any(
            ri.l3_vni is not None for ri in tree.routing_instances
        )
        if tree.vxlan_vnis or has_l3_vnis:
            out.append("interface Vxlan1")
            out.append("   vxlan source-interface Loopback0")
            out.append("   vxlan udp-port 4789")
            for v in tree.vxlan_vnis:
                out.append(f"   vxlan vlan {v.vlan_id} vni {v.vni}")
            for ri in tree.routing_instances:
                if ri.l3_vni is not None:
                    out.append(f"   vxlan vrf {ri.name} vni {ri.l3_vni}")
            out.append("!")

        # --- router bgp VRF blocks (GAP 6) — emit ``router bgp <asn> /
        #     vrf <name> / rd / route-target import/export`` when any
        #     VRF carries RD or RTs.  ASN defaults to a placeholder
        #     since CanonicalIntent doesn't model BGP config beyond
        #     what VRFs need; operators re-emit as needed.
        vrfs_with_bgp_meta = [
            ri for ri in tree.routing_instances
            if ri.route_distinguisher or ri.rt_imports or ri.rt_exports
        ]
        if vrfs_with_bgp_meta:
            out.append("router bgp 65000")
            for ri in vrfs_with_bgp_meta:
                out.append("   !")
                out.append(f"   vrf {ri.name}")
                if ri.route_distinguisher:
                    out.append(f"      rd {ri.route_distinguisher}")
                # Use ``route-target both`` for matched import/export
                # pairs (compact + canonical-friendly); emit separate
                # import/export lines when they diverge.
                if (
                    ri.rt_imports == ri.rt_exports and ri.rt_imports
                ):
                    for rt in ri.rt_imports:
                        out.append(f"      route-target both {rt}")
                else:
                    for rt in ri.rt_imports:
                        out.append(f"      route-target import evpn {rt}")
                    for rt in ri.rt_exports:
                        out.append(f"      route-target export evpn {rt}")
            out.append("!")

        # --- Static routes ---
        if tree.static_routes:
            for route in tree.static_routes:
                if route.gateway:
                    out.append(
                        f"ip route {route.destination} {route.gateway}"
                    )
            out.append("!")
            out.append("ip routing")
            out.append("!")

        out.append("end")
        return "\n".join(out) + "\n"

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _infer_iface_type(name: str) -> str:
    """Infer IANA iftype from an EOS interface name."""
    lower = name.lower()
    if lower.startswith("ethernet"):
        return "ianaift:ethernetCsmacd"
    if lower.startswith("management"):
        return "ianaift:ethernetCsmacd"
    if lower.startswith("loopback"):
        return "ianaift:softwareLoopback"
    if lower.startswith("vlan"):
        return "ianaift:l3ipvlan"
    if lower.startswith("port-channel"):
        return "ianaift:ieee8023adLag"
    if lower.startswith("tunnel"):
        return "ianaift:tunnel"
    return ""


def _expand_vlan_list(spec: str) -> list[int]:
    """Expand a VLAN-list spec like ``10,20,30-35`` into [10,20,30..35]."""
    out: list[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            try:
                for n in range(int(a), int(b) + 1):
                    out.append(n)
            except ValueError:
                continue
        else:
            try:
                out.append(int(chunk))
            except ValueError:
                continue
    return out
