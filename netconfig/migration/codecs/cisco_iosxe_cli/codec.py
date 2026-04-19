"""
``CiscoIOSXECLICodec`` — parse ``show running-config`` text.

Direction: ``parse_only``.  No ``render()`` — generating syntactically
valid IOS CLI from a tree is substantially harder than parsing it and
is deferred to a future phase.

Parser strategy
---------------
IOS ``show running-config`` is a line-oriented, indentation-significant
format.  Interfaces are delimited by ``interface <name>`` lines and
terminated by ``!`` comment lines.  The parser:

1. Scans for ``interface <name>`` lines.
2. Captures indented sub-commands until the next ``!`` or un-indented
   line.
3. Extracts known keywords: ``description``, ``shutdown`` / ``no
   shutdown``, ``ip address <ip> <mask>``.
4. Builds the same nested dict shape as ``CiscoIOSXECodec`` so the
   two codecs are interchangeable as pipeline SOURCEs.

Limitations (``experimental`` certainty):
    * Only parses interface stanzas — routing protocols, ACLs, VLANs,
      AAA, crypto, and everything else is silently skipped.
    * Subnet mask → prefix-length conversion handles standard masks
      only (``255.255.255.0`` → ``/24``).  Non-contiguous masks are
      rejected.
    * ``secondary`` IP addresses are ignored (first address only).
    * ``switchport`` interfaces are treated as having no IP.
"""

from __future__ import annotations

import ipaddress
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
    CanonicalLAG,
    CanonicalSNMP,
    CanonicalStaticRoute,
    CanonicalVlan,
)
from ..base import CodecBase, ParseError, RenderError
from ..registry import register


