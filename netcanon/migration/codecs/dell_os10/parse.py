"""
Parse path for Dell SmartFabric OS10 (``show running-configuration`` form).

Public function: :func:`parse_intent` — raw text in,
:class:`CanonicalIntent` out.  Targets OS10 10.5.x on the S-series
(S3048-ON / S4100 / S5200 / S5232F) and Z-series.

Note: probe lives in :mod:`.codec`; this module assumes the input has
already been classified as Dell OS10 CLI.

Phase 1 surface (see ``docs/vendor-research/dell_os10/30-codec-plan.md``
§ 8): hostname, ``! Version`` banner, interfaces (description / admin
state / mtu / IPv4 + IPv6 CIDR / ``ip vrf forwarding`` / L2 switchport /
``channel-group``), VLANs (SVI-derived + switchport projection), LAGs,
top-level VRF declarations, and static routes.  SNMP, local users and
VRRP are Phase 3 and are deliberately NOT parsed here.

Grammar notes — every one of these was MEASURED across the 14 OS10
captures held OUT-OF-TREE at ``local/dell-os10/configs/`` (gitignored —
they carry real password hashes), not inferred from another vendor:

* **``interface breakout`` and ``interface range`` are not interfaces.**
  Both sit at column 0 and begin with the word ``interface``
  (``interface breakout 1/1/1 map 100g-1x`` ×148, ``interface range
  ethernet1/1/1-1/1/12`` ×10).  A naive ``^interface\\s+(\\S+)`` header
  anchor creates phantom interfaces named ``breakout`` / ``range`` and
  absorbs the real config that follows.  :data:`_IFACE_RE` excludes both
  explicitly AND requires the header to end after the name, so a third
  such keyword added by a later OS10 release fails closed (no match)
  rather than becoming a phantom port.

* **An indented ``!`` does NOT close a stanza.**  Device dumps separate
  an SVI's L3 block from its VRRP block with a one-space ``!``::

      interface vlan101
       ip address 172.22.56.2/27
       !
       vrrp-group 11
        priority 150
      !

  The shared :func:`..._scanner._default_terminator` fires on
  ``line.strip() == "!"``, which would close the stanza at the INDENTED
  separator and silently drop everything after it.  This module passes a
  column-0-only terminator instead (same rule ``cisco_nxos`` uses).

* **Interface keyword case and spacing are not stable.**  The SVI header
  appears as ``interface vlan700`` ×161 (device output), ``interface Vlan
  700`` ×28 and ``interface vlan 700`` ×24 (operator-authored).  Parse
  accepts all three and normalises to the device form ``vlan700`` so one
  VLAN cannot enter the canonical tree under two names.

* **``switchport access vlan`` on a TRUNK port is the native VLAN**, not
  an access VLAN — the same semantic as Cisco's ``switchport trunk
  native vlan``, spelled differently.  Both real trunk examples carry it
  (``port-channel100``: ``mode trunk`` + ``access vlan 1`` + ``trunk
  allowed vlan 32,34,47,461``).  The raw value is stashed on the scratch
  and resolved in :func:`_build_canonical_interface` once the stanza has
  closed, so the mapping does not depend on line ORDER within the
  stanza.  OS10 emits no ``switchport trunk native vlan`` line at all
  (measured: 0 occurrences), so this is the only route to a native VLAN.

* **``management route`` is not ``ip route``.**  It outnumbers ``ip
  route`` 8:2 in the corpus and installs a default into the management
  VRF only.  Parsing it as a global static route would put a
  management-only default into the global RIB.  It is harvested onto
  ``CanonicalStaticRoute.vrf="management"`` — OS10's own name for that
  VRF — which preserves the operator's intent without polluting the
  global table.

* **OS10 declares no top-level ``vlan <id>`` stanza.**  Unlike NX-OS /
  Arista there is no ``vlan 10 / name PROD`` form and no ``tagged`` /
  ``untagged`` member lines (measured: 0 of each).  VLANs are implied by
  ``interface vlan<N>`` SVIs and by per-port switchport membership, so
  :func:`_synthesize_vlans_from_svis` plus the shared switchport
  projection are the ONLY sources of ``intent.vlans``.

* ``ipv6 address autoconfig`` (×10) and ``no ip address`` / ``no ip
  address dhcp`` are negations and stateless-autoconfig markers, not
  addresses.  The address regexes require a literal ``/<prefix>`` so
  none of them match.
"""

from __future__ import annotations

import ipaddress
import logging
import re

from ...canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalLAG,
    CanonicalLocalUser,
    CanonicalRoutingInstance,
    CanonicalSNMP,
    CanonicalSNMPv3User,
    CanonicalStaticRoute,
    CanonicalVlan,
    CanonicalVRRPGroup,
)
from .._helpers import _is_link_local_v6, _mask_to_prefix, merge_trunk_allowed
from .._input_shape import detect_input_shape
from .._scanner import scan_stanzas
from ..base import ParseError

