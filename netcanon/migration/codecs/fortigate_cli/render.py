"""
FortiGate CLI renderer — canonical tree to FortiOS ``config / edit /
set / next / end`` text.

Extracted from ``codec.py`` during the parse/render split.  Public
surface (consumed by codec.py's ``render()`` method):

* :func:`render_intent` — one-shot render: ``CanonicalIntent`` in,
  FortiOS CLI string out.

The render emits blocks in the same order operator workflows expect
from a FortiOS export: ``system global`` → ``system dns`` →
``system ntp`` → ``system interface`` (including nested
``config vrrp / edit N / set vrip / set priority / set preempt /
set adv-interval / set authentication / set status / next / end``
for **VRRP groups** on the interface) → ``system snmp`` →
``system admin`` → ``user radius`` → ``system dhcp server`` →
``router static``.  Ordering is stable for diff-friendliness.
Multi-VIP cross-vendor sources and non-``vrrp`` modes (HSRP / CARP)
surface as ``# review:`` comments inside the interface edit body.

Defaults that FortiOS omits on export (e.g. ``set radius-port 1812``,
``set mtu 1500``) are NOT emitted here so our renders round-trip
against real exports — see comments inline for the specific
default-omission choices.

Shares IP-mask utilities (``_prefix_to_mask`` / ``_split_cidr``) and
the canonical→FortiGate LACP-mode map with :mod:`.parse` — those
live in the parse module and are imported here to avoid duplication.
VLAN-naming helpers (``_looks_like_vlan_iface``, ``_vlan_id_for``,
``_parent_for_vlan_iface``) come from :mod:`.vlan_heuristics`.

Empty-stub elision (Finding 8 in user_smoke_findings.md) mirrors the
Junos tiered policy: cross-vendor sources frequently leave empty
canonical-interface stubs after port-rename (OPNsense ``igc0`` WAN
with ``<ipaddr>dhcp</ipaddr>`` parses to a content-free
:class:`CanonicalInterface`).  We elide those when their NAME doesn't
match a FortiGate-native physical-port shape — preserving same-vendor
round-trip stability while suppressing foreign-vendor leaks.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from ..base import RenderError
from ..._user_secrets import (
    classify_hash,
    format_review_comment,
    is_migratable,
)
from ...canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
)
from .parse import (
    _CANONICAL_MODE_TO_FORTIGATE_LACP,
    _prefix_to_mask,
    _split_cidr,
)
from .vlan_heuristics import (
    looks_like_vlan_iface as _looks_like_vlan_iface,
    parent_for_vlan_iface as _parent_for_vlan_iface_fallback,
    vlan_id_for as _vlan_id_for,
)


# RFC1918 private-IPv4 prefixes — used by the LAN-preference scorer
# in ``_parent_for_vlan_iface`` to spot canonical interfaces that
# look like the operator's LAN side (vs. the WAN, which is typically
# a public/DHCP-assigned address or no address at all).
_RFC1918_NETWORKS = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)


def _has_private_ipv4(iface: CanonicalInterface) -> bool:
    """Return True when *iface* has at least one RFC1918 IPv4
    address.  Used as a LAN-side signal in the VLAN-parent scorer."""
    for addr in iface.ipv4_addresses:
        try:
            ip = ipaddress.IPv4Address(addr.ip)
        except (ipaddress.AddressValueError, ValueError):
            continue
        for net in _RFC1918_NETWORKS:
            if ip in net:
                return True
    return False


def _port_index_for(name: str) -> int:
    """Extract the trailing numeric index from a port-shape name
    (e.g. ``port5`` -> 5, ``wan2`` -> 2, ``ixl0`` -> 0).  Returns 0
    when no trailing digits are present.  Used as a tiebreaker in the
    VLAN-parent scorer — higher port-index ports are slightly less
    likely to be the WAN (which conventionally lands on port1/wan1)."""
    m = re.search(r"(\d+)$", name)
    return int(m.group(1)) if m else 0


def _parent_for_vlan_iface(
    name: str,
    deduped_ifaces: list[CanonicalInterface],
) -> str | None:
    """Resolve the parent physical interface for a VLAN sub-interface
    with a deterministic LAN-preference scorer.

    Finding 21 (``user_smoke_findings.md``): the original
    :func:`vlan_heuristics.parent_for_vlan_iface` walks
    *deduped_ifaces* post-elision and picks the first non-VLAN match.
    With OPNsense source where ``igc0`` (WAN, DHCP-client) and
    ``port1`` (LAN, ixl0-renamed with a static RFC1918 address) both
    survive elision, the legacy iteration ordering picks WAN first —
    wrong.

    Scoring scheme (per candidate):

    * ``+10`` — has a private RFC1918 IPv4 (192.168/16, 10/8, 172.16/12)
    * ``+5``  — has L2 trunk semantics (``trunk_allowed_vlans`` set)
    * ``-5``  — ``dhcp_client=True`` (likely the WAN)

    These are the *signal* components.  A candidate's port-index
    (trailing digits in the name) is layered in as a deterministic
    tiebreaker — when two candidates tie on signal score, the higher
    port-index wins (WAN is conventionally on ``port1`` / ``wan1``,
    so a higher index is slightly less WAN-like).  Port-index is
    NEVER allowed to *create* a positive score on its own — that
    would silently change the legacy first-non-VLAN fallback
    behaviour for signal-free trees and break round-trip stability
    on existing tests.

    When NO candidate has any positive signal (signal score <= 0 on
    every iface), fall back to
    :func:`vlan_heuristics.parent_for_vlan_iface` for byte-identity
    backward compatibility — pre-Finding-21 behaviour for canonical
    trees with bare-stub interfaces and no LAN/WAN discriminators.

    The dotted-form fast path (``port1.10`` -> parent ``port1``) is
    delegated to the fallback helper so a single source of truth
    handles dotted-form parents.
    """
    # Dotted-form fast path delegates to the legacy helper.
    if "." in name:
        return _parent_for_vlan_iface_fallback(name, deduped_ifaces)

    candidates = [
        i for i in deduped_ifaces
        if not _looks_like_vlan_iface(i.name)
        and i.interface_type != "ianaift:l3ipvlan"
    ]
    if not candidates:
        return _parent_for_vlan_iface_fallback(name, deduped_ifaces)

    scored: list[tuple[int, int, int, int, str]] = []
    for idx, cand in enumerate(candidates):
        signal = 0
        if _has_private_ipv4(cand):
            signal += 10
        if cand.trunk_allowed_vlans:
            signal += 5
        if cand.dhcp_client:
            signal -= 5
        port_idx = _port_index_for(cand.name)
        # Sort key (lowest first wins because we negate signal):
        #   1. -signal       (highest signal first)
        #   2. -port_idx     (highest port-index first as tiebreaker)
        #   3. idx           (enumeration order — final deterministic
        #                     tiebreaker for byte-identity)
        scored.append((-signal, -port_idx, idx, signal, cand.name))

    scored.sort()
    top = scored[0]
    # If the top candidate has zero or negative signal, no candidate
    # has positive LAN evidence — preserve the legacy first-non-VLAN
    # fallback so signal-free trees keep their pre-Finding-21
    # ordering (existing tests pin port1 over port2 in this state).
    if top[3] <= 0:
        return _parent_for_vlan_iface_fallback(name, deduped_ifaces)
    return top[4]


def _build_vlan_children(
    tree: CanonicalIntent,
    deduped_ifaces: list[CanonicalInterface],
) -> list[dict]:
    """Build the VLAN-on-parent child interface list (Issue #6).

    For every canonical VLAN, synthesise a FortiOS-style child
    entry that the renderer emits inside ``config system interface``
    as ``edit "vlan<id>" / set type vlan / set vlanid <id> / set
    interface "<parent>" / set ip <addr> <mask>``.

    Resolution rules:

    * **Parent** -- first :class:`CanonicalLAG` on the tree (operators
      almost always trunk VLANs over a LAG); fall back to the first
      non-VLAN-shaped, non-empty-stub interface in *deduped_ifaces*
      if no LAG exists; ``None`` when neither candidate is available.
      Preferring an interface that carries L3 / L2 content over a
      bare WAN stub matters for OPNsense sources where the WAN is a
      DHCP-only ``igc0`` with no canonical content (Finding 6 in
      ``user_smoke_findings.md``); the bare stub gets elided by the
      caller before this function runs, so the fallback naturally
      lands on the LAN port.

    * **SVI IP** resolution order:
        1. ``CanonicalVlan.ipv4_addresses`` directly (Cisco-source
           parsers merge ``interface Vlan<N>`` IPs into the VLAN
           record; FortiGate-source round-trip carries the IP via
           the vlan child interface).
        2. Sibling interface whose VLAN id resolves to the same
           ``vlan.id``.  Covers cross-vendor sources where the SVI
           IP lives on a separate interface record:
            * Cisco-style ``Vlan<id>`` (already merged into
              ``vlan.ipv4_addresses`` by the cisco parser; this
              fallback covers paths that bypass that merge).
            * OPNsense-style ``vlan0.<id>`` dotted form (Finding 5
              in ``user_smoke_findings.md`` — opt1-opt5 zones store
              the SVI IP on a ``CanonicalInterface`` named after
              the OPNsense ``<vlanif>`` rather than merging into
              the VLAN record).
            * FortiGate-native ``vlan<id>`` from cross-vendor
              translation through :func:`format_port_identity`.

    Returns a list of dicts with keys ``name``, ``vlanid``,
    ``parent``, ``ip``, ``mask`` -- empty list when *tree.vlans* is
    empty.  Caller filters out names that already appear in
    *deduped_ifaces* (intra-vendor round-trip pre-emits them).
    """
    if not tree.vlans:
        return []

    parent_name = None
    if tree.lags:
        parent_name = tree.lags[0].name
    if parent_name is None:
        # Finding 21: route synthesised VLAN children through the
        # LAN-preference scorer so OPNsense-style sources where both
        # WAN (``igc0``, dhcp_client) and LAN (``port1``, RFC1918
        # static) survive elision anchor on the LAN.  The synthetic
        # child names are ``vlan<id>`` (no dot) so the scorer's
        # signal-based ranking applies — dotted-form fast path is
        # not relevant here.
        parent_name = _parent_for_vlan_iface("vlan", deduped_ifaces)

    iface_by_name = {i.name: i for i in deduped_ifaces}

    # Pre-build a {vlan_id -> first matching iface} index from the
    # canonical interface list.  Walking interfaces by ``_vlan_id_for``
    # covers every cross-vendor SVI iface shape (Cisco ``Vlan11``,
    # OPNsense ``vlan0.10``, FortiGate-native ``vlan10`` after
    # rename) without per-shape special cases.
    iface_by_vlan_id: dict[int, CanonicalInterface] = {}
    for cand in deduped_ifaces:
        if not cand.ipv4_addresses:
            continue
        cand_vid = _vlan_id_for(cand.name, tree.vlans)
        if cand_vid is not None and cand_vid not in iface_by_vlan_id:
            iface_by_vlan_id[cand_vid] = cand

    children = []
    for vlan in tree.vlans:
        ip = ""
        mask = ""
        if vlan.ipv4_addresses:
            addr = vlan.ipv4_addresses[0]
            ip = addr.ip
            try:
                mask = _prefix_to_mask(addr.prefix_length)
            except Exception:
                mask = ""
        else:
            # Step 2a: Cisco/FortiGate-native exact-name lookup
            # (kept as fast-path for clarity even though the vlan-id
            # walk below would also catch these).
            for cand_name in (f"Vlan{vlan.id}", f"vlan{vlan.id}"):
                cand = iface_by_name.get(cand_name)
                if cand and cand.ipv4_addresses:
                    addr = cand.ipv4_addresses[0]
                    ip = addr.ip
                    try:
                        mask = _prefix_to_mask(addr.prefix_length)
                    except Exception:
                        mask = ""
                    break
            # Step 2b: walk by resolved vlan_id for foreign SVI
            # iface shapes (OPNsense ``vlan0.<id>`` etc.).
            if not ip:
                cand = iface_by_vlan_id.get(vlan.id)
                if cand and cand.ipv4_addresses:
                    addr = cand.ipv4_addresses[0]
                    ip = addr.ip
                    try:
                        mask = _prefix_to_mask(addr.prefix_length)
                    except Exception:
                        mask = ""

        children.append({
            "name": f"vlan{vlan.id}",
            "vlanid": vlan.id,
            "parent": parent_name,
            "ip": ip,
            "mask": mask,
        })
    return children


# FortiGate-native physical-port name shapes.  Used by the empty-
# stub elision predicate to decide whether a content-free canonical
# iface is "really there" (FortiOS-source intra-vendor round-trip
# shapes) and therefore needs the bare ``edit "<name>" / set status
# up / next`` block, vs. a cross-vendor leak (``igc0``, ``ge-0/0/0``)
# that should be suppressed entirely.  Mirrors the Junos tiered
# elision policy from ``juniper_junos/render.py`` (commit ``0fdf7e9``).
#
# Patterns:
#   * ``port<N>``                      -- generic FG-100F+ numbering
#   * ``port-<stack>-<module>-<port>`` -- multi-axis disambiguator
#                                         (Cisco c9300 source path)
#   * ``mgmt`` / ``mgmt<N>``           -- out-of-band management
#   * ``wan<N>`` / ``lan`` / ``lan<N>`` -- role-coded physical
#   * ``dmz<N>`` / ``ha<N>`` / ``modem<N>``
#   * ``internal`` / ``internal<N>``   -- hw-switch member / aggregate
#   * ``vlan<N>``                      -- vlan child interface
#   * ``loopback<N>``
#   * ``fortilink`` / ``fortilink<N>`` -- NPU-fastpath default
#   * ``a`` / ``b``                    -- FG-60F/61F bare letters
#   * ``ssl.root``                     -- SSL-VPN root tunnel
#   * ``gre<N>``                       -- GRE tunnel
_IS_FORTIGATE_PHYSICAL_PORT_RE = re.compile(
    r"^(?:"
    r"port(?:\d+|-\d+-\d+-\d+)"   # port1, port-1-1-1
    r"|mgmt\d*"
    r"|wan\d*"
    r"|lan\d*"
    r"|dmz\d*"
    r"|ha\d*"
    r"|modem\d*"
    r"|internal\d*"
    r"|vlan\d+"
    r"|loopback\d+"
    r"|fortilink\d*"
    r"|[ab]"
    r"|ssl\.root"
    r"|gre\d+"
    r")$",
    re.IGNORECASE,
)


def _iface_is_empty_stub(iface: CanonicalInterface) -> bool:
    """Return True when *iface* carries zero renderable canonical
    content (no IP, no description, no MTU override, no L2/LAG/VLAN
    state, no VRF binding) AND the source codec didn't bother
    populating ``interface_type`` (a strong signal of "foreign
    source that left the type empty because its grammar doesn't
    distinguish here" -- OPNsense parser is the canonical example).

    Such stubs leak across vendor boundaries: OPNsense's WAN
    ``<wan><if>igc0</if><ipaddr>dhcp</ipaddr></wan>`` parses to a
    bare canonical iface with ``enabled=True``, ``interface_type=""``
    and nothing else, because OPNsense's ``dhcp`` keyword isn't
    representable as a static :class:`CanonicalIPv4Address`.  After
    cross-vendor port rename the foreign name (``igc0``) survives
    verbatim because FortiGate has no role to map it to, producing
    ``edit "igc0" / set status up / next`` blocks in the output.
    These blocks are pure noise on the FortiGate side -- the operator
    wants the target's native WAN port (``port1`` / ``wan1``) instead.

    Any non-empty ``interface_type`` (L2 / L3 / LAG / loopback /
    tunnel / ethernetCsmacd / etc.) means the source codec made a
    deliberate choice about what this iface is, and intra-vendor
    round-trip stability requires us to preserve it -- e.g. FortiGate
    source ``ssl.root`` / ``l2t.root`` / ``default-mesh`` parse with
    ``interface_type="ianaift:ethernetCsmacd"`` and zero per-iface
    attrs; eliding them would silently drop the SD-WAN / SSL-VPN /
    wireless-mesh objects from a FortiGate -> FortiGate round-trip.
    """
    if iface.interface_type:
        return False
    return not (
        iface.description
        or iface.ipv4_addresses
        or iface.ipv6_addresses
        or iface.mtu is not None
        or iface.switchport_mode
        or iface.access_vlan is not None
        or iface.trunk_allowed_vlans
        or iface.lag_member_of
        or iface.vrf
        or iface.dhcp_client
        or (not iface.enabled)        # explicit shutdown is meaningful
    )


def _is_fortigate_native_name(name: str) -> bool:
    """Return True when *name* matches a FortiOS-native interface
    shape (physical port, mgmt, vlan child, loopback, tunnel).

    Used to decide whether a content-free interface should be
    preserved for round-trip stability (FortiGate-native names) or
    elided as a cross-vendor leak (foreign names like ``igc0``,
    ``ge-0/0/0``, ``ether1``).
    """
    return bool(_IS_FORTIGATE_PHYSICAL_PORT_RE.match(name))


def render_intent(tree: Any) -> str:
    """Render a :class:`CanonicalIntent` tree to FortiOS CLI text.

    Raises:
        RenderError: If *tree* is not a :class:`CanonicalIntent` (mock
            adapters produce other shapes).
    """
    if not isinstance(tree, CanonicalIntent):
        raise RenderError(
            "fortigate_cli: tree must be a CanonicalIntent.",
            yang_path="/",
        )

    out: list[str] = []
    out.append("#config-version=netcanon-translator")

    # --- system global ---
    if tree.hostname:
        out.append("config system global")
        out.append(f'    set hostname "{tree.hostname}"')
        out.append("end")

    # --- system dns ---
    # ``set domain "<fqdn>"`` is the FortiOS-native domain-name
    # configuration form, sitting alongside the primary / secondary
    # resolver IPs inside ``config system dns``.  Single-domain
    # canonical (``CanonicalIntent.domain``) renders as a one-entry
    # ``set domain "<value>"`` line; FortiOS accepts a comma-
    # separated list for multi-domain DNS suffix search but the
    # canonical model only carries one (Finding 12 in
    # ``user_smoke_findings.md``).  Emit the ``config system dns``
    # block when EITHER DNS resolvers OR the domain are populated
    # so a domain-only OPNsense source (DNS resolution provided by
    # upstream WAN DHCP) still surfaces the FQDN suffix.
    # Reference: docs.fortinet.com/document/fortigate/7.6.6/cli-
    # reference/190194324/config-system-dns.
    if tree.dns_servers or tree.domain:
        out.append("config system dns")
        if len(tree.dns_servers) >= 1:
            out.append(f"    set primary {tree.dns_servers[0]}")
        if len(tree.dns_servers) >= 2:
            out.append(f"    set secondary {tree.dns_servers[1]}")
        if tree.domain:
            out.append(f'    set domain "{tree.domain}"')
        out.append("end")

    # --- system ntp (nested subtable) ---
    if tree.ntp_servers:
        out.append("config system ntp")
        out.append("    set ntpsync enable")
        out.append("    config ntpserver")
        for idx, server in enumerate(tree.ntp_servers, start=1):
            out.append(f"        edit {idx}")
            out.append(f'            set server "{server}"')
            out.append("        next")
        out.append("    end")
        out.append("end")

    # --- system interface ---
    # Build a quick lookup: which interface names are LAG aggregates?
    lag_by_name: dict[str, CanonicalLAG] = {
        lag.name: lag for lag in tree.lags
    }
    # Also: which names aren't in intent.interfaces but ARE LAGs
    # from intent.lags?  Synthesize interface edits for them so
    # the FortiOS config is self-consistent.
    existing_iface_names = {i.name for i in tree.interfaces}
    synthetic_lag_ifaces = [
        CanonicalInterface(
            name=lag.name,
            interface_type="ianaift:ieee8023adLag",
            enabled=True,
        )
        for lag in tree.lags
        if lag.name not in existing_iface_names
    ]
    all_ifaces = list(tree.interfaces) + synthetic_lag_ifaces

    # Render-time port-name collision guard (Issue #2 from
    # tests/fixtures/real/user_smoke_findings.md).  Belt-and-braces
    # alongside the multi-axis disambiguation in
    # :func:`port_names.format_port_identity`.  We dedup by emission
    # order -- first occurrence wins, later collisions get a
    # ``# port collision: ...`` comment instead of a duplicate
    # ``edit "..."`` block (which FortiOS rejects on commit).
    #
    # Empty-stub elision (Finding 8 in
    # tests/fixtures/real/user_smoke_findings.md) folds in here:
    # cross-vendor sources that leave content-free ifaces with
    # foreign names (OPNsense ``igc0`` WAN -> DHCP-only stub;
    # Junos-source ``ge-0/0/0`` mgmt-vrf shell) get suppressed
    # entirely.  FortiGate-native names (``port1``, ``mgmt``,
    # ``vlan10``) keep the bare ``edit "<name>" / set status ... /
    # next`` block for same-vendor round-trip stability.  The
    # predicate uses the tiered policy from Junos (commit
    # ``0fdf7e9``): empty AND not native -> elide.
    seen_iface_names = set()
    deduped_ifaces = []
    collision_comments = []
    for iface in all_ifaces:
        if iface.name in seen_iface_names:
            collision_comments.append(
                f"# port collision: {iface.name} already emitted earlier; "
                f"duplicate dropped -- review source names for unique mapping"
            )
            continue
        # Cross-vendor empty-stub leak (Finding 8): foreign-shaped
        # name with no canonical content -> elide so the rendered
        # output isn't polluted by the source vendor's port-naming
        # leaking through verbatim.
        if (
            _iface_is_empty_stub(iface)
            and not _is_fortigate_native_name(iface.name)
            and iface.name not in lag_by_name
        ):
            continue
        seen_iface_names.add(iface.name)
        deduped_ifaces.append(iface)

    # VLAN child interface synthesis (Issue #6).
    vlan_children = _build_vlan_children(tree, deduped_ifaces)
    existing_vlan_ids = set()
    for cand in deduped_ifaces:
        vid = _vlan_id_for(cand.name, tree.vlans)
        if vid is not None:
            existing_vlan_ids.add(vid)
    vlan_children = [
        v for v in vlan_children
        if v["name"] not in seen_iface_names
        and v["vlanid"] not in existing_vlan_ids
    ]

    if deduped_ifaces or vlan_children:
        out.append("config system interface")
        for c in collision_comments:
            out.append(f"    {c}")
        for iface in deduped_ifaces:
            out.append(f'    edit "{iface.name}"')
            if iface.description:
                # FortiOS alias caps at 25 chars per spec.
                alias = iface.description[:25]
                out.append(f'        set alias "{alias}"')
            # LAG aggregate marker takes precedence over VLAN.
            lag = lag_by_name.get(iface.name)
            if lag is not None:
                out.append("        set type aggregate")
                if lag.members:
                    quoted = " ".join(f'"{m}"' for m in lag.members)
                    out.append(f"        set member {quoted}")
                out.append(
                    f"        set lacp-mode "
                    f"{_CANONICAL_MODE_TO_FORTIGATE_LACP.get(lag.mode, 'active')}"
                )
            elif (
                iface.interface_type == "ianaift:l3ipvlan"
                or _looks_like_vlan_iface(iface.name)
            ):
                # VLAN identification can come from either signal —
                # canonical interface_type OR FortiGate-native
                # name convention.  Real configs name VLAN ifaces
                # freely (VL_100, DATA, etc.) so name alone isn't
                # sufficient.
                vid = _vlan_id_for(iface.name, tree.vlans)
                # Use the elided iface list (post-stub-removal) so
                # the parent fallback prefers a real LAN port over a
                # bare WAN stub like OPNsense's ``igc0`` (Finding 6
                # in user_smoke_findings.md).  The pre-elision tree
                # still has ``igc0`` as its first iface, which would
                # incorrectly anchor every VLAN child to the WAN.
                parent = _parent_for_vlan_iface(iface.name, deduped_ifaces)
                if vid is not None:
                    out.append("        set type vlan")
                    out.append(f"        set vlanid {vid}")
                    if parent:
                        out.append(f'        set interface "{parent}"')
            if iface.ipv4_addresses:
                addr = iface.ipv4_addresses[0]
                mask = _prefix_to_mask(addr.prefix_length)
                out.append(f"        set ip {addr.ip} {mask}")
                out.append("        set mode static")
            elif iface.dhcp_client:
                # Finding 20 (``user_smoke_findings.md``): foreign
                # DHCP-client interfaces (OPNsense ``<ipaddr>dhcp
                # </ipaddr>`` parsed to ``CanonicalInterface.dhcp_client
                # =True`` in commit ``c16d2c0``) need FortiOS's
                # ``set mode dhcp`` line so the WAN port is configured
                # as a DHCP client rather than a static-mode interface
                # with no IP.  Reference: docs.fortinet.com/document/
                # fortigate/7.6.6/cli-reference/190194324/config-
                # system-interface ``set mode {static | dhcp}``.
                # Mutual exclusion with the static branch is enforced
                # by the ``elif`` — when both are set on the canonical
                # tree (a contradictory state the schema technically
                # permits), the static path wins.  FortiOS treats the
                # explicit ``set ip`` as the dominant source so this
                # is the safe-deploy choice.
                out.append("        set mode dhcp")
            # GAP-EVPN-3: IPv6 addresses.  FortiOS uses CIDR
            # natively (``set ip6-address <addr>/<prefix>``); only
            # one v6 address per interface fits the FortiOS schema.
            if iface.ipv6_addresses:
                v6 = iface.ipv6_addresses[0]
                out.append(
                    f"        set ip6-address {v6.ip}/{v6.prefix_length}"
                )
            # IPv6 dynamic-address mode.  FortiOS accepts ``set
            # ip6-mode {static|dhcp|delegated|pppoe}``; only the
            # ``dhcp`` form maps cleanly from the canonical
            # ``dhcp_client_v6 == "dhcp6"`` value.  SLAAC has no
            # explicit FortiOS keyword (the autoconfig is the
            # kernel default when no static address is present);
            # other values drop to a comment.
            if iface.dhcp_client_v6 == "dhcp6":
                out.append("        set ip6-mode dhcp")
            elif iface.dhcp_client_v6 not in ("", "dhcp6", "slaac"):
                out.append(
                    f"        ! review: dhcp_client_v6="
                    f"{iface.dhcp_client_v6} has no FortiOS equivalent"
                )
            if iface.mtu is not None:
                # FortiOS requires mtu-override enable before
                # set mtu has effect on physical ports.  Emit
                # both so the config is deployable.
                out.append("        set mtu-override enable")
                out.append(f"        set mtu {iface.mtu}")
            if iface.enabled:
                out.append("        set status up")
            else:
                out.append("        set status down")
            # VRRP groups (Wave B) — nested ``config vrrp / edit N ...
            # next / end`` block lives INSIDE the interface edit, after
            # the per-iface settings and BEFORE the closing ``next``.
            # Mirrors FortiOS's own export ordering so a parse-render-
            # parse round-trip is stable on real captures.  Indentation
            # is 8 spaces for the ``config vrrp`` line (one level deep
            # inside the iface body) and 12 spaces for the inner ``edit``
            # contents — matching the codec's existing 4-space-per-level
            # convention.
            #
            # ``mode`` discriminator handling: only ``"vrrp"`` (IETF
            # VRRPv2 / VRRPv3) round-trips into FortiOS.  HSRP / CARP
            # groups from cross-vendor sources surface as a comment-form
            # ``review:`` line per the shared hash-portability pattern
            # (``user_secrets.format_review_comment``).  An operator
            # migrating from Cisco HSRP to FortiGate must reauthor the
            # group with VRRP semantics — the wire protocols are not
            # interoperable.
            #
            # Multi-IP guard: FortiOS schema accepts a single ``set
            # vrip``.  Canonical ``virtual_ips`` can hold multiple
            # entries (IOS-XE repeated ``vrrp N ip X``, Junos
            # ``virtual-address [X Y Z]``).  We emit the first and
            # leave a ``! review:`` line naming the dropped tail so the
            # operator sees the loss explicitly rather than discovering
            # it at deploy time.
            if iface.vrrp_groups:
                out.append("        config vrrp")
                for group in iface.vrrp_groups:
                    if group.mode != "vrrp":
                        out.append(
                            f"        # review: vrrp_groups[{group.group_id}]"
                            f" mode={group.mode!r} has no FortiOS "
                            f"equivalent — VRRP is the only L3 redundancy "
                            f"protocol on FortiOS"
                        )
                        continue
                    out.append(f"            edit {group.group_id}")
                    if group.virtual_ips:
                        out.append(
                            f"                set vrip {group.virtual_ips[0]}"
                        )
                        if len(group.virtual_ips) > 1:
                            extra = ", ".join(group.virtual_ips[1:])
                            out.append(
                                f"                # review: FortiOS "
                                f"accepts one vrip per group; additional "
                                f"virtual_ips dropped: {extra}"
                            )
                    if group.virtual_ipv6s:
                        out.append(
                            f"                set vrip6 "
                            f"{group.virtual_ipv6s[0]}"
                        )
                        # ``set version 3`` is FortiOS's VRRPv3 enabler
                        # — required when vrip6 is set.  VRRPv2 is IPv4-
                        # only by spec; presence of vrip6 implies v3.
                        out.append("                set version 3")
                    if group.priority != 100:
                        out.append(
                            f"                set priority {group.priority}"
                        )
                    # FortiOS preempt default is ``enable``; emit only
                    # when the canonical diverges from the FortiOS default
                    # so round-trip output stays minimal.
                    if not group.preempt:
                        out.append("                set preempt disable")
                    if group.advertisement_interval != 1:
                        out.append(
                            f"                set adv-interval "
                            f"{group.advertisement_interval}"
                        )
                    if group.authentication.startswith("plain:"):
                        out.append(
                            f'                set authentication '
                            f'"{group.authentication[6:]}"'
                        )
                    if group.track_interfaces:
                        # FortiOS ``set vrdst`` is single-valued; emit
                        # the first and drop the rest with a review note.
                        out.append(
                            f"                set vrdst "
                            f"{group.track_interfaces[0]}"
                        )
                        if len(group.track_interfaces) > 1:
                            extra = ", ".join(group.track_interfaces[1:])
                            out.append(
                                f"                # review: FortiOS "
                                f"accepts one vrdst per group; additional "
                                f"track_interfaces dropped: {extra}"
                            )
                    out.append("                set status enable")
                    out.append("            next")
                out.append("        end")
            out.append("    next")

        # VLAN child interface emit (Issue #6).
        for child in vlan_children:
            out.append(f'    edit "{child["name"]}"')
            out.append("        set type vlan")
            out.append(f'        set vlanid {child["vlanid"]}')
            if child.get("parent"):
                out.append(f'        set interface "{child["parent"]}"')
            if child.get("ip") and child.get("mask"):
                out.append(f'        set ip {child["ip"]} {child["mask"]}')
                out.append("        set mode static")
            out.append("    next")
        out.append("end")

    # --- system snmp (Tier 2) ---
    if tree.snmp is not None and (
        tree.snmp.community or tree.snmp.location
        or tree.snmp.contact or tree.snmp.trap_hosts
        or tree.snmp.v3_users
    ):
        out.append("config system snmp sysinfo")
        out.append("    set status enable")
        if tree.snmp.location:
            out.append(f'    set location "{tree.snmp.location}"')
        if tree.snmp.contact:
            out.append(f'    set contact-info "{tree.snmp.contact}"')
        out.append("end")
        # FortiOS nests trap targets inside ``config system snmp
        # community / config hosts`` — there is no top-level "trap
        # destinations" surface independent of a community record.  When
        # the canonical tree carries trap_hosts but no community (e.g.
        # cross-vendor sources where SNMPv3 is the primary monitoring
        # path and v2c is suppressed), synthesise a minimal ``public``
        # community so the trap-target list still survives the render.
        # Without this fallback, ``trap_hosts`` silently drops on
        # render-side and the operator's monitoring stops working.
        if tree.snmp.community or tree.snmp.trap_hosts:
            out.append("config system snmp community")
            out.append("    edit 1")
            community_name = tree.snmp.community or "public"
            out.append(f'        set name "{community_name}"')
            if tree.snmp.trap_hosts:
                out.append("        config hosts")
                for idx, host in enumerate(tree.snmp.trap_hosts, start=1):
                    out.append(f"            edit {idx}")
                    out.append(f'                set ip "{host} 255.255.255.255"')
                    out.append("            next")
                out.append("        end")
            out.append("    next")
            out.append("end")
        # SNMPv3 users.  security-level derives from auth/priv
        # presence (noAuthNoPriv / auth-no-priv / auth-priv — the
        # three FortiOS-accepted values).  Canonical priv_protocol
        # back to FortiOS: aes128 → aes; aes256 / aes192 / des
        # preserved.  Unknown / empty auth_protocol → sha fallback
        # to satisfy FortiOS validation when security-level implies
        # auth.
        _CAN_TO_FG_AUTH = {
            "md5": "md5", "sha": "sha", "sha224": "sha256",
            "sha256": "sha256", "sha384": "sha384", "sha512": "sha512",
        }
        _CAN_TO_FG_PRIV = {
            "des": "des", "aes": "aes", "aes128": "aes",
            "aes192": "aes192", "aes256": "aes256", "3des": "aes",
        }
        if tree.snmp.v3_users:
            out.append("config system snmp user")
            for u in tree.snmp.v3_users:
                out.append(f'    edit "{u.name}"')
                if u.auth_protocol and u.priv_protocol:
                    out.append("        set security-level auth-priv")
                elif u.auth_protocol:
                    out.append("        set security-level auth-no-priv")
                else:
                    out.append("        set security-level no-auth-no-priv")
                if u.auth_protocol:
                    fg_auth = _CAN_TO_FG_AUTH.get(u.auth_protocol, "sha")
                    out.append(f"        set auth-proto {fg_auth}")
                    if u.auth_passphrase:
                        # Preserve operator-supplied hash verbatim.
                        # Source-joined ``ENC <hash>`` round-trips as-is;
                        # cross-vendor hashes get an ENC prefix.
                        val = u.auth_passphrase
                        if val.startswith("ENC "):
                            out.append(f'        set auth-pwd "{val}"')
                        else:
                            out.append(f'        set auth-pwd "ENC {val}"')
                if u.priv_protocol:
                    fg_priv = _CAN_TO_FG_PRIV.get(u.priv_protocol, "aes")
                    out.append(f"        set priv-proto {fg_priv}")
                    if u.priv_passphrase:
                        val = u.priv_passphrase
                        if val.startswith("ENC "):
                            out.append(f'        set priv-pwd "{val}"')
                        else:
                            out.append(f'        set priv-pwd "ENC {val}"')
                out.append("    next")
            out.append("end")

    # --- system admin (Tier 2 local users) ---
    if tree.local_users:
        out.append("config system admin")
        for user in tree.local_users:
            out.append(f'    edit "{user.name}"')
            # Hash-portability gate (Issue #1a from
            # tests/fixtures/real/user_smoke_findings.md).  Foreign
            # hashes (Cisco type-5/7/8/9, Arista sha512, OPNsense
            # bcrypt) are NOT consumable by FortiOS's ``set password
            # ENC <blob>`` -- that ENC blob has FortiOS-internal key
            # semantics, NOT a generic "any hash" wrapper.  Before
            # the fix the renderer leaked the literal source hash on
            # the wire (e.g. ``set password ENC 9 $9$...``) which
            # FortiOS would either reject at commit time or, worse,
            # parse as garbage.  Now we consult the shared
            # :mod:`netcanon.migration._user_secrets` policy and
            # emit a comment-form ``review:`` line instead, naming
            # the source algorithm so the operator knows exactly
            # which user to reset.  Native fortigate hashes tagged
            # ``fortios:<blob>`` still pass through unchanged.
            if user.hashed_password:
                if is_migratable(user.hashed_password, "fortigate_cli"):
                    alg, _, raw = user.hashed_password.partition(":")
                    if alg == "fortios":
                        out.append(f"        set password {raw}")
                    elif raw:
                        out.append(f"        set password ENC {raw}")
                    else:
                        out.append(
                            f"        set password ENC "
                            f"{user.hashed_password}"
                        )
                else:
                    algorithm, _payload = classify_hash(
                        user.hashed_password,
                    )
                    out.append(
                        f"        {format_review_comment(user.name, algorithm, comment_syntax='hash', target_label='FortiOS')}"
                    )
            # Map canonical privilege back to accprofile.
            accprofile = (
                "super_admin" if user.privilege_level == 15
                else (user.role or "prof_admin")
            )
            out.append(f'        set accprofile "{accprofile}"')
            out.append("    next")
        out.append("end")

    # --- user radius (Tier 2 RADIUS servers) ---
    if tree.radius_servers:
        out.append("config user radius")
        for idx, server in enumerate(tree.radius_servers, start=1):
            out.append(f'    edit "radius-{idx}"')
            out.append(f'        set server "{server.host}"')
            if server.key:
                alg, _, raw = server.key.partition(":")
                if alg == "fortios":
                    out.append(f"        set secret {raw}")
                elif raw:
                    out.append(f"        set secret ENC {raw}")
                else:
                    out.append(f"        set secret ENC {server.key}")
            if server.auth_port and server.auth_port != 1812:
                out.append(f"        set radius-port {server.auth_port}")
            out.append("    next")
        out.append("end")

    # --- system dhcp server (Tier 2 DHCP pools) ---
    if tree.dhcp_servers:
        out.append("config system dhcp server")
        for idx, pool in enumerate(tree.dhcp_servers, start=1):
            out.append(f"    edit {idx}")
            if pool.lease_time:
                out.append(f"        set lease-time {pool.lease_time}")
            if pool.gateway:
                out.append(f"        set default-gateway {pool.gateway}")
            if pool.network:
                try:
                    net = ipaddress.IPv4Network(pool.network, strict=False)
                    out.append(f"        set netmask {net.netmask}")
                except (ValueError, ipaddress.AddressValueError):
                    pass
            if pool.interface:
                out.append(f'        set interface "{pool.interface}"')
            for i, dns in enumerate(pool.dns_servers[:3], start=1):
                out.append(f"        set dns-server{i} {dns}")
            if pool.dns_servers:
                out.append("        set dns-service specify")
            if pool.domain_name:
                out.append(f'        set domain "{pool.domain_name}"')
            if pool.start_ip or pool.end_ip:
                out.append("        config ip-range")
                out.append("            edit 1")
                if pool.start_ip:
                    out.append(f"                set start-ip {pool.start_ip}")
                if pool.end_ip:
                    out.append(f"                set end-ip {pool.end_ip}")
                out.append("            next")
                out.append("        end")
            out.append("    next")
        out.append("end")

    # --- router static ---
    if tree.static_routes:
        out.append("config router static")
        for idx, route in enumerate(tree.static_routes, start=1):
            out.append(f"    edit {idx}")
            dst_ip, dst_prefix = _split_cidr(route.destination)
            dst_mask = _prefix_to_mask(dst_prefix)
            out.append(f"        set dst {dst_ip} {dst_mask}")
            if route.gateway:
                out.append(f"        set gateway {route.gateway}")
            if route.interface:
                out.append(f'        set device "{route.interface}"')
            if route.description:
                # FortiOS uses ``set comment`` (singular) on
                # ``config router static`` entries; max 255 chars.
                # Ref: https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/522620/config-router-static
                out.append(f'        set comment "{route.description}"')
            out.append("    next")
        out.append("end")

    return "\n".join(out) + "\n"
