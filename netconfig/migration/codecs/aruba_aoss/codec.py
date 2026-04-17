"""
``ArubaAOSSCodec`` — 4th real codec, Session C of vendor-config-research.

See package ``__init__`` for scope and structural-quirks notes.
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
    CanonicalSNMP,
    CanonicalStaticRoute,
    CanonicalVlan,
)
from ..base import CodecBase, ParseError, RenderError
from ..registry import register


@register
class ArubaAOSSCodec(CodecBase):
    """Codec for Aruba AOS-S ``show running-config`` text.

    Declares ``device_classes=[switch, router]`` — AOS-S ships
    primarily as L2 access switches but L3 features (routed ports,
    static routes) are in scope here.
    """

    name: ClassVar[str] = "aruba_aoss"
    version_hint: ClassVar[str | None] = "16.x"
    input_format: ClassVar[str] = "cli-aruba-aoss"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "best_effort"
    canonical_model: ClassVar[str] = "openconfig-lite"
    description: ClassVar[str] = (
        "Paste the output of `show running-config` from an Aruba AOS-S "
        "(ProCurve / ArubaOS-Switch 16.x) device.  NOT the same as "
        "AOS-CX — CX uses a different codec."
    )
    sample_input: ClassVar[str] = (
        '; J9729A Configuration Editor; Created on release #WC.16.11\n'
        'hostname "sw-edge-01"\n'
        'snmp-server community "public" Operator\n'
        'vlan 1\n'
        '   name "DEFAULT_VLAN"\n'
        '   untagged 1-24\n'
        '   no ip address\n'
        '   exit\n'
        'vlan 10\n'
        '   name "USERS"\n'
        '   untagged 1-24\n'
        '   tagged 25-26\n'
        '   ip address 192.168.10.1/24\n'
        '   exit\n'
        'interface 1\n'
        '   name "Desk 1"\n'
        '   enable\n'
        '   exit\n'
        'ip default-gateway 192.168.10.254\n'
    )
    output_extension: ClassVar[str] = "cfg"

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="aruba_aoss",
        vendor_id="aruba_aoss",
        version_range="16.x",
        device_classes=[DeviceClass.switch, DeviceClass.router],
        supported=[
            "/system/hostname",
            "/system/dns-server",
            "/system/ntp-server",
            "/interfaces/interface/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/config/type",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/vlans/vlan/tagged-ports",
            "/vlans/vlan/untagged-ports",
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
                    "AOS-S does not declare IANA ifType; the codec "
                    "infers type from interface-name shape (bare "
                    "number -> ethernet, 'Trk' -> port-channel, "
                    "'Vlan' -> l3ipvlan)."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            UnsupportedPath(
                path="/filter/rule",
                reason=(
                    "AOS-S access-lists are Tier 3 (informational) "
                    "and not yet auto-rendered."
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
        """Parse AOS-S ``show running-config`` text into a
        :class:`CanonicalIntent`."""
        if not raw.strip():
            raise ParseError(
                "aruba_aoss: empty input",
                snippet="",
            )
        stripped = raw.lstrip()
        if stripped.startswith("<"):
            raise ParseError(
                "aruba_aoss: input looks like XML, not AOS-S CLI.",
                snippet=stripped[:120],
            )
        if stripped.startswith("{"):
            raise ParseError(
                "aruba_aoss: input looks like JSON, not AOS-S CLI.",
                snippet=stripped[:120],
            )

        intent = CanonicalIntent(
            source_vendor="aruba_aoss",
            source_format="cli-aruba-aoss",
        )

        lines = raw.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped_line = line.strip()

            # Skip comments (AOS-S uses ';') and blank lines.
            if not stripped_line or stripped_line.startswith(";"):
                i += 1
                continue

            # Top-level lines start in column 0.
            if line[0].isspace():
                i += 1
                continue

            hm = _HOSTNAME_RE.match(stripped_line)
            if hm:
                intent.hostname = _unquote(hm.group(1))
                i += 1
                continue

            comm = _SNMP_COMMUNITY_LINE_RE.match(stripped_line)
            if comm:
                if intent.snmp is None:
                    intent.snmp = CanonicalSNMP()
                if not intent.snmp.community:
                    intent.snmp.community = comm.group(1)
                i += 1
                continue

            loc = _SNMP_LOCATION_RE.match(stripped_line)
            if loc:
                if intent.snmp is None:
                    intent.snmp = CanonicalSNMP()
                intent.snmp.location = loc.group(1).strip().strip('"')
                i += 1
                continue

            contact = _SNMP_CONTACT_RE.match(stripped_line)
            if contact:
                if intent.snmp is None:
                    intent.snmp = CanonicalSNMP()
                intent.snmp.contact = contact.group(1).strip().strip('"')
                i += 1
                continue

            snmp_host = _SNMP_HOST_RE.match(stripped_line)
            if snmp_host:
                if intent.snmp is None:
                    intent.snmp = CanonicalSNMP()
                intent.snmp.trap_hosts.append(snmp_host.group(1))
                i += 1
                continue

            dns = _DNS_SERVER_RE.match(stripped_line)
            if dns:
                intent.dns_servers.append(dns.group(1))
                i += 1
                continue

            ntp = _SNTP_SERVER_RE.match(stripped_line)
            if ntp:
                intent.ntp_servers.append(ntp.group(1))
                i += 1
                continue

            gw = _DEFAULT_GW_RE.match(stripped_line)
            if gw:
                intent.static_routes.append(CanonicalStaticRoute(
                    destination="0.0.0.0/0",
                    gateway=gw.group(1),
                ))
                i += 1
                continue

            rt = _IP_ROUTE_RE.match(stripped_line)
            if rt:
                dest, gateway = rt.group(1), rt.group(2)
                intent.static_routes.append(CanonicalStaticRoute(
                    destination=_dest_to_cidr(dest),
                    gateway=gateway,
                ))
                i += 1
                continue

            vm = _VLAN_HEADER_RE.match(stripped_line)
            if vm:
                vlan_id = int(vm.group(1))
                vlan, next_i = _parse_vlan_stanza(lines, i + 1, vlan_id)
                intent.vlans.append(vlan)
                # Stanzas may also declare an SVI IP; if so, create a
                # VLAN interface so the canonical tree has an L3 record.
                if vlan.ipv4_addresses:
                    intent.interfaces.append(CanonicalInterface(
                        name=f"Vlan{vlan_id}",
                        description=vlan.name,
                        enabled=True,
                        interface_type="ianaift:l3ipvlan",
                        ipv4_addresses=list(vlan.ipv4_addresses),
                    ))
                i = next_i
                continue

            im = _IFACE_HEADER_RE.match(stripped_line)
            if im:
                iface_name = im.group(1).strip('"')
                iface, next_i = _parse_interface_stanza(lines, i + 1, iface_name)
                intent.interfaces.append(iface)
                i = next_i
                continue

            # Unrecognised top-level line — skip.
            i += 1

        return intent

    # -----------------------------------------------------------------
    # Render
    # -----------------------------------------------------------------

    def render(self, tree: Any) -> str:
        """Render a :class:`CanonicalIntent` to AOS-S ``show running-
        config`` text.

        Raises:
            RenderError: If *tree* is not a CanonicalIntent.
        """
        if not isinstance(tree, CanonicalIntent):
            raise RenderError(
                "aruba_aoss: tree must be a CanonicalIntent.",
                yang_path="/",
            )

        lines: list[str] = []
        lines.append(
            "; generated by netconfig translator (aruba_aoss codec)"
        )

        if tree.hostname:
            lines.append(f'hostname "{tree.hostname}"')

        for server in tree.dns_servers:
            lines.append(f"ip dns server-address priority 1 {server}")

        for server in tree.ntp_servers:
            lines.append(f"sntp server priority 1 {server}")

        # SNMP (Tier 2)
        if tree.snmp is not None and (
            tree.snmp.community or tree.snmp.location
            or tree.snmp.contact or tree.snmp.trap_hosts
        ):
            if tree.snmp.community:
                lines.append(
                    f'snmp-server community "{tree.snmp.community}" Operator'
                )
            if tree.snmp.location:
                lines.append(f'snmp-server location "{tree.snmp.location}"')
            if tree.snmp.contact:
                lines.append(f'snmp-server contact "{tree.snmp.contact}"')
            for host in tree.snmp.trap_hosts:
                comm = tree.snmp.community or "public"
                lines.append(
                    f'snmp-server host {host} community "{comm}"'
                )

        # VLANs — the architecturally interesting part.  AOS-S's
        # VLAN-centric port membership is our canonical model's
        # natural form, so this is a direct projection.
        vlan_ifaces_by_name = {
            iface.name: iface for iface in tree.interfaces
            if iface.name.lower().startswith("vlan")
        }
        for vlan in tree.vlans:
            lines.append(f"vlan {vlan.id}")
            if vlan.name:
                lines.append(f'   name "{vlan.name}"')
            if vlan.untagged_ports:
                lines.append(
                    f"   untagged {_format_port_list(vlan.untagged_ports)}"
                )
            if vlan.tagged_ports:
                lines.append(
                    f"   tagged {_format_port_list(vlan.tagged_ports)}"
                )
            # SVI address: may live on the vlan itself OR on a Vlan<N>
            # interface — honour whichever has data.
            addrs = list(vlan.ipv4_addresses)
            svi_iface = vlan_ifaces_by_name.get(f"Vlan{vlan.id}")
            if not addrs and svi_iface is not None:
                addrs = list(svi_iface.ipv4_addresses)
            for addr in addrs:
                lines.append(
                    f"   ip address {addr.ip}/{addr.prefix_length}"
                )
            lines.append("   exit")

        # Physical / named interfaces.  Skip Vlan<N> stubs that were
        # already handled inside the VLAN stanza.
        for iface in tree.interfaces:
            if iface.name.lower().startswith("vlan"):
                continue
            lines.append(f"interface {iface.name}")
            if iface.description:
                lines.append(f'   name "{iface.description}"')
            if iface.enabled:
                lines.append("   enable")
            else:
                lines.append("   disable")
            if iface.ipv4_addresses:
                lines.append("   routing")
                for addr in iface.ipv4_addresses:
                    lines.append(
                        f"   ip address {addr.ip}/{addr.prefix_length}"
                    )
            lines.append("   exit")

        # Static routes.  Default route (0.0.0.0/0) becomes
        # ``ip default-gateway`` per AOS-S convention.
        for route in tree.static_routes:
            if route.destination in ("0.0.0.0/0", "default"):
                lines.append(f"ip default-gateway {route.gateway}")
            else:
                lines.append(
                    f"ip route {route.destination} {route.gateway}"
                )

        return "\n".join(lines) + "\n"

    # -----------------------------------------------------------------
    # iter_xpaths
    # -----------------------------------------------------------------

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        if isinstance(tree, CanonicalIntent):
            from ..cisco_iosxe_cli.codec import _walk_canonical
            yield from _walk_canonical(tree)
            # VLAN port-membership xpaths (this codec is the first
            # that actually populates them).
            for vlan in tree.vlans:
                for _ in vlan.tagged_ports:
                    yield "/vlans/vlan/tagged-ports"
                for _ in vlan.untagged_ports:
                    yield "/vlans/vlan/untagged-ports"

    # -----------------------------------------------------------------
    # Auto-detection probe (R5)
    # -----------------------------------------------------------------

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Detect AOS-S running-config by its unique structural cues.

        Key discriminators vs. Cisco IOS CLI:
          * ``;`` banner comment (IOS uses ``!``)
          * ``interface <N>`` with a bare number, no ``Ethernet``/``Gig`` prefix
          * ``vlan <N>`` ... ``untagged <range>`` inside the stanza
          * ``routing`` keyword on a port (not ``no switchport``)
        """
        stripped = raw_prefix.lstrip()
        if stripped.startswith("<") or stripped.startswith("{"):
            return None

        # Unique banner: ``; J####A Configuration Editor`` or similar.
        if re.search(r"^;\s*J\d+A\s+Configuration", raw_prefix, re.MULTILINE):
            return (98, "AOS-S ProCurve configuration banner present")

        # Structural: vlan stanzas with inline untagged/tagged.
        has_vlan_with_untagged = bool(re.search(
            r"^vlan\s+\d+[\s\S]{0,400}?^\s+untagged\s+\d",
            raw_prefix, re.MULTILINE,
        ))
        has_iface_bare_num = bool(re.search(
            r"^interface\s+[A-Z]?\d+(/\d+)?\s*$",
            raw_prefix, re.MULTILINE,
        ))
        has_routing_keyword = bool(re.search(
            r"^\s+routing\s*$", raw_prefix, re.MULTILINE,
        ))
        has_aos_comment = bool(re.search(
            r"^;", raw_prefix, re.MULTILINE,
        ))

        strong_hits = sum((
            has_vlan_with_untagged,
            has_iface_bare_num,
            has_routing_keyword,
        ))
        if strong_hits >= 2 and has_aos_comment:
            return (95, f"{strong_hits} AOS-S structural markers + ';' comment")
        if strong_hits >= 2:
            return (88, f"{strong_hits} AOS-S structural markers present")
        if has_vlan_with_untagged:
            return (78, "VLAN stanza with inline 'untagged' port list")
        if has_iface_bare_num and has_aos_comment:
            return (70, "'interface <N>' shape + ';' comment prefix")
        return None


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------


