"""
MikroTik RouterOS parser — ``/export`` CLI form to ``CanonicalIntent``.

Extracted from ``codec.py`` during the parse/render split per the
``codecs/README.md`` split-codec convention.  Public function
(consumed by ``codec.py::MikroTikRouterOSCodec.parse()``):

* :func:`parse_intent` — one-shot parse entry: raw text in, fully-
  populated :class:`CanonicalIntent` out.

Each command in a RouterOS ``/export`` is a self-contained line; the
parser dispatches on the leading path (``/ip address``,
``/interface ethernet``, ``/ipv6 address``, etc.).  Stable across
RouterOS 6-7.

Shared helpers (``_is_ethernet_name``, ``_is_vlan_name``,
``_infer_iface_type_from_name``, ``_sort_interfaces``) live here and
are imported by :mod:`.render` — one directional edge, no circular
risk, per the README's split-codec guidance.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any, Iterable

from ...canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
    CanonicalLocalUser,
    CanonicalRADIUSServer,
    CanonicalSNMP,
    CanonicalStaticRoute,
    CanonicalVlan,
    CanonicalVRRPGroup,
)
from .._input_shape import detect_input_shape
from ..base import ParseError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------


def parse_intent(raw: str) -> CanonicalIntent:
    """Parse RouterOS ``/export verbose`` text into a
    :class:`CanonicalIntent`.

    Raises:
        ParseError: On empty input or input that clearly isn't
            RouterOS (XML, JSON, etc).
    """
    if not raw.strip():
        raise ParseError(
            "mikrotik_routeros: empty input",
            snippet="",
        )
    # Shape sanity — Round-4.2 shared helper tolerates leading
    # shell-echo / banner framing on real captures.
    shape = detect_input_shape(raw)
    if shape == "xml":
        raise ParseError(
            "mikrotik_routeros: input looks like XML, not RouterOS "
            "export.  Use the opnsense or cisco_iosxe codec instead.",
            snippet=raw.lstrip()[:120],
        )
    if shape == "json":
        raise ParseError(
            "mikrotik_routeros: input looks like JSON, not RouterOS "
            "export.",
            snippet=raw.lstrip()[:120],
        )

    intent = CanonicalIntent(
        source_vendor="mikrotik_routeros",
        source_format="cli-mikrotik",
    )

    # Pre-process: join `\` line continuations.
    joined = _join_continuations(raw)

    # Group lines by their /section context.
    sections = _group_by_section(joined)

    # Walk each section with a section-specific handler.
    # Interfaces need to be assembled across multiple sections
    # (ethernet sets properties, vlan adds a new interface, ip
    # address attaches addresses) so we carry an accumulator.
    iface_by_name: dict[str, CanonicalInterface] = {}

    # Some sections must run AFTER others regardless of file order.
    # /ip pool carries DHCP-range data that needs to merge into pool
    # records created by /ip dhcp-server network; running them in
    # file order would split a single logical pool into two
    # canonical records when the file happens to list /ip pool
    # first.  Defer /ip pool to a post-pass.
    deferred_ip_pool: list[list[str]] = []

    # VRRP scratch — keyed by the VRRP pseudo-interface name (the
    # ``name=`` attribute on the ``/interface vrrp add`` line, e.g.
    # ``vrrp10``).  RouterOS models the VRRP group as a pseudo-
    # interface declared in ``/interface vrrp`` and then binds the
    # virtual IP via a separate ``/ip address add ... interface=<X>``
    # line where ``<X>`` references the pseudo-name.  Parsing is
    # therefore two-stage: first collect the scratch records, then
    # post-pass the ``/ip address`` lines to attach virtual IPs by
    # cross-referencing the pseudo-name.  See ``docs/v0.2.0-planning/
    # 01-vrrp-canonical/03-parse-render-touchpoints.md`` §6 for the
    # full design.
    #
    # Pre-walk to populate the scratch dict BEFORE the main section
    # walker runs.  RouterOS ``/export`` typically emits
    # ``/interface vrrp`` before ``/ip address`` so a single in-order
    # pass would work for well-formed input, but the pre-walk keeps
    # the cross-reference robust against hand-edited / reordered
    # exports where ``/ip address`` precedes ``/interface vrrp``.
    vrrp_scratch: dict[str, dict[str, Any]] = {}
    for section, lines in sections:
        if section == "/interface vrrp":
            _parse_interface_vrrp(lines, vrrp_scratch)

    for section, lines in sections:
        if section == "/system identity":
            _parse_system_identity(lines, intent)
        elif section == "/system dns":
            _parse_system_dns(lines, intent)
        elif section == "/system ntp client":
            _parse_system_ntp(lines, intent)
        elif section == "/interface ethernet":
            _parse_interface_ethernet(lines, iface_by_name)
        elif section == "/interface vlan":
            _parse_interface_vlan(lines, iface_by_name, intent)
        elif section == "/interface bridge":
            _parse_interface_bridge(lines, iface_by_name)
        elif section == "/interface bonding":
            _parse_interface_bonding(lines, iface_by_name, intent)
        elif section == "/interface gre":
            _parse_interface_tunnel(lines, iface_by_name, "gre")
        elif section == "/interface eoip":
            _parse_interface_tunnel(lines, iface_by_name, "eoip")
        elif section == "/interface ipip":
            _parse_interface_tunnel(lines, iface_by_name, "ipip")
        elif section == "/interface vrrp":
            # Already handled in the pre-walk above.  The branch stays
            # in the dispatch so unknown ``/interface ...`` sections
            # don't silently fall through to a default handler.
            pass
        elif section == "/ip address":
            _parse_ip_address(lines, iface_by_name, vrrp_scratch)
        elif section == "/ipv6 address":              # GAP-EVPN-3
            _parse_ipv6_address(lines, iface_by_name, vrrp_scratch)
        elif section == "/ip route":
            _parse_ip_route(lines, intent)
        elif section == "/snmp":
            _parse_snmp_root(lines, intent)
        elif section == "/snmp community":
            _parse_snmp_community(lines, intent)
        elif section == "/user":
            _parse_user(lines, intent)
        elif section == "/ip dhcp-server network":
            _parse_dhcp_server_network(lines, intent)
        elif section == "/ip pool":
            deferred_ip_pool.append(lines)
        elif section == "/radius":
            _parse_radius(lines, intent)
        # Other sections silently ignored — not in scope yet.

    for pool_lines in deferred_ip_pool:
        _parse_ip_pool(pool_lines, intent)

    # VRRP post-pass — materialise scratch records into
    # CanonicalVRRPGroup entries on the parent interface.  Iterate in
    # insertion order so groups land on parents in the same order they
    # appeared in the source ``/interface vrrp`` section, keeping
    # render output deterministic.
    _materialise_vrrp_groups(vrrp_scratch, iface_by_name)

    # Order interfaces deterministically: ethernet ports first
    # (by natural-sort name), then bridges, then VLANs, then rest.
    intent.interfaces = _sort_interfaces(iface_by_name.values())

    logger.debug(
        "mikrotik_routeros parsed: hostname=%r ifaces=%d vlans=%d "
        "routes=%d lags=%d users=%d snmp=%s (input=%d chars)",
        intent.hostname,
        len(intent.interfaces),
        len(intent.vlans),
        len(intent.static_routes),
        len(intent.lags),
        len(intent.local_users),
        "yes" if intent.snmp else "no",
        len(raw),
    )
    return intent


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------


_SECTION_RE = re.compile(r"^(/[a-zA-Z][a-zA-Z0-9 \-]*)$")
_COMMENT_RE = re.compile(r"^\s*#")


def _join_continuations(raw: str) -> str:
    """Collapse RouterOS ``\\`` line continuations into single lines."""
    out: list[str] = []
    buffer = ""
    for line in raw.splitlines():
        if buffer:
            buffer += " " + line.strip()
        else:
            buffer = line
        if buffer.rstrip().endswith("\\"):
            # Strip the trailing backslash and keep buffering.
            buffer = buffer.rstrip()[:-1].rstrip()
            continue
        out.append(buffer)
        buffer = ""
    if buffer:
        out.append(buffer)
    return "\n".join(out)


def _group_by_section(raw: str) -> list[tuple[str, list[str]]]:
    """Group lines by their ``/section`` heading.

    Returns a list of (section, lines) pairs preserving order.  Lines
    that don't belong to any section (file-level banner) are dropped.
    """
    groups: list[tuple[str, list[str]]] = []
    current_section: str | None = None
    current_lines: list[str] = []

    for line in raw.splitlines():
        stripped = line.rstrip()
        if not stripped or _COMMENT_RE.match(stripped):
            continue
        m = _SECTION_RE.match(stripped)
        if m:
            if current_section is not None:
                groups.append((current_section, current_lines))
            current_section = m.group(1)
            current_lines = []
            continue
        if current_section is None:
            continue
        current_lines.append(stripped)

    if current_section is not None:
        groups.append((current_section, current_lines))
    return groups


_KV_RE = re.compile(
    r"""
    ([\w\-]+)             # key
    =
    (                     # value:
        "[^"]*"           #   double-quoted string, OR
      | [^\s]+            #   bare token (no spaces)
    )
    """,
    re.VERBOSE,
)


def _parse_kv(line: str) -> dict[str, str]:
    """Parse ``key=value`` pairs from a single command line.

    Handles quoted values with spaces.  Unquotes the result so the
    caller gets the raw value.  Ignores the leading verb
    (``add``/``set``/``remove``) and any ``[ find ... ]`` predicate.
    """
    pairs: dict[str, str] = {}
    for m in _KV_RE.finditer(line):
        key = m.group(1)
        val = m.group(2)
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        pairs[key] = val
    return pairs


_FIND_DEFAULT_NAME_RE = re.compile(r"\[\s*find\s+default-name=(\S+)\s*\]")
# Cross-vendor render path emits ``[ find name=X ]`` against the
# canonical name when no ``default_name`` was tracked; we need to
# accept both forms on the parse side so round-trips don't drop the
# row.  Quoted names (``[ find name="ge-0/0/1" ]``) need the value
# extracted without the surrounding quotes.
_FIND_NAME_RE = re.compile(r'\[\s*find\s+name=(?:"([^"]*)"|(\S+?))\s*\]')


def _parse_system_identity(lines: list[str], intent: CanonicalIntent) -> None:
    for line in lines:
        if line.startswith("set"):
            kv = _parse_kv(line)
            if "name" in kv:
                intent.hostname = kv["name"]
                return


def _parse_system_dns(lines: list[str], intent: CanonicalIntent) -> None:
    for line in lines:
        if line.startswith("set"):
            kv = _parse_kv(line)
            if "servers" in kv:
                intent.dns_servers = [
                    s.strip() for s in kv["servers"].split(",") if s.strip()
                ]


def _parse_system_ntp(lines: list[str], intent: CanonicalIntent) -> None:
    for line in lines:
        if line.startswith("set"):
            kv = _parse_kv(line)
            if "servers" in kv:
                intent.ntp_servers = [
                    s.strip() for s in kv["servers"].split(",") if s.strip()
                ]


def _parse_interface_ethernet(
    lines: list[str],
    iface_by_name: dict[str, CanonicalInterface],
) -> None:
    """Parse ``set [ find default-name=etherN ] ...`` tweaks.

    Real RouterOS configs routinely rename ports for descriptive
    purposes — e.g. ``set [ find default-name=ether2 ] name="Access
    Point"``.  When that happens, the RENAMED name (``Access Point``)
    is how the rest of the config references the port (in
    ``/interface bridge port interface=...``, ``/queue interface``,
    ``/ip address interface=``, etc.).  The canonical must therefore
    track the renamed name as ``CanonicalInterface.name``, with the
    original factory default-name preserved on ``default_name`` so
    the renderer can reconstruct the ``set [ find default-name=X ]``
    lookup.
    """
    for line in lines:
        if not line.startswith("set"):
            continue
        # Two find-clause forms accepted: ``[ find default-name=X ]``
        # (the MikroTik factory-port lookup) and ``[ find name=X ]``
        # (the cross-vendor render path's fallback when no
        # ``default_name`` was tracked).  The latter never sets
        # ``default_name`` on the resulting CanonicalInterface,
        # preserving round-trip equality for sources like Junos
        # ``ge-0/0/1`` or OPNsense ``wan`` whose names don't match
        # the MikroTik factory shape.
        fm = _FIND_DEFAULT_NAME_RE.search(line)
        nm = _FIND_NAME_RE.search(line) if fm is None else None
        if fm is None and nm is None:
            continue
        if fm is not None:
            default_name = fm.group(1)
            canonical_default = default_name
        else:
            default_name = ""
            # _FIND_NAME_RE: group(1) is the quoted form, group(2) the bare.
            canonical_default = nm.group(1) if nm.group(1) is not None else nm.group(2)
        kv = _parse_kv(line)
        canonical_name = kv.get("name", canonical_default)
        iface = iface_by_name.get(canonical_name)
        if iface is None:
            # Only the ``default-name=`` form implies the iface is a
            # MikroTik factory ethernet port - that's the find clause
            # that only resolves on a real device.  The ``name=`` form
            # is the cross-vendor fallback and carries no such
            # implication; defer to ``_infer_iface_type_from_name`` so
            # an iface named ``eth3_vlan1`` (created by ``/ip address``
            # in the first pass with empty ``interface_type``) doesn't
            # gain a synthetic type on the second pass.
            inferred_type = (
                "ianaift:ethernetCsmacd"
                if fm is not None
                else _infer_iface_type_from_name(canonical_name)
            )
            iface = CanonicalInterface(
                name=canonical_name,
                default_name=default_name,
                interface_type=inferred_type,
            )
            iface_by_name[canonical_name] = iface
        else:
            # Merge default_name if we hadn't captured it yet.
            if not iface.default_name and default_name:
                iface.default_name = default_name
        if "comment" in kv:
            iface.description = kv["comment"]
        if "disabled" in kv:
            iface.enabled = kv["disabled"].lower() == "no"
        if "mtu" in kv:
            try:
                iface.mtu = int(kv["mtu"])
            except ValueError:
                pass


def _parse_interface_vlan(
    lines: list[str],
    iface_by_name: dict[str, CanonicalInterface],
    intent: CanonicalIntent,
) -> None:
    """Parse ``add ... vlan-id=N name=X ...`` VLAN interface definitions."""
    for line in lines:
        if not line.startswith("add"):
            continue
        kv = _parse_kv(line)
        name = kv.get("name")
        if not name:
            continue
        vlan_id_str = kv.get("vlan-id")
        if not vlan_id_str or not vlan_id_str.isdigit():
            continue
        vlan_id = int(vlan_id_str)
        iface = iface_by_name.setdefault(
            name,
            CanonicalInterface(
                name=name,
                interface_type="ianaift:l3ipvlan",
            ),
        )
        if "comment" in kv:
            iface.description = kv["comment"]
        # Disabled flag (defaults to enabled if not present).
        if "disabled" in kv:
            iface.enabled = kv["disabled"].lower() == "no"
        # Also record in intent.vlans so the VLAN database is complete.
        # Use the IFACE name as the canonical VLAN name (not the
        # comment) — the render path's `_vlan_id_for` lookup matches
        # iface.name -> vlans[*].name, so keeping those in sync is
        # essential for round-trip stability.  The comment (a human-
        # readable label like "Management" or "Cluster") goes onto the
        # VLAN's description field instead.
        intent.vlans.append(CanonicalVlan(
            id=vlan_id,
            name=name,
            description=kv.get("comment", ""),
        ))


def _parse_interface_bridge(
    lines: list[str],
    iface_by_name: dict[str, CanonicalInterface],
) -> None:
    """Parse bridge interface definitions (just record existence + name)."""
    for line in lines:
        if not line.startswith("add"):
            continue
        kv = _parse_kv(line)
        name = kv.get("name")
        if not name:
            continue
        iface = iface_by_name.setdefault(
            name,
            CanonicalInterface(
                name=name,
                interface_type="ianaift:bridge",
            ),
        )
        if "comment" in kv:
            iface.description = kv["comment"]


def _parse_interface_bonding(
    lines: list[str],
    iface_by_name: dict[str, CanonicalInterface],
    intent: CanonicalIntent,
) -> None:
    """Parse ``/interface bonding`` section into :class:`CanonicalLAG`
    records plus a synthetic LAG interface.

    Expected shape::

        /interface bonding
        add name=bond1 slaves=ether1,ether2 mode=802.3ad

    ``mode`` values:
        802.3ad -> LACP (canonical "active")
        active-backup / balance-* / broadcast -> static
    """
    for line in lines:
        if not line.startswith("add"):
            continue
        kv = _parse_kv(line)
        name = kv.get("name")
        if not name:
            continue
        slaves_raw = kv.get("slaves", "")
        members = [s.strip() for s in slaves_raw.split(",") if s.strip()]
        mode = _ROUTEROS_BONDING_MODE_TO_CANONICAL.get(
            kv.get("mode", "").lower(), "static"
        )
        lag = CanonicalLAG(name=name, members=members, mode=mode)
        intent.lags.append(lag)

        # Also materialise the LAG as a CanonicalInterface so the
        # rest of the canonical model treats it uniformly (IP
        # addresses can be attached, etc.).
        iface = iface_by_name.setdefault(
            name,
            CanonicalInterface(
                name=name,
                interface_type="ianaift:ieee8023adLag",
            ),
        )
        if "comment" in kv:
            iface.description = kv["comment"]
        # Reverse-link members.
        for m in members:
            m_iface = iface_by_name.setdefault(
                m,
                CanonicalInterface(
                    name=m,
                    interface_type=_infer_iface_type_from_name(m),
                ),
            )
            if m_iface.lag_member_of is None:
                m_iface.lag_member_of = name


_ROUTEROS_BONDING_MODE_TO_CANONICAL = {
    "802.3ad": "active",
    "active-backup": "static",
    "balance-rr": "static",
    "balance-xor": "static",
    "balance-tlb": "static",
    "balance-alb": "static",
    "broadcast": "static",
}


def _parse_interface_tunnel(
    lines: list[str],
    iface_by_name: dict[str, CanonicalInterface],
    tunnel_kind: str,
) -> None:
    """Parse ``/interface gre`` / ``/interface eoip`` / ``/interface ipip``
    sections into :class:`CanonicalInterface` records carrying the
    canonical ``tunnel_type`` discriminator.

    Expected shape (RouterOS)::

        /interface gre
        add name=gre-tun1 remote-address=1.2.3.4 local-address=5.6.7.8

    Populates ``iface.interface_type='ianaift:tunnel'`` plus
    ``iface.tunnel_type=<tunnel_kind>`` so the cross-vendor render
    path can pick the matching emit form.  Endpoint addresses are NOT
    canonicalised in v1 (the schema has no local/remote pair); the
    name + tunnel_type round-trip is what the renderer needs to emit
    the right ``/interface <encap>`` section.
    """
    for line in lines:
        if not line.startswith("add"):
            continue
        kv = _parse_kv(line)
        name = kv.get("name")
        if not name:
            continue
        iface = iface_by_name.setdefault(
            name,
            CanonicalInterface(
                name=name,
                interface_type="ianaift:tunnel",
            ),
        )
        # Force the canonical type even if a prior section seeded the
        # iface with a different / empty type.
        iface.interface_type = "ianaift:tunnel"
        iface.tunnel_type = tunnel_kind
        if "comment" in kv:
            iface.description = kv["comment"]
        if "disabled" in kv:
            iface.enabled = kv["disabled"].lower() == "no"


def _parse_interface_vrrp(
    lines: list[str],
    vrrp_scratch: dict[str, dict[str, Any]],
) -> None:
    """Parse the ``/interface vrrp`` section into scratch records.

    Each ``add`` line declares one VRRP pseudo-interface that lives at
    the top level of RouterOS' interface tree.  Sample::

        /interface vrrp
        add interface=ether1 name=vrrp10 vrid=10 priority=110 \\
            v3-protocol=ipv4 preemption-mode=yes interval=1s
        add interface=ether2 name=vrrp20 vrid=20 priority=90 \\
            preemption-mode=no authentication=simple password=foo

    Recognised attributes (mapped to canonical fields):

    * ``interface=X`` — parent interface that hosts the group; stored
      in the scratch dict under ``parent`` so the post-pass can attach
      the materialised CanonicalVRRPGroup to ``iface_by_name[X]``.
    * ``name=Y`` — pseudo-iface name; used as the scratch dict key and
      as the ``/ip address`` cross-reference target.
    * ``vrid=N`` — canonical ``group_id``.
    * ``priority=P`` — canonical ``priority``; defaults to 100.
    * ``preemption-mode=yes|no`` — canonical ``preempt``; defaults to
      ``True`` (the IETF VRRP default).
    * ``interval=Ns`` — canonical ``advertisement_interval``; the
      trailing ``s`` is RouterOS' time-unit suffix and stripped before
      parsing.  Defaults to 1.
    * ``v3-protocol=ipv4|ipv6`` — discriminator for which canonical
      virtual-IP list the ``/ip address`` post-pass populates.  Per
      RouterOS docs, defaults to ``ipv4`` when absent.
    * ``authentication=ah|simple|none`` + ``password=X`` — combined
      into the canonical ``authentication`` field in
      ``<scheme>:<value>`` form (``ah:X``, ``plain:X``).  ``none`` /
      missing maps to the empty string.
    * ``disabled=yes|no`` — RouterOS-native enable flag; canonical
      VRRPGroup has no equivalent (the group's existence implies it
      is operational), so this is parse-and-ignore.  ``on-backup``
      script bindings are Tier-3 and likewise dropped.
    """
    for line in lines:
        if not line.startswith("add"):
            continue
        kv = _parse_kv(line)
        parent = kv.get("interface", "")
        name = kv.get("name", "")
        if not parent or not name:
            continue
        try:
            vrid = int(kv.get("vrid", "1"))
        except ValueError:
            continue
        try:
            priority = int(kv.get("priority", "100"))
        except ValueError:
            priority = 100
        # ``interval`` accepts ``1``, ``1s``, ``500ms`` — we only model
        # whole-second intervals on the canonical surface, so round
        # millisecond values to the nearest second (min 1).
        interval_raw = (kv.get("interval", "1") or "1").strip()
        adv_interval = _parse_routeros_interval_seconds(interval_raw)
        preempt = kv.get("preemption-mode", "yes").lower() != "no"
        v3_protocol = kv.get("v3-protocol", "ipv4").lower()
        # version: RouterOS exposes a separate ``version`` key (2 or 3);
        # we don't carry it on the canonical surface (VRRPv3 is implied
        # by v6 VIPs or by explicit ``version=3``) — parse but discard.
        auth = _build_routeros_auth(kv)
        vrrp_scratch[name] = {
            "parent": parent,
            "group_id": vrid,
            "priority": priority,
            "preempt": preempt,
            "advertisement_interval": adv_interval,
            "v3_protocol": v3_protocol,
            "authentication": auth,
            "virtual_ips": [],
            "virtual_ipv6s": [],
            "virtual_ip_prefix": 0,    # populated by /ip address post-pass
            "virtual_ip6_prefix": 0,   # populated by /ipv6 address post-pass
        }


_TIME_INTERVAL_RE = re.compile(
    r"^(?P<value>\d+)(?P<unit>ms|s|m|h)?$",
    re.IGNORECASE,
)


def _parse_routeros_interval_seconds(raw: str) -> int:
    """Convert a RouterOS time literal into whole seconds (min 1).

    RouterOS interval values look like ``1``, ``1s``, ``500ms``, ``2m``;
    canonical advertisement_interval is an int seconds field, so this
    helper normalises.  Sub-second values round up to 1 (the smallest
    valid canonical value), unknown / unparseable input also falls back
    to 1.
    """
    m = _TIME_INTERVAL_RE.match(raw.strip())
    if not m:
        return 1
    value = int(m.group("value"))
    unit = (m.group("unit") or "s").lower()
    if unit == "ms":
        seconds = max(1, (value + 999) // 1000)
    elif unit == "s":
        seconds = max(1, value)
    elif unit == "m":
        seconds = max(1, value * 60)
    elif unit == "h":
        seconds = max(1, value * 3600)
    else:
        seconds = 1
    return seconds


def _build_routeros_auth(kv: dict[str, str]) -> str:
    """Combine RouterOS ``authentication=`` + ``password=`` into the
    canonical ``<scheme>:<value>`` token form.

    RouterOS auth modes (per the Manual:Interface/VRRP page):

    * ``none`` (or unset) — no authentication; canonical empty string.
    * ``simple`` — plaintext shared secret; canonical ``plain:<pwd>``.
    * ``ah`` — IPsec AH-style HMAC; canonical ``ah:<pwd>``.  RouterOS
      uses the same ``password=`` field for the AH key.

    Missing or empty passwords collapse to the empty string even when
    a non-none scheme is declared — operators routinely declare the
    scheme but defer the key to a secrets manager (the same pattern
    the local-users wire-up follows).
    """
    scheme = (kv.get("authentication") or "none").lower()
    password = kv.get("password", "")
    if scheme in ("none", ""):
        return ""
    if not password:
        return ""
    if scheme == "simple":
        return f"plain:{password}"
    if scheme == "ah":
        return f"ah:{password}"
    return ""


def _materialise_vrrp_groups(
    vrrp_scratch: dict[str, dict[str, Any]],
    iface_by_name: dict[str, CanonicalInterface],
) -> None:
    """Build :class:`CanonicalVRRPGroup` records from the scratch dict
    and attach them to their parent interfaces.

    Parents are looked up by name; an unknown parent (the ``interface=``
    value didn't match anything we've parsed yet) results in a synthetic
    CanonicalInterface so the group still survives — RouterOS allows
    binding to any iface name and we'd rather carry a partial canonical
    record than drop the row.  Insertion order across the scratch dict
    is preserved so render output is deterministic.
    """
    for scratch in vrrp_scratch.values():
        parent_name = scratch["parent"]
        parent_iface = iface_by_name.get(parent_name)
        if parent_iface is None:
            parent_iface = CanonicalInterface(
                name=parent_name,
                interface_type=_infer_iface_type_from_name(parent_name),
                default_name=(
                    parent_name if _is_ethernet_name(parent_name) else ""
                ),
            )
            iface_by_name[parent_name] = parent_iface
        group = CanonicalVRRPGroup(
            group_id=scratch["group_id"],
            mode="vrrp",
            virtual_ips=list(scratch["virtual_ips"]),
            virtual_ipv6s=list(scratch["virtual_ipv6s"]),
            priority=scratch["priority"],
            preempt=scratch["preempt"],
            advertisement_interval=scratch["advertisement_interval"],
            authentication=scratch["authentication"],
        )
        parent_iface.vrrp_groups.append(group)


def _parse_ip_address(
    lines: list[str],
    iface_by_name: dict[str, CanonicalInterface],
    vrrp_scratch: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Parse ``add address=X/Y interface=Z`` lines and attach to iface.

    When ``Z`` matches a VRRP pseudo-interface name previously seen in
    ``/interface vrrp``, the address is routed into ``vrrp_scratch[Z]
    ['virtual_ips']`` (with the prefix tracked separately so the
    renderer can reconstruct ``X/Y``) rather than minting a phantom
    ``CanonicalInterface`` for the pseudo-name.
    """
    for line in lines:
        if not line.startswith("add"):
            continue
        kv = _parse_kv(line)
        addr = kv.get("address")
        iface_name = kv.get("interface")
        if not addr or not iface_name:
            continue
        if "/" not in addr:
            raise ParseError(
                f"mikrotik_routeros: address {addr!r} missing CIDR prefix",
                path=f"/ip address/{iface_name}",
                snippet=line[:120],
            )
        ip_str, prefix_str = addr.split("/", 1)
        try:
            prefix_len = int(prefix_str)
        except ValueError:
            raise ParseError(
                f"mikrotik_routeros: invalid CIDR prefix {prefix_str!r}",
                path=f"/ip address/{iface_name}",
                snippet=line[:120],
            )
        # Route VIP rows to the VRRP scratch — don't materialise a
        # phantom CanonicalInterface for ``vrrpN`` pseudo-names.
        if vrrp_scratch is not None and iface_name in vrrp_scratch:
            scratch = vrrp_scratch[iface_name]
            scratch["virtual_ips"].append(ip_str.strip())
            # Stash the prefix length so the renderer can rebuild
            # ``/ip address add address=X/Y`` cleanly.  First non-zero
            # value wins; subsequent VIPs on the same group reuse it.
            if not scratch.get("virtual_ip_prefix"):
                scratch["virtual_ip_prefix"] = prefix_len
            continue
        iface = iface_by_name.setdefault(
            iface_name,
            CanonicalInterface(
                name=iface_name,
                interface_type=_infer_iface_type_from_name(iface_name),
                # If the name already matches a factory default pattern,
                # use it as the default_name too.  Keeps round-trip
                # consistent for ifaces that only appear in /ip address
                # (no /interface ethernet set line carries the default-
                # name lookup).
                default_name=iface_name if _is_ethernet_name(iface_name) else "",
            ),
        )
        iface.ipv4_addresses.append(CanonicalIPv4Address(
            ip=ip_str.strip(),
            prefix_length=prefix_len,
        ))


