"""
Parse path for Cisco NX-OS (``show running-config`` form).

Public function: :func:`parse_intent` — raw text in,
:class:`CanonicalIntent` out.  Targets the Nexus 3000 / 5000 / 7000 /
9000 series on NX-OS 9.x / 10.x.

Note: probe is in :mod:`.codec`; this module assumes input has already
been classified as Cisco NX-OS CLI.

Phase 1 surface (see ``docs/v0.2.0-planning/03-nxos-codec/``):

* ``hostname <name>`` → :attr:`CanonicalIntent.hostname`.
* ``version <N.N(N)> Bios:version`` → :attr:`CanonicalIntent.source_version`
  (metadata only; the banner line itself is synthesised on render).
* ``vrf context <name>`` (top-level) → :class:`CanonicalRoutingInstance`
  (name + description only; ``rd`` / ``route-target`` / ``vni`` are
  Phase 3 / Phase 4 and parse-and-ignore here).
* ``interface <name>`` blocks → :class:`CanonicalInterface` carrying
  ``description`` / ``shutdown`` / ``mtu`` / ``ip address X/N`` (CIDR) /
  ``ipv6 address X/N`` / ``vrf member <name>``.
* top-level ``vlan <id-list>`` (comma + range form) and ``vlan N / name
  <text>`` → :class:`CanonicalVlan`, plus SVI synthesis.
* top-level ``ip route <dest>/<prefix> <gw> [<pref>]`` (default VRF only)
  → :class:`CanonicalStaticRoute`.

Deliberately NOT parsed in Phase 1 (declared ``unsupported`` in the
capability matrix — they land in later phases): switchport / L2 mode,
LAGs, SNMP, local users, per-VRF static routes, VRF RD/RT, VXLAN-EVPN.
``feature`` / ``vdc`` / ``boot`` / ``line`` lines are discarded on parse
and re-synthesised on render (the matrix declares the cosmetic loss).

Where this codec diverges from ``cisco_iosxe_cli`` (see
``02-codec-architecture.md`` § 14):

* IP addresses are **CIDR only** (``ip address X/N``), never dotted mask.
* VRF stanza keyword is ``vrf context`` (not ``vrf definition``).
* Per-interface VRF bind is ``vrf member`` (not ``vrf forwarding``).
* Physical ports are uniform ``Ethernet<slot>/<port>`` — no speed prefix.
"""

from __future__ import annotations

import ipaddress
import logging
import re

from ...canonical.intent import (
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
    CanonicalLocalUser,
    CanonicalRoutingInstance,
    CanonicalSNMP,
    CanonicalSNMPv3User,
    CanonicalStaticRoute,
    CanonicalVlan,
    CanonicalVRRPGroup,
)
from .._input_shape import detect_input_shape
from ..base import ParseError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex constants — module-level so they compile once per import.
# Shapes lifted from cisco_iosxe_cli/parse.py; the IP / VRF families
# diverge per NX-OS grammar (see module docstring).
# ---------------------------------------------------------------------------

_HOSTNAME_RE = re.compile(r"^hostname\s+(\S+)", re.IGNORECASE | re.MULTILINE)
#: ``version 9.2(3) Bios:version`` / ``version 10.3(9)`` — first token
#: after ``version`` is the NX-OS release string.
_VERSION_RE = re.compile(r"^version\s+(\S+)", re.IGNORECASE | re.MULTILINE)

_IFACE_RE = re.compile(r"^interface\s+(\S+)", re.IGNORECASE)
_DESC_RE = re.compile(r"^\s+description\s+(.+)", re.IGNORECASE)
_SHUTDOWN_RE = re.compile(r"^\s+shutdown\s*$", re.IGNORECASE)
_NO_SHUTDOWN_RE = re.compile(r"^\s+no\s+shutdown\s*$", re.IGNORECASE)
_MTU_RE = re.compile(r"^\s+mtu\s+(\d+)\s*$", re.IGNORECASE)
#: ``ip address 10.10.10.1/24`` — CIDR form, NEVER dotted mask.  The
#: optional ``secondary`` trailer is consumed but not modelled in Phase 1.
_IP_CIDR_RE = re.compile(
    r"^\s+ip\s+address\s+(\d+\.\d+\.\d+\.\d+)/(\d+)(?:\s+(secondary))?",
    re.IGNORECASE,
)
#: ``ipv6 address 2001:db8::1/64`` — CIDR form.  Optional ``link-local``
#: trailer tags scope explicitly; fe80::/10 prefix infers it otherwise.
_IPV6_CIDR_RE = re.compile(
    r"^\s+ipv6\s+address\s+(\S+?)/(\d+)(?:\s+(link-local))?\s*$",
    re.IGNORECASE,
)
#: ``vrf member <name>`` inside an interface stanza (NX-OS form of
#: IOS-XE's ``vrf forwarding``).
_VRF_MEMBER_RE = re.compile(r"^\s+vrf\s+member\s+(\S+)\s*$", re.IGNORECASE)