logger = logging.getLogger(__name__)

_VENDOR = "dell_os10"

# ---------------------------------------------------------------------------
# Top-level globals
# ---------------------------------------------------------------------------

_HOSTNAME_RE = re.compile(r"^hostname\s+(\S+)", re.IGNORECASE | re.MULTILINE)
#: ``! Version 10.5.1.0`` — the first line of a device dump.  Operator-authored
#: configs carry no banner and yield an empty ``source_version``.
_VERSION_RE = re.compile(r"^!\s*Version\s+(\S+)\s*$", re.IGNORECASE | re.MULTILINE)

#: ``ip vrf <name>`` at column 0 declares a VRF.  ``ip vrf default`` is the
#: global RIB stated explicitly (an OS10 tell, ×8) and is NOT a VRF record;
#: ``ip vrf forwarding`` is the per-interface bind and must not match here.
_VRF_DECL_RE = re.compile(
    r"^ip\s+vrf\s+(?!forwarding\b|default\s*$)(\S+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Interface stanza
# ---------------------------------------------------------------------------

#: Interface header.  Two guards, both load-bearing:
#:
#:   1. the negative lookahead rejects ``breakout`` / ``range``, which are
#:      column-0 ``interface ...`` commands that declare no interface;
#:   2. the trailing ``\s*$`` requires the header to END after the name (or
#:      after a space-separated numeric index), so any other multi-token
#:      ``interface <verb> ...`` form fails closed instead of becoming a
#:      phantom port.
#:
#: Group 2 captures the index of the space-separated operator spelling
#: (``interface Vlan 700``); it is ``None`` for the device form.
_IFACE_RE = re.compile(
    r"^interface\s+(?!breakout\b|range\b)(\S+)(?:\s+(\d+))?\s*$",
    re.IGNORECASE,
)

#: Splits a single-token SVI name (``vlan700``) so the keyword's case can be
#: normalised without disturbing the index.
_SVI_SPLIT_RE = re.compile(r"^vlan(\d+)$", re.IGNORECASE)
#: Matches an already-normalised SVI name, for VLAN synthesis.
_SVI_NAME_RE = re.compile(r"^vlan(\d+)$")

# ``(\S.*)`` rather than ``(.+)`` keeps the ``\s+`` separator and the value
# from both matching the same run of spaces — the polynomial-ReDoS overlap
# CodeQL flags (py/polynomial-redos).  Consumers ``.strip()`` the group, so
# requiring a non-space first character is behaviour-identical.
_DESC_RE = re.compile(r"^\s+description\s+(\S.*)$", re.IGNORECASE)
_SHUTDOWN_RE = re.compile(r"^\s+shutdown\s*$", re.IGNORECASE)
_NO_SHUTDOWN_RE = re.compile(r"^\s+no\s+shutdown\s*$", re.IGNORECASE)
_MTU_RE = re.compile(r"^\s+mtu\s+(\d+)\s*$", re.IGNORECASE)
#: ``ip address 10.0.0.122/24`` — CIDR, like NX-OS / Arista.  The leading
#: ``\s+`` means ``no ip address`` (negation) can never match.
_IP_CIDR_RE = re.compile(
    r"^\s+ip\s+address\s+(\d+\.\d+\.\d+\.\d+)/(\d+)(?:\s+(secondary))?\s*$",
    re.IGNORECASE,
)
#: ``ipv6 address 2001:db8::1/64``.  The mandatory ``/<len>`` excludes
#: ``ipv6 address autoconfig``.
_IPV6_CIDR_RE = re.compile(
    r"^\s+ipv6\s+address\s+(\S+?)/(\d+)(?:\s+(link-local))?\s*$",
    re.IGNORECASE,
)
_VRF_FORWARDING_RE = re.compile(
    r"^\s+ip\s+vrf\s+forwarding\s+(\S+)\s*$", re.IGNORECASE,
)
_NO_SWITCHPORT_RE = re.compile(r"^\s+no\s+switchport\s*$", re.IGNORECASE)
_SWITCHPORT_MODE_RE = re.compile(
    r"^\s+switchport\s+mode\s+(access|trunk)\s*$", re.IGNORECASE,
)
_SWITCHPORT_ACCESS_RE = re.compile(
    r"^\s+switchport\s+access\s+vlan\s+(\d+)\s*$", re.IGNORECASE,
)
_SWITCHPORT_TRUNK_ALLOWED_RE = re.compile(
    r"^\s+switchport\s+trunk\s+allowed\s+vlan\s+(\S.*)$", re.IGNORECASE,
)
_CHANNEL_GROUP_RE = re.compile(
    r"^\s+channel-group\s+(\d+)\s+mode\s+(\S+)", re.IGNORECASE,
)
# ── VRRP (Phase 3b) ──
# OS10 runs REAL VRRP, so no HSRP normalisation is needed — unlike the
# NX-OS codec, whose every FHRP group becomes an `hsrp` block.  The group
# is a nested block inside an L3 interface::
#
#     interface vlan101
#      ip address 172.22.56.2/27
#      !                              <- INDENTED separator, not a terminator
#      vrrp-group 11
#       priority 150
#       virtual-address 172.22.56.1
#       no preempt
#
#: ``vrrp-group <1-255>`` opens a group.  Sub-command indent is NOT stable
#: (``virtual-address`` appears at both one and two spaces across the
#: corpus), so the block is tracked by state in the scratch rather than by
#: measuring indent depth.
_VRRP_GROUP_RE = re.compile(r"^\s+vrrp-group\s+(\d+)\s*$", re.IGNORECASE)
#: ``virtual-address <ip1> [... <ip10>]`` — up to TEN addresses on one line
#: (10.5.2 User Guide L58972), so the tail is split rather than captured as
#: a single address.
_VRRP_VADDR_RE = re.compile(
    r"^\s+virtual-address\s+(\S.*)$", re.IGNORECASE,
)
#: ⚠️ Anchored to end-of-line on purpose: a bare ``priority`` prefix also
#: matches ``priority-flow-control mode on``, which appears 24 times in the
#: corpus on ordinary data ports.
_VRRP_PRIORITY_RE = re.compile(r"^\s+priority\s+(\d+)\s*$", re.IGNORECASE)
#: OS10 VRRP preempts by DEFAULT (real VRRP), so only the negation appears
#: in real configs — ``no preempt`` x16, bare ``preempt`` never.
_VRRP_PREEMPT_RE = re.compile(r"^\s+(no\s+)?preempt\s*$", re.IGNORECASE)

#: OS10 ``channel-group ... mode`` vocabulary → canonical LAG modes.
#: ``on`` (static aggregation) is accepted for completeness though the
#: corpus carries only ``active`` (×63) and ``passive`` (×18).
_OS10_LAG_MODE_MAP = {"active": "active", "passive": "passive", "on": "static"}

# ---------------------------------------------------------------------------
# Static routes
# ---------------------------------------------------------------------------

#: ``ip route [vrf <name>] <dest>{/<len>|<mask>} <next-hop...> [<distance>]``.
#: The next-hop tail is captured whole and tokenised by
#: :func:`_split_nexthop` because OS10 accepts a SPACE-separated interface
#: next-hop (``ip route 10.1.1.0/24 ethernet 1/1/1``) that a fixed
#: ``(\S+)`` group would silently fail to match, dropping the route.
_IP_ROUTE_RE = re.compile(
    r"^ip\s+route\s+(?:vrf\s+(?P<vrf>\S+)\s+)?"
    r"(?P<dest>\d+\.\d+\.\d+\.\d+)"
    r"(?:/(?P<plen>\d+)|\s+(?P<mask>\d+\.\d+\.\d+\.\d+))"
    r"\s+(?P<rest>\S.*?)\s*$",
    re.IGNORECASE,
)
#: ``ipv6 route [vrf <name>] <prefix>/<len> <next-hop...> [<distance>]``.
_IPV6_ROUTE_RE = re.compile(
    r"^ipv6\s+route\s+(?:vrf\s+(?P<vrf>\S+)\s+)?"
    r"(?P<dest>[0-9A-Fa-f:]+/\d+)\s+(?P<rest>\S.*?)\s*$",
    re.IGNORECASE,
)
#: ``management route <dest>/<len> <gateway>`` — the management-VRF default.
#: Trailing whitespace is real in the corpus, hence ``\s*$``.
_MGMT_ROUTE_RE = re.compile(
    r"^management\s+route\s+(?P<dest>\d+\.\d+\.\d+\.\d+)/(?P<plen>\d+)"
    r"\s+(?P<rest>\S.*?)\s*$",
    re.IGNORECASE,
)

#: The VRF a ``management route`` installs into.  OS10's own name for the
#: out-of-band table; see the module docstring.
_MANAGEMENT_VRF = "management"

# ---------------------------------------------------------------------------
# Local users + SNMP (Phase 3a)
# ---------------------------------------------------------------------------

#: ``username <name> password <secret> role <role> [priv-lvl <0-15>]``.
#:
#: BOTH tails are optional, and for different reasons.  ``priv-lvl`` is
#: genuinely optional in the grammar — 2 of the 8 real ``username`` lines
#: omit it (``username netops password <x> role sysadmin``) — so a
#: parser that requires it silently drops those accounts.  ``password`` is
#: made optional so that a CROSS-VENDOR user carrying no secret, which the
#: render emits without a password clause, is still read back; otherwise
#: the account would vanish on re-parse.
_USERNAME_RE = re.compile(
    r"^username\s+(\S+)(?:\s+password\s+(\S+))?\s+role\s+(\S+)"
    r"(?:\s+priv-lvl\s+(\d+))?\s*$",
    re.IGNORECASE,
)
#: OS10 roles that carry full administrative privilege when the line
#: states no explicit ``priv-lvl``.
_OS10_ADMIN_ROLES = frozenset({"sysadmin", "secadmin"})

_SNMP_COMMUNITY_RE = re.compile(
    r"^snmp-server\s+community\s+(\S+)", re.IGNORECASE | re.MULTILINE,
)
_SNMP_LOCATION_RE = re.compile(
    r"^snmp-server\s+location\s+(\S.*)$", re.IGNORECASE | re.MULTILINE,
)
_SNMP_CONTACT_RE = re.compile(
    r"^snmp-server\s+contact\s+(\S.*)$", re.IGNORECASE | re.MULTILINE,
)
_SNMP_HOST_RE = re.compile(
    r"^snmp-server\s+host\s+(\d+\.\d+\.\d+\.\d+)",
    re.IGNORECASE | re.MULTILINE,
)
#: ``snmp-server user <name> <group> <security-model>
#:      [auth {md5|sha} <key>] [priv {des|aes} <key>] [localized] [access <acl>]``
#: (10.5.2 User Guide L9085).
#:
#: ⚠️ The trailing ``localized`` keyword is the agent's statement about its
#: OWN value: present, the key is already localised against THIS switch's
#: engine ID and cannot travel (L8942); absent, the value is a passphrase
#: the switch localises itself on commit.  The keyword is captured and
#: recorded per value — re-deriving the kind from the value's SHAPE is the
#: #460 fail-open, and a sanitised digest looks exactly like a word.
#:
#: The privacy cipher is an ENUMERATED token, never a bare ``(\S+)``: a
#: greedy pair would swallow the priv KEY as the cipher and the trailing
#: ``localized`` as the key, landing real key material in the unsanitised
#: ``priv_protocol`` field (the NX-OS disclosure this shape exists to
#: avoid).
_SNMP_V3_USER_RE = re.compile(
    r"^snmp-server\s+user\s+(\S+)\s+(\S+)\s+(\d+)"
    r"(?:\s+auth\s+(md5|sha)\s+(\S+))?"
    r"(?:\s+priv\s+(des|aes)\s+(\S+))?"
    r"(?:\s+(localized))?"
    r"(?:\s+access\s+\S+)?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

#: Interface-name prefix → IANA ifType hint.  OS10 uses one ``ethernet``
#: prefix for every speed.
_TYPE_HINTS: tuple[tuple[str, str], ...] = (
    ("ethernet", "ianaift:ethernetCsmacd"),
    ("mgmt", "ianaift:ethernetCsmacd"),
    ("port-channel", "ianaift:ieee8023adLag"),
    ("vlan", "ianaift:l3ipvlan"),
    ("loopback", "ianaift:softwareLoopback"),
)


def _infer_type(iface_name: str) -> str:
    """Best-effort IANA ifType from the OS10 interface-name prefix."""
    lower = iface_name.lower()
    for prefix, iftype in _TYPE_HINTS:
        if lower.startswith(prefix):
            return iftype
    return "ianaift:other"


def _column_zero_terminator(line: str) -> bool:
    """Close a stanza only on a non-indented (column-0) line.

    Deliberately NOT the shared :func:`_default_terminator`, which also
    closes on a bare ``!``.  OS10 device dumps use a ONE-SPACE ``!`` to
    separate an SVI's L3 block from its nested VRRP block, so the shared
    rule would close the stanza at that separator and drop the rest of
    the interface.  Same rule ``cisco_nxos`` applies, for the same reason.
    """
    return bool(line) and not line[0].isspace()


def _iface_name(m: re.Match[str]) -> str:
    """Normalised interface name from an :data:`_IFACE_RE` match.

    Collapses the three measured SVI spellings (``vlan700`` ×161, ``Vlan
    700`` ×28, ``vlan 700`` ×24) onto the device-emitted ``vlan700`` so a
    single VLAN cannot enter the canonical tree under two names — and so
    a render can emit the form a real device produces.  Every other OS10
    interface type is already lower-case and single-token in 100% of
    captures and passes through verbatim.
    """
    head, index = m.group(1), m.group(2)
    if index is not None:
        # Space-separated operator spelling: ``Vlan 700`` / ``vlan 700``.
        return f"{head.lower()}{index}"
    svi = _SVI_SPLIT_RE.match(head)
    if svi:
        return f"vlan{svi.group(1)}"
    return head


def parse_intent(raw: str) -> CanonicalIntent:
    """Parse Dell OS10 ``show running-configuration`` output into a
    :class:`CanonicalIntent`.

    Raises:
        ParseError: If the input is empty or looks like XML / JSON rather
            than OS10 CLI text.
    """
    if not raw.strip():
        raise ParseError("dell_os10: empty input", snippet="")

    shape = detect_input_shape(raw)
    if shape is not None:
        raise ParseError(
            f"dell_os10: input looks like {shape.upper()}, not Dell OS10 "
            f"CLI.  Paste the output of `show running-configuration`.",
            snippet=raw.lstrip()[:120],
        )

    intent = CanonicalIntent(
        source_vendor="dell_os10",
        source_format="cli-dellos10",
    )

    intent.hostname = _extract_hostname(raw)
    intent.source_version = _extract_version(raw)
    intent.routing_instances = _parse_routing_instances(raw)
    intent.interfaces = _parse_interfaces(raw)
    intent.static_routes = _parse_static_routes(raw)
    intent.lags = _parse_lags(raw)
    intent.local_users = _parse_local_users(raw)
    intent.snmp = _parse_snmp(raw)

    # OS10 has no top-level ``vlan <id>`` stanza, so every VLAN record is
    # derived — from an SVI, or from per-port switchport membership.
    intent.vlans = []
    _synthesize_vlans_from_svis(intent)

    # Shared switchport→VLAN projection, with the phantom-VLAN guard:
    # snapshot the legitimate ids first, project, then prune.  A wide
    # ``switchport trunk allowed vlan 1-4094`` must not inflate
    # ``intent.vlans`` with thousands of phantom records, but a single
    # operator-declared access / native VLAN with no SVI is legitimate
    # and has to survive.
    from ...canonical.transforms import (
        access_and_native_vlan_ids,
        project_switchport_to_vlan,
    )

    legitimate_vlan_ids = (
        {v.id for v in intent.vlans} | access_and_native_vlan_ids(intent)
    )
    project_switchport_to_vlan(intent)
    intent.vlans = [v for v in intent.vlans if v.id in legitimate_vlan_ids]

    logger.debug(
        "dell_os10 parsed: hostname=%r ifaces=%d vlans=%d routes=%d "
        "lags=%d vrfs=%d (input=%d chars)",
        intent.hostname,
        len(intent.interfaces),
        len(intent.vlans),
        len(intent.static_routes),
        len(intent.lags),
        len(intent.routing_instances),
        len(raw),
    )
    return intent


def _extract_hostname(raw: str) -> str:
    m = _HOSTNAME_RE.search(raw)
    return m.group(1) if m else ""


def _extract_version(raw: str) -> str:
    """Return the OS10 release from the ``! Version 10.5.1.0`` banner.

    Stored as :attr:`CanonicalIntent.source_version` (metadata, excluded
    from every comparator) so a same-vendor render can echo the device's
    own release rather than relabelling it with a constant (#297).
    """
    m = _VERSION_RE.search(raw)
    return m.group(1) if m else ""


def _parse_routing_instances(raw: str) -> list[CanonicalRoutingInstance]:
    """Extract column-0 ``ip vrf <name>`` declarations.

    ``ip vrf default`` is excluded by :data:`_VRF_DECL_RE` — OS10 states
    the global RIB as an explicit stanza (it is one of the markers that
    identifies an OS10 config at all), but it is not a VRF and must not
    become a routing-instance record.

    The per-interface ``ip vrf forwarding <name>`` bind is harvested by
    :func:`_parse_interfaces` onto ``CanonicalInterface.vrf``; it never
    materialises an instance here, so a config that binds a port to a VRF
    it never declared cannot conjure a phantom routing-instance.
    """
    seen: set[str] = set()
    instances: list[CanonicalRoutingInstance] = []
    for m in _VRF_DECL_RE.finditer(raw):
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        instances.append(CanonicalRoutingInstance(name=name))
    return instances


def _new_iface_scratch(name: str) -> dict:
    """Fresh per-interface parse-time scratch dict.

    Single source of truth for the field set so the stanza-open site and
    the build step cannot drift apart.
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
        "switchport_mode": None,
        # Raw ``switchport access vlan <N>`` value.  Resolved to EITHER
        # access_vlan or trunk_native_vlan at build time — see
        # _build_canonical_interface.
        "access_vlan_raw": None,
        "trunk_allowed": [],
        "lag_member_of": None,
        # VRRP (Phase 3b): {gid: {virtual_ips, priority, preempt}}.
        "vrrp_groups": {},
        "_vrrp_gid": None,   # active group while inside a vrrp-group block
    }


def _parse_interfaces(raw: str) -> list[CanonicalInterface]:
    """Extract ``interface <name>`` stanzas from OS10 config text.

    Per interface: description, admin state, mtu, IPv4 / IPv6 (CIDR), VRF
    bind, L2 switchport state and ``channel-group`` LAG membership.
    """

    def _on_line(line: str, current: dict) -> None:
        # ── VRRP nested block (Phase 3b) ──
        # Tracked by scratch state rather than indent depth: the
        # sub-command indent is not stable across the corpus.
        vg = _VRRP_GROUP_RE.match(line)
        if vg:
            current["vrrp_groups"].setdefault(int(vg.group(1)), {
                "virtual_ips": [],
                "priority": 100,
                "preempt": True,   # OS10 VRRP default: preempt ENABLED
            })
            current["_vrrp_gid"] = int(vg.group(1))
            return
        _gid = current["_vrrp_gid"]
        if _gid is not None:
            g = current["vrrp_groups"][_gid]
            vam = _VRRP_VADDR_RE.match(line)
            if vam:
                g["virtual_ips"].extend(vam.group(1).split())
                return
            prm = _VRRP_PRIORITY_RE.match(line)
            if prm:
                g["priority"] = int(prm.group(1))
                return
            pem = _VRRP_PREEMPT_RE.match(line)
            if pem:
                g["preempt"] = not bool(pem.group(1))
                return
            # Anything else closes the group and falls through to the
            # interface-level cascade below.
            current["_vrrp_gid"] = None

        dm = _DESC_RE.match(line)
        if dm:
            # Operator-authored configs quote descriptions containing
            # spaces (``description "mgmt 10.0.1.0/24"``); device output
            # does not.  Strip symmetric quotes so the two dialects agree.
            current["description"] = dm.group(1).strip().strip('"')
            return

        if _NO_SHUTDOWN_RE.match(line):
            current["enabled"] = True
            return
        if _SHUTDOWN_RE.match(line):
            current["enabled"] = False
            return

        mm = _MTU_RE.match(line)
        if mm:
            current["mtu"] = int(mm.group(1))
            return

        im = _IP_CIDR_RE.match(line)
        if im:
            current["ipv4"].append({
                "ip": im.group(1),
                "prefix_length": int(im.group(2)),
                "is_secondary": im.group(3) is not None,
            })
            return

        v6m = _IPV6_CIDR_RE.match(line)
        if v6m:
            addr = v6m.group(1)
            scope = (
                "link-local"
                if (v6m.group(3) or _is_link_local_v6(addr))
                else "global"
            )
            current["ipv6"].append({
                "ip": addr,
                "prefix_length": int(v6m.group(2)),
                "scope": scope,
            })
            return

        vm = _VRF_FORWARDING_RE.match(line)
        if vm:
            current["vrf"] = vm.group(1)
            return

        if _NO_SWITCHPORT_RE.match(line):
            # Routed port.  OS10 defaults physical / LAG ports to L2, so
            # the routed intent is stated explicitly; leaving
            # switchport_mode None already encodes "routed".
            return
        sm = _SWITCHPORT_MODE_RE.match(line)
        if sm:
            current["switchport_mode"] = sm.group(1).lower()
            return
        am = _SWITCHPORT_ACCESS_RE.match(line)
        if am:
            # Stash only — whether this is the access VLAN or the trunk
            # NATIVE VLAN depends on the stanza's final switchport mode,
            # which may be declared on a later line.
            current["access_vlan_raw"] = int(am.group(1))
            return
        tam = _SWITCHPORT_TRUNK_ALLOWED_RE.match(line)
        if tam:
            current["switchport_mode"] = current["switchport_mode"] or "trunk"
            current["trunk_allowed"] = merge_trunk_allowed(
                current["trunk_allowed"], tam.group(1).strip(),
            )
            return

        cgm = _CHANNEL_GROUP_RE.match(line)
        if cgm:
            current["lag_member_of"] = f"port-channel{int(cgm.group(1))}"
            return

    return scan_stanzas(
        raw.splitlines(),
        is_header=_IFACE_RE.match,
        open_scratch=lambda m: _new_iface_scratch(_iface_name(m)),
        on_line=_on_line,
        build=_build_canonical_interface,
        is_terminator=_column_zero_terminator,
    )


def _build_canonical_interface(raw: dict) -> CanonicalInterface:
    """Convert the parse-time scratch dict into a :class:`CanonicalInterface`.

    Resolves the ``switchport access vlan`` ambiguity here, once the whole
    stanza has been seen, so the outcome does not depend on the order the
    switchport lines appeared in:

    * mode ``trunk``  → the value is the NATIVE (untagged) VLAN;
    * otherwise       → it is the access VLAN, and the port is an access
      port even if no explicit ``switchport mode access`` line was given
      (OS10 defaults a switched port to access).

    Mapping the trunk case to ``access_vlan`` would invert the port's L2
    semantics on every downstream codec — the class of defect #239 fixed
    for Junos.
    """
    mode = raw.get("switchport_mode")
    access_raw = raw.get("access_vlan_raw")
    access_vlan = None
    trunk_native = None
    if access_raw is not None:
        if mode == "trunk":
            trunk_native = access_raw
        else:
            access_vlan = access_raw
            mode = mode or "access"

    # VRRP groups (Phase 3b) → CanonicalVRRPGroup(mode="vrrp").  OS10 runs
    # real VRRP, so the canonical mode is the wire protocol, not a
    # normalisation.  Sorted by group id for deterministic ordering (the
    # round-trip invariant does not normalise vrrp_groups order).
    vrrp_groups = [
        CanonicalVRRPGroup(
            group_id=gid,
            mode="vrrp",
            virtual_ips=list(g.get("virtual_ips", [])),
            priority=g.get("priority", 100),
            preempt=g.get("preempt", True),
        )
        for gid, g in sorted(raw.get("vrrp_groups", {}).items())
    ]

    return CanonicalInterface(
        name=raw["name"],
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
        vrf=raw.get("vrf", ""),
        switchport_mode=mode,
        access_vlan=access_vlan,
        trunk_allowed_vlans=raw.get("trunk_allowed", []),
        trunk_native_vlan=trunk_native,
        lag_member_of=raw.get("lag_member_of"),
        vrrp_groups=vrrp_groups,
    )


def _lag_sort_key(name: str) -> tuple[int, int, str]:
    """Total-order sort key grouping ``port-channel<N>`` numerically."""
    m = re.match(r"^port-channel(\d+)$", name, re.IGNORECASE)
    return (0, int(m.group(1)), name) if m else (1, 0, name)


def _parse_lags(raw: str) -> list[CanonicalLAG]:
    """Build :class:`CanonicalLAG` records from OS10 config.

    Two signals, either sufficient:

    * an ``interface port-channel<N>`` stanza declares the LAG exists;
    * a ``channel-group <N> mode <m>`` line under a physical port declares
      that port a member of ``port-channel<N>``.

    Mode is the first member's mode; an empty LAG keeps
    :attr:`CanonicalLAG.mode`'s default.
    """
    members_by_lag: dict[str, list[str]] = {}
    mode_by_lag: dict[str, str] = {}
    declared: set[str] = set()
    current_iface: str | None = None

    def _note_header(name: str) -> None:
        m = re.match(r"^port-channel(\d+)$", name, re.IGNORECASE)
        if m:
            declared.add(f"port-channel{int(m.group(1))}")

    for line in raw.splitlines():
        hm = _IFACE_RE.match(line)
        if hm:
            current_iface = _iface_name(hm)
            _note_header(current_iface)
            continue
        if current_iface is None:
            continue
        if _column_zero_terminator(line):
            current_iface = None
            continue
        cgm = _CHANNEL_GROUP_RE.match(line)
        if cgm:
            lag_name = f"port-channel{int(cgm.group(1))}"
            mode = _OS10_LAG_MODE_MAP.get(cgm.group(2).lower(), "active")
            members = members_by_lag.setdefault(lag_name, [])
            if current_iface not in members:
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


def _split_nexthop(rest: str) -> tuple[str, str, int]:
    """Split a static route's next-hop tail into ``(gateway, interface, metric)``.

    OS10 accepts several shapes after the destination::

        10.1.1.1                  → gateway
        ethernet1/1/1             → egress interface
        ethernet 1/1/1            → egress interface, SPACE-separated
        ethernet 1/1/1 10.1.1.1   → interface + gateway
        10.1.1.1 200              → gateway + administrative distance

    A fixed ``(\\S+)`` capture would fail to match the space-separated
    interface form outright, silently dropping the route — hence the
    tail is captured whole and tokenised here.  A trailing all-digits
    token is the administrative distance, but only when something else
    precedes it (so a bare numeric next-hop can never be eaten as a
    metric).
    """
    tokens = rest.split()
    metric = 0
    if len(tokens) > 1 and tokens[-1].isdigit():
        metric = int(tokens[-1])
        tokens = tokens[:-1]

    def _is_ip(token: str) -> bool:
        try:
            ipaddress.ip_address(token)
        except ValueError:
            return False
        return True

    if not tokens:
        return "", "", metric
    if len(tokens) == 1:
        return (tokens[0], "", metric) if _is_ip(tokens[0]) else ("", tokens[0], metric)
    if _is_ip(tokens[-1]):
        # ``<interface...> <gateway>`` — the interface name may itself be
        # space-separated, so rejoin everything before the gateway.
        return tokens[-1], " ".join(tokens[:-1]), metric
    return "", " ".join(tokens), metric


def _parse_static_routes(raw: str) -> list[CanonicalStaticRoute]:
    """Extract ``ip route`` / ``ipv6 route`` / ``management route`` lines.

    ``management route`` is harvested with ``vrf="management"`` rather
    than as a global route — see the module docstring.  ``ip route``
    accepts both the dominant CIDR form and the legacy dotted-mask form
    the OS10 manual documents (10.5.2 User Guide L15622); no capture in
    the corpus exercises the dotted-mask form, so it is covered by a
    synthetic unit test instead.
    """
    routes: list[CanonicalStaticRoute] = []
    for line in raw.splitlines():
        m6 = _IPV6_ROUTE_RE.match(line)
        if m6:
            gateway, iface, metric = _split_nexthop(m6.group("rest"))
            routes.append(CanonicalStaticRoute(
                destination=m6.group("dest"),
                gateway=gateway,
                interface=iface,
                metric=metric,
                vrf=m6.group("vrf") or "",
            ))
            continue

        mm = _MGMT_ROUTE_RE.match(line)
        if mm:
            gateway, iface, metric = _split_nexthop(mm.group("rest"))
            routes.append(CanonicalStaticRoute(
                destination=f"{mm.group('dest')}/{mm.group('plen')}",
                gateway=gateway,
                interface=iface,
                metric=metric,
                vrf=_MANAGEMENT_VRF,
            ))
            continue

        m4 = _IP_ROUTE_RE.match(line)
        if not m4:
            continue
        plen = m4.group("plen")
        if plen is None:
            # Legacy dotted-mask form.  A malformed / non-contiguous mask
            # raises ParseError naming this codec (shared helper).
            plen = _mask_to_prefix(m4.group("mask"), vendor=_VENDOR)
        gateway, iface, metric = _split_nexthop(m4.group("rest"))
        routes.append(CanonicalStaticRoute(
            destination=f"{m4.group('dest')}/{int(plen)}",
            gateway=gateway,
            interface=iface,
            metric=metric,
            vrf=m4.group("vrf") or "",
        ))
    return routes


def _parse_local_users(raw: str) -> list[CanonicalLocalUser]:
    """Extract ``username ... role ...`` lines.

    OS10 carries a REAL numeric privilege (``priv-lvl 0-15``) alongside the
    named role, unlike NX-OS which has only the role — so the canonical
    privilege level is read directly when stated.  When it is omitted (2 of
    the 8 real lines), it is derived from the role: ``sysadmin`` /
    ``secadmin`` are administrative, everything else is not.

    ``system-user linuxadmin`` is deliberately NOT modelled here.  It is the
    switch's underlying Linux shell account, not a NOS login, and there is
    no canonical field that would distinguish it on render — emitting it
    back as a plain ``username`` would silently convert a shell account into
    a NOS operator.  Its drop is surfaced through
    ``dropped_tier3_sections`` instead (the label is the bare keyword, so no
    hash reaches the banner).
    """
    users: list[CanonicalLocalUser] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        m = _USERNAME_RE.match(line)
        if not m:
            continue
        name, secret, role, priv = m.groups()
        if name in seen:
            continue
        seen.add(name)
        users.append(CanonicalLocalUser(
            name=name,
            hashed_password=secret or "",
            role=role,
            privilege_level=(
                int(priv) if priv
                else (15 if role.lower() in _OS10_ADMIN_ROLES else 1)
            ),
        ))
    return users


def _parse_snmp(raw: str) -> CanonicalSNMP | None:
    """Extract SNMP config (v2c community + v3 USM users).

    Returns ``None`` when the config carries no ``snmp-server`` line, so the
    tree does not gain an empty stub.

    ⚠️ The per-line ``localized`` keyword is recorded into ``auth_kind`` /
    ``priv_kind`` rather than inferred from the value.  One keyword governs
    the whole line, so it applies to both keys the user carries.

    Note on corpus coverage: the 14 OS10 captures held contain exactly one
    ``snmp-server user`` line, and it carries NO ``localized`` marker — so
    the marked branch is attested by Dell's manual (L9085) and covered
    synthetically, not by a real capture.  ``snmp-server community`` appears
    in no capture at all and is likewise manual-attested.
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

    from ..._usm_keys import LOCALISED, PLAINTEXT  # lazy: policy module

    for m in v3_matches:
        name, group, _model, auth_p, auth_pw, priv_p, priv_pw, marker = m.groups()
        kind = LOCALISED if marker else PLAINTEXT
        snmp.v3_users.append(CanonicalSNMPv3User(
            name=name,
            group=group or "",
            auth_protocol=(auth_p or "").lower(),
            auth_passphrase=auth_pw or "",
            auth_kind=kind,
            priv_protocol=(priv_p or "").lower(),
            priv_passphrase=priv_pw or "",
            priv_kind=kind,
        ))
    return snmp


def _synthesize_vlans_from_svis(intent: CanonicalIntent) -> None:
    """Derive VLAN records from ``interface vlan<N>`` SVIs.

    OS10 declares no top-level ``vlan <id>`` stanza (measured: 0 across
    the corpus), so an SVI is the only place a VLAN's identity and its L3
    config are stated.  The SVI's description becomes the VLAN name —
    that is the only human label OS10 carries for a VLAN — and its IPv4
    addresses are mirrored onto the VLAN record so VLAN-centric target
    codecs can render the SVI.
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
