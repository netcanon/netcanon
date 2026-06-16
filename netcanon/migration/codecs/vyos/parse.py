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

Phase 2 added ``bonding`` LAGs, ``system login`` local users, and
``system`` / ``service`` NTP servers.  Phase 3 added ``service snmp``
(v1/v2c community + location / contact + v3 USM users) and VRF (``vrf
name <X> { table <N> }`` routing instances + the per-interface ``vrf
<X>`` binding).  **Phase 5** (this commit) adds ``interfaces vxlan
vxlanN`` netdevs → :class:`CanonicalVxlan` (one VNI per netdev:
``vni`` / ``source-address`` / ``group`` / ``remote`` / ``port``).

**set-form input**: the parser also accepts VyOS *set-form* text (the
output of ``show configuration commands`` — a flat sequence of ``set
<path> [value]`` lines).  :func:`_setform_to_brace` converts it to the
equivalent curly-brace text up front, so the brace-stack walker (and
every phase of its dispatch) runs unchanged — mirroring how the
``juniper_junos`` codec converts block-form to set-form ahead of its
set-parser.  The conversion is idempotent on curly-brace input.  Render
always emits curly-brace ``config.boot`` (the native backup form); a
``set``-form-in / ``set``-form-out round-trip is not a goal.

Deferred to later phases (parse-and-ignore for now): the remaining
``service`` management-plane blocks (SSH / DHCP / syslog / DNS), the
VXLAN-to-bridge L2 VLAN binding (``interfaces bridge`` membership) +
single-device SVD ``vlan-to-vni``, per-VRF static routes (``vrf name
<X> { protocols static ... }``), and the Tier-3 ``protocols bgp/ospf``
/ ``nat`` / ``firewall`` / ``policy`` blocks.
"""

from __future__ import annotations

import logging

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
    CanonicalVxlan,
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


# ---------------------------------------------------------------------------
# set-form → curly-brace normalisation
# ---------------------------------------------------------------------------
#
# VyOS accepts two interchangeable text grammars for the same config:
#
#   * **curly-brace** ``config.boot`` — the native on-disk backup, parsed
#     directly by the brace-stack walker in :func:`parse_intent`.
#   * **set-form** — the output of ``show configuration commands`` (a flat
#     sequence of ``set <space-separated path> [value]`` lines).
#
# Rather than duplicate the walker's dispatch, set-form is *converted to
# the equivalent curly-brace text* up front and then handed to the SAME
# walker (mirroring how the ``juniper_junos`` codec converts block-form to
# set-form ahead of its set-parser).  The walker — and every phase of its
# dispatch — is therefore untouched.
#
# The conversion needs to know, per path token, whether it is a *tag node*
# (consumes the next token as an identifier → a two-token brace header like
# ``ethernet eth0``) or a *leaf* (terminal — the remainder of the line is
# its value).  Anything else is treated as a plain single-token container.
# These two tables are kept in sync with the block-open / leaf dispatch in
# :func:`parse_intent`; unknown keywords default to "container" so Tier-3
# blocks (``set firewall …`` / ``set nat …`` / ``set protocols bgp …``)
# still nest under a recognisable top-level header for the Tier-3 banner
# detector (they parse-and-ignore in the walker regardless).

#: Keywords that consume the FOLLOWING token as a node identifier (a
#: two-token brace header ``"<kw> <id>"``).  ``vrf`` is handled separately
#: (it is a container only in the ``vrf name <X>`` bigram — see
#: :func:`_chunk_setline`).
_SETFORM_TAG_NODES = frozenset({
    "ethernet", "loopback", "dummy", "bonding", "vxlan", "bridge",
    "wireguard", "tunnel", "vti", "pppoe", "geneve", "vif",
    "route", "route6", "next-hop",
    "name",            # `vrf name <X>` (and Tier-3 `firewall name <X>`)
    "community", "user", "server", "interface",
})

#: Terminal keywords — the remainder of the ``set`` line is the leaf value
#: (or empty for a bare flag like ``disable``).  Kept in sync with the leaf
#: dispatch in :func:`parse_intent`.
_SETFORM_LEAVES = frozenset({
    "host-name", "address", "description", "disable", "mtu", "hw-id", "mac",
    "distance", "mode", "bond-group",
    "encrypted-password", "plaintext-password", "encrypted-key", "type",
    "vni", "group", "remote", "source-address", "source-interface",
    "link", "dev", "port", "table",
    "location", "contact", "engineid",
})


def _looks_like_setform(raw: str) -> bool:
    """True iff *raw* is VyOS set-form (the first meaningful line is a
    ``set `` command).  Curly-brace ``config.boot`` opens with a block
    header (``interfaces {`` / ``system {`` …), so this is a clean
    either/or — the two grammars are never interleaved in practice."""
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", "//", "/*", "*")):
            continue
        return s.startswith("set ")
    return False


def _chunk_setline(tokens: list[str]) -> tuple[list[str], str | None]:
    """Split the tokens of a ``set`` line (after the leading ``set``) into
    the list of brace-header strings (the node path) and an optional leaf
    line (``"<key> <value...>"``).

    The single context-sensitive case is ``vrf``: a top-level ``vrf name
    <X>`` declaration makes ``vrf`` a container (and ``name`` its tag
    node), whereas the per-interface ``vrf <name>`` binding makes ``vrf``
    a leaf.  The ``vrf name`` bigram disambiguates them.
    """
    headers: list[str] = []
    i, n = 0, len(tokens)
    while i < n:
        tok = tokens[i]
        if tok == "vrf":
            if i + 1 < n and tokens[i + 1] == "name":
                headers.append("vrf")          # container; `name` follows
                i += 1
                continue
            return headers, " ".join(tokens[i:])   # per-interface leaf
        if tok in _SETFORM_LEAVES:
            return headers, " ".join(tokens[i:])
        if tok in _SETFORM_TAG_NODES and i + 1 < n:
            headers.append(f"{tok} {tokens[i + 1]}")
            i += 2
            continue
        headers.append(tok)                    # container / unknown
        i += 1
    return headers, None


_LEAVES_KEY = "\x00leaves"


def _setform_to_brace(raw: str) -> str:
    """Convert VyOS set-form text to the equivalent curly-brace text.

    Idempotent on curly-brace input (returned unchanged), so this is safe
    to call unconditionally ahead of the brace-stack walker.  Non-``set``
    lines (blank / comment / a stray ``deactivate``) are skipped, matching
    the walker's parse-tolerance.
    """
    if not _looks_like_setform(raw):
        return raw

    root: dict = {}
    for line in raw.splitlines():
        s = line.strip()
        if not s.startswith("set "):
            continue
        headers, leaf = _chunk_setline(s[4:].split())
        node = root
        for h in headers:
            node = node.setdefault(h, {})
        if leaf is not None:
            node.setdefault(_LEAVES_KEY, []).append(leaf)

    return "\n".join(_serialise_brace(root, 0))


def _serialise_brace(node: dict, depth: int) -> list[str]:
    """Render a nested node dict (built by :func:`_setform_to_brace`) into
    indented VyOS curly-brace lines.  Leaves are emitted before child
    blocks; sibling order is irrelevant to the stack-based walker."""
    pad = "    " * depth
    out: list[str] = []
    for leaf in node.get(_LEAVES_KEY, []):
        out.append(f"{pad}{leaf}")
    for header, child in node.items():
        if header == _LEAVES_KEY:
            continue
        out.append(f"{pad}{header} {{")
        out.extend(_serialise_brace(child, depth + 1))
        out.append(f"{pad}}}")
    return out


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

    # Accept set-form (`show configuration commands`) by converting it to
    # the equivalent curly-brace text up front; idempotent on brace input.
    raw = _setform_to_brace(raw)

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
    # ── Phase 3 scratch ──
    snmp_seen = False                 # any `service snmp` content present
    snmp_community = ""
    snmp_location = ""
    snmp_contact = ""
    snmp_engine_id = ""               # config-wide v3 engineID (mapped per-user)
    v3_users: dict[str, dict] = {}    # name -> {auth/priv proto+pass, group}
    v3_user_order: list[str] = []
    vrfs: dict[str, dict] = {}        # vrf name -> {} (numeric table id dropped)
    vrf_order: list[str] = []
    # ── Phase 5 scratch ──
    vxlans: dict[str, dict] = {}      # vxlanN -> {vni, mcast, source, udp_port, flood}
    vxlan_order: list[str] = []

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

    def _touch_v3_user(name: str) -> dict:
        u = v3_users.get(name)
        if u is None:
            u = {
                "auth_proto": "", "auth_pass": "",
                "priv_proto": "", "priv_pass": "", "group": "",
            }
            v3_users[name] = u
            v3_user_order.append(name)
        return u

    def _touch_vrf(name: str) -> None:
        """Materialise a routing-instance from its authoritative ``vrf
        name <X>`` declaration only.  A per-interface ``vrf <X>`` binding
        NEVER calls this (it only stamps the interface scratch) — that is
        the phantom-instance guard: an interface referencing a VRF that
        was never declared does not conjure an empty instance."""
        if name not in vrfs:
            vrfs[name] = {}
            vrf_order.append(name)

    def _touch_vxlan(name: str) -> dict:
        vx = vxlans.get(name)
        if vx is None:
            vx = {
                "vni": None, "mcast": "", "source": "",
                "udp_port": None, "flood": [],
            }
            vxlans[name] = vx
            vxlan_order.append(name)
        return vx

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
                "vrf": "",
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
            not line or line.startswith(("//", "/*", "*"))
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
            # ── Phase 5: an ``interfaces vxlan vxlanN`` netdev (one VNI
            # per netdev — NOT a generic L3 interface; handled separately
            # from ``_current_iface``).
            elif (
                node[0] == "vxlan" and node[1]
                and len(stack) == 2
                and stack[0][0] == "interfaces"
            ):
                _touch_vxlan(node[1])
            # ── Phase 3: a ``vrf { name <X> { ... } }`` routing instance,
            # materialised from this authoritative declaration only.
            elif (
                node[0] == "name" and node[1]
                and len(stack) == 2
                and stack[0][0] == "vrf"
            ):
                _touch_vrf(node[1])
            # ── Phase 3: the ``service { snmp { ... } }`` block.
            elif (
                node[0] == "snmp"
                and len(stack) == 2
                and stack[0][0] == "service"
            ):
                snmp_seen = True
            # ── Phase 3: ``snmp { community <name> { ... } }`` (v1/v2c) —
            # only the community name is canonical (authorization dropped).
            elif (
                node[0] == "community" and node[1]
                and len(stack) == 3
                and stack[0][0] == "service" and stack[1][0] == "snmp"
            ):
                snmp_seen = True
                if not snmp_community:
                    snmp_community = node[1]
            # ── Phase 3: an SNMP v3 ``user <name>`` block (distinct from
            # the ``system login user`` block above — guarded by path).
            elif (
                node[0] == "user" and node[1]
                and len(stack) == 4
                and stack[0][0] == "service" and stack[1][0] == "snmp"
                and stack[2][0] == "v3"
            ):
                snmp_seen = True
                _touch_v3_user(node[1])
            # ── Phase 5: NTP server in BLOCK form
            # (``system``/``service`` / ``ntp`` / ``server <host> { ... }``).
            # VyOS 1.4-rolling (mid-2023+) writes NTP servers as blocks; the
            # older bare-leaf ``server <host>`` form is handled in the leaf
            # dispatch below.  Both yield the same canonical host list.
            elif (
                node[0] == "server" and node[1]
                and len(stack) == 3
                and stack[0][0] in ("system", "service")
                and stack[1][0] == "ntp"
            ):
                if node[1] not in ntp_servers:
                    ntp_servers.append(node[1])
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

        # ── Phase 3: SNMP location / contact (service / snmp / <leaf>) ──
        if (
            key in ("location", "contact") and value
            and len(stack) == 2
            and stack[0][0] == "service" and stack[1][0] == "snmp"
        ):
            snmp_seen = True
            if key == "location":
                snmp_location = value
            else:
                snmp_contact = value
            continue

        # ── Phase 3: SNMP v3 config-wide engineID
        # (service / snmp / v3 / engineid <hex>) ──
        if (
            key == "engineid" and value
            and len(stack) == 3
            and stack[0][0] == "service" and stack[1][0] == "snmp"
            and stack[2][0] == "v3"
        ):
            snmp_seen = True
            snmp_engine_id = value
            continue

        # ── Phase 3: SNMP v3 user group
        # (service / snmp / v3 / user <name> / group <g>) ──
        if (
            key == "group" and value
            and len(stack) == 4
            and stack[0][0] == "service" and stack[1][0] == "snmp"
            and stack[2][0] == "v3" and stack[3][0] == "user"
        ):
            _touch_v3_user(stack[3][1])["group"] = value
            continue

        # ── Phase 3: SNMP v3 user auth / privacy leaves
        # (.../ user <name> / {auth|privacy} / {type | encrypted-password
        # | encrypted-key}).  Plaintext keys never appear in a saved
        # config; the opaque ciphertext round-trips verbatim same-vendor. ──
        if (
            len(stack) == 5
            and stack[0][0] == "service" and stack[1][0] == "snmp"
            and stack[2][0] == "v3" and stack[3][0] == "user"
            and stack[4][0] in ("auth", "privacy")
            and key in ("type", "encrypted-password", "encrypted-key")
            and value
        ):
            u = _touch_v3_user(stack[3][1])
            if key == "type":
                if stack[4][0] == "auth":
                    u["auth_proto"] = value.lower()
                else:
                    u["priv_proto"] = value.lower()
            else:  # encrypted-password / encrypted-key → opaque key blob
                if stack[4][0] == "auth":
                    u["auth_pass"] = value
                else:
                    u["priv_pass"] = value
            continue

        # ── Phase 5: VXLAN netdev leaves
        # (interfaces / vxlan vxlanN / {vni|group|remote|source-*|port}) ──
        if (
            len(stack) == 2
            and stack[0][0] == "interfaces" and stack[1][0] == "vxlan"
            and value
        ):
            vx = _touch_vxlan(stack[1][1])
            if key == "vni" and value.isdigit():
                vx["vni"] = int(value)
            elif key == "group":
                vx["mcast"] = value
            elif key == "remote":
                if value not in vx["flood"]:
                    vx["flood"].append(value)
            elif key in ("source-address", "source-interface", "link", "dev"):
                vx["source"] = value
            elif key == "port" and value.isdigit():
                vx["udp_port"] = int(value)
            # address / mtu / parameters / vlan-to-vni → parse-and-ignore
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

    # ── Phase 3 surfaces ──
    if snmp_seen:
        intent.snmp = CanonicalSNMP(
            community=snmp_community,
            location=snmp_location,
            contact=snmp_contact,
            v3_users=[
                CanonicalSNMPv3User(
                    name=name,
                    group=v3_users[name]["group"],
                    auth_protocol=v3_users[name]["auth_proto"],
                    auth_passphrase=v3_users[name]["auth_pass"],
                    priv_protocol=v3_users[name]["priv_proto"],
                    priv_passphrase=v3_users[name]["priv_pass"],
                    engine_id=snmp_engine_id,
                )
                for name in v3_user_order
            ],
        )
    intent.routing_instances = [
        CanonicalRoutingInstance(name=name) for name in vrf_order
    ]

    # ── Phase 5: VXLAN netdevs (one VNI each).  ``vlan_id`` is synthesised
    # — VyOS carries no VLAN on the netdev (the L2 binding lives on a
    # separate bridge), but the canonical field is required; the derivation
    # is deterministic so it survives the round-trip.  Sorted by vni (the
    # round-trip does not normalise ``vxlan_vnis`` order). ──
    vxlan_vnis = []
    for name in vxlan_order:
        vx = vxlans[name]
        if vx["vni"] is None:
            continue  # a vxlan netdev with no `vni` isn't a usable binding
        vni = vx["vni"]
        vxlan_vnis.append(
            CanonicalVxlan(
                vlan_id=((vni - 1) % 4094) + 1,
                vni=vni,
                mcast_group=vx["mcast"],
                flood_list=list(vx["flood"]),
                source_interface=vx["source"],
                udp_port=vx["udp_port"] if vx["udp_port"] is not None else 8472,
            )
        )
    intent.vxlan_vnis = sorted(vxlan_vnis, key=lambda v: v.vni)

    logger.debug(
        "vyos parsed: hostname=%r ifaces=%d routes=%d users=%d lags=%d "
        "ntp=%d snmp=%s vrfs=%d vxlans=%d (input=%d chars)",
        intent.hostname, len(intent.interfaces), len(intent.static_routes),
        len(intent.local_users), len(intent.lags), len(intent.ntp_servers),
        intent.snmp is not None, len(intent.routing_instances),
        len(intent.vxlan_vnis),
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
    elif key == "vrf" and value:
        # ── Phase 3: per-interface VRF binding.  Stamps the scratch
        # only — never materialises a routing-instance (phantom guard).
        sc["vrf"] = value
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
        vrf=sc.get("vrf", ""),
    )