_HOSTNAME_RE = re.compile(r'^hostname\s+"?([^"\n]+)"?', re.IGNORECASE)
# Capture the quoted community token.  AOS-S: `snmp-server community "public" Operator`
_SNMP_COMMUNITY_LINE_RE = re.compile(
    r'^snmp-server\s+community\s+"?([^"\s]+)"?', re.IGNORECASE,
)
_SNMP_LOCATION_RE = re.compile(
    r'^snmp-server\s+location\s+(.+)$', re.IGNORECASE,
)
_SNMP_CONTACT_RE = re.compile(
    r'^snmp-server\s+contact\s+(.+)$', re.IGNORECASE,
)
_SNMP_HOST_RE = re.compile(
    r'^snmp-server\s+host\s+(\d+\.\d+\.\d+\.\d+)', re.IGNORECASE,
)
_DNS_SERVER_RE = re.compile(
    r"^ip\s+dns\s+server-address\s+priority\s+\d+\s+(\S+)",
    re.IGNORECASE,
)
_SNTP_SERVER_RE = re.compile(
    r"^sntp\s+server\s+priority\s+\d+\s+(\S+)", re.IGNORECASE,
)
_DEFAULT_GW_RE = re.compile(
    r"^ip\s+default-gateway\s+(\d+\.\d+\.\d+\.\d+)", re.IGNORECASE,
)
_IP_ROUTE_RE = re.compile(
    r"^ip\s+route\s+(\S+)\s+(\d+\.\d+\.\d+\.\d+)", re.IGNORECASE,
)
_VLAN_HEADER_RE = re.compile(r"^vlan\s+(\d+)\s*$", re.IGNORECASE)
_IFACE_HEADER_RE = re.compile(
    r'^interface\s+("?[A-Za-z]*\d+(?:/\d+)?"?)\s*$', re.IGNORECASE,
)

