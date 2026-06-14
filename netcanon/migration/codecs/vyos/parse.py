"""
Parse path for VyOS (``config.boot`` / ``show configuration`` curly-brace
form).

Public function: :func:`parse_intent` — raw text in,
:class:`CanonicalIntent` out.  Targets the VyOS router/firewall NOS
(Debian-derived; the OSS Vyatta successor) on VyOS 1.3 / 1.4 / rolling.

VyOS stores its configuration as a JunOS-style **curly-brace tree** —
NOT the line-oriented CLI of the other text codecs and NOT the Junos
``set``-form the ``juniper_junos`` codec consumes::

    interfaces {
        ethernet eth0 {
            address 10.0.0.1/30
            description "uplink"
        }
        loopback lo {
            address 10.255.0.1/32
        }
    }
    protocols {
        static {
            route 0.0.0.0/0 {
                next-hop 10.0.0.2 {
                    distance 1
                }
            }
        }
    }
    system {
        host-name vyos-router
    }
    // vyos-config-version: "..."

Phase 1 (Tier-1) surface:

* ``system host-name <name>`` → :attr:`CanonicalIntent.hostname`.
* ``interfaces ethernet <ethN>`` / ``loopback <lo>`` / ``dummy <dumN>``
  blocks → :class:`CanonicalInterface` carrying ``address`` (IPv4 / IPv6
  CIDR, or ``dhcp`` / ``dhcpv6``), ``description``, ``disable`` (→
  admin-down; VyOS interfaces are UP by default), and ``mtu``.
* ``ethernet <ethN> { vif <vid> { ... } }`` → a sub-interface
  :class:`CanonicalInterface` named ``<ethN>.<vid>`` (router-on-a-stick
  VLAN tagging).
* ``protocols static route <CIDR> { next-hop <ip> { distance <N> } }``
  (+ ``route6``) → :class:`CanonicalStaticRoute`.

Grammar notes that shape the walker:

* **No statement terminators** — VyOS uses bare newlines inside ``{ }``
  blocks (unlike Junos curly-form which terminates leaves with ``;``).
  This is the cheap structural discriminator from a Junos
  ``show configuration`` capture (handled in the probe).
* **Values may be quoted or bare** — VyOS 1.4+ quotes leaf values
  (``address "10.0.0.1/30"``); older 1.3 / 1.4-rolling configs leave
  them bare.  :func:`_unquote` strips an optional matching ``'``/``"``
  pair so the canonical value is quote-agnostic (round-trip stable).
* **Comments** — ``/* ... */`` node comments and ``//`` trailer lines
  (incl. the ``// vyos-config-version`` stamp) are skipped.

Deferred to later phases (parse-and-ignore in v1): ``bonding`` LAGs,
``system login`` local users, ``service`` (SSH / NTP / SNMP / DHCP),
VRF (``vrf name <X>``), and the Tier-3 ``protocols bgp/ospf`` / ``nat``
/ ``firewall`` / ``policy`` blocks.
"""

from __future__ import annotations

import logging
import re

from ...canonical.intent import (
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
    CanonicalLocalUser,
    CanonicalStaticRoute,
)
from .._input_shape import detect_input_shape
from ..base import ParseError

logger = logging.getLogger(__name__)


#: ``system host-name <name>`` leaf (matched by path + this value regex).
_HOSTNAME_KEY = "host-name"

#: Interface block types that materialise a :class:`CanonicalInterface`
#: in Phase 1 (``bonding`` is deferred to the LAG phase).
_IFACE_BLOCK_TYPES = frozenset({"ethernet", "loopback", "dummy"})