def _parse_ipv6_address(
    lines: list[str],
    iface_by_name: dict[str, CanonicalInterface],
    vrrp_scratch: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Parse ``/ipv6 address`` section entries (GAP-EVPN-3).

    Mirrors :func:`_parse_ip_address` for v6.  RouterOS form:
        /ipv6 address
        add address=2001:db8::1/64 interface=ether1
        add address=fe80::1/64 interface=ether1 advertise=no

    When ``interface`` references a known VRRP pseudo-name (the
    ``v3-protocol=ipv6`` flavour of an ``/interface vrrp`` group) the
    v6 address is routed into the scratch record's ``virtual_ipv6s``
    list rather than minting a phantom CanonicalInterface.
    """
    for line in lines:
        if not line.startswith("add"):
            continue
        kv = _parse_kv(line)
        addr = kv.get("address")
        iface_name = kv.get("interface")
        if not addr or not iface_name:
            continue
        if "/" not in addr:
            continue
        ip_str, prefix_str = addr.split("/", 1)
        try:
            prefix_len = int(prefix_str)
        except ValueError:
            continue
        # Route v6 VIPs into the VRRP scratch when the interface name
        # matches a known pseudo-iface (v3-protocol=ipv6 group).  The
        # prefix is stashed under ``virtual_ip6_prefix`` so the
        # renderer can rebuild the ``/ipv6 address`` line.
        if vrrp_scratch is not None and iface_name in vrrp_scratch:
            scratch = vrrp_scratch[iface_name]
            scratch["virtual_ipv6s"].append(ip_str.strip())
            if not scratch.get("virtual_ip6_prefix"):
                scratch["virtual_ip6_prefix"] = prefix_len
            continue
        # Scope inferred from fe80::/10 — RouterOS doesn't keyword-tag
        # link-local addresses on the wire (the ``advertise=no`` flag
        # is informational; we don't model it).
        lo = ip_str.strip().lower()
        scope = (
            "link-local"
            if (
                len(lo) >= 3
                and lo[:2] == "fe"
                and lo[2] in ("8", "9", "a", "b")
            )
            else "global"
        )
        iface = iface_by_name.setdefault(
            iface_name,
            CanonicalInterface(
                name=iface_name,
                interface_type=_infer_iface_type_from_name(iface_name),
                default_name=iface_name if _is_ethernet_name(iface_name) else "",
            ),
        )
        iface.ipv6_addresses.append(CanonicalIPv6Address(
            ip=ip_str.strip(),
            prefix_length=prefix_len,
            scope=scope,
        ))


def _parse_snmp_root(lines: list[str], intent: CanonicalIntent) -> None:
    """Parse ``/snmp set enabled=yes contact=X location=Y`` (Tier 2).

    Sets global SNMP agent properties (contact + location).  The
    community strings live under ``/snmp community`` and are handled
    by :func:`_parse_snmp_community`.
    """
    for line in lines:
        if not line.startswith("set"):
            continue
        kv = _parse_kv(line)
        if intent.snmp is None:
            intent.snmp = CanonicalSNMP()
        if "contact" in kv:
            intent.snmp.contact = kv["contact"]
        if "location" in kv:
            intent.snmp.location = kv["location"]
        if "trap-target" in kv:
            for host in kv["trap-target"].split(","):
                h = host.strip()
                if h:
                    intent.snmp.trap_hosts.append(h)


def _parse_radius(
    lines: list[str], intent: CanonicalIntent,
) -> None:
    """Parse ``/radius`` section entries into CanonicalRADIUSServer.

    RouterOS form:
        /radius
        add address=10.0.0.4 secret=shared-secret service=login,dhcp \\
            authentication-port=1812 accounting-port=1813
    """
    for line in lines:
        if not line.startswith("add"):
            continue
        kv = _parse_kv(line)
        address = kv.get("address")
        if not address:
            continue
        auth_port = 1812
        acct_port = 1813
        try:
            auth_port = int(kv.get("authentication-port") or 1812)
        except ValueError:
            pass
        try:
            acct_port = int(kv.get("accounting-port") or 1813)
        except ValueError:
            pass
        intent.radius_servers.append(CanonicalRADIUSServer(
            host=address,
            key=kv.get("secret", ""),
            auth_port=auth_port,
            acct_port=acct_port,
        ))


def _parse_dhcp_server_network(
    lines: list[str], intent: CanonicalIntent,
) -> None:
    """Parse ``/ip dhcp-server network`` section into CanonicalDHCPPool.

    RouterOS DHCP is genuinely spread across THREE sections:
        /ip dhcp-server          - the server instance (binds to iface)
        /ip dhcp-server network  - network-scoped options (gateway, DNS)
        /ip pool                 - the allocation range

    For canonical translation, the `network` section is the richest
    per-pool record — it carries gateway, DNS, domain, and the address
    CIDR.  We use it as the pool's primary record and merge address-
    range data from /ip pool in a separate pass.  Real configs keep
    the sections structurally parallel so match-by-position works in
    simple cases; more complex cases need a future refinement pass.
    """
    for line in lines:
        if not line.startswith("add"):
            continue
        kv = _parse_kv(line)
        address = kv.get("address")
        if not address:
            continue
        pool = CanonicalDHCPPool(
            network=address,
            gateway=kv.get("gateway", ""),
            domain_name=kv.get("domain", ""),
        )
        dns_raw = kv.get("dns-server", "")
        if dns_raw:
            pool.dns_servers.extend(
                s.strip() for s in dns_raw.split(",") if s.strip()
            )
        intent.dhcp_servers.append(pool)


def _parse_ip_pool(lines: list[str], intent: CanonicalIntent) -> None:
    """Merge ``/ip pool add ranges=START-END`` data into existing
    CanonicalDHCPPool records.

    Matching strategy: find the pool whose network contains the range's
    start IP.  If none matches (orphan pool) we create a new
    CanonicalDHCPPool with just the range populated.
    """
    for line in lines:
        if not line.startswith("add"):
            continue
        kv = _parse_kv(line)
        ranges = kv.get("ranges", "")
        if not ranges or "-" not in ranges:
            continue
        # ranges= can be comma-separated multiple; take the first.
        first_range = ranges.split(",")[0].strip()
        start_str, _, end_str = first_range.partition("-")
        if not (start_str and end_str):
            continue
        try:
            start_ip = ipaddress.IPv4Address(start_str.strip())
        except ipaddress.AddressValueError:
            continue
        # Find an existing pool whose network contains start_ip.
        merged = False
        for pool in intent.dhcp_servers:
            if not pool.network:
                continue
            try:
                network = ipaddress.IPv4Network(pool.network, strict=False)
            except (ValueError, ipaddress.AddressValueError):
                continue
            if start_ip in network:
                pool.start_ip = start_str.strip()
                pool.end_ip = end_str.strip()
                merged = True
                break
        if not merged:
            intent.dhcp_servers.append(CanonicalDHCPPool(
                start_ip=start_str.strip(),
                end_ip=end_str.strip(),
            ))


def _parse_user(lines: list[str], intent: CanonicalIntent) -> None:
    """Parse ``/user`` section entries into CanonicalLocalUser records.

    RouterOS ``/export`` intentionally omits password hashes (they
    live in a separate protected store), so canonical
    ``hashed_password`` will be empty from this parser.  Group membership
    maps to canonical privilege:
        full   -> 15 (admin)
        write  -> 10 (operator, elevated)
        read   -> 1  (operator, read-only)
        any custom group -> 1 (operator; unknown group treated as least-privileged)
    """
    for line in lines:
        if not line.startswith("add"):
            continue
        kv = _parse_kv(line)
        name = kv.get("name")
        if not name:
            continue
        group = (kv.get("group") or "").lower()
        privilege = _ROUTEROS_GROUP_TO_PRIVILEGE.get(group, 1)
        intent.local_users.append(CanonicalLocalUser(
            name=name,
            privilege_level=privilege,
            hashed_password="",   # /export omits hashes
            role="admin" if privilege == 15 else "operator",
        ))


_ROUTEROS_GROUP_TO_PRIVILEGE = {
    "full": 15,
    "write": 10,
    "read": 1,
}


#: RouterOS auth-protocol → canonical auth_protocol short form.
_MT_AUTH_MAP = {
    "md5": "md5",
    "sha1": "sha",
    "sha256": "sha256",
    "sha512": "sha512",
}
#: RouterOS encryption-protocol → canonical priv_protocol short form.
_MT_PRIV_MAP = {
    "des": "des",
    "aes": "aes128",
    "aes-128-ccm": "aes128",
    "aes-128-cfb": "aes128",
    "aes-192-cfb": "aes192",
    "aes-256-cfb": "aes256",
}


def _parse_snmp_community(lines: list[str], intent: CanonicalIntent) -> None:
    """Parse ``/snmp community set [ find default=yes ] name=X``
    + ``add name=Y`` lines.

    RouterOS overloads the ``/snmp community`` section to carry BOTH
    v1/v2c communities AND v3 USM users — disambiguated by the
    presence of ``authentication-protocol=`` on the line:

    * No auth-proto → v1/v2c community (populates
      :attr:`CanonicalSNMP.community`; first wins).
    * Has auth-proto → SNMPv3 user (populates
      :attr:`CanonicalSNMP.v3_users`).

    RouterOS supports multiple community entries; we record the first
    one as the canonical community (CanonicalSNMP has a single
    community field — full multi-community is a Tier 2.5 refinement).
    """
    from ...canonical.intent import CanonicalSNMPv3User  # lazy local import
    for line in lines:
        kv = _parse_kv(line)
        name = kv.get("name")
        if not name:
            continue
        if intent.snmp is None:
            intent.snmp = CanonicalSNMP()
        auth_proto_raw = kv.get("authentication-protocol", "")
        priv_proto_raw = kv.get("encryption-protocol", "")
        if auth_proto_raw or priv_proto_raw:
            # Has crypto knobs → v3 user record.
            intent.snmp.v3_users.append(CanonicalSNMPv3User(
                name=name,
                auth_protocol=_MT_AUTH_MAP.get(
                    auth_proto_raw.lower(), auth_proto_raw.lower(),
                ),
                auth_passphrase=kv.get("authentication-password", ""),
                priv_protocol=_MT_PRIV_MAP.get(
                    priv_proto_raw.lower(), priv_proto_raw.lower(),
                ),
                priv_passphrase=kv.get("encryption-password", ""),
            ))
        else:
            # Plain v1/v2c community.
            if not intent.snmp.community:
                intent.snmp.community = name


def _parse_ip_route(lines: list[str], intent: CanonicalIntent) -> None:
    """Parse ``add dst-address=... gateway=...`` static routes."""
    for line in lines:
        if not line.startswith("add"):
            continue
        kv = _parse_kv(line)
        dest = kv.get("dst-address")
        if not dest:
            continue
        gateway = kv.get("gateway", "")
        # gateway may be an IP or an interface name; both are fine for
        # the canonical form since we expose both fields.
        route = CanonicalStaticRoute(
            destination=dest,
            gateway=gateway,
            description=kv.get("comment", ""),
        )
        intent.static_routes.append(route)


# ---------------------------------------------------------------------------
# Shared name/type helpers (re-imported by render.py)
# ---------------------------------------------------------------------------


def _is_ethernet_name(name: str) -> bool:
    """Does this name look like a MikroTik default ethernet port?"""
    return bool(re.match(r"^ether\d", name, re.IGNORECASE))


def _is_vlan_name(name: str) -> bool:
    """Does this name look like a VLAN interface?"""
    return bool(re.match(r"^vlan\d", name, re.IGNORECASE))


# ---------------------------------------------------------------------------
# Cross-vendor name classifiers
# ---------------------------------------------------------------------------
#
# When a CanonicalIntent originates from a non-MikroTik codec the
# interface ``name`` is whatever the source vendor minted (``wan``,
# ``lan``, ``ge-0/0/0``, ``GigabitEthernet0/0/0``, ``Loopback0`` ...)
# and ``default_name`` is empty.  The render path needs a way to
# decide which interfaces belong inside which RouterOS section
# (``/interface vlan``, ``/interface bridge``, ``/interface bonding``,
# ``/interface ethernet``).  ``_is_vlan_name`` / ``_is_ethernet_name``
# above are MikroTik-shaped; the helpers below are intentionally
# permissive cross-vendor classifiers used as exclusion filters in
# the renderer.


def _looks_like_vlan_iface(name: str) -> bool:
    """Permissive: name looks like a VLAN/SVI interface from any vendor.

    Matches MikroTik ``vlanN`` form, generic ``vlan*`` names, and the
    Junos/IOS-style subinterface unit form (``ge-0/0/0.10``,
    ``Vlan100``, ``irb.0``).
    """
    if not name:
        return False
    if re.match(r"^vlan", name, re.IGNORECASE):
        return True
    # Subinterface unit form: anything with a dot followed by digits.
    # Junos `ge-0/0/0.10`, IOS `GigabitEthernet0/0/0.100`, etc.
    if re.search(r"\.\d+$", name):
        return True
    return False


def _looks_like_bridge_iface(name: str) -> bool:
    """Permissive: name looks like a bridge interface from any vendor."""
    if not name:
        return False
    return bool(re.match(r"^(bridge|br\d)", name, re.IGNORECASE))


def _looks_like_lag_iface(name: str) -> bool:
    """Permissive: name looks like a LAG/port-channel interface.

    Covers MikroTik ``bondN``, Cisco ``Port-channelN`` /
    ``port-channelN`` / ``PoN``, ArubaOS-S ``trkN`` / ``TrkN``,
    and Junos aggregated ethernet ``aeN``.
    """
    if not name:
        return False
    return bool(
        re.match(r"^(bond\d|port-channel\d|po\d|trk\d|ae\d)",
                 name, re.IGNORECASE)
    )


def _infer_iface_type_from_name(name: str) -> str:
    """Map a RouterOS interface-name pattern to the canonical IANA
    interface-type string.

    Any code that materialises a fresh ``CanonicalInterface`` must use
    this — otherwise different sections populate ``interface_type``
    inconsistently and round-trips drift.  Order matters: more-specific
    patterns come first.
    """
    if _is_vlan_name(name):
        return "ianaift:l3ipvlan"
    if _is_ethernet_name(name):
        return "ianaift:ethernetCsmacd"
    if re.match(r"^bond\d", name, re.IGNORECASE):
        return "ianaift:ieee8023adLag"
    if re.match(r"^(br|bridge)\d", name, re.IGNORECASE):
        return "ianaift:bridge"
    return ""


def _sort_interfaces(
    ifaces: Iterable[CanonicalInterface],
) -> list[CanonicalInterface]:
    """Deterministic interface ordering for reproducible output.

    Ethernet ports first (natural-sort by numeric suffix), then bridges,
    then VLAN interfaces, then everything else.
    """
    def sort_key(iface: CanonicalInterface) -> tuple[int, int, str]:
        name = iface.name
        if _is_ethernet_name(name):
            m = re.match(r"^ether(\d+)", name, re.IGNORECASE)
            return (0, int(m.group(1)) if m else 0, name)
        if name.startswith("bridge"):
            return (1, 0, name)
        if _is_vlan_name(name):
            m = re.match(r"^vlan(\d+)", name, re.IGNORECASE)
            return (2, int(m.group(1)) if m else 0, name)
        return (3, 0, name)
    return sorted(ifaces, key=sort_key)