_VLAN_NAME_RE = re.compile(r'^name\s+"?([^"\n]+)"?', re.IGNORECASE)
_UNTAGGED_RE = re.compile(r"^(no\s+)?untagged\s+(.+)$", re.IGNORECASE)
_TAGGED_RE = re.compile(r"^(no\s+)?tagged\s+(.+)$", re.IGNORECASE)
_IP_ADDR_CIDR_RE = re.compile(
    r"^ip\s+address\s+(\d+\.\d+\.\d+\.\d+)/(\d+)$", re.IGNORECASE,
)
_IP_ADDR_MASK_RE = re.compile(
    r"^ip\s+address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)$",
    re.IGNORECASE,
)
_IFACE_NAME_RE = re.compile(r'^name\s+"?([^"\n]+)"?', re.IGNORECASE)


def _unquote(s: str) -> str:
    """Strip surrounding ASCII quotes if present."""
    s = s.strip()
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s


def _mask_to_prefix(mask: str) -> int:
    """Convert dotted-decimal mask to CIDR prefix length."""
    try:
        addr = ipaddress.IPv4Address(mask)
    except ipaddress.AddressValueError:
        raise ParseError(
            f"aruba_aoss: invalid subnet mask {mask!r}",
            snippet=mask,
        )
    bits = bin(int(addr))[2:]
    if "01" in bits:
        raise ParseError(
            f"aruba_aoss: non-contiguous subnet mask {mask!r}",
            snippet=mask,
        )
    return bits.count("1")