# ── L2 switchport grammar (Phase 2) ──
# NX-OS Ethernet / port-channel ports default to L2 switchport; a routed
# port requires an explicit ``no switchport``.  Mirrors arista_eos's
# render-decides model: set ``switchport_mode`` only on explicit
# mode/access/trunk lines, leave it ``None`` otherwise, and let render
# emit ``no switchport`` for a physical/LAG port that carries an IP.
# ``no switchport`` is consumed (it marks the port routed) but sets no
# canonical field — ``switchport_mode=None`` already means "routed".
_NO_SWITCHPORT_RE = re.compile(r"^\s+no\s+switchport\s*$", re.IGNORECASE)
_SWITCHPORT_MODE_RE = re.compile(
    r"^\s+switchport\s+mode\s+(\S+)", re.IGNORECASE,
)
_SWITCHPORT_ACCESS_RE = re.compile(
    r"^\s+switchport\s+access\s+vlan\s+(\d+)", re.IGNORECASE,
)
_SWITCHPORT_TRUNK_ALLOWED_RE = re.compile(
    r"^\s+switchport\s+trunk\s+allowed\s+vlan\s+(.+)", re.IGNORECASE,
)
_SWITCHPORT_TRUNK_NATIVE_RE = re.compile(
    r"^\s+switchport\s+trunk\s+native\s+vlan\s+(\d+)", re.IGNORECASE,
)
# ``channel-group N mode active|passive|on`` declares the port a member
# of ``port-channelN``.  NX-OS mode vocab → canonical LAG modes
# (``on`` is static aggregation).
_CHANNEL_GROUP_RE = re.compile(
    r"^\s+channel-group\s+(\d+)\s+mode\s+(\S+)", re.IGNORECASE,
)
_NXOS_LAG_MODE_MAP = {"active": "active", "passive": "passive", "on": "static"}

# ── HSRP (Phase 2c) ──
# NX-OS HSRP is a nested block under an L3 interface:
#   interface Vlan10
#     hsrp version 2          (interface-level; not modelled)
#     hsrp 10                 (2-indent — opens a group)
#       ip 10.10.10.254       (4-indent — group sub-commands)
#       priority 110
#       preempt
# Maps to CanonicalVRRPGroup(mode="hsrp").  NX-OS HSRP defaults preempt
# DISABLED (unlike VRRP), so the scratch default is preempt=False.
_HSRP_GROUP_RE = re.compile(r"^\s+hsrp\s+(\d+)\s*$", re.IGNORECASE)
_HSRP_VERSION_RE = re.compile(r"^\s+hsrp\s+version\s+\d+\s*$", re.IGNORECASE)
_HSRP_IP_RE = re.compile(r"^\s+ip\s+(\d+\.\d+\.\d+\.\d+)\s*$", re.IGNORECASE)
_HSRP_PRIORITY_RE = re.compile(r"^\s+priority\s+(\d+)\s*$", re.IGNORECASE)
_HSRP_PREEMPT_RE = re.compile(r"^\s+(no\s+)?preempt\b", re.IGNORECASE)
_HSRP_AUTH_MD5_RE = re.compile(
    r"^\s+authentication\s+md5\s+key-string\s+(\S+)", re.IGNORECASE,
)
_HSRP_AUTH_TEXT_RE = re.compile(
    r"^\s+authentication\s+text\s+(\S+)", re.IGNORECASE,
)

