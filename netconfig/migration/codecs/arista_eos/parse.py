"""
Parse path for Arista EOS CLI (``show running-config`` form).

Public function: :func:`parse_intent` — raw text in,
:class:`CanonicalIntent` out.

Handles standard interfaces, VLANs, VRFs (``vrf instance`` form),
EVPN MAC-VRFs (``router bgp / vlan N`` form), VXLAN (interface
``Vxlan1`` with ``source-interface`` + ``udp-port`` + vlan/vrf VNIs),
IPv4 + IPv6 addresses (with global / link-local scope classification),
DHCP server pools (``ip dhcp pool`` family), RADIUS servers
(``radius-server host`` one-liner with ``auth-port`` / ``acct-port`` /
``key`` modifiers), SNMP (community / location / contact / trap-host /
v3 USM users), local users, and static routes.

Extracted verbatim from ``codec.py`` during the parse/render split;
behaviour is identical to the prior in-class implementation.  The
codec module's ``parse()`` method is now a one-line delegator to
:func:`parse_intent`.

Internal helpers (``_parse_stanzas``, ``_parse_router_bgp``,
``_apply_iface_subcommand``, ``_infer_iface_type``,
``_expand_vlan_list``) and the module-level regex constants
(``_HOSTNAME_RE`` etc.) live here because they are parse-only.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any

from ...canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
    CanonicalRADIUSServer,
    CanonicalRoutingInstance,
    CanonicalVxlan,
    CanonicalLocalUser,
    CanonicalSNMP,
    CanonicalSNMPv3User,
    CanonicalStaticRoute,
    CanonicalVlan,
)
from ..base import ParseError

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

# RADIUS server line (legacy Cisco-derived one-liner that EOS preserved).
# Form: ``radius-server host <ip> [auth-port N] [acct-port N] [key SECRET]``
# Token order is fixed (host first) but the optional clauses may appear in
# any order on the wire.  Match host + remainder, then post-extract.
_RADIUS_SERVER_RE = re.compile(
    r"^radius-server\s+host\s+(\d+\.\d+\.\d+\.\d+)\s*(.*)$",
    re.MULTILINE,
)
_RADIUS_AUTH_PORT_RE = re.compile(r"\bauth-port\s+(\d+)")
_RADIUS_ACCT_PORT_RE = re.compile(r"\bacct-port\s+(\d+)")
# Key payload: bare token or quoted string.  EOS accepts both.
_RADIUS_KEY_RE = re.compile(r'\bkey\s+(?:"([^"]*)"|(\S+))')

_VRF_INSTANCE_RE = re.compile(r"^vrf\s+instance\s+(\S+)\s*$", re.MULTILINE)
_INTERFACE_HEADER_RE = re.compile(r"^interface\s+(\S+)\s*$")

# VLAN stanza: ``vlan <id>`` optionally followed by ``   name <name>``.
_VLAN_HEADER_RE = re.compile(r"^vlan\s+(\d+)\s*$")


# ---------------------------------------------------------------------------
# DHCP-server pool grammar (Arista EOS User Manual, "DHCP and DHCP Relay"
# https://www.arista.com/en/um-eos/eos-dhcp-and-dhcp-relay).
#
# EOS DHCP-pool form is structurally identical to the Cisco-IOS-XE
# ``ip dhcp pool`` family for the subset we model (network, default-
# router, dns-server, domain-name, lease).  EOS adds an explicit
# ``range <start_ip> <end_ip>`` allocatable-window line that Cisco
# lacks.  EOS's ``network`` clause accepts BOTH dotted-mask and CIDR
# forms — the sample doc snippet pairs a USERS pool ``network
# 10.10.10.0 255.255.255.0`` with a VOICE pool ``network 10.10.20.0
# /24`` so we tolerate both shapes on parse and emit the dotted form
# (the older + more universally accepted spelling) on render.
_DHCP_POOL_HEADER_RE = re.compile(
    r"^ip\s+dhcp\s+pool\s+(\S+)\s*$", re.IGNORECASE,
)
_DHCP_NETWORK_DOTTED_RE = re.compile(
    r"^\s+network\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s*$",
    re.IGNORECASE,
)
# CIDR form: ``network 10.10.20.0/24`` or ``network 10.10.20.0 /24``
# (the doc snippet shows the space-separated variant).
_DHCP_NETWORK_CIDR_RE = re.compile(
    r"^\s+network\s+(\d+\.\d+\.\d+\.\d+)\s*/\s*(\d+)\s*$",
    re.IGNORECASE,
)
_DHCP_RANGE_RE = re.compile(
    r"^\s+range\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s*$",
    re.IGNORECASE,
)
_DHCP_DEFAULT_ROUTER_RE = re.compile(
    r"^\s+default-router\s+(\d+\.\d+\.\d+\.\d+)",
    re.IGNORECASE,
)
_DHCP_DNS_SERVER_RE = re.compile(
    r"^\s+dns-server\s+(.+)$", re.IGNORECASE,
)
_DHCP_DOMAIN_NAME_RE = re.compile(
    r"^\s+domain-name\s+(\S+)", re.IGNORECASE,
)
# EOS lease syntax: ``lease <days> [<hours>] [<minutes>]`` or
# ``lease infinite`` (DHCP-protocol max-uint32 sentinel).
_DHCP_LEASE_RE = re.compile(
    r"^\s+lease\s+(\S+)(?:\s+(\d+))?(?:\s+(\d+))?\s*$",
    re.IGNORECASE,
)


def _parse_dhcp_pools(raw: str) -> list[CanonicalDHCPPool]:
    """Extract ``ip dhcp pool`` stanzas into CanonicalDHCPPool records.

    Mirrors the cisco_iosxe_cli pattern; diverges on the explicit
    ``range`` line (EOS-only) and on the CIDR-form ``network`` line
    (EOS accepts both, Cisco only accepts dotted-mask).  Pool name
    lands on ``CanonicalDHCPPool.interface`` — same convention as
    cisco_iosxe_cli, fortigate_cli (interface field carries the
    operator-chosen pool identifier on Cisco-derived grammars).
    """
    pools: list[CanonicalDHCPPool] = []
    current: CanonicalDHCPPool | None = None

    for line in raw.splitlines():
        header = _DHCP_POOL_HEADER_RE.match(line)
        if header:
            if current is not None:
                pools.append(current)
            current = CanonicalDHCPPool(interface=header.group(1))
            continue
        if current is None:
            continue
        # End-of-stanza: ``!`` marker or a non-indented top-level line.
        if line.startswith("!") or (line and not line[0].isspace()):
            pools.append(current)
            current = None
            continue

        nm = _DHCP_NETWORK_DOTTED_RE.match(line)
        if nm:
            ip_str, mask = nm.group(1), nm.group(2)
            try:
                prefix = _mask_to_prefix(mask)
            except ParseError:
                continue
            current.network = f"{ip_str}/{prefix}"
            continue
        nm = _DHCP_NETWORK_CIDR_RE.match(line)
        if nm:
            current.network = f"{nm.group(1)}/{nm.group(2)}"
            continue
        rm = _DHCP_RANGE_RE.match(line)
        if rm:
            current.start_ip = rm.group(1)
            current.end_ip = rm.group(2)
            continue
        gm = _DHCP_DEFAULT_ROUTER_RE.match(line)
        if gm:
            current.gateway = gm.group(1)
            continue
        dm = _DHCP_DNS_SERVER_RE.match(line)
        if dm:
            servers = dm.group(1).split()
            current.dns_servers.extend(servers)
            continue
        dnm = _DHCP_DOMAIN_NAME_RE.match(line)
        if dnm:
            current.domain_name = dnm.group(1)
            continue
        lm = _DHCP_LEASE_RE.match(line)
        if lm:
            lease_val = lm.group(1).lower()
            if lease_val == "infinite":
                current.lease_time = 0xFFFFFFFF
            else:
                try:
                    days = int(lease_val)
                    hours = int(lm.group(2) or 0)
                    minutes = int(lm.group(3) or 0)
                    current.lease_time = (
                        days * 86400 + hours * 3600 + minutes * 60
                    )
                except ValueError:
                    pass

    if current is not None:
        pools.append(current)
    return pools


def _mask_to_prefix(mask_str: str) -> int:
    """Convert a dotted-decimal subnet mask to a CIDR prefix length.

    Local copy of the cisco_iosxe_cli helper — keeping it in-codec
    avoids a cross-codec import for one regex helper.
    """
    try:
        addr = ipaddress.IPv4Address(mask_str)
    except ipaddress.AddressValueError:
        raise ParseError(
            f"arista_eos: invalid subnet mask {mask_str!r}",
            snippet=mask_str,
        )
    bits = bin(int(addr))[2:]
    if "01" in bits:
        raise ParseError(
            f"arista_eos: non-contiguous subnet mask {mask_str!r}",
            snippet=mask_str,
        )
    return bits.count("1")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def parse_intent(raw: str) -> CanonicalIntent:
    """Parse Arista EOS ``show running-config`` text into a canonical tree."""
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

    # --- RADIUS servers (Tier 2) ---
    # Arista accepts the Cisco-derived one-liner form
    # ``radius-server host <ip> [auth-port N] [acct-port N]
    # [key SECRET]``.  Round-trip with the matching render path —
    # host is positional, remaining clauses are order-tolerant.
    for rad_m in _RADIUS_SERVER_RE.finditer(raw):
        host = rad_m.group(1)
        rest = rad_m.group(2) or ""
        auth_port = 1812
        acct_port = 1813
        key = ""
        ap = _RADIUS_AUTH_PORT_RE.search(rest)
        if ap:
            try:
                auth_port = int(ap.group(1))
            except ValueError:
                pass
        cp = _RADIUS_ACCT_PORT_RE.search(rest)
        if cp:
            try:
                acct_port = int(cp.group(1))
            except ValueError:
                pass
        km = _RADIUS_KEY_RE.search(rest)
        if km:
            key = km.group(1) if km.group(1) is not None else km.group(2)
        intent.radius_servers.append(CanonicalRADIUSServer(
            host=host, key=key,
            auth_port=auth_port, acct_port=acct_port,
        ))

    # --- DHCP server pools (Tier 2) — ``ip dhcp pool <name>``
    #     stanzas.  See module docstring at _parse_dhcp_pools for
    #     grammar notes.  Vendor doc: Arista EOS User Manual,
    #     "DHCP and DHCP Relay".
    intent.dhcp_servers = _parse_dhcp_pools(raw)

    # --- VRF declarations (GAP 6) — ``vrf instance <name>`` top-
    #     level lines create CanonicalRoutingInstance records.
    #     RD + RTs get populated later from the router-bgp pass.
    for vrf_m in _VRF_INSTANCE_RE.finditer(raw):
        intent.routing_instances.append(
            CanonicalRoutingInstance(name=vrf_m.group(1))
        )

    # --- Interface + VLAN + Vxlan stanzas (line-scan with
    #     current-stanza tracking, same pattern as cisco_iosxe_cli) ---
    _parse_stanzas(raw, intent)

    # --- router bgp <asn> / vrf <name> / rd + route-target (GAP 6) ---
    _parse_router_bgp(raw, intent)

    # SVI fold: ``interface Vlan<N> / ip address ...`` lines carry
    # the Layer-3 surface for VLAN <N>.  VLAN-centric renderers
    # (Aruba AOS-S, OPNsense) read the L3 off
    # ``CanonicalVlan.ipv4_addresses``, not off the sibling
    # interface, so without this fold the SVI IP silently drops on
    # cross-vendor render.  Mirrors the same call in
    # ``cisco_iosxe_cli/parse.py``.  See translator-plans.txt BUG 1.
    from ...canonical.transforms import (
        project_svi_to_vlan,
        project_switchport_to_vlan,
    )
    project_svi_to_vlan(intent)

    # Bug 3 transpose: mirror per-port switchport state into the
    # VLAN-centric tagged_ports / untagged_ports lists so VLAN-
    # centric renderers (Aruba, OPNsense) can emit the membership.
    # Without this, per-interface `switchport access vlan 20` /
    # `switchport trunk allowed vlan 11,20` never reaches the
    # target config.  See translator-plans.txt BUG 3.
    #
    # Phantom-VLAN guard (Phase 4b Wave 7c-C): mirrors the
    # cisco_iosxe_cli pattern.  ``project_switchport_to_vlan``
    # synthesises bare :class:`CanonicalVlan` records for any VID
    # referenced by a ``switchport ... vlan`` line that didn't have
    # a matching top-level ``vlan <N>`` stanza (or SVI).  On a
    # cross-vendor pass from a source that already pruned phantoms
    # (Cisco IOS-XE), a wide ``switchport trunk allowed vlan``
    # range on the rendered Arista output silently re-inflates the
    # canonical VLAN table on round-trip parse.  Snapshot the
    # legitimate VLAN ids BEFORE projection, then prune any VLAN
    # whose id wasn't in the snapshot AFTER.  ``trunk_allowed_vlans``
    # on the per-interface side is not touched; the L2 attribute
    # round-trips back out unchanged.
    legitimate_vlan_ids = {v.id for v in intent.vlans}
    project_switchport_to_vlan(intent)
    intent.vlans = [v for v in intent.vlans if v.id in legitimate_vlan_ids]

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


# ---------------------------------------------------------------------------
# Stanza walkers
# ---------------------------------------------------------------------------


def _parse_stanzas(raw: str, intent: CanonicalIntent) -> None:
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
    # GAP-EVPN-2: switch-level VXLAN settings are captured inside
    # ``interface Vxlan1`` but apply globally to every CanonicalVxlan
    # record produced from that stanza.  Stash them as parse-time
    # locals; the per-VNI population code patches them onto each
    # record at append-time, and a post-pass normalises any records
    # that landed before the source-interface line was seen.
    vxlan_state: dict[str, Any] = {
        "source_interface": "",
        "udp_port": 4789,
        "records": [],     # list of CanonicalVxlan records emitted from THIS Vxlan stanza
    }

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
            _apply_iface_subcommand(
                current_iface, stripped, lag_members, intent,
                vxlan_state,
            )
            # Track L3 flip so subsequent ``ip address`` lines are
            # understood as routed rather than SVI-like.
            if stripped == "no switchport":
                current_iface_is_l3 = True
        elif current_vlan is not None:
            if stripped.startswith("name "):
                current_vlan.name = stripped.split(None, 1)[1].strip()

    # GAP-EVPN-2 post-pass: stamp every CanonicalVxlan record we
    # produced with the switch-level source-interface + udp-port we
    # observed.  Records appended BEFORE the source-interface line
    # was scanned (legal — operators sometimes put VNI mappings
    # ahead of the global config) get back-patched here.
    if vxlan_state["records"]:
        si = vxlan_state["source_interface"]
        up = vxlan_state["udp_port"]
        for rec in vxlan_state["records"]:
            # Don't overwrite a value already set on this record
            # (defensive — repeated parses or unusual ordering).
            if si and not rec.source_interface:
                rec.source_interface = si
            if up and rec.udp_port == 4789:
                rec.udp_port = up

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


def _parse_router_bgp(raw: str, intent: CanonicalIntent) -> None:
    """Parse ``router bgp <asn> / vrf <name> / rd <rd> /
    route-target import|export|both <rt>`` — VRF metadata — AND
    ``router bgp <asn> / vlan <N> / rd ... / route-target ...``
    — the per-VLAN EVPN MAC-VRF binding form (GAP-EVPN-1).
    BGP neighbor/address-family details stay parse-and-ignore.

    Lines in EOS `router bgp` are indented; `vrf <name>` and
    `vlan <N>` nest 3-spaces deeper than the router-bgp stanza.
    We track stanza depth via leading-whitespace count.

    For ``vlan <N>``: the routing-instance is keyed by the
    matching CanonicalVlan.name (the ``vlan <N> name <NAME>``
    block earlier in the file).  ``instance_type="mac-vrf"`` to
    discriminate from L3 VRF entries (``instance_type="vrf"``).
    Junos render emits these with the same instance_type
    propagated.
    """
    in_bgp = False
    # Renamed from current_vrf — now tracks both VRF and MAC-VRF
    # contexts with the same RD/RT machinery.
    current_ri: CanonicalRoutingInstance | None = None
    for raw_line in raw.splitlines():
        stripped = raw_line.strip()
        # Blank line: end of file / section.
        if not stripped:
            in_bgp = False
            current_ri = None
            continue
        # Top-level ``router bgp <asn>`` opens the section.
        if raw_line.startswith("router bgp "):
            in_bgp = True
            current_ri = None
            continue
        # ``!`` alone (possibly indented) is a sub-stanza separator
        # inside router-bgp; close the per-vrf / per-vlan context
        # but KEEP in_bgp active so the next sub-stanza parses.
        if stripped == "!":
            current_ri = None
            continue
        # Another top-level stanza (non-indented, non-comment)
        # closes router-bgp.
        if not raw_line.startswith((" ", "\t")):
            in_bgp = False
            current_ri = None
            continue
        if not in_bgp:
            continue
        # Inside router-bgp: 3-space indent for top-level router
        # subs, 6-space indent for per-vrf / per-vlan subs.  Count
        # leading spaces to distinguish.
        leading_spaces = len(raw_line) - len(raw_line.lstrip(" "))
        if stripped.startswith("vrf "):
            vrf_name = stripped.split(None, 1)[1].strip()
            current_ri = next(
                (r for r in intent.routing_instances if r.name == vrf_name),
                None,
            )
            if current_ri is None:
                # ``router bgp X / vrf Y`` declares a VRF context
                # even if no standalone ``vrf instance Y`` was
                # seen upstream — create one so RD/RTs don't get
                # dropped.
                current_ri = CanonicalRoutingInstance(name=vrf_name)
                intent.routing_instances.append(current_ri)
            # Defensive: a freshly-seen VRF context is L3, not
            # MAC-VRF.  If a previous parse had marked it
            # ``mac-vrf``, that's a re-declaration error and we
            # leave the existing tag (don't silently flip).
            continue
        # GAP-EVPN-1: ``vlan <N>`` opens a per-VLAN EVPN MAC-VRF
        # binding block.  Look up the matching CanonicalVlan to
        # derive the routing-instance name (vlan.name when set;
        # ``VLAN<N>`` synthetic fallback otherwise).  The same
        # synthetic-name convention lets render look up the
        # source vlan_id back from the routing-instance name.
        #
        # CRITICAL: only fire at the 3-space top-level indent
        # within router-bgp.  At deeper indents, ``vlan <N>``
        # appears as a sub-line of vlan-aware-bundle blocks
        # (``vlan-aware-bundle <NAME> / vlan 110``) and would
        # otherwise spawn a spurious MAC-VRF context.
        m_vlan = (
            re.match(r"^vlan\s+(\d+)\s*$", stripped)
            if leading_spaces == 3 else None
        )
        if m_vlan:
            try:
                vid = int(m_vlan.group(1))
            except ValueError:
                current_ri = None
                continue
            vlan = next(
                (v for v in intent.vlans if v.id == vid), None,
            )
            ri_name = (vlan.name if vlan and vlan.name else f"VLAN{vid}")
            existing = next(
                (r for r in intent.routing_instances if r.name == ri_name),
                None,
            )
            if existing is None:
                current_ri = CanonicalRoutingInstance(
                    name=ri_name, instance_type="mac-vrf",
                )
                intent.routing_instances.append(current_ri)
            else:
                # Existing entry: tag it as mac-vrf if no other
                # parse path already populated as L3.  ``vrf``
                # context wins by precedence; if both are seen
                # (extremely unusual — same name as both an L3
                # VRF and a MAC-VRF binding), keep the first
                # type and merge RD/RTs.
                current_ri = existing
                if (
                    existing.instance_type == "vrf"
                    and not existing.route_distinguisher
                    and not existing.rt_imports
                    and not existing.rt_exports
                ):
                    # Empty placeholder — safe to upgrade.
                    existing.instance_type = "mac-vrf"
            continue
        if current_ri is None:
            continue
        # Deeper indent = sub-command of ``vrf <name>`` or
        # ``vlan <N>``.
        if leading_spaces < 6:
            # Back up to router-bgp top-level — close context.
            current_ri = None
            continue
        if stripped.startswith("rd "):
            parts = stripped.split(None, 1)
            if len(parts) >= 2:
                current_ri.route_distinguisher = parts[1].strip()
            continue
        if stripped.startswith("route-target both "):
            rt = stripped.split(None, 2)[2].strip()
            if rt not in current_ri.rt_imports:
                current_ri.rt_imports.append(rt)
            if rt not in current_ri.rt_exports:
                current_ri.rt_exports.append(rt)
            continue
        if stripped.startswith("route-target import "):
            rt = stripped.split(None, 2)[2].strip()
            # EOS also has ``route-target import evpn <rt>`` inside
            # ``router bgp / vrf <name>`` stanzas — the ``evpn``
            # keyword is just marking the address-family; the
            # actual RT follows.  Strip the ``evpn `` prefix.
            if rt.startswith("evpn "):
                rt = rt[len("evpn "):].strip()
            if rt and rt not in current_ri.rt_imports:
                current_ri.rt_imports.append(rt)
            continue
        if stripped.startswith("route-target export "):
            rt = stripped.split(None, 2)[2].strip()
            if rt.startswith("evpn "):
                rt = rt[len("evpn "):].strip()
            if rt and rt not in current_ri.rt_exports:
                current_ri.rt_exports.append(rt)
            continue
        # ``redistribute learned`` / ``redistribute connected`` —
        # parse-and-ignore.  Future enrichment under
        # CanonicalRoutingInstance.redistribute_*.


def _apply_iface_subcommand(
    iface: CanonicalInterface,
    line: str,
    lag_members: dict[int, list[str]],
    intent: CanonicalIntent,
    vxlan_state: dict[str, Any] | None = None,
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
    if line.startswith("ipv6 address "):
        # GAP-EVPN-3: ``ipv6 address 2001:db8::1/64`` (global) or
        # ``ipv6 address fe80::1 link-local`` (explicit link-local).
        # The link-local form is keyword-tagged on EOS and Cisco
        # IOS-XE; we normalise the canonical ``scope`` enum here.
        tail = line.split(None, 2)[2].strip()
        tokens = tail.split()
        if not tokens:
            return
        addr = tokens[0]
        scope = "global"
        if len(tokens) >= 2 and tokens[1].lower() == "link-local":
            scope = "link-local"
        if "/" in addr:
            ip, prefix = addr.split("/", 1)
            try:
                iface.ipv6_addresses.append(CanonicalIPv6Address(
                    ip=ip,
                    prefix_length=int(prefix),
                    scope=scope,
                ))
            except ValueError:
                pass
        elif scope == "link-local":
            # ``ipv6 address fe80::1 link-local`` (no /N) — EOS
            # accepts a bare link-local address with implicit /64
            # in the fe80::/10 block.  Store the literal /64 as
            # the canonical default.
            try:
                iface.ipv6_addresses.append(CanonicalIPv6Address(
                    ip=addr,
                    prefix_length=64,
                    scope="link-local",
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
    if line.startswith("switchport trunk native vlan "):
        # Phase 4b Wave 7c-C: ``switchport trunk native vlan <N>``.
        # Symmetric with the Cisco IOS-XE / Arista render emit;
        # without parse symmetry, a Cisco→Arista round-trip flips
        # native-tagged ports from untagged_ports back into
        # tagged_ports under :func:`project_switchport_to_vlan`.
        # Arista EOS accepts the same syntax as Cisco IOS-XE here
        # (Arista EOS User Manual, "Switchport Configuration").
        try:
            iface.trunk_native_vlan = int(line.split()[-1])
            iface.switchport_mode = "trunk"
        except ValueError:
            pass
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
        # GAP-EVPN-2: ``vxlan source-interface <NAME>`` is a
        # switch-level setting that applies to every VNI emitted
        # from this stanza.  Capture into vxlan_state; the parse-
        # walk's post-pass stamps the value onto each record.
        m = re.match(r"^vxlan\s+source-interface\s+(\S+)\s*$", line)
        if m and vxlan_state is not None:
            vxlan_state["source_interface"] = m.group(1)
            # Back-patch any VNI records that were already emitted
            # before the source-interface line (rare; supports
            # operator orderings that put mappings before globals).
            for rec in vxlan_state.get("records", []):
                if not rec.source_interface:
                    rec.source_interface = m.group(1)
            return
        # GAP-EVPN-2: ``vxlan udp-port <N>`` — switch-level.
        m = re.match(r"^vxlan\s+udp-port\s+(\d+)\s*$", line)
        if m and vxlan_state is not None:
            try:
                port = int(m.group(1))
            except ValueError:
                return
            vxlan_state["udp_port"] = port
            for rec in vxlan_state.get("records", []):
                if rec.udp_port == 4789:
                    rec.udp_port = port
            return
        # ``vxlan vlan <vid> vni <vni>``
        m = re.match(r"^vxlan\s+vlan\s+(\d+)\s+vni\s+(\d+)\s*$", line)
        if m:
            try:
                vid = int(m.group(1))
                vni = int(m.group(2))
            except ValueError:
                return
            rec = CanonicalVxlan(
                vlan_id=vid,
                vni=vni,
                source_interface=(
                    vxlan_state["source_interface"]
                    if vxlan_state else ""
                ),
                udp_port=(
                    vxlan_state["udp_port"]
                    if vxlan_state else 4789
                ),
            )
            intent.vxlan_vnis.append(rec)
            if vxlan_state is not None:
                vxlan_state["records"].append(rec)
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
        # Other ``vxlan virtual-router`` / ``vxlan flood vtep`` lines
        # fall through to parse-and-ignore — vendor-native details
        # we don't model cross-vendor today.
    # Unrecognised sub-command — parse-and-ignore.


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