def _dest_to_cidr(dest: str) -> str:
    """Accept either ``A.B.C.D/N`` or just ``A.B.C.D``; default /32."""
    if "/" in dest:
        return dest
    return dest + "/32"


def _parse_port_list(text: str) -> list[str]:
    """Expand AOS-S port-list syntax into individual port names.

    Handles ``1-24``, ``1,3,5``, ``A1-A4``, ``1,3-5,A1``.
    Preserves order; de-duplicates.
    """
    result: list[str] = []
    seen: set[str] = set()
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            lo, hi = token.split("-", 1)
            lo, hi = lo.strip(), hi.strip()
            expanded = _expand_port_range(lo, hi)
            for p in expanded:
                if p not in seen:
                    seen.add(p)
                    result.append(p)
        else:
            if token not in seen:
                seen.add(token)
                result.append(token)
    return result


def _expand_port_range(lo: str, hi: str) -> list[str]:
    """Expand ``1-24`` or ``A1-A4`` into individual port names."""
    m_lo = re.match(r"^([A-Za-z]*)(\d+)(?:/(\d+))?$", lo)
    m_hi = re.match(r"^([A-Za-z]*)(\d+)(?:/(\d+))?$", hi)
    if not m_lo or not m_hi:
        return [lo, hi]   # can't expand — pass through as-is
    prefix_lo, num_lo = m_lo.group(1), int(m_lo.group(2))
    prefix_hi, num_hi = m_hi.group(1), int(m_hi.group(2))
    if prefix_lo != prefix_hi or num_hi < num_lo:
        return [lo, hi]
    return [f"{prefix_lo}{n}" for n in range(num_lo, num_hi + 1)]