# ── SNMP + local users (Phase 2b) ──
_SNMP_COMMUNITY_RE = re.compile(
    r"^snmp-server\s+community\s+(\S+)", re.IGNORECASE | re.MULTILINE,
)
_SNMP_LOCATION_RE = re.compile(
    r"^snmp-server\s+location\s+(.+)$", re.IGNORECASE | re.MULTILINE,
)
_SNMP_CONTACT_RE = re.compile(
    r"^snmp-server\s+contact\s+(.+)$", re.IGNORECASE | re.MULTILINE,
)
_SNMP_HOST_RE = re.compile(
    r"^snmp-server\s+host\s+(\d+\.\d+\.\d+\.\d+)",
    re.IGNORECASE | re.MULTILINE,
)
# NX-OS SNMPv3 USM user:
#   snmp-server user <name> [<group>] auth <proto> <key>
#       [priv <proto> <key>] [localized[V2]key] [engineID <id>]
# Keys are 0x-prefixed localized digests on the wire — preserved
# verbatim.  ``priv`` is optional (auth-no-priv users); ``localizedV2key``
# (NX-OS 10.x digest) is detected but not modelled — render always emits
# the older ``localizedkey`` form (declared lossy).
_SNMP_V3_USER_RE = re.compile(
    r"^snmp-server\s+user\s+(\S+)(?:\s+(\S+))?"
    r"\s+auth\s+(md5|sha|sha224|sha256|sha384|sha512)\s+(\S+)"
    r"(?:\s+priv\s+(\S+)\s+(\S+))?"
    r"(?:\s+localized(V2)?key)?"
    r"(?:\s+engineID\s+(\S+))?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# ``username <name> password <type> <hash> role <role>``.  NX-OS uses a
# named ``role`` (network-admin / network-operator / custom) rather than
# a numeric privilege level.
_USERNAME_RE = re.compile(
    r"^username\s+(\S+)\s+password\s+(\d+)\s+(\S+)\s+role\s+(\S+)",
    re.IGNORECASE,
)
#: NX-OS roles that map to the cross-vendor admin privilege (15).
_NXOS_ADMIN_ROLES = {"network-admin", "vdc-admin"}


def _normalise_priv_proto(proto: str | None) -> str:
    """NX-OS privacy-cipher token -> canonical short form.

    ``aes-128`` -> ``aes128`` (strip the hyphen); ``des`` / ``3des``
    pass through lower-cased.  Empty for auth-no-priv users.
    """
    if not proto:
        return ""
    return proto.lower().replace("-", "")
#: ``vrf context <name>`` opens a top-level VRF stanza.
_VRF_CONTEXT_RE = re.compile(r"^vrf\s+context\s+(\S+)\s*$", re.IGNORECASE)
_VRF_DESCRIPTION_RE = re.compile(r"^\s+description\s+(.+)$", re.IGNORECASE)
#: ``vlan 1,10,2000`` / ``vlan 10-20`` — comma + range list (unique to
#: NX-OS / Arista in this codebase).
_VLAN_TOP_RE = re.compile(r"^vlan\s+([\d,\-]+)\s*$", re.IGNORECASE)
_VLAN_NAME_RE = re.compile(r"^\s+name\s+(.+)", re.IGNORECASE)
#: ``ip route 0.0.0.0/0 10.0.0.2 [<pref>]`` — top-level (default VRF)
#: static route.  Per-VRF routes (indented inside ``vrf context``) do
#: NOT match this top-level anchor and are deferred to Phase 3.
_STATIC_ROUTE_RE = re.compile(
    r"^ip\s+route\s+(\d+\.\d+\.\d+\.\d+)/(\d+)\s+(\S+)(?:\s+(\d+))?",
    re.IGNORECASE,
)
_SVI_NAME_RE = re.compile(r"^Vlan(\d+)$", re.IGNORECASE)

#: Interface-name prefix → IANA ifType hint.  NX-OS uses a single
#: ``Ethernet`` prefix for every speed.
_TYPE_HINTS: tuple[tuple[str, str], ...] = (
    ("ethernet", "ianaift:ethernetCsmacd"),
    ("loopback", "ianaift:softwareLoopback"),
    ("vlan", "ianaift:l3ipvlan"),
    ("port-channel", "ianaift:ieee8023adLag"),
    ("nve", "ianaift:tunnel"),
    ("mgmt", "ianaift:ethernetCsmacd"),
)

#: A VRF whose name matches this heuristic is the device's management
#: (OOBM) VRF.  NX-OS convention is the literal ``management`` VRF;
#: ``mgmt`` / ``management`` are accepted case-insensitively.
_MGMT_VRF_RE = re.compile(r"^(?:management|mgmt)$", re.IGNORECASE)


def _infer_type(iface_name: str) -> str:
    """Best-effort IANA ifType from the NX-OS interface-name prefix."""
    lower = iface_name.lower()
    for prefix, iftype in _TYPE_HINTS:
        if lower.startswith(prefix):
            return iftype
    return "ianaift:other"


def _is_link_local_v6(addr: str) -> bool:
    """Return True iff *addr* is in the IPv6 link-local prefix fe80::/10.

    Mirrors ``cisco_iosxe_cli.parse._is_link_local_v6`` — the prefix is
    vendor-neutral (RFC 4291 §2.4), so scope can be recovered even when
    the operator omits the ``link-local`` keyword.
    """
    if not addr:
        return False
    lo = addr.lower()
    return len(lo) >= 3 and lo[:2] == "fe" and lo[2] in ("8", "9", "a", "b")


def _is_mgmt_vrf(vrf_name: str) -> bool:
    """Return True when *vrf_name* is the NX-OS management VRF."""
    return bool(_MGMT_VRF_RE.match(vrf_name or ""))


def parse_intent(raw: str) -> CanonicalIntent:
    """Parse NX-OS ``show running-config`` output into a
    :class:`CanonicalIntent`.

    Raises:
        ParseError: If the input is empty or looks like XML / JSON
            rather than NX-OS CLI text.
    """
    if not raw.strip():
        raise ParseError("cisco_nxos: empty input", snippet="")

    # Shape sanity: reject XML / JSON early so the operator gets a clean
    # error instead of a near-empty render.  Mirrors cisco_iosxe_cli.
    shape = detect_input_shape(raw)
    if shape is not None:
        raise ParseError(
            f"cisco_nxos: input looks like {shape.upper()}, not NX-OS "
            f"CLI.  Paste the output of `show running-config`.",
            snippet=raw.lstrip()[:120],
        )

    intent = CanonicalIntent(
        source_vendor="cisco_nxos",
        source_format="cli-nxos",
    )

    intent.hostname = _extract_hostname(raw)
    intent.source_version = _extract_version(raw)

    # VRF declarations (``vrf context <name>`` top-level stanzas).
    # Phase 1 harvests name + description only; rd / route-target / vni
    # land in later phases.  Per-interface ``vrf member`` membership is
    # set by :func:`_parse_interfaces`.
    intent.routing_instances = _parse_routing_instances(raw)

    intent.interfaces = _parse_interfaces(raw)

    intent.vlans = _parse_vlans(raw)
    # Derive VLAN records from ``interface Vlan<N>`` SVIs that had no
    # matching top-level ``vlan`` stanza — same fix as iosxe_cli to
    # avoid silently dropping the SVI's L3 config on VLAN-centric
    # downstream codecs.
    _synthesize_vlans_from_svis(intent)

    # Static routes — top-level (default VRF) only in Phase 1.  Per-VRF
    # routes embedded in ``vrf context`` blocks are deferred to Phase 3
    # (declared unsupported).
    intent.static_routes = _parse_static_routes(raw)

    # LAGs (Phase 2) — both the ``interface port-channelN`` declaration
    # and per-member ``channel-group N mode M`` lines contribute.
    intent.lags = _parse_lags(raw)

    # SNMP (Phase 2b) — v2c community + v3 USM users.
    intent.snmp = _parse_snmp(raw)

    # Local users (Phase 2b) — ``username ... role <role>``.
    intent.local_users = _parse_local_users(raw)

    # Shared switchport→VLAN projection: mirror per-port switchport state
    # into the VLAN-centric tagged/untagged lists so VLAN-centric
    # renderers can emit the membership.  The phantom-VLAN guard
    # (snapshot legitimate VLAN ids before, prune after) mirrors
    # iosxe_cli — a wide ``switchport trunk allowed`` range must not
    # inflate tree.vlans with thousands of phantom records.
    legitimate_vlan_ids = {v.id for v in intent.vlans}
    from ...canonical.transforms import project_switchport_to_vlan
    project_switchport_to_vlan(intent)
    intent.vlans = [v for v in intent.vlans if v.id in legitimate_vlan_ids]

    logger.debug(
        "cisco_nxos parsed: hostname=%r ifaces=%d vlans=%d routes=%d "
        "vrfs=%d (input=%d chars)",
        intent.hostname,
        len(intent.interfaces),
        len(intent.vlans),
        len(intent.static_routes),
        len(intent.routing_instances),
        len(raw),
    )
    return intent


def _extract_hostname(raw: str) -> str:
    m = _HOSTNAME_RE.search(raw)
    return m.group(1) if m else ""


def _extract_version(raw: str) -> str:
    """Return the NX-OS release string from the ``version`` line.

    Stored as :attr:`CanonicalIntent.source_version` (metadata).  The
    render path synthesises a fresh banner rather than echoing this, so
    it is informational only.
    """
    m = _VERSION_RE.search(raw)
    return m.group(1) if m else ""


def _parse_routing_instances(raw: str) -> list[CanonicalRoutingInstance]:
    """Extract ``vrf context <name>`` blocks (name + description only).

    A NX-OS VRF stanza looks like::

        vrf context TENANT-A
          description tenant a
          vni 10001                       ← Phase 4 (ignored)
          rd auto                         ← Phase 3 (ignored)
          address-family ipv4 unicast     ← Phase 3 (ignored)
            route-target both auto evpn   ← Phase 3 (ignored)

    Phase 1 harvests ``name`` + ``description``.  Everything else inside
    the block is parse-and-ignore (declared unsupported in the matrix).
    Block-walker pattern mirrors ``cisco_iosxe_cli`` — open on the header
    regex, absorb indented sub-lines, close on the first non-indented
    line.
    """
    instances: list[CanonicalRoutingInstance] = []
    current: CanonicalRoutingInstance | None = None

    for line in raw.splitlines():
        header = _VRF_CONTEXT_RE.match(line)
        if header:
            if current is not None:
                instances.append(current)
            current = CanonicalRoutingInstance(name=header.group(1))
            continue

        if current is None:
            continue

        # Stanza terminator: any non-indented line (a sibling top-level
        # stanza).  NX-OS does not bracket VRF blocks with ``!``.
        if line and not line[0].isspace():
            instances.append(current)
            current = None
            # Fall through is unnecessary — a top-level line that opens a
            # new vrf context is re-matched on the next iteration; but we
            # already consumed it, so re-check the header here.
            header = _VRF_CONTEXT_RE.match(line)
            if header:
                current = CanonicalRoutingInstance(name=header.group(1))
            continue

        dm = _VRF_DESCRIPTION_RE.match(line)
        if dm:
            current.description = dm.group(1).strip()
            continue
        # rd / route-target / vni / address-family — Phase 3/4; ignore.

    if current is not None:
        instances.append(current)
    return instances


def _new_iface_scratch(name: str) -> dict:
    """Fresh per-interface parse-time scratch dict.

    Single source of truth for the field set so the two stanza-open
    sites in :func:`_parse_interfaces` can't drift apart.
    """
    return {
        "name": name,
        "description": "",
        "enabled": True,
        "type": _infer_type(name),
        "mtu": None,
        "ipv4": [],
        "ipv6": [],
        "vrf": "",
        "kind": "",
        "switchport_mode": None,
        "access_vlan": None,
        "trunk_allowed": [],
        "trunk_native": None,
        "lag_member_of": None,
        # HSRP (Phase 2c): {gid: {virtual_ips, priority, preempt, auth}}.
        "hsrp_groups": {},
        "_hsrp_gid": None,   # active group while inside an ``hsrp N`` block
    }


def _parse_interfaces(raw: str) -> list[CanonicalInterface]:
    """Extract ``interface <name>`` stanzas from NX-OS config text.

    Per interface: description, enabled (shutdown / no shutdown), mtu,
    IPv4 (CIDR), IPv6 (CIDR + scope), VRF membership (``vrf member``),
    and (Phase 2) L2 switchport state (mode / access-vlan / trunk-allowed
    / trunk-native) + LAG membership (``channel-group``).  The
    management-VRF heuristic promotes a physical-named port bound to the
    ``management`` VRF to ``kind="mgmt"`` (mgmt0 already classifies mgmt
    by name).
    """
    lines = raw.splitlines()
    interfaces: list[CanonicalInterface] = []
    current: dict | None = None

    def _flush() -> None:
        if current is not None:
            interfaces.append(_build_canonical_interface(current))

    for line in lines:
        m = _IFACE_RE.match(line)
        if m:
            _flush()
            current = _new_iface_scratch(m.group(1))
            continue

        if current is None:
            continue

        # Non-indented line closes the current stanza.
        if line and not line[0].isspace():
            _flush()
            current = None
            # The closing line might itself open a new interface.
            m = _IFACE_RE.match(line)
            if m:
                current = _new_iface_scratch(m.group(1))
            continue

        # ── HSRP nested block (Phase 2c) ──
        # ``hsrp <N>`` opens a group; its sub-commands are further-indented
        # (>= 4 spaces).  Any shallower indented line ends the block.
        hg = _HSRP_GROUP_RE.match(line)
        if hg:
            gid = int(hg.group(1))
            current["hsrp_groups"].setdefault(gid, {
                "virtual_ips": [],
                "priority": 100,
                "preempt": False,   # NX-OS HSRP default: preempt disabled
                "authentication": "",
            })
            current["_hsrp_gid"] = gid
            continue
        if _HSRP_VERSION_RE.match(line):
            # ``hsrp version 2`` is interface-level; not modelled.
            current["_hsrp_gid"] = None
            continue
        _gid = current["_hsrp_gid"]
        if _gid is not None and (len(line) - len(line.lstrip())) >= 4:
            g = current["hsrp_groups"][_gid]
            him = _HSRP_IP_RE.match(line)
            if him:
                g["virtual_ips"].append(him.group(1))
                continue
            hpm = _HSRP_PRIORITY_RE.match(line)
            if hpm:
                g["priority"] = int(hpm.group(1))
                continue
            hpe = _HSRP_PREEMPT_RE.match(line)
            if hpe:
                g["preempt"] = not bool(hpe.group(1))   # ``no preempt`` -> False
                continue
            ham = _HSRP_AUTH_MD5_RE.match(line)
            if ham:
                g["authentication"] = f"md5:{ham.group(1)}"
                continue
            hat = _HSRP_AUTH_TEXT_RE.match(line)
            if hat:
                g["authentication"] = f"plain:{hat.group(1)}"
                continue
            # Unknown hsrp sub-command (timers / mac-address / track) —
            # consume it; still inside the group block.
            continue
        # Any other indented line ends the active hsrp group block.
        current["_hsrp_gid"] = None

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

        mm = _MTU_RE.match(line)
        if mm:
            try:
                current["mtu"] = int(mm.group(1))
            except ValueError:
                pass
            continue

        im = _IP_CIDR_RE.match(line)
        if im:
            try:
                current["ipv4"].append({
                    "ip": im.group(1),
                    "prefix_length": int(im.group(2)),
                    "is_secondary": im.group(3) is not None,
                })
            except ValueError:
                pass
            continue

        v6m = _IPV6_CIDR_RE.match(line)
        if v6m:
            addr = v6m.group(1)
            keyword_ll = v6m.group(3)
            try:
                scope = (
                    "link-local"
                    if (keyword_ll or _is_link_local_v6(addr))
                    else "global"
                )
                current["ipv6"].append({
                    "ip": addr,
                    "prefix_length": int(v6m.group(2)),
                    "scope": scope,
                })
            except ValueError:
                pass
            continue

        vm = _VRF_MEMBER_RE.match(line)
        if vm:
            current["vrf"] = vm.group(1)
            continue

        # ── L2 switchport (Phase 2) ──
        if _NO_SWITCHPORT_RE.match(line):
            # Routed port — leave switchport_mode None (render emits
            # ``no switchport`` for a physical/LAG port carrying an IP).
            continue
        sm = _SWITCHPORT_MODE_RE.match(line)
        if sm:
            current["switchport_mode"] = sm.group(1).lower()
            continue
        am = _SWITCHPORT_ACCESS_RE.match(line)
        if am:
            current["switchport_mode"] = current["switchport_mode"] or "access"
            current["access_vlan"] = int(am.group(1))
            continue
        tam = _SWITCHPORT_TRUNK_ALLOWED_RE.match(line)
        if tam:
            current["switchport_mode"] = current["switchport_mode"] or "trunk"
            current["trunk_allowed"] = _parse_vlan_list(tam.group(1).strip())
            continue
        tnm = _SWITCHPORT_TRUNK_NATIVE_RE.match(line)
        if tnm:
            current["switchport_mode"] = current["switchport_mode"] or "trunk"
            current["trunk_native"] = int(tnm.group(1))
            continue

        cgm = _CHANNEL_GROUP_RE.match(line)
        if cgm:
            current["lag_member_of"] = f"port-channel{int(cgm.group(1))}"
            continue

    _flush()
    return interfaces


def _build_canonical_interface(raw: dict) -> CanonicalInterface:
    """Convert the parse-time scratch dict into a CanonicalInterface."""
    name = raw["name"]
    vrf = raw.get("vrf", "")
    kind = raw.get("kind", "")

    # Management-VRF cascade: a physical-named port bound to the
    # ``management`` VRF is semantically the OOBM port.  mgmt0 already
    # classifies as kind="mgmt" by name, so only promote when the name
    # alone would classify as "physical".  Mirrors iosxe_cli.
    if not kind and _is_mgmt_vrf(vrf):
        from . import port_names as _port_names
        ident = _port_names.classify_port_name(name)
        if ident.kind == "physical":
            kind = "mgmt"

    # HSRP groups (Phase 2c) -> CanonicalVRRPGroup(mode="hsrp"), sorted by
    # group id for deterministic ordering (the round-trip invariant does
    # not normalise vrrp_groups order).
    vrrp_groups = [
        CanonicalVRRPGroup(
            group_id=gid,
            mode="hsrp",
            virtual_ips=list(g.get("virtual_ips", [])),
            priority=g.get("priority", 100),
            preempt=g.get("preempt", False),
            authentication=g.get("authentication", ""),
        )
        for gid, g in sorted(raw.get("hsrp_groups", {}).items())
    ]

    return CanonicalInterface(
        name=name,
        description=raw.get("description", ""),
        enabled=raw.get("enabled", True),
        interface_type=raw.get("type", ""),
        mtu=raw.get("mtu"),
        ipv4_addresses=[
            CanonicalIPv4Address(
                ip=a["ip"],
                prefix_length=a["prefix_length"],
                is_secondary=a.get("is_secondary", False),
            )
            for a in raw.get("ipv4", [])
        ],
        ipv6_addresses=[
            CanonicalIPv6Address(
                ip=a["ip"],
                prefix_length=a["prefix_length"],
                scope=a.get("scope", "global"),
            )
            for a in raw.get("ipv6", [])
        ],
        vrf=vrf,
        kind=kind,
        switchport_mode=raw.get("switchport_mode"),
        access_vlan=raw.get("access_vlan"),
        trunk_allowed_vlans=raw.get("trunk_allowed", []),
        trunk_native_vlan=raw.get("trunk_native"),
        lag_member_of=raw.get("lag_member_of"),
        vrrp_groups=vrrp_groups,
    )


def _lag_sort_key(name: str) -> tuple[int, int]:
    """Stable sort key grouping ``port-channel<N>`` numerically."""
    m = re.match(r"^port-channel(\d+)$", name, re.IGNORECASE)
    return (0, int(m.group(1))) if m else (1, 0)


def _parse_lags(raw: str) -> list[CanonicalLAG]:
    """Build :class:`CanonicalLAG` records from NX-OS config.

    Two signals, either sufficient (mirrors cisco_iosxe_cli):
      * an ``interface port-channel<N>`` stanza declares the LAG exists;
      * a ``channel-group <N> mode <m>`` line under a physical port
        declares that port a member of ``port-channel<N>``.

    Mode is the first member's mode (NX-OS ``on`` → canonical
    ``static``); an empty LAG keeps :attr:`CanonicalLAG.mode` default.
    """
    members_by_lag: dict[str, list[str]] = {}
    mode_by_lag: dict[str, str] = {}
    declared: set[str] = set()
    current_iface: str | None = None

    def _note_header(name: str) -> None:
        if name.lower().startswith("port-channel"):
            declared.add(name)

    for line in raw.splitlines():
        m = _IFACE_RE.match(line)
        if m:
            current_iface = m.group(1)
            _note_header(current_iface)
            continue
        if current_iface is None:
            continue
        if line and not line[0].isspace():
            current_iface = None
            m = _IFACE_RE.match(line)
            if m:
                current_iface = m.group(1)
                _note_header(current_iface)
            continue
        cgm = _CHANNEL_GROUP_RE.match(line)
        if cgm:
            lag_name = f"port-channel{int(cgm.group(1))}"
            mode = _NXOS_LAG_MODE_MAP.get(cgm.group(2).lower(), "active")
            members = members_by_lag.setdefault(lag_name, [])
            if current_iface and current_iface not in members:
                members.append(current_iface)
            mode_by_lag.setdefault(lag_name, mode)

    lags: list[CanonicalLAG] = []
    for lag_name in sorted(declared | set(members_by_lag), key=_lag_sort_key):
        lag = CanonicalLAG(
            name=lag_name, members=list(members_by_lag.get(lag_name, [])),
        )
        if lag_name in mode_by_lag:
            lag.mode = mode_by_lag[lag_name]
        lags.append(lag)
    return lags


def _parse_vlan_list(text: str) -> list[int]:
    """Parse an NX-OS VLAN id-list like ``1,10,2000`` or ``10-20`` into a
    flat list of ints.  Ranges are expanded inclusively."""
    result: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            try:
                result.extend(range(int(lo.strip()), int(hi.strip()) + 1))
            except ValueError:
                continue
        elif part.isdigit():
            result.append(int(part))
    return result


def _parse_vlans(raw: str) -> list[CanonicalVlan]:
    """Extract VLAN definitions from NX-OS config text.

    NX-OS declares VLANs two ways, often both in one config:

    1. A bare id-list line: ``vlan 1,10,2000`` / ``vlan 10-20`` (declares
       the VLANs exist; no per-VLAN body).
    2. A single-id stanza with a name: ``vlan 10 / name PROD``.

    Both feed the same :class:`CanonicalVlan` set, de-duplicated by id.
    A named single-id stanza wins the ``name`` for its id.
    """
    vlans_by_id: dict[int, CanonicalVlan] = {}
    order: list[int] = []

    def _touch(vid: int) -> CanonicalVlan:
        v = vlans_by_id.get(vid)
        if v is None:
            v = CanonicalVlan(id=vid, name="")
            vlans_by_id[vid] = v
            order.append(vid)
        return v

    lines = raw.splitlines()
    current_id: int | None = None

    for line in lines:
        tm = _VLAN_TOP_RE.match(line)
        if tm:
            ids = _parse_vlan_list(tm.group(1))
            for vid in ids:
                if 1 <= vid <= 4094:
                    _touch(vid)
            # A single-id ``vlan N`` line opens a stanza whose indented
            # ``name`` sub-command (if any) applies to N.
            current_id = ids[0] if len(ids) == 1 else None
            continue

        if current_id is not None:
            nm = _VLAN_NAME_RE.match(line)
            if nm:
                _touch(current_id).name = nm.group(1).strip()
                continue
            # Any non-indented line closes the stanza.
            if line and not line[0].isspace():
                current_id = None

    return [vlans_by_id[vid] for vid in order]


def _synthesize_vlans_from_svis(intent: CanonicalIntent) -> None:
    """Derive VLAN records from ``interface Vlan<N>`` SVIs.

    Mirrors ``cisco_iosxe_cli._synthesize_vlans_from_svis``: an SVI whose
    VLAN has no top-level ``vlan`` stanza still implies the VLAN exists
    (and carries its L3 config), so create / merge a record.
    """
    existing_by_id: dict[int, CanonicalVlan] = {v.id: v for v in intent.vlans}
    for iface in intent.interfaces:
        m = _SVI_NAME_RE.match(iface.name)
        if not m:
            continue
        vid = int(m.group(1))
        if not (1 <= vid <= 4094):
            continue
        existing = existing_by_id.get(vid)
        if existing is None:
            synthesised = CanonicalVlan(
                id=vid,
                name=iface.description,
                ipv4_addresses=list(iface.ipv4_addresses),
            )
            intent.vlans.append(synthesised)
            existing_by_id[vid] = synthesised
            continue
        for addr in iface.ipv4_addresses:
            if addr not in existing.ipv4_addresses:
                existing.ipv4_addresses.append(addr)


def _parse_static_routes(raw: str) -> list[CanonicalStaticRoute]:
    """Extract top-level ``ip route`` lines (default VRF) from NX-OS text.

    NX-OS form: ``ip route <dest>/<prefix> <gw> [<pref>]``.  The trailing
    integer (if present) is the route preference / administrative
    distance and maps to :attr:`CanonicalStaticRoute.metric`.

    Per-VRF static routes (indented inside a ``vrf context`` block) do
    NOT match the top-level ``^ip route`` anchor and are deferred to
    Phase 3 (declared unsupported; requires no phantom routing-instance —
    see the per-VRF harvest memory).
    """
    routes: list[CanonicalStaticRoute] = []
    for line in raw.splitlines():
        m = _STATIC_ROUTE_RE.match(line)
        if not m:
            continue
        dest = f"{m.group(1)}/{m.group(2)}"
        gw_or_iface = m.group(3)
        metric = int(m.group(4)) if m.group(4) else 0
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
            metric=metric,
        ))
    return routes


