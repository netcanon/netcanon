"""
Parse path for Aruba AOS-CX (``show running-config`` form).

Public function: :func:`parse_intent` — raw text in,
:class:`CanonicalIntent` out.  Targets the AOS-CX switch portfolio
(6000 / 6100 / 6200 / 6300 / 6400 / 8100 / 8320 / 8325 / 8360 / 8400 /
9300 / CX-10000) on AOS-CX 10.x.

Note: probe is in :mod:`.codec`; this module assumes input has already
been classified as Aruba AOS-CX CLI text.

Surface (Phase 1 = Tier-1; Phase 2 adds the L2 + LAG + users surface):

* ``hostname <name>`` → :attr:`CanonicalIntent.hostname`.
* ``!Version ArubaOS-CX <ver>`` → :attr:`CanonicalIntent.source_version`
  (metadata only; the banner is synthesised on render).
* ``vlan <id>`` stanzas (one id per line) + nested ``name`` / ``description``
  → :class:`CanonicalVlan`, plus SVI synthesis from ``interface vlan N``.
* ``vrf <name>`` (top-level) → :class:`CanonicalRoutingInstance` (name
  only).
* ``interface <name>`` blocks → :class:`CanonicalInterface` carrying
  ``description`` / admin-state (``no shutdown`` / ``shutdown``) / ``mtu``
  / ``ip address X/N`` (CIDR) / ``ipv6 address X/N`` / ``vrf attach <name>``
  and (Phase 2) the L2 switchport surface — ``no routing`` + ``vlan
  access <N>`` / ``vlan trunk native <N> [tag]`` / ``vlan trunk allowed
  <list|all>`` — plus LAG membership (``lag <N>``).
* ``interface lag <N> [multi-chassis]`` stanzas → :class:`CanonicalLAG`
  (Phase 2; ``lacp mode active|passive`` → mode, absent → static) AND a
  :class:`CanonicalInterface` (kind ``lag``) carrying the LAG's switchport
  state.  The ``multi-chassis`` (VSX MLAG) modifier is dropped in v1.
* ``user <name> group <group> password ciphertext <blob>`` (Phase 2) →
  :class:`CanonicalLocalUser` (``group`` → role; administrators → priv
  15, else 1).
* top-level ``ip route <dest>/<prefix> <gw> [<dist>]`` (default VRF only)
  → :class:`CanonicalStaticRoute`.

Where this codec diverges from ``cisco_nxos`` (its closest template) —
see ``docs/fixture-research-2015/11-aruba_aoscx.md``:

* **Interface names are multi-token**: ``interface 1/1/1`` (member /
  slot / port triple), ``interface vlan 11``, ``interface lag 1``,
  ``interface loopback 0``, ``interface mgmt``.  The canonical ``name``
  carries the space; :mod:`.port_names` splits it back.
* **Default admin-state is DOWN** for physical / SVI / mgmt / LAG ports
  (active ports carry an explicit ``no shutdown``); loopbacks are up by
  default.  The scratch default is therefore type-aware.
* **L2 is opt-in**: AOS-CX ports default to routed (L3); ``no routing``
  marks a port L2, with ``vlan access`` / ``vlan trunk`` carrying the
  membership — the INVERSE of NX-OS (which defaults L2 and uses ``no
  switchport`` for routed).
* VRF stanza keyword is bare ``vrf <name>``; per-interface bind is ``vrf
  attach <name>``.

Deferred to later phases (parse-and-ignore in v1): SNMP, the
``active-gateway`` anycast surface, VSX (incl. the LAG ``multi-chassis``
flag), VXLAN / EVPN (``interface vxlan`` / ``evpn``), and the Tier-3
protocol / ACL / QoS blocks.
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
)
from .._input_shape import detect_input_shape
from ..base import ParseError
from . import port_names as _port_names

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex constants — module-level so they compile once per import.
# ---------------------------------------------------------------------------

_HOSTNAME_RE = re.compile(r"^hostname\s+(\S+)", re.IGNORECASE | re.MULTILINE)
#: ``!Version ArubaOS-CX FL.10.13.1000`` — the platform-family-prefixed
#: release string after the ``ArubaOS-CX`` marker.
_VERSION_RE = re.compile(
    r"^!Version\s+ArubaOS-CX\s+(\S+)", re.IGNORECASE | re.MULTILINE,
)

#: ``interface <name>`` — captures the type token plus an OPTIONAL
#: space-separated numeric index, so ``interface vlan 11`` -> ``vlan 11``,
#: ``interface lag 1 multi-chassis`` -> ``lag 1`` (modifier dropped), and
#: ``interface 1/1/1`` -> ``1/1/1`` (the triple is one ``\S+`` token).
_IFACE_RE = re.compile(r"^interface\s+(\S+)(?:\s+(\d+))?\b", re.IGNORECASE)
_DESC_RE = re.compile(r"^\s+description\s+(.+)", re.IGNORECASE)
_SHUTDOWN_RE = re.compile(r"^\s+shutdown\s*$", re.IGNORECASE)
_NO_SHUTDOWN_RE = re.compile(r"^\s+no\s+shutdown\s*$", re.IGNORECASE)
#: ``mtu 9198`` — the L2 frame MTU.  The separate ``ip mtu`` line (L3
#: MTU) is parse-and-ignore in v1.
_MTU_RE = re.compile(r"^\s+mtu\s+(\d+)\s*$", re.IGNORECASE)
#: ``ip address 10.0.0.1/24`` — CIDR form, never dotted mask.  The mgmt
#: port's ``ip static`` / ``ip dhcp`` forms are deferred (not this regex).
_IP_CIDR_RE = re.compile(
    r"^\s+ip\s+address\s+(\d+\.\d+\.\d+\.\d+)/(\d+)(?:\s+(secondary))?\s*$",
    re.IGNORECASE,
)
#: ``ipv6 address 2001:db8::1/64`` — CIDR form.  An optional ``link-local``
#: trailer tags scope explicitly; the fe80::/10 prefix infers it otherwise.
_IPV6_CIDR_RE = re.compile(
    r"^\s+ipv6\s+address\s+(\S+?)/(\d+)(?:\s+(link-local))?\s*$",
    re.IGNORECASE,
)
#: ``vrf attach <name>`` inside an interface stanza (AOS-CX form of
#: NX-OS's ``vrf member`` / IOS-XE's ``vrf forwarding``).
_VRF_ATTACH_RE = re.compile(r"^\s+vrf\s+attach\s+(\S+)\s*$", re.IGNORECASE)

# ── L2 switchport grammar (Phase 2) ──
# AOS-CX ports default to routed (L3); ``no routing`` marks a port L2 and
# the ``vlan access`` / ``vlan trunk`` lines carry the membership.  Mode
# is set by the vlan lines (mirrors the arista/NX-OS render-decides model,
# inverted): a port carrying an IP keeps ``switchport_mode=None`` (routed).
_NO_ROUTING_RE = re.compile(r"^\s+no\s+routing\s*$", re.IGNORECASE)
_VLAN_ACCESS_RE = re.compile(r"^\s+vlan\s+access\s+(\d+)\s*$", re.IGNORECASE)
#: ``vlan trunk native <N> [tag]`` — the ``tag`` modifier (tag the native
#: VLAN) is consumed but not modelled in v1.
_VLAN_TRUNK_NATIVE_RE = re.compile(
    r"^\s+vlan\s+trunk\s+native\s+(\d+)(?:\s+tag)?\s*$", re.IGNORECASE,
)
#: ``vlan trunk allowed <list|all>`` — ``all`` maps to an empty
#: allowed-list (the render re-emits ``all`` for an empty list).
_VLAN_TRUNK_ALLOWED_RE = re.compile(
    r"^\s+vlan\s+trunk\s+allowed\s+(.+?)\s*$", re.IGNORECASE,
)
#: ``lag <N>`` on a physical port declares it a member of ``lag <N>``.
_LAG_MEMBER_RE = re.compile(r"^\s+lag\s+(\d+)\s*$", re.IGNORECASE)
#: ``lacp mode active|passive`` inside an ``interface lag N`` stanza.
_LACP_MODE_RE = re.compile(
    r"^\s+lacp\s+mode\s+(active|passive)\s*$", re.IGNORECASE,
)

#: ``user <name> group <group> password ciphertext <blob>`` (Phase 2).
#: The ciphertext blob is a single token (base64-ish, no spaces).  The
#: ``plaintext`` form is not parsed (rare in a running-config; would drop
#: the user).
_USER_RE = re.compile(
    r"^user\s+(\S+)\s+group\s+(\S+)\s+password\s+ciphertext\s+(\S+)",
    re.IGNORECASE | re.MULTILINE,
)
#: AOS-CX built-in group that maps to the cross-vendor admin privilege.
_AOSCX_ADMIN_GROUPS = {"administrators"}

# ── SNMP (Phase 2b) ──
# AOS-CX uses `system-location` / `system-contact` (not `location` /
# `contact`), `snmp-server community <name>`, and a `snmpv3 user` block
# whose auth / priv keys are `<ciphertext|plaintext> <blob>`.
_SNMP_COMMUNITY_RE = re.compile(
    r"^snmp-server\s+community\s+(\S+)", re.IGNORECASE | re.MULTILINE,
)
_SNMP_LOCATION_RE = re.compile(
    r"^snmp-server\s+system-location\s+(.+)$", re.IGNORECASE | re.MULTILINE,
)
_SNMP_CONTACT_RE = re.compile(
    r"^snmp-server\s+system-contact\s+(.+)$", re.IGNORECASE | re.MULTILINE,
)
#: ``snmpv3 user <name> auth <proto> auth-pass <ciphertext|plaintext>
#: <blob> [priv <proto> priv-pass <ciphertext|plaintext> <blob>]``.  The
#: blob is device-key-encrypted (preserved verbatim; lossy cross-vendor /
#: cross-device).  The ``ciphertext`` / ``plaintext`` keyword is consumed
#: (render always emits ``ciphertext``).
_SNMPV3_USER_RE = re.compile(
    r"^snmpv3\s+user\s+(\S+)"
    r"\s+auth\s+(\S+)\s+auth-pass\s+(?:ciphertext|plaintext)\s+(\S+)"
    r"(?:\s+priv\s+(\S+)\s+priv-pass\s+(?:ciphertext|plaintext)\s+(\S+))?",
    re.IGNORECASE | re.MULTILINE,
)

# ── Active-gateway anycast (Phase 3) ──
# AOS-CX VSX/EVPN distributed gateway, configured PER-SVI (Arista-VARP
# style — the VIP is distinct from the SVI's own `ip address`, unlike
# NX-OS DAG where they coincide).  Maps onto the shared anycast canonical
# surface: `active-gateway ip <vip>` -> virtual_gateway_address on the
# SVI's primary address; the first `active-gateway ip mac <mac>` ->
# CanonicalIntent.anycast_gateway_mac.
_ACTIVE_GW_MAC_RE = re.compile(
    r"^\s+active-gateway\s+ip\s+mac\s+(\S+)\s*$", re.IGNORECASE,
)
#: MULTILINE variant for the intent-level chassis-MAC scan.
_ACTIVE_GW_MAC_TOP_RE = re.compile(
    r"^\s+active-gateway\s+ip\s+mac\s+(\S+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
#: ``active-gateway ip <vip>`` — the digit guard means it never matches
#: the ``active-gateway ip mac ...`` line.
_ACTIVE_GW_IP_RE = re.compile(
    r"^\s+active-gateway\s+ip\s+(\d+\.\d+\.\d+\.\d+)\s*$", re.IGNORECASE,
)


def _normalise_mac_to_colon_hex(mac: str) -> str:
    """Normalise a MAC to canonical lower-case colon-hex.

    AOS-CX emits colon-hex already (``02:00:0a:01:65:01``); this also
    tolerates dotted-triplet / dash forms.  Returns empty string for
    input it can't classify.  Forked from cisco_nxos per the
    duplicate-rather-than-lift convention.
    """
    if not mac:
        return ""
    hex_only = re.sub(r"[^0-9a-f]", "", mac.strip().lower())
    if len(hex_only) != 12:
        return ""
    return ":".join(hex_only[i:i + 2] for i in range(0, 12, 2))


#: ``vrf <name>`` opens a top-level VRF declaration (single token, whole
#: line).  Distinct from the interface-level ``vrf attach`` (indented) and
#: from ``ssh server vrf mgmt`` / ``ntp vrf mgmt`` (different leading
#: keyword), so the anchored single-token match is unambiguous.
_VRF_DECL_RE = re.compile(r"^vrf\s+(\S+)\s*$", re.IGNORECASE)

#: ``vlan <id>`` — AOS-CX declares one VLAN id per line (no comma / range
#: list in ``show running-config``).
_VLAN_TOP_RE = re.compile(r"^vlan\s+(\d+)\s*$", re.IGNORECASE)
_VLAN_NAME_RE = re.compile(r"^\s+name\s+(.+)", re.IGNORECASE)
_VLAN_DESC_RE = re.compile(r"^\s+description\s+(.+)", re.IGNORECASE)

#: ``ip route <dest>/<prefix> <gw> [<dist>]`` — top-level (default VRF)
#: static route.  AOS-CX uses CIDR destinations.
_STATIC_ROUTE_RE = re.compile(
    r"^ip\s+route\s+(\d+\.\d+\.\d+\.\d+)/(\d+)\s+(\S+)(?:\s+(\d+))?",
    re.IGNORECASE,
)

#: ``interface vlan <N>`` SVI name (post-capture; the canonical name is
#: the space-separated ``vlan N``).
_SVI_NAME_RE = re.compile(r"^vlan\s+(\d+)$", re.IGNORECASE)

#: PortIdentity kind -> IANA ifType hint.  AOS-CX declares no ifType, so
#: this is inferred from the name shape (declared lossy in the matrix).
_KIND_TO_IFTYPE: dict[str, str] = {
    "physical": "ianaift:ethernetCsmacd",
    "svi": "ianaift:l3ipvlan",
    "lag": "ianaift:ieee8023adLag",
    "loopback": "ianaift:softwareLoopback",
    "mgmt": "ianaift:ethernetCsmacd",
    "vtep": "ianaift:tunnel",
}


def _infer_type(iface_name: str) -> str:
    """Best-effort IANA ifType from the AOS-CX interface-name shape."""
    kind = _port_names.classify_port_name(iface_name).kind
    return _KIND_TO_IFTYPE.get(kind, "ianaift:other")


def _default_enabled(iface_name: str) -> bool:
    """Return the AOS-CX default admin-state for an interface by name.

    Loopbacks come up without an explicit ``no shutdown``; every other
    port type (physical / SVI / mgmt / LAG) is admin-down by default and
    needs an explicit ``no shutdown`` to enable.  An explicit
    ``shutdown`` / ``no shutdown`` line in the stanza overrides this.
    """
    return _port_names.classify_port_name(iface_name).kind == "loopback"


def _is_link_local_v6(addr: str) -> bool:
    """Return True iff *addr* is in the IPv6 link-local prefix fe80::/10.

    Mirrors ``cisco_nxos.parse._is_link_local_v6`` — the prefix is
    vendor-neutral (RFC 4291 §2.4), so scope can be recovered even when
    the operator omits the ``link-local`` keyword.
    """
    if not addr:
        return False
    lo = addr.lower()
    return len(lo) >= 3 and lo[:2] == "fe" and lo[2] in ("8", "9", "a", "b")


def _parse_vlan_list(text: str) -> list[int]:
    """Parse a VLAN id-list like ``101-102`` or ``10,20,30`` into a flat
    list of ints.  Ranges are expanded inclusively (mirrors cisco_nxos)."""
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


def _lag_sort_key(name: str) -> tuple[int, int]:
    """Stable sort key grouping ``lag <N>`` numerically."""
    m = re.match(r"^lag\s+(\d+)$", name, re.IGNORECASE)
    return (0, int(m.group(1))) if m else (1, 0)


def parse_intent(raw: str) -> CanonicalIntent:
    """Parse AOS-CX ``show running-config`` output into a
    :class:`CanonicalIntent`.

    Raises:
        ParseError: If the input is empty or looks like XML / JSON
            rather than AOS-CX CLI text.
    """
    if not raw.strip():
        raise ParseError("aruba_aoscx: empty input", snippet="")

    shape = detect_input_shape(raw)
    if shape is not None:
        raise ParseError(
            f"aruba_aoscx: input looks like {shape.upper()}, not AOS-CX "
            f"CLI.  Paste the output of `show running-config`.",
            snippet=raw.lstrip()[:120],
        )

    intent = CanonicalIntent(
        source_vendor="aruba_aoscx",
        source_format="cli-aoscx",
    )

    intent.hostname = _extract_hostname(raw)
    intent.source_version = _extract_version(raw)

    # Active-gateway anycast (Phase 3): the per-SVI `active-gateway ip
    # mac` (first occurrence) is the chassis-wide anycast MAC.  The
    # per-SVI `active-gateway ip <vip>` is harvested into
    # virtual_gateway_address by :func:`_parse_interfaces`.
    agm = _ACTIVE_GW_MAC_TOP_RE.search(raw)
    if agm:
        normalised = _normalise_mac_to_colon_hex(agm.group(1))
        if normalised:
            intent.anycast_gateway_mac = normalised

    # VRF declarations (``vrf <name>`` top-level).  Harvests the name only;
    # per-interface ``vrf attach`` membership is set by
    # :func:`_parse_interfaces`.
    intent.routing_instances = _parse_routing_instances(raw)

    intent.interfaces = _parse_interfaces(raw)

    intent.vlans = _parse_vlans(raw)
    # Derive VLAN records from ``interface vlan <N>`` SVIs with no matching
    # top-level ``vlan`` stanza (mirrors cisco_nxos) so VLAN-centric
    # downstream codecs don't silently drop the SVI's L3 config.
    _synthesize_vlans_from_svis(intent)

    intent.static_routes = _parse_static_routes(raw)

    # LAGs (Phase 2) — ``interface lag N`` declares the LAG; per-member
    # ``lag N`` lines + the stanza's ``lacp mode`` contribute.
    intent.lags = _parse_lags(raw)

    # Local users (Phase 2) — ``user <name> group <group> password
    # ciphertext <blob>``.
    intent.local_users = _parse_local_users(raw)

    # SNMP (Phase 2b) — v2c community + system-location / system-contact
    # + v3 USM users.
    intent.snmp = _parse_snmp(raw)

    # Shared switchport→VLAN projection: mirror per-port switchport state
    # into the VLAN-centric tagged/untagged lists so VLAN-centric
    # renderers can emit the membership.  The phantom-VLAN guard
    # (snapshot legitimate VLAN ids before, prune after) mirrors
    # cisco_nxos — a wide ``vlan trunk allowed`` range must not inflate
    # tree.vlans with phantom records.
    legitimate_vlan_ids = {v.id for v in intent.vlans}
    from ...canonical.transforms import project_switchport_to_vlan
    project_switchport_to_vlan(intent)
    intent.vlans = [v for v in intent.vlans if v.id in legitimate_vlan_ids]

    logger.debug(
        "aruba_aoscx parsed: hostname=%r ifaces=%d vlans=%d routes=%d "
        "vrfs=%d lags=%d users=%d (input=%d chars)",
        intent.hostname,
        len(intent.interfaces),
        len(intent.vlans),
        len(intent.static_routes),
        len(intent.routing_instances),
        len(intent.lags),
        len(intent.local_users),
        len(raw),
    )
    return intent


def _extract_hostname(raw: str) -> str:
    m = _HOSTNAME_RE.search(raw)
    return m.group(1) if m else ""


def _extract_version(raw: str) -> str:
    """Return the AOS-CX release string from the ``!Version`` banner.

    Stored as :attr:`CanonicalIntent.source_version` (metadata).  The
    render path synthesises a fresh banner rather than echoing this, so
    it is informational only.
    """
    m = _VERSION_RE.search(raw)
    return m.group(1) if m else ""


def _parse_routing_instances(raw: str) -> list[CanonicalRoutingInstance]:
    """Extract top-level ``vrf <name>`` declarations.

    AOS-CX creates a VRF with a bare ``vrf <name>`` line (no nested body
    in the common case — RD / route-target live under the deferred
    ``evpn`` / ``router bgp`` stanzas).  Harvests the name only.
    References such as ``ssh server vrf mgmt`` do NOT match this anchored
    single-token pattern.
    """
    instances: list[CanonicalRoutingInstance] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        m = _VRF_DECL_RE.match(line)
        if not m:
            continue
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        instances.append(CanonicalRoutingInstance(name=name))
    return instances


def _new_iface_scratch(name: str) -> dict:
    """Fresh per-interface parse-time scratch dict.

    Single source of truth for the field set so the two stanza-open sites
    in :func:`_parse_interfaces` can't drift apart.  ``enabled`` defaults
    type-aware (loopbacks up, everything else down — see
    :func:`_default_enabled`).
    """
    return {
        "name": name,
        "description": "",
        "enabled": _default_enabled(name),
        "type": _infer_type(name),
        "mtu": None,
        "ipv4": [],
        "ipv6": [],
        "vrf": "",
        "switchport_mode": None,
        "access_vlan": None,
        "trunk_allowed": [],
        "trunk_native": None,
        "lag_member_of": None,
        # Active-gateway anycast: the per-SVI `active-gateway ip <vip>`
        # mirrors into virtual_gateway_address in
        # _build_canonical_interface.
        "active_gw_ip": None,
    }


def _iface_name(m: re.Match) -> str:
    """Reconstruct the canonical interface name from an :data:`_IFACE_RE`
    match: the type token plus the optional space-separated index."""
    base = m.group(1)
    idx = m.group(2)
    return f"{base} {idx}" if idx else base


def _parse_interfaces(raw: str) -> list[CanonicalInterface]:
    """Extract ``interface <name>`` stanzas from AOS-CX config text.

    Per interface: description, admin-state (``no shutdown`` / ``shutdown``
    over the type-aware default), mtu, IPv4 (CIDR), IPv6 (CIDR + scope),
    VRF membership (``vrf attach``), the L2 switchport surface (``no
    routing`` + ``vlan access`` / ``vlan trunk``), and LAG membership
    (``lag N``).  ``interface lag N`` IS materialised as a kind-``lag``
    interface (it carries the LAG's switchport config).  ``interface
    vxlan N`` is intercepted and NOT materialised (the VTEP is a VXLAN
    config container — a later phase), mirroring cisco_nxos's ``nve1``
    interception.
    """
    lines = raw.splitlines()
    interfaces: list[CanonicalInterface] = []
    current: dict | None = None

    def _flush() -> None:
        if current is not None:
            interfaces.append(_build_canonical_interface(current))

    def _open(m: re.Match) -> dict | None:
        """Return a fresh scratch for an interface header, or None for the
        ``vxlan`` kind (a later phase)."""
        name = _iface_name(m)
        if name.lower().startswith("vxlan "):
            return None
        return _new_iface_scratch(name)

    for line in lines:
        m = _IFACE_RE.match(line)
        if m:
            _flush()
            current = _open(m)
            continue

        if current is None:
            continue

        # Non-indented line closes the current stanza.
        if line and not line[0].isspace():
            _flush()
            current = None
            m = _IFACE_RE.match(line)
            if m:
                current = _open(m)
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

        vm = _VRF_ATTACH_RE.match(line)
        if vm:
            current["vrf"] = vm.group(1)
            continue

        # ── Active-gateway anycast (Phase 3) ──
        # The `active-gateway ip mac` line is consumed here (the MAC is
        # harvested at intent level); `active-gateway ip <vip>` sets the
        # SVI's virtual gateway.
        if _ACTIVE_GW_MAC_RE.match(line):
            continue
        agi = _ACTIVE_GW_IP_RE.match(line)
        if agi:
            current["active_gw_ip"] = agi.group(1)
            continue

        # ── L2 switchport (Phase 2) ──
        if _NO_ROUTING_RE.match(line):
            # The L2 marker; the mode is set by the vlan lines below.
            continue
        am = _VLAN_ACCESS_RE.match(line)
        if am:
            current["switchport_mode"] = "access"
            current["access_vlan"] = int(am.group(1))
            continue
        tnm = _VLAN_TRUNK_NATIVE_RE.match(line)
        if tnm:
            current["switchport_mode"] = current["switchport_mode"] or "trunk"
            current["trunk_native"] = int(tnm.group(1))
            continue
        tam = _VLAN_TRUNK_ALLOWED_RE.match(line)
        if tam:
            current["switchport_mode"] = current["switchport_mode"] or "trunk"
            val = tam.group(1).strip()
            current["trunk_allowed"] = (
                [] if val.lower() == "all" else _parse_vlan_list(val)
            )
            continue

        # ── LAG membership (Phase 2) ── ``lag N`` on a physical port.
        lm = _LAG_MEMBER_RE.match(line)
        if lm:
            current["lag_member_of"] = f"lag {int(lm.group(1))}"
            continue

        # Any other indented line (lacp mode / spanning-tree / ip mtu /
        # active-gateway / ...) is deferred — parse-and-ignore.

    _flush()
    return interfaces


def _build_canonical_interface(raw: dict) -> CanonicalInterface:
    """Convert the parse-time scratch dict into a CanonicalInterface."""
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
                # Active-gateway anycast: the `active-gateway ip <vip>`
                # attaches to the SVI's PRIMARY (first) address.
                virtual_gateway_address=(
                    (raw.get("active_gw_ip") or "") if idx == 0 else ""
                ),
            )
            for idx, a in enumerate(raw.get("ipv4", []))
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
        switchport_mode=raw.get("switchport_mode"),
        access_vlan=raw.get("access_vlan"),
        trunk_allowed_vlans=raw.get("trunk_allowed", []),
        trunk_native_vlan=raw.get("trunk_native"),
        lag_member_of=raw.get("lag_member_of"),
    )


def _parse_lags(raw: str) -> list[CanonicalLAG]:
    """Build :class:`CanonicalLAG` records from AOS-CX config.

    Two signals, either sufficient:
      * an ``interface lag <N>`` stanza declares the LAG exists (and
        carries ``lacp mode active|passive`` — absent means a static
        LAG);
      * a ``lag <N>`` line under a physical port declares that port a
        member of ``lag <N>``.

    Mirrors ``cisco_nxos._parse_lags`` (block-walker over the interface
    stanzas).  The ``multi-chassis`` (VSX MLAG) modifier on the header is
    dropped in v1.
    """
    members_by_lag: dict[str, list[str]] = {}
    mode_by_lag: dict[str, str] = {}
    declared: set[str] = set()
    current_iface: str | None = None
    current_lag: str | None = None  # set when the current stanza is a LAG

    def _note_header(name: str) -> None:
        nonlocal current_lag
        if name.lower().startswith("lag "):
            declared.add(name)
            current_lag = name
        else:
            current_lag = None

    for line in raw.splitlines():
        m = _IFACE_RE.match(line)
        if m:
            current_iface = _iface_name(m)
            _note_header(current_iface)
            continue
        if current_iface is None:
            continue
        if line and not line[0].isspace():
            current_iface = None
            current_lag = None
            m = _IFACE_RE.match(line)
            if m:
                current_iface = _iface_name(m)
                _note_header(current_iface)
            continue
        # ``lacp mode`` on the LAG stanza itself.
        if current_lag is not None:
            lcm = _LACP_MODE_RE.match(line)
            if lcm:
                mode_by_lag[current_lag] = lcm.group(1).lower()
            continue
        # ``lag N`` membership on a (non-LAG) port stanza.
        lm = _LAG_MEMBER_RE.match(line)
        if lm:
            lag_name = f"lag {int(lm.group(1))}"
            members = members_by_lag.setdefault(lag_name, [])
            if current_iface and current_iface not in members:
                members.append(current_iface)

    lags: list[CanonicalLAG] = []
    for lag_name in sorted(declared | set(members_by_lag), key=_lag_sort_key):
        lag = CanonicalLAG(
            name=lag_name, members=list(members_by_lag.get(lag_name, [])),
        )
        # AOS-CX LAGs are static unless an explicit ``lacp mode`` is set.
        lag.mode = mode_by_lag.get(lag_name, "static")
        lags.append(lag)
    return lags


def _parse_local_users(raw: str) -> list[CanonicalLocalUser]:
    """Extract ``user <name> group <group> password ciphertext <blob>``.

    AOS-CX uses a named ``group`` (administrators / operators / auditors /
    custom) rather than a numeric privilege; the group → role maps
    directly, and ``administrators`` → privilege 15, everything else → 1
    (lossy — cross-vendor renderers expecting numeric privilege round-trip
    non-admin groups as 1).  The ``ciphertext`` blob is preserved verbatim
    in ``hashed_password`` (it is AES-encrypted with the device key, so it
    is portable only same-device; declared lossy cross-vendor).
    """
    users: list[CanonicalLocalUser] = []
    seen: set[str] = set()
    for m in _USER_RE.finditer(raw):
        name, group, blob = m.group(1), m.group(2), m.group(3)
        if name in seen:
            continue
        seen.add(name)
        users.append(CanonicalLocalUser(
            name=name,
            privilege_level=15 if group.lower() in _AOSCX_ADMIN_GROUPS else 1,
            hashed_password=blob,
            role=group,
        ))
    return users


def _parse_snmp(raw: str) -> CanonicalSNMP | None:
    """Extract SNMP config from AOS-CX text (v2c community + v3 USM).

    AOS-CX diverges from NX-OS: ``snmp-server system-location`` /
    ``system-contact`` (not ``location`` / ``contact``), and a ``snmpv3
    user`` block whose auth / priv keys are ``<ciphertext|plaintext>
    <blob>``.  The auth protocol is lower-cased; the privacy cipher is
    lower-cased too (``des`` / ``aes``).  Returns ``None`` when no SNMP
    lines are present so the tree doesn't carry an empty stub.  Trap
    hosts (``snmp-server host``) and the ``snmp-server vrf`` binding are
    deferred (parse-and-ignore).
    """
    community_m = _SNMP_COMMUNITY_RE.search(raw)
    location_m = _SNMP_LOCATION_RE.search(raw)
    contact_m = _SNMP_CONTACT_RE.search(raw)
    v3_matches = list(_SNMPV3_USER_RE.finditer(raw))
    if not (community_m or location_m or contact_m or v3_matches):
        return None
    snmp = CanonicalSNMP()
    if community_m:
        snmp.community = community_m.group(1).strip()
    if location_m:
        snmp.location = location_m.group(1).strip().strip('"')
    if contact_m:
        snmp.contact = contact_m.group(1).strip().strip('"')
    for m in v3_matches:
        name, auth_p, auth_pw, priv_p, priv_pw = m.groups()
        snmp.v3_users.append(CanonicalSNMPv3User(
            name=name,
            auth_protocol=(auth_p or "").lower(),
            auth_passphrase=auth_pw or "",
            priv_protocol=(priv_p or "").lower(),
            priv_passphrase=priv_pw or "",
        ))
    return snmp


def _parse_vlans(raw: str) -> list[CanonicalVlan]:
    """Extract VLAN definitions from AOS-CX config text.

    AOS-CX declares one VLAN id per line (``vlan 101``) optionally
    followed by indented ``name`` / ``description`` sub-commands.  De-
    duplicated by id, preserving first-seen order.
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

    current_id: int | None = None
    for line in raw.splitlines():
        tm = _VLAN_TOP_RE.match(line)
        if tm:
            vid = int(tm.group(1))
            if 1 <= vid <= 4094:
                _touch(vid)
                current_id = vid
            else:
                current_id = None
            continue

        if current_id is not None:
            nm = _VLAN_NAME_RE.match(line)
            if nm:
                _touch(current_id).name = nm.group(1).strip()
                continue
            dm = _VLAN_DESC_RE.match(line)
            if dm:
                _touch(current_id).description = dm.group(1).strip()
                continue
            # Any non-indented line closes the stanza.
            if line and not line[0].isspace():
                current_id = None

    return [vlans_by_id[vid] for vid in order]


def _synthesize_vlans_from_svis(intent: CanonicalIntent) -> None:
    """Derive VLAN records from ``interface vlan <N>`` SVIs.

    Mirrors ``cisco_nxos._synthesize_vlans_from_svis``: an SVI whose VLAN
    has no top-level ``vlan`` stanza still implies the VLAN exists (and
    carries its L3 config), so create / merge a record.
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
    """Extract top-level ``ip route`` lines (default VRF) from AOS-CX text.

    AOS-CX form: ``ip route <dest>/<prefix> <gw> [<dist>]``.  The trailing
    integer (if present) is the administrative distance and maps to
    :attr:`CanonicalStaticRoute.metric`.  A next-hop that parses as an
    IPv4 address becomes ``gateway``; otherwise it's an egress
    ``interface``.  Per-VRF static routes are deferred (declared
    unsupported).
    """
    routes: list[CanonicalStaticRoute] = []
    for line in raw.splitlines():
        m = _STATIC_ROUTE_RE.match(line)
        if not m:
            continue
        dest_ip, prefix, gw_or_iface, metric_str = m.groups()
        metric = int(metric_str) if metric_str else 0
        gateway = ""
        iface = ""
        try:
            ipaddress.IPv4Address(gw_or_iface)
            gateway = gw_or_iface
        except ipaddress.AddressValueError:
            iface = gw_or_iface
        routes.append(CanonicalStaticRoute(
            destination=f"{dest_ip}/{prefix}",
            gateway=gateway,
            interface=iface,
            metric=metric,
        ))
    return routes