def _format_port_list(ports: list[str]) -> str:
    """Render a flat port list back into AOS-S range syntax.

    Contiguous numeric ports with the same alpha prefix collapse into
    ``prefix<lo>-prefix<hi>``.  Non-contiguous ports are comma-joined.
    """
    if not ports:
        return ""
    # Group by alpha prefix preserving order.
    groups: list[tuple[str, list[int]]] = []
    for p in ports:
        m = re.match(r"^([A-Za-z]*)(\d+)$", p)
        if not m:
            groups.append((p, []))  # non-numeric port — keep as-is
            continue
        prefix, num = m.group(1), int(m.group(2))
        if groups and groups[-1][0] == prefix and groups[-1][1]:
            groups[-1][1].append(num)
        else:
            groups.append((prefix, [num]))

    parts: list[str] = []
    for prefix, nums in groups:
        if not nums:
            parts.append(prefix)
            continue
        # Find runs of consecutive integers.
        run_start = nums[0]
        prev = nums[0]
        run: list[int] = [nums[0]]
        def flush(start: int, end: int) -> str:
            if start == end:
                return f"{prefix}{start}"
            return f"{prefix}{start}-{prefix}{end}"
        for n in nums[1:]:
            if n == prev + 1:
                run.append(n)
                prev = n
            else:
                parts.append(flush(run_start, prev))
                run_start = n
                prev = n
                run = [n]
        parts.append(flush(run_start, prev))
    return ",".join(parts)