def _parse_snmp(raw: str) -> CanonicalSNMP | None:
    """Extract SNMP config from NX-OS text (v2c community + v3 USM).

    Returns ``None`` when no ``snmp-server`` lines are present so the
    tree doesn't carry an empty stub.  Mirrors cisco_iosxe_cli
    conventions: privacy cipher normalised to the canonical short form,
    opaque keys preserved verbatim, location / contact quote-stripped.
    The ``engineID`` (NX-OS colon-decimal) is preserved verbatim for the
    same-vendor round-trip; it is declared lossy cross-vendor.
    """
    community_m = _SNMP_COMMUNITY_RE.search(raw)
    location_m = _SNMP_LOCATION_RE.search(raw)
    contact_m = _SNMP_CONTACT_RE.search(raw)
    hosts = _SNMP_HOST_RE.findall(raw)
    v3_matches = list(_SNMP_V3_USER_RE.finditer(raw))
    if not (community_m or location_m or contact_m or hosts or v3_matches):
        return None
    snmp = CanonicalSNMP()
    if community_m:
        snmp.community = community_m.group(1).strip()
    if location_m:
        snmp.location = location_m.group(1).strip().strip('"')
    if contact_m:
        snmp.contact = contact_m.group(1).strip().strip('"')
    snmp.trap_hosts = list(hosts)
    for m in v3_matches:
        name, group, auth_p, auth_pw, priv_p, priv_pw, _v2, eng = m.groups()
        snmp.v3_users.append(CanonicalSNMPv3User(
            name=name,
            group=group or "",
            auth_protocol=(auth_p or "").lower(),
            auth_passphrase=auth_pw or "",
            priv_protocol=_normalise_priv_proto(priv_p),
            priv_passphrase=priv_pw or "",
            engine_id=eng or "",
        ))
    return snmp


def _parse_local_users(raw: str) -> list[CanonicalLocalUser]:
    """Extract ``username <name> password <type> <hash> role <role>``.

    NX-OS uses a named ``role`` rather than a numeric privilege; we map
    ``network-admin`` / ``vdc-admin`` -> 15 and everything else -> 1
    (lossy — cross-vendor renderers expecting numeric privilege
    round-trip non-admin roles as 1).  The hash is preserved with its
    type-digit prefix (``5 $5$...``) so a same-vendor round-trip
    reconstructs the line; type 0 (the plaintext marker) is stored bare,
    mirroring cisco_iosxe_cli to avoid the ``password 0 0 X``
    double-prefix bug.
    """
    users: list[CanonicalLocalUser] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        m = _USERNAME_RE.match(line)
        if not m:
            continue
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        hash_type = m.group(2)
        payload = m.group(3)
        role = m.group(4)
        if hash_type and hash_type != "0":
            hashed = f"{hash_type} {payload}"
        else:
            hashed = payload
        users.append(CanonicalLocalUser(
            name=name,
            privilege_level=15 if role.lower() in _NXOS_ADMIN_ROLES else 1,
            hashed_password=hashed,
            role=role,
        ))
    return users