def _unquote(value: str) -> str:
    """Strip a single surrounding pair of matching ``'`` or ``"`` quotes.

    VyOS 1.4+ quotes leaf values; older configs leave them bare.  The
    canonical value is the unquoted text either way (so a quoted-vs-bare
    difference never registers as round-trip drift)."""
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def _split_header(header: str) -> tuple[str, str]:
    """Split a block header ``"ethernet eth0"`` into ``("ethernet",
    "eth0")``; a single-token header ``"static"`` into ``("static",
    "")``.  The arg keeps any internal spaces (rare, but e.g. a quoted
    description block — not used in v1)."""
    parts = header.split(None, 1)
    if not parts:
        return ("", "")
    return (parts[0], parts[1].strip() if len(parts) > 1 else "")


def _is_v6(addr: str) -> bool:
    """True iff *addr* (the host part of a CIDR) looks like IPv6."""
    return ":" in addr


def parse_intent(raw: str) -> CanonicalIntent:
    """Parse VyOS ``config.boot`` text into a :class:`CanonicalIntent`.

    Raises:
        ParseError: If the input is empty or looks like XML / JSON.
    """
    if not raw.strip():
        raise ParseError("vyos: empty input", snippet="")

    shape = detect_input_shape(raw)
    if shape is not None:
        raise ParseError(
            f"vyos: input looks like {shape.upper()}, not VyOS "
            f"config.  Paste the output of `show configuration` or the "
            f"contents of /config/config.boot.",
            snippet=raw.lstrip()[:120],
        )

    intent = CanonicalIntent(source_vendor="vyos", source_format="cli-vyos")

    # Per-interface scratch keyed by canonical name (preserves first-seen
    # order via ``iface_order``).
    iface_scratch: dict[str, dict] = {}
    iface_order: list[str] = []
    static_routes: list[dict] = []
    cur_route: dict | None = None  # the route whose next-hop block is open
    # ── Phase 2 scratch ──
    users: dict[str, dict] = {}       # name -> {"hash": str, "level": str}
    user_order: list[str] = []
    ntp_servers: list[str] = []
    lags: dict[str, dict] = {}        # bondN -> {"mode": str, "members": list}
    lag_order: list[str] = []

    stack: list[tuple[str, str]] = []

    def _touch_user(name: str) -> dict:
        u = users.get(name)
        if u is None:
            u = {"hash": "", "level": ""}
            users[name] = u
            user_order.append(name)
        return u

    def _touch_lag(name: str) -> dict:
        lg = lags.get(name)
        if lg is None:
            lg = {"mode": "static", "members": []}
            lags[name] = lg
            lag_order.append(name)
        return lg

    def _add_lag_member(bond: str, member: str) -> None:
        lg = _touch_lag(bond)
        if member and member not in lg["members"]:
            lg["members"].append(member)
        # Materialise the member iface + set its back-reference.
        _touch_iface(member, "ethernet")["lag_member_of"] = bond

    def _touch_iface(name: str, kind: str) -> dict:
        sc = iface_scratch.get(name)
        if sc is None:
            sc = {
                "name": name,
                "kind": kind,
                "description": "",
                "enabled": True,   # VyOS interfaces are UP by default
                "mtu": None,
                "ipv4": [],
                "ipv6": [],
                "dhcp_client": False,
                "dhcp_client_v6": "",
                "lag_member_of": None,
            }
            iface_scratch[name] = sc
            iface_order.append(name)
        return sc

    def _current_iface(stk: list[tuple[str, str]]) -> dict | None:
        """Return the interface scratch for the current stack path, or
        None when the leaf isn't at an interface (or vif) level we model.
        """
        if len(stk) < 2 or stk[0][0] != "interfaces":
            return None
        typ, arg = stk[1]
        # A ``bonding bondN`` block is an L3-capable interface (it can
        # carry address / description / mtu); its ``mode`` / ``member``
        # are handled separately in the leaf / block-open dispatch.
        if typ == "bonding" and arg and len(stk) == 2:
            return _touch_iface(arg, "bonding")
        if typ not in _IFACE_BLOCK_TYPES or not arg:
            return None
        if len(stk) == 2:
            return _touch_iface(arg, typ)
        if len(stk) == 3 and stk[2][0] == "vif" and stk[2][1]:
            return _touch_iface(f"{arg}.{stk[2][1]}", "ethernet")
        return None  # deeper nesting we don't model in v1

    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if (
            not line
            or line.startswith("//")
            or line.startswith("/*")
            or line.startswith("*")
        ):
            continue

        if line == "}":
            if stack:
                popped = stack.pop()
                if popped[0] == "next-hop":
                    cur_route = None
            continue

        if line.endswith("{"):
            header = line[:-1].strip()
            node = _split_header(header)
            stack.append(node)
            # Materialise an interface stub on block-open so an empty
            # interface (no leaves) still round-trips.  ``bonding bondN``
            # is L3-capable AND declares a LAG.
            if node[0] in ("vif", "bonding") or node[0] in _IFACE_BLOCK_TYPES:
                _current_iface(stack)
                if node[0] == "bonding" and node[1]:
                    _touch_lag(node[1])
            # A ``user <name>`` block under ``system { login { ... } }``.
            elif (
                node[0] == "user" and node[1]
                and len(stack) == 3
                and stack[0][0] == "system"
                and stack[1][0] == "login"
            ):
                _touch_user(node[1])
            # A bond member declared 1.3+/1.4-style:
            # ``interfaces / bonding bondN / member / interface ethN``.
            elif (
                node[0] == "interface" and node[1]
                and len(stack) == 4
                and stack[0][0] == "interfaces"
                and stack[1][0] == "bonding"
                and stack[2][0] == "member"
            ):
                _add_lag_member(stack[1][1], node[1])
            # A ``next-hop`` block under ``static route`` creates a route.
            elif node[0] == "next-hop":
                cur_route = _open_route(stack, node[1], static_routes)
            continue

        # ── Leaf line: "<key> <value...>" or bare "<key>" ──
        key, _, rest = line.partition(" ")
        value = _unquote(rest) if rest else ""

        # system host-name
        if (
            len(stack) == 1
            and stack[0][0] == "system"
            and key == _HOSTNAME_KEY
            and value
        ):
            intent.hostname = value
            continue

        # static-route metric (distance) inside the open next-hop block
        if key == "distance" and cur_route is not None and value.isdigit():
            cur_route["metric"] = int(value)
            continue

        # ── Phase 2: bond mode (interfaces / bonding bondN / mode <m>) ──
        # `802.3ad` is LACP -> "active"; other modes (active-backup,
        # balance-rr, ...) collapse to "static" (declared lossy).
        if (
            key == "mode" and value
            and len(stack) == 2
            and stack[0][0] == "interfaces"
            and stack[1][0] == "bonding"
        ):
            _touch_lag(stack[1][1])["mode"] = (
                "active" if value == "802.3ad" else "static"
            )
            continue

        # ── Phase 2: bond member, legacy 1.2 form
        # (interfaces / ethernet ethN / bond-group bondN) ──
        if (
            key == "bond-group" and value
            and len(stack) == 2
            and stack[0][0] == "interfaces"
            and stack[1][0] == "ethernet"
        ):
            _add_lag_member(value, stack[1][1])
            continue

        # ── Phase 2: local-user password
        # (system / login / user X / authentication / encrypted-password) ──
        if (
            key == "encrypted-password" and value
            and len(stack) == 4
            and stack[0][0] == "system" and stack[1][0] == "login"
            and stack[2][0] == "user" and stack[3][0] == "authentication"
        ):
            _touch_user(stack[2][1])["hash"] = value
            continue

        # ── Phase 2: NTP servers (system/service / ntp / server <host>) ──
        if (
            key == "server" and value
            and len(stack) == 2
            and stack[0][0] in ("system", "service")
            and stack[1][0] == "ntp"
        ):
            if value not in ntp_servers:
                ntp_servers.append(value)
            continue

        # interface leaves
        sc = _current_iface(stack)
        if sc is not None:
            _apply_iface_leaf(sc, key, value)
            continue

        # Anything else (service / deeper protocols / nat / firewall /
        # system login / ...) is parse-and-ignore in v1.

    intent.interfaces = [
        _build_iface(iface_scratch[name]) for name in iface_order
    ]
    intent.static_routes = [
        CanonicalStaticRoute(
            destination=r["destination"],
            gateway=r["gateway"],
            metric=r["metric"],
        )
        for r in static_routes
    ]

    # ── Phase 2 surfaces ──
    intent.local_users = [
        CanonicalLocalUser(
            name=name,
            privilege_level=15,  # VyOS login users have full access
            role="admin",
            hashed_password=users[name]["hash"],
        )
        for name in user_order
    ]
    intent.ntp_servers = list(ntp_servers)
    intent.lags = [
        CanonicalLAG(
            name=name,
            members=list(lags[name]["members"]),
            mode=lags[name]["mode"],
        )
        for name in lag_order
    ]

    logger.debug(
        "vyos parsed: hostname=%r ifaces=%d routes=%d users=%d lags=%d "
        "ntp=%d (input=%d chars)",
        intent.hostname, len(intent.interfaces), len(intent.static_routes),
        len(intent.local_users), len(intent.lags), len(intent.ntp_servers),
        len(raw),
    )
    return intent