@register
class CiscoIOSXECLICodec(CodecBase):
    """Parse-only codec for Cisco IOS-XE ``show running-config`` output.

    Shares ``vendor_id=cisco_iosxe`` with the NETCONF codec — both
    target the same vendor YAML.
    """

    name: ClassVar[str] = "cisco_iosxe_cli"
    version_hint: ClassVar[str | None] = "15.x / 16.x / 17.x"
    input_format: ClassVar[str] = "cli-ios"
    direction: ClassVar[str] = "parse_only"
    certainty: ClassVar[str] = "best_effort"
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
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/routing/static-route",
            # Tier 2 — SNMP
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/trap-host",
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
        ],
        unsupported=[
            UnsupportedPath(
                path="/interfaces/interface/subinterfaces/subinterface/ipv6",
                reason="Phase 0.5 scope — IPv4 only.",
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
        """Parse IOS-XE ``show running-config`` output into a
        :class:`CanonicalIntent`.

        Raises:
            ParseError: If the input doesn't look like IOS config at all
                (e.g. XML or JSON).
        """
        if not raw.strip():
            raise ParseError(
                "cisco_iosxe_cli: empty input",
                snippet="",
            )
        # Quick sanity: if it starts with '<' it's XML, not CLI.
        stripped = raw.lstrip()
        if stripped.startswith("<") or stripped.startswith("{"):
            raise ParseError(
                "cisco_iosxe_cli: input looks like XML or JSON, not IOS CLI. "
                "Use the cisco_iosxe (NETCONF) codec for XML input.",
                snippet=stripped[:120],
            )

        intent = CanonicalIntent(
            source_vendor="cisco_iosxe",
            source_format="cli-ios",
        )

        # System-level fields
        intent.hostname = _extract_hostname(raw)

        # Interfaces
        intent.interfaces = _parse_interfaces(raw)

        # VLANs (top-level `vlan N / name X` stanzas)
        intent.vlans = _parse_vlans(raw)

        # Synthesize VLAN records for any `interface Vlan<N>` SVIs that
        # didn't have a matching top-level stanza.  Without this, VLAN-
        # centric downstream codecs (Aruba, OPNsense) can't find the
        # SVI's IP and silently drop it.  See translator-plans.txt
        # "KNOWN DATA-LOSS BUGS / BUG 1".
        _synthesize_vlans_from_svis(intent)

        # Static routes
        intent.static_routes = _parse_static_routes(raw)

        # SNMP (Tier 2)
        intent.snmp = _parse_snmp(raw)

        # LAGs (Tier 2) — both the `interface Port-channelN` declaration
        # and the per-member `channel-group N mode M` lines contribute.
        # See translator-plans.txt BUG 2.
        intent.lags = _parse_lags(raw, intent)

        # Bug 3 transpose: mirror per-port switchport state into the
        # VLAN-centric tagged_ports / untagged_ports lists so VLAN-
        # centric renderers (Aruba, OPNsense) can emit the membership.
        # Without this, per-interface `switchport access vlan 20` /
        # `switchport trunk allowed vlan 11,20` never reaches the
        # target config.  See translator-plans.txt BUG 3.
        from ...canonical.transforms import project_switchport_to_vlan
        project_switchport_to_vlan(intent)

        return intent

    # -----------------------------------------------------------------
    # Render — NOT IMPLEMENTED (parse_only codec)
    # -----------------------------------------------------------------

    def render(self, tree: Any) -> str:
        """Not implemented — this codec is parse-only.

        Raises:
            RenderError: Always.
        """
        raise RenderError(
            "cisco_iosxe_cli is a parse-only codec; rendering IOS CLI "
            "from a tree is not yet implemented. Use cisco_iosxe "
            "(NETCONF) as the TARGET codec instead.",
            yang_path="/",
        )

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
    # Auto-detection probe (R5)
    # -----------------------------------------------------------------

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Detect Cisco IOS CLI ``show running-config`` text.

        Strong signals: ``Building configuration...`` banner,
        ``interface GigabitEthernet``, ``ip address X Y`` (dotted-
        decimal mask), ``no shutdown``.  Weaker signals: ``!``
        stanza delimiter, leading ``hostname``.
        """
        lowered = raw_prefix.lower()
        # XML or JSON - not IOS CLI.
        stripped = raw_prefix.lstrip()
        if stripped.startswith("<") or stripped.startswith("{"):
            return None
        # MikroTik or Fortigate sections share `!` but the signals
        # below distinguish IOS.
        if "building configuration" in lowered:
            return (98, "'Building configuration...' banner is IOS-specific")
        if "show running-config" in lowered:
            return (95, "'show running-config' header present")
        # Strong IOS-shape markers (one enough for high confidence).
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


# ---------------------------------------------------------------------------
# CLI parser internals
# ---------------------------------------------------------------------------

_IFACE_RE = re.compile(r"^interface\s+(\S+)", re.IGNORECASE)
_DESC_RE = re.compile(r"^\s+description\s+(.+)", re.IGNORECASE)
_IP_RE = re.compile(
    r"^\s+ip\s+address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)",
    re.IGNORECASE,
)
_SHUTDOWN_RE = re.compile(r"^\s+shutdown\s*$", re.IGNORECASE)
_NO_SHUTDOWN_RE = re.compile(r"^\s+no\s+shutdown\s*$", re.IGNORECASE)

#: Interface-name prefix → IANA ifType hint.
_TYPE_HINTS: dict[str, str] = {
    "gigabitethernet": "ianaift:ethernetCsmacd",
    "fastethernet": "ianaift:ethernetCsmacd",
    "tengigabitethernet": "ianaift:ethernetCsmacd",
    "twentyfivegige": "ianaift:ethernetCsmacd",
    "fortygigabitethernet": "ianaift:ethernetCsmacd",
    "hundredgige": "ianaift:ethernetCsmacd",
    "ethernet": "ianaift:ethernetCsmacd",
    "loopback": "ianaift:softwareLoopback",
    "vlan": "ianaift:l3ipvlan",
    "port-channel": "ianaift:ieee8023adLag",
    "tunnel": "ianaift:tunnel",
    "bdi": "ianaift:l3ipvlan",
}


def _infer_type(iface_name: str) -> str:
    """Best-effort IANA ifType from the interface name prefix."""
    lower = iface_name.lower()
    for prefix, iftype in _TYPE_HINTS.items():
        if lower.startswith(prefix):
            return iftype
    return "ianaift:other"


def _mask_to_prefix(mask_str: str) -> int:
    """Convert a dotted-decimal subnet mask to a CIDR prefix length.

    Raises ParseError for non-contiguous masks.
    """
    try:
        addr = ipaddress.IPv4Address(mask_str)
    except ipaddress.AddressValueError:
        raise ParseError(
            f"cisco_iosxe_cli: invalid subnet mask {mask_str!r}",
            snippet=mask_str,
        )
    bits = bin(int(addr))[2:]
    if "01" in bits:
        raise ParseError(
            f"cisco_iosxe_cli: non-contiguous subnet mask {mask_str!r}",
            snippet=mask_str,
        )
    return bits.count("1")


_HOSTNAME_RE = re.compile(r"^hostname\s+(\S+)", re.IGNORECASE | re.MULTILINE)
_VLAN_RE = re.compile(r"^vlan\s+(\d+)", re.IGNORECASE)
_VLAN_NAME_RE = re.compile(r"^\s+name\s+(.+)", re.IGNORECASE)
_STATIC_ROUTE_RE = re.compile(
    r"^ip\s+route\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s+(\S+)",
    re.IGNORECASE,
)
# ``ip default-gateway X`` is the L2-switch form of a default route.
# Common on Catalyst switches that have no routing enabled — the switch
# itself still needs a gateway for its management SVI.  We map it to the
# same CanonicalStaticRoute shape the Aruba renderer already uses for
# 0.0.0.0/0 destinations.
_DEFAULT_GATEWAY_RE = re.compile(
    r"^ip\s+default-gateway\s+(\d+\.\d+\.\d+\.\d+)",
    re.IGNORECASE,
)
_SWITCHPORT_ACCESS_RE = re.compile(
    r"^\s+switchport\s+access\s+vlan\s+(\d+)", re.IGNORECASE
)
_SWITCHPORT_TRUNK_ALLOWED_RE = re.compile(
    r"^\s+switchport\s+trunk\s+allowed\s+vlan\s+(.+)", re.IGNORECASE
)
_SWITCHPORT_TRUNK_NATIVE_RE = re.compile(
    r"^\s+switchport\s+trunk\s+native\s+vlan\s+(\d+)", re.IGNORECASE
)
_SWITCHPORT_MODE_RE = re.compile(
    r"^\s+switchport\s+mode\s+(\S+)", re.IGNORECASE
)
# ``channel-group N mode M`` declares this physical port as a member of
# LAG ``Port-channelN``.  Cisco's mode vocabulary:
#   active  -> LACP active  (canonical: "active")
#   passive -> LACP passive (canonical: "passive")
#   on      -> static        (canonical: "static")
#   auto/desirable -> PAgP (Cisco-proprietary; we fold to "active")
_CHANNEL_GROUP_RE = re.compile(
    r"^\s+channel-group\s+(\d+)\s+mode\s+(\S+)", re.IGNORECASE,
)
_CISCO_LAG_MODE_MAP = {
    "active": "active",
    "passive": "passive",
    "on": "static",
    "auto": "active",       # PAgP → best-effort equivalent
    "desirable": "active",  # PAgP → best-effort equivalent
}


def _extract_hostname(raw: str) -> str:
    m = _HOSTNAME_RE.search(raw)
    return m.group(1) if m else ""


def _parse_interfaces(raw: str) -> list[CanonicalInterface]:
    """Extract interface stanzas from IOS config text."""
    lines = raw.splitlines()
    interfaces: list[CanonicalInterface] = []
    current: dict[str, Any] | None = None

    for line in lines:
        m = _IFACE_RE.match(line)
        if m:
            if current is not None:
                interfaces.append(_build_canonical_interface(current))
            iface_name = m.group(1)
            current = {
                "name": iface_name,
                "description": "",
                "enabled": True,
                "type": _infer_type(iface_name),
                "ipv4": [],
                "switchport_mode": None,
                "access_vlan": None,
                "trunk_allowed": [],
                "trunk_native": None,
                "lag_member_of": None,
            }
            continue

        if current is None:
            continue

        if line.startswith("!") or (line and not line[0].isspace()):
            interfaces.append(_build_canonical_interface(current))
            current = None
            continue

        dm = _DESC_RE.match(line)
        if dm:
            current["description"] = dm.group(1).strip()
            continue

        if _SHUTDOWN_RE.match(line):
            current["enabled"] = False
            continue

        if _NO_SHUTDOWN_RE.match(line):
            current["enabled"] = True
            continue

        im = _IP_RE.match(line)
        if im:
            ip_str = im.group(1)
            mask_str = im.group(2)
            prefix_len = _mask_to_prefix(mask_str)
            if not current["ipv4"]:  # primary only
                current["ipv4"].append({"ip": ip_str, "prefix_length": prefix_len})
            continue

        sm = _SWITCHPORT_MODE_RE.match(line)
        if sm:
            current["switchport_mode"] = sm.group(1).lower()
            continue

        am = _SWITCHPORT_ACCESS_RE.match(line)
        if am:
            current["access_vlan"] = int(am.group(1))
            continue

        tm = _SWITCHPORT_TRUNK_ALLOWED_RE.match(line)
        if tm:
            current["trunk_allowed"] = _parse_vlan_list(tm.group(1).strip())
            continue

        nm = _SWITCHPORT_TRUNK_NATIVE_RE.match(line)
        if nm:
            current["trunk_native"] = int(nm.group(1))
            continue

        cgm = _CHANNEL_GROUP_RE.match(line)
        if cgm:
            current["lag_member_of"] = f"Port-channel{int(cgm.group(1))}"
            continue

    if current is not None:
        interfaces.append(_build_canonical_interface(current))

    return interfaces


def _build_canonical_interface(raw: dict[str, Any]) -> CanonicalInterface:
    """Convert the parse-time dict into a CanonicalInterface."""
    return CanonicalInterface(
        name=raw["name"],
        description=raw.get("description", ""),
        enabled=raw.get("enabled", True),
        interface_type=raw.get("type", ""),
        ipv4_addresses=[
            CanonicalIPv4Address(ip=a["ip"], prefix_length=a["prefix_length"])
            for a in raw.get("ipv4", [])
        ],
        switchport_mode=raw.get("switchport_mode"),
        access_vlan=raw.get("access_vlan"),
        trunk_allowed_vlans=raw.get("trunk_allowed", []),
        trunk_native_vlan=raw.get("trunk_native"),
        lag_member_of=raw.get("lag_member_of"),
    )


def _parse_vlan_list(text: str) -> list[int]:
    """Parse a Cisco VLAN list like '10,20,30-40' into a flat list of ints."""
    result: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            result.extend(range(int(lo.strip()), int(hi.strip()) + 1))
        elif part.isdigit():
            result.append(int(part))
    return result


def _parse_vlans(raw: str) -> list[CanonicalVlan]:
    """Extract VLAN definitions from IOS config text.

    Looks for ``vlan <id>`` stanzas followed by indented ``name``
    sub-commands.
    """
    lines = raw.splitlines()
    vlans: list[CanonicalVlan] = []
    current_id: int | None = None
    current_name: str = ""

    for line in lines:
        vm = _VLAN_RE.match(line)
        if vm:
            if current_id is not None:
                vlans.append(CanonicalVlan(id=current_id, name=current_name))
            current_id = int(vm.group(1))
            current_name = ""
            continue

        if current_id is not None:
            nm = _VLAN_NAME_RE.match(line)
            if nm:
                current_name = nm.group(1).strip()
                continue
            if line.startswith("!") or (line and not line[0].isspace()):
                vlans.append(CanonicalVlan(id=current_id, name=current_name))
                current_id = None
                current_name = ""

    if current_id is not None:
        vlans.append(CanonicalVlan(id=current_id, name=current_name))

    return vlans


_SVI_NAME_RE = re.compile(r"^Vlan(\d+)$", re.IGNORECASE)


def _synthesize_vlans_from_svis(intent: CanonicalIntent) -> None:
    """Post-parse pass that derives VLAN records from ``interface
    Vlan<N>`` stanzas.

    On Cisco IOS, a VLAN can exist two ways:

    1. Explicit L2 database entry — ``vlan 11 / name Users``
    2. Implicit, via the SVI alone — ``interface Vlan11 / ip address
       X / description Users``

    :func:`_parse_vlans` only catches form (1).  Without this helper
    the L3 data attached to form (2) would get silently dropped by
    any VLAN-centric downstream codec (Aruba, OPNsense) because its
    renderer looks for the IP under ``tree.vlans``, not under the
    ``Vlan<N>`` interface itself.

    Behaviour:
        * SVI with no existing VLAN record → create one with the
          SVI's IPs attached.
        * SVI with an existing VLAN record (matching id) → merge
          the SVI's IPs in.  The top-level stanza's ``name`` wins
          over the SVI's (they're semantically different — VLAN
          name is an L2 tag, SVI description is an L3 interface
          hint — but with no better info we keep whichever came
          first).
        * SVI with no IP (e.g. ``interface Vlan1 / no ip address``)
          still creates/touches a VLAN record so "this VLAN exists"
          is preserved end-to-end.
    """
    existing_by_id: dict[int, CanonicalVlan] = {
        v.id: v for v in intent.vlans
    }
    for iface in intent.interfaces:
        m = _SVI_NAME_RE.match(iface.name)
        if not m:
            continue
        vid = int(m.group(1))
        existing = existing_by_id.get(vid)
        if existing is None:
            synthesised = CanonicalVlan(
                id=vid,
                # SVI description is a reasonable fallback for the
                # VLAN name when no explicit stanza was present.
                name=iface.description,
                ipv4_addresses=list(iface.ipv4_addresses),
            )
            intent.vlans.append(synthesised)
            existing_by_id[vid] = synthesised
            continue
        # Merge SVI IPs into existing VLAN record.  De-dupe in case
        # the same IP was declared both places.
        for addr in iface.ipv4_addresses:
            if addr not in existing.ipv4_addresses:
                existing.ipv4_addresses.append(addr)


def _parse_lags(raw: str, intent: CanonicalIntent) -> list[CanonicalLAG]:
    """Build :class:`CanonicalLAG` records from Cisco CLI.

    Sources of truth in a Cisco config:
      * ``interface Port-channelN`` stanza declares the LAG exists
        (and carries the LAG's description / switchport / IP state
        via the existing interface parse path — that's already on
        ``intent.interfaces``).
      * ``channel-group N mode M`` under a physical interface declares
        that physical port a member of Port-channelN.

    A LAG must exist if EITHER signal is present (Cisco allows defining
    Port-channelN explicitly OR lazily via member channel-group lines).

    Mode is whatever the members agree on; if members disagree, the
    first member's mode wins (rare in practice, but pathological
    configs shouldn't crash us).  If no physical members exist (empty
    LAG stanza), mode defaults to ``CanonicalLAG.mode`` default.
    """
    # Scan: for each `interface X` stanza, note its channel-group (if any).
    members_by_lag: dict[str, list[str]] = {}
    mode_by_lag: dict[str, str] = {}
    declared_lag_names: set[str] = set()

    current_iface: str | None = None
    for line in raw.splitlines():
        m = _IFACE_RE.match(line)
        if m:
            current_iface = m.group(1)
            if current_iface.lower().startswith("port-channel"):
                declared_lag_names.add(current_iface)
            continue
        if current_iface is None:
            continue
        if line.startswith("!") or (line and not line[0].isspace()):
            current_iface = None
            continue
        cgm = _CHANNEL_GROUP_RE.match(line)
        if cgm:
            lag_name = f"Port-channel{int(cgm.group(1))}"
            cisco_mode = cgm.group(2).lower()
            canonical_mode = _CISCO_LAG_MODE_MAP.get(cisco_mode, "active")
            # Real configs (and Batfish's grammar-kitchen-sink fixtures)
            # can stack multiple `channel-group N mode M` lines on a
            # single physical interface — either as a historical artefact
            # of mode changes or as test-config variants.  Dedupe so the
            # member list has one entry per physical port.
            members = members_by_lag.setdefault(lag_name, [])
            if current_iface not in members:
                members.append(current_iface)
            # First member's mode wins.
            mode_by_lag.setdefault(lag_name, canonical_mode)

    all_lag_names = declared_lag_names | set(members_by_lag)
    lags: list[CanonicalLAG] = []
    for lag_name in sorted(all_lag_names, key=_lag_sort_key):
        lag = CanonicalLAG(
            name=lag_name,
            members=list(members_by_lag.get(lag_name, [])),
        )
        if lag_name in mode_by_lag:
            lag.mode = mode_by_lag[lag_name]
        lags.append(lag)
    return lags


def _lag_sort_key(name: str) -> tuple[str, int, str]:
    """Stable sort key that groups ``Port-channel<N>`` numerically."""
    m = re.match(r"^(port-channel|trk|bond|lag|lagg)(\d+)$", name, re.IGNORECASE)
    if m:
        return (m.group(1).lower(), int(m.group(2)), "")
    return ("", 0, name)


def _parse_static_routes(raw: str) -> list[CanonicalStaticRoute]:
    """Extract ``ip route`` and ``ip default-gateway`` lines from IOS config text."""
    routes: list[CanonicalStaticRoute] = []
    for line in raw.splitlines():
        m = _STATIC_ROUTE_RE.match(line)
        if m:
            dest_ip = m.group(1)
            mask = m.group(2)
            gw_or_iface = m.group(3)
            prefix_len = _mask_to_prefix(mask)
            dest = f"{dest_ip}/{prefix_len}"
            # Gateway could be an IP or an interface name.
            gateway = ""
            iface = ""
            try:
                ipaddress.IPv4Address(gw_or_iface)
                gateway = gw_or_iface
            except ipaddress.AddressValueError:
                iface = gw_or_iface
            routes.append(CanonicalStaticRoute(
                destination=dest,
                gateway=gateway,
                interface=iface,
            ))
            continue
        m = _DEFAULT_GATEWAY_RE.match(line)
        if m:
            # ``ip default-gateway X`` -> 0.0.0.0/0 via X.  Aruba's
            # renderer re-collapses this back to the native
            # ``ip default-gateway`` form.
            routes.append(CanonicalStaticRoute(
                destination="0.0.0.0/0",
                gateway=m.group(1),
            ))
    return routes


def _walk_canonical(intent: CanonicalIntent) -> Iterable[str]:
    """Yield schema xpaths from a CanonicalIntent for validation."""
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


# -- SNMP parse helpers (shared via re-export for sibling codecs if needed)

_SNMP_COMMUNITY_RE = re.compile(
    r'^snmp-server\s+community\s+(\S+)', re.IGNORECASE | re.MULTILINE,
)
_SNMP_LOCATION_RE = re.compile(
    r'^snmp-server\s+location\s+(.+)$', re.IGNORECASE | re.MULTILINE,
)
_SNMP_CONTACT_RE = re.compile(
    r'^snmp-server\s+contact\s+(.+)$', re.IGNORECASE | re.MULTILINE,
)
_SNMP_HOST_RE = re.compile(
    r'^snmp-server\s+host\s+(\d+\.\d+\.\d+\.\d+)',
    re.IGNORECASE | re.MULTILINE,
)


def _parse_snmp(raw: str) -> CanonicalSNMP | None:
    """Extract SNMP server config from IOS CLI text.

    Returns None when no snmp-server lines are present so the
    downstream canonical tree doesn't carry an empty stub.
    """
    community_m = _SNMP_COMMUNITY_RE.search(raw)
    location_m = _SNMP_LOCATION_RE.search(raw)
    contact_m = _SNMP_CONTACT_RE.search(raw)
    hosts = _SNMP_HOST_RE.findall(raw)
    if not (community_m or location_m or contact_m or hosts):
        return None
    snmp = CanonicalSNMP()
    if community_m:
        snmp.community = community_m.group(1).strip()
    if location_m:
        snmp.location = location_m.group(1).strip().strip('"')
    if contact_m:
        snmp.contact = contact_m.group(1).strip().strip('"')
    snmp.trap_hosts = list(hosts)
    return snmp