def _parse_vlan_stanza(
    lines: list[str], start: int, vlan_id: int,
) -> tuple[CanonicalVlan, int]:
    """Parse a ``vlan N`` stanza starting at *start* (body line).

    Returns the parsed :class:`CanonicalVlan` and the index of the
    first line AFTER the stanza's ``exit``.
    """
    vlan = CanonicalVlan(id=vlan_id)
    i = start
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith(";"):
            i += 1
            continue
        # Stanza terminates at `exit` or the next un-indented line.
        if stripped == "exit":
            i += 1
            break
        if not line[0].isspace():
            break

        nm = _VLAN_NAME_RE.match(stripped)
        if nm:
            vlan.name = _unquote(nm.group(1))
            i += 1
            continue

        um = _UNTAGGED_RE.match(stripped)
        if um:
            if um.group(1):  # "no untagged ..." — strip ports
                to_remove = set(_parse_port_list(um.group(2)))
                vlan.untagged_ports = [
                    p for p in vlan.untagged_ports if p not in to_remove
                ]
            else:
                vlan.untagged_ports.extend(_parse_port_list(um.group(2)))
            i += 1
            continue

        tm = _TAGGED_RE.match(stripped)
        if tm:
            if tm.group(1):  # "no tagged ..."
                to_remove = set(_parse_port_list(tm.group(2)))
                vlan.tagged_ports = [
                    p for p in vlan.tagged_ports if p not in to_remove
                ]
            else:
                vlan.tagged_ports.extend(_parse_port_list(tm.group(2)))
            i += 1
            continue

        ip_cidr = _IP_ADDR_CIDR_RE.match(stripped)
        if ip_cidr:
            vlan.ipv4_addresses.append(CanonicalIPv4Address(
                ip=ip_cidr.group(1),
                prefix_length=int(ip_cidr.group(2)),
            ))
            i += 1
            continue

        ip_mask = _IP_ADDR_MASK_RE.match(stripped)
        if ip_mask:
            vlan.ipv4_addresses.append(CanonicalIPv4Address(
                ip=ip_mask.group(1),
                prefix_length=_mask_to_prefix(ip_mask.group(2)),
            ))
            i += 1
            continue

        i += 1
    return vlan, i


def _parse_interface_stanza(
    lines: list[str], start: int, iface_name: str,
) -> tuple[CanonicalInterface, int]:
    """Parse an ``interface X`` stanza starting at *start*.

    Returns the parsed :class:`CanonicalInterface` and the index of
    the first line AFTER the stanza's ``exit``.
    """
    iface = CanonicalInterface(
        name=iface_name,
        enabled=True,
        interface_type=_infer_iface_type(iface_name),
    )
    i = start
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith(";"):
            i += 1
            continue
        if stripped == "exit":
            i += 1
            break
        if not line[0].isspace():
            break

        nm = _IFACE_NAME_RE.match(stripped)
        if nm:
            iface.description = _unquote(nm.group(1))
            i += 1
            continue

        if stripped == "enable":
            iface.enabled = True
            i += 1
            continue

        if stripped == "disable":
            iface.enabled = False
            i += 1
            continue

        ip_cidr = _IP_ADDR_CIDR_RE.match(stripped)
        if ip_cidr:
            iface.ipv4_addresses.append(CanonicalIPv4Address(
                ip=ip_cidr.group(1),
                prefix_length=int(ip_cidr.group(2)),
            ))
            i += 1
            continue

        ip_mask = _IP_ADDR_MASK_RE.match(stripped)
        if ip_mask:
            iface.ipv4_addresses.append(CanonicalIPv4Address(
                ip=ip_mask.group(1),
                prefix_length=_mask_to_prefix(ip_mask.group(2)),
            ))
            i += 1
            continue

        # `routing` keyword toggles L3 mode — informational since we
        # infer from the presence of `ip address`.
        i += 1
    return iface, i


def _infer_iface_type(name: str) -> str:
    """Best-effort IANA ifType from the port name."""
    lower = name.lower()
    if lower.startswith("trk"):
        return "ianaift:ieee8023adLag"
    if lower.startswith("vlan"):
        return "ianaift:l3ipvlan"
    return "ianaift:ethernetCsmacd"