def _open_route(
    stack: list[tuple[str, str]], gateway: str, routes: list[dict],
) -> dict | None:
    """Create a static-route scratch when a ``next-hop`` block opens.

    Expects the stack path ``protocols / static / route <CIDR> /
    next-hop <gw>`` (``route6`` accepted for IPv6).  Returns the new
    scratch dict (so the caller can attach a ``distance`` metric) or
    None when the path doesn't match.
    """
    if (
        len(stack) >= 4
        and stack[-4][0] == "protocols"
        and stack[-3][0] == "static"
        and stack[-2][0] in ("route", "route6")
    ):
        dest = stack[-2][1]
        if dest:
            route = {"destination": dest, "gateway": gateway, "metric": 0}
            routes.append(route)
            return route
    return None


def _apply_iface_leaf(sc: dict, key: str, value: str) -> None:
    """Apply one interface-block leaf to the scratch dict."""
    if key == "address" and value:
        if value.lower() == "dhcp":
            sc["dhcp_client"] = True
        elif value.lower() == "dhcpv6":
            sc["dhcp_client_v6"] = "dhcpv6"
        elif "/" in value:
            addr, _, plen = value.partition("/")
            try:
                prefix = int(plen)
            except ValueError:
                return
            if _is_v6(addr):
                sc["ipv6"].append({"ip": addr, "prefix_length": prefix})
            else:
                sc["ipv4"].append({"ip": addr, "prefix_length": prefix})
    elif key == "description":
        sc["description"] = value
    elif key == "disable":
        sc["enabled"] = False
    elif key == "mtu" and value.isdigit():
        sc["mtu"] = int(value)
    # hw-id / mac / other leaves → parse-and-ignore.


def _build_iface(sc: dict) -> CanonicalInterface:
    """Convert an interface scratch dict into a CanonicalInterface."""
    scope_v6 = "global"
    return CanonicalInterface(
        name=sc["name"],
        description=sc.get("description", ""),
        enabled=sc.get("enabled", True),
        mtu=sc.get("mtu"),
        ipv4_addresses=[
            CanonicalIPv4Address(ip=a["ip"], prefix_length=a["prefix_length"])
            for a in sc.get("ipv4", [])
        ],
        ipv6_addresses=[
            CanonicalIPv6Address(
                ip=a["ip"], prefix_length=a["prefix_length"], scope=scope_v6,
            )
            for a in sc.get("ipv6", [])
        ],
        dhcp_client=sc.get("dhcp_client", False),
        dhcp_client_v6=sc.get("dhcp_client_v6", ""),
        lag_member_of=sc.get("lag_member_of"),
    )
