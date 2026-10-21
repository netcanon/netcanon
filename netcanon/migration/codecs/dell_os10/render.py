"""
Render path for Dell SmartFabric OS10 (canonical tree → ``show
running-configuration`` text).

Public function: :func:`render_intent` — :class:`CanonicalIntent` in,
OS10 CLI text out.

Phase 2 emits the surface Phase 1 parses: the ``! Version`` banner, the
explicit ``ip vrf default`` stanza, named VRF declarations, hostname,
interface stanzas (description / admin state / LAG membership / L2
switchport / mtu / VRF bind / IPv4 + IPv6 CIDR), and static routes.  It
stays deliberately tolerant of the canonical surfaces it does NOT emit
(SNMP, local users, VRRP, the management plane): a cross-vendor source
tree carrying those renders cleanly, simply omitting them, and the
capability matrix declares each omission so the migrate-page banner
surfaces the gap.

Three inversions of the parse-side traps live here — each one is the
reason the round-trip holds:

* **The native VLAN re-emits as ``switchport access vlan``.**  OS10 has
  no ``switchport trunk native vlan`` line at all (measured: 0
  occurrences), so a trunk's native VLAN can only be written with the
  access-vlan keyword.  Emitting it as anything else would round-trip
  into ``access_vlan`` and invert the port's L2 semantics.

* **The allowed line is the list WITHOUT the native VLAN.**  In the
  tree a trunk's list is everything the port carries, its native VLAN
  among them; OS10's allowed line names the tagged VLANs and its
  access line the untagged one, and one VLAN is never on both
  (``BESIDE_THE_LIST`` in ``NATIVE_VLAN_AND_THE_LIST``,
  :mod:`.._helpers`).  The parser puts the access VLAN back into the
  list, so a trunk comes back as it went.  A native VLAN the list does
  NOT hold is, in the tree, stated and not carried: no access VLAN is
  written for it, and ``no switchport access vlan`` under a
  ``! review:`` line stands in its place.  So does a trunk with NO
  native VLAN, which carries no VLAN untagged: with neither line an
  OS10 trunk is an untagged member of the switch's default VLAN, and
  Dell's pages disagree on what the ``no`` line leaves it with, which
  its review line says.  The parser reads a trunk with the line and
  one with neither as the same tree, so the line comes back for both.
  An interface another record of which states its untagged VLAN -- a
  native VLAN, or an access VLAN -- is not written the line: OS10
  applies an interface's stanzas in turn, and the line would take
  that VLAN back.

* **A ``vrf="management"`` route re-emits as ``management route``**, not
  ``ip route vrf management`` — the inverse of the parse mapping, so the
  management-only default never lands in the global RIB.  An IPv6
  destination falls back to ``ipv6 route vrf management`` because the
  ``management route`` grammar observed in the corpus is IPv4-only;
  re-parse still recovers ``vrf="management"`` either way.

* **SVIs re-emit in the device form ``interface vlan<N>``** (no space,
  lower case) rather than the operator spelling ``Vlan <N>``, matching
  what a real switch prints.

Deliberate non-emissions, each load-bearing for round-trip stability:

* **No stanza is synthesised for a LAG or VLAN that exists only by
  implication.**  A ``port-channel`` known only from a member's
  ``channel-group`` line, or a VLAN known only from switchport
  projection, is reconstructed by the parser from those same member
  lines — emitting a stanza for it would add an interface the source
  tree never had and drift the ``interfaces`` list.  A VLAN that carries
  information the member lines CANNOT encode (a name or an IP) and has
  no SVI does get one, because otherwise that information is lost; this
  cannot fire on a same-vendor round-trip, where a named VLAN always
  came from an SVI's description and therefore already has one.

* **``hostname`` is emitted only when set.**  Substituting a default for
  an empty hostname (the NX-OS render does this because its ``vdc``
  wrapper needs a name) would re-parse as that default and drift.

Known fidelity gap, stated rather than papered over: a routed port with
no IP address — an OS10 ``channel-group`` member carrying ``no
switchport`` — re-emits without that line, because the canonical model
has no field for "explicitly routed, no address".  The round-trip is
unaffected (the parser sets no field for it either way) and on a real
device the member port follows its port-channel's mode.  The same gap
exists in the ``cisco_nxos`` render for the same reason.
"""

from __future__ import annotations

from ..._user_secrets import classify_hash, format_review_comment, is_migratable
from ..._usm_keys import PLAINTEXT, user_usm_is_migratable, user_usm_kind
from ...canonical.intent import CanonicalIntent, CanonicalInterface
from .._helpers import (
    TRUNK_ALL,
    mtu_written,
    native_vlan_stated,
    same_vendor_version,
    switchport_trunk_allowed_value,
    trunk_list_says,
    trunk_list_written,
    trunk_untagged_vlan,
)
from . import port_names as _port_names

#: Canonical SNMPv3 auth protocol → OS10 keyword.  OS10 offers ONLY
#: ``md5`` and ``sha`` (10.5.2 User Guide L9085), so every SHA-2 variant
#: collapses to ``sha`` — a real downgrade, declared lossy on
#: ``/snmp/v3-user/auth-protocol``.
_CANON_TO_OS10_AUTH = {
    "md5": "md5", "sha": "sha", "sha1": "sha",
    "sha224": "sha", "sha256": "sha", "sha384": "sha", "sha512": "sha",
}

#: Canonical SNMPv3 privacy cipher → OS10 keyword.  OS10 offers ONLY
#: ``des`` and ``aes``, so AES-192/256 collapse to ``aes`` — declared lossy
#: on ``/snmp/v3-user/priv-protocol``.
_CANON_TO_OS10_PRIV = {
    "aes": "aes", "aes128": "aes", "aes192": "aes", "aes256": "aes",
    "des": "des", "3des": "des",
}

#: Synthesised OS10 release stamped into the banner when the source
#: device's own release is unknown.  When the tree was parsed by THIS
#: codec and carries a ``source_version``, that real release is echoed
#: instead — otherwise a same-vendor pass silently relabels the device's
#: config with a constant (#297).  ``source_version`` is metadata-excluded
#: from every comparator, so this is round-trip-invisible.
_DEFAULT_VERSION = "10.5.1.0"

#: Canonical LAG mode → OS10 ``channel-group ... mode`` keyword (inverse
#: of ``parse._OS10_LAG_MODE_MAP``; canonical ``static`` → OS10 ``on``).
_CANON_TO_OS10_LAG_MODE = {
    "active": "active",
    "passive": "passive",
    "static": "on",
}

#: Interface-kind render order, matching the order a real switch prints
#: (measured on the JetPack dumps): SVIs, then port-channels, then the
#: management port, then physical ethernet, then loopbacks.  Ordering is
#: cosmetic — the round-trip comparator sorts interfaces by name — but
#: matching the device makes diffs reviewable.
_KIND_ORDER: dict[str, int] = {
    "svi": 0,
    "lag": 1,
    "mgmt": 2,
    "physical": 3,
    "breakout": 3,
    "loopback": 4,
}


def _version_token(tree: CanonicalIntent) -> str:
    """The OS10 release to stamp: the device's own when same-vendor and
    known, else the synthetic default (shared helper, review #63)."""
    return same_vendor_version(
        tree, vendor_id="dell_os10", default=_DEFAULT_VERSION,
    )


def render_intent(tree: CanonicalIntent) -> str:
    """Render a :class:`CanonicalIntent` as Dell OS10 config text."""
    lines: list[str] = []

    # ── Banner ──
    # Only the version line.  A real dump's second line is `! Last
    # configuration change at <timestamp>`, which is deliberately NOT
    # reproduced: it is a timestamp we would have to invent, and it is
    # the exact string that made `cisco_iosxe_cli` claim every Dell
    # config at confidence 95 before PR #475.
    lines.append(f"! Version {_version_token(tree)}")
    lines.append("!")

    # ── VRFs ──
    # OS10 states the global RIB as an explicit stanza.  Emitting it is
    # deliberate: it costs one line and makes our own output
    # self-identifying — `dell_os10.probe()` scores it 95, and
    # `cisco_iosxe_cli.probe()` defers on it (PR #475), so a rendered
    # Dell config cannot be re-detected as Cisco.
    lines.append("ip vrf default")
    lines.append("!")
    for ri in tree.routing_instances:
        if ri.name.lower() == "default":
            continue
        lines.append(f"ip vrf {ri.name}")
        lines.append("!")

    # ── Hostname ── (only when set — see module docstring)
    if tree.hostname:
        lines.append(f"hostname {tree.hostname}")
        lines.append("!")

    # ── Local users ── (device order: accounts sit just below hostname)
    for user in tree.local_users:
        lines.append(_render_local_user(user))
    if tree.local_users:
        lines.append("!")

    # ── Interfaces ──
    lag_mode_by_name = {lag.name: lag.mode for lag in tree.lags}
    untagged_stated = _untagged_stated(tree.interfaces)
    for iface in _sort_interfaces(_interfaces_to_render(tree)):
        lines.extend(_render_interface(iface, lag_mode_by_name, untagged_stated))
        lines.append("!")

    # ── Static routes ──
    for route in tree.static_routes:
        lines.append(_render_static_route(route))
    if tree.static_routes:
        lines.append("!")

    # ── SNMP ── (device order: the snmp-server block sits near the end)
    if tree.snmp is not None:
        snmp_lines = _render_snmp(tree.snmp, tree.source_vendor)
        if snmp_lines:
            lines.extend(snmp_lines)
            lines.append("!")

    return "\n".join(lines) + "\n"


def _render_local_user(user) -> str:
    """Render one ``username ... password ... role ... priv-lvl ...`` line.

    The secret goes through the shared :func:`is_migratable` gate first.
    A hash OS10 cannot consume DROPS the account and leaves a review
    comment instead of being re-emitted — re-emitting it would make the
    digest itself the password, which is the #460 fail-open.

    The ``payload`` (not the raw canonical value) is emitted, so a
    vendor-tagged secret such as ``junos:$6$…`` writes the bare crypt
    string OS10 actually accepts rather than the tag.
    """
    role = user.role or (
        "sysadmin" if user.privilege_level >= 15 else "netoperator"
    )
    if not user.hashed_password:
        # A cross-vendor account with no secret.  The parser reads this
        # form back (the password clause is optional), so the account
        # survives instead of vanishing.
        return f"username {user.name} role {role} priv-lvl {user.privilege_level}"
    algorithm, payload = classify_hash(user.hashed_password)
    if not is_migratable(user.hashed_password, "dell_os10"):
        return format_review_comment(
            user.name, algorithm,
            comment_syntax="exclamation", target_label="Dell OS10",
        )
    return (
        f"username {user.name} password {payload} role {role} "
        f"priv-lvl {user.privilege_level}"
    )


def _render_snmp(snmp, source_vendor: str = "") -> list[str]:
    """Render the ``snmp-server`` block (v2c community + v3 USM users).

    ⚠️ The trailing ``localized`` keyword is a CLAIM about the value: it
    tells the switch the key is already localised against its own engine
    ID.  It is emitted only when the recorded provenance says the key
    actually is one.  Appending it to a passphrase makes the switch derive
    a key from a key, and the user then authenticates nobody — the #471
    same-vendor corruption, which is invisible to a round-trip guard
    because parse→render→parse stays stable while the rendered TEXT is
    wrong.

    Conversely a key bound to ANOTHER agent's engine ID cannot be
    re-localised here at all, so it is refused with a review comment
    rather than installed.  A passphrase is the one portable shape: it is
    emitted WITHOUT the keyword and OS10 localises it on commit.
    """
    lines: list[str] = []
    if snmp.community:
        lines.append(f"snmp-server community {snmp.community}")
    if snmp.location:
        lines.append(f'snmp-server location "{snmp.location}"')
    if snmp.contact:
        lines.append(f'snmp-server contact "{snmp.contact}"')
    # OS10 needs `traps version <v> <community|user>`; a bare
    # `snmp-server host <ip>` is rejected AND silently discarded
    # snmp.community.  Authentic corpus form:
    # `snmp-server host 10.0.0.20 traps version 3 priv iicsnmp`.
    # Batfish does not parse OS10, so the independent-parser oracle that
    # surfaced this class on the three Cisco/Arista targets could not see
    # this site -- it was found by reading the render paths.
    for host in snmp.trap_hosts:
        community = snmp.community or "public"
        lines.append(f"snmp-server host {host} traps version 2c {community}")
        if not snmp.community:
            lines.append(
                f"! snmp-server host {host} -- review: the source carried "
                f"no SNMP community, so `public` was synthesised to keep "
                f"the trap target valid; set the real community or convert "
                f"this host to v3"
            )

    for user in snmp.v3_users:
        if user.auth_protocol and not user_usm_is_migratable(
            user, source_vendor, "dell_os10",
        ):
            kind = user_usm_kind(user, source_vendor)
            lines.append(
                f"! snmpv3 user {user.name} -- review: a {kind} USM key is "
                f"bound to the source agent's engine ID and cannot be re-used "
                f"on Dell OS10; re-create this user and re-key it on the target"
            )
            continue
        # One keyword governs the whole line, so it must describe the
        # LEAST portable key the user carries.
        localised = user_usm_kind(user, source_vendor) != PLAINTEXT
        line = f"snmp-server user {user.name} {user.group or 'netadmin'} 3"
        if user.auth_protocol:
            auth = _CANON_TO_OS10_AUTH.get(user.auth_protocol.lower(), "sha")
            line += f" auth {auth} {user.auth_passphrase}"
            if user.priv_passphrase:
                priv = _CANON_TO_OS10_PRIV.get(
                    (user.priv_protocol or "").lower(), "aes",
                )
                line += f" priv {priv} {user.priv_passphrase}"
            if localised:
                line += " localized"
        lines.append(line)
    return lines


def _interfaces_to_render(tree: CanonicalIntent) -> list[CanonicalInterface]:
    """Every interface stanza to emit.

    The tree's own interfaces, plus a synthesised SVI for any VLAN that
    carries a name or an IP address but has no ``vlan<N>`` interface.
    That synthesis is the ONLY way OS10 can express such a VLAN — it has
    no top-level ``vlan <id>`` stanza — but it is deliberately withheld
    from VLANs that carry neither, because those are reconstructed from
    switchport membership on re-parse and synthesising one would add an
    interface the source tree never had.
    """
    existing_svi_ids = {
        ident.index
        for ident in (
            _port_names.classify_port_name(i.name) for i in tree.interfaces
        )
        if ident.kind == "svi" and ident.index is not None
    }
    synthesised = [
        CanonicalInterface(
            name=f"vlan{vlan.id}",
            description=vlan.name,
            interface_type="ianaift:l3ipvlan",
            ipv4_addresses=list(vlan.ipv4_addresses),
        )
        for vlan in tree.vlans
        if vlan.id not in existing_svi_ids
        and (vlan.name or vlan.ipv4_addresses)
    ]
    return list(tree.interfaces) + synthesised


def _untagged_stated(interfaces: list[CanonicalInterface]) -> frozenset[str]:
    """The names whose untagged VLAN some record of the tree states: a
    trunk record with a native VLAN (:func:`.._helpers.native_vlan_stated`),
    or an ACCESS record with an access VLAN.

    A config can hold one interface's stanza more than once, and OS10
    applies the stanzas in turn: ``switchport access vlan 10`` in one
    and ``switchport mode trunk`` in the next leave a trunk whose
    untagged VLAN is 10.  A trunk record of such a name that has no
    native VLAN is written no ``no switchport access vlan``, which would
    take that VLAN back.  Only an access record counts: the access VLAN
    a TRUNK record holds beside its own lines is not that trunk's
    untagged VLAN in the tree.
    """
    return native_vlan_stated(interfaces) | frozenset(
        iface.name for iface in interfaces
        if iface.switchport_mode == "access" and iface.access_vlan is not None
    )


def _sort_interfaces(interfaces: list[CanonicalInterface]):
    """Return *interfaces* in OS10 show-output order."""

    def _key(iface: CanonicalInterface):
        ident = _port_names.classify_port_name(iface.name)
        kind_rank = _KIND_ORDER.get(ident.kind, 99)
        nums = (
            ident.stack or 0,
            ident.module or 0,
            ident.port or 0,
            ident.index or 0,
            ident.breakout_lane or 0,
        )
        return (kind_rank, nums, iface.name)

    return sorted(interfaces, key=_key)


#: Written above the allowed line of a trunk of every VLAN.
_EVERY_VLAN_REVIEW = (
    " ! review: the source trunk allows every VLAN; OS10 has no word "
    "for that, its VLAN ids end at 4093 and a VLAN must exist before "
    "it is listed -- list the VLANs this trunk is to carry"
)


#: Written above ``no switchport access vlan``, for a trunk whose
#: native VLAN is outside its allowed list.  ``{native}`` is the id
#: the OUTPUT has for that VLAN -- a VLAN map can have renumbered it
#: -- so the line does not call it the source's.
_NATIVE_NOT_CARRIED_REVIEW = (
    " ! review: native VLAN {native} is stated for this trunk and its "
    "allowed list leaves it out, so no untagged VLAN is written for "
    "this port; Dell's pages disagree on whether the next line leaves "
    "an OS10 trunk with no untagged VLAN or with VLAN 1 -- check what "
    "this port is to carry untagged"
)


#: Written above ``no switchport access vlan``, for a trunk that has no
#: native VLAN in the tree: one that carries no VLAN untagged.  Left
#: with neither an access line nor that line, an OS10 trunk is an
#: untagged member of its switch's default VLAN ("By default, native
#: VLAN of a port is the default VLAN ID of the switch.", Dell's "L2
#: mode configuration").  Dell's VLAN-stacking notes reach "pure trunk
#: ports without any access VLAN membership", which "drop any untagged
#: ... traffic", with that line; its command page says the line
#: "resets access VLAN membership on a L2 access or trunk port to VLAN
#: 1".  The line names both readings.  ``{vlan_1}`` is
#: :data:`_VLAN_1_ON_THE_LIST` where the allowed line written below
#: holds VLAN 1, and empty otherwise.
_NO_UNTAGGED_VLAN_REVIEW = (
    " ! review: no untagged VLAN is stated for this trunk; an OS10 "
    "trunk with neither an access line nor the next line is an untagged "
    "member of the switch's default VLAN, and Dell's pages disagree on "
    "whether the next line leaves it with no untagged VLAN or with VLAN "
    "1{vlan_1} -- check what this port is to carry untagged"
)

#: ...and what it adds where the allowed line holds VLAN 1: no Dell
#: example in the 10.5.5-10.6.1 user guides puts VLAN 1 on an allowed
#: line, so what such a trunk does is not established either.
_VLAN_1_ON_THE_LIST = (
    "; no Dell page shows VLAN 1 on an OS10 trunk's allowed line"
)


def _render_switchport_lines(
    iface: CanonicalInterface, untagged_stated: frozenset[str] = frozenset(),
) -> list[str]:
    """The L2 switchport lines for an interface.

    Empty for the inherently-L3 kinds (SVI / loopback / management).
    The trunk branch re-emits the native VLAN with the ``access vlan``
    keyword — OS10's only spelling for it (see module docstring) — and
    the allowed line without it.

    Args:
        iface: The interface.
        untagged_stated: The names whose untagged VLAN some record of
            the tree states, as a native VLAN or in an access record
            (:func:`_untagged_stated`).  A trunk record of such a name
            that has no native VLAN is another stanza of an interface
            that states one, and is written no ``no switchport access
            vlan``: OS10 applies the stanzas in turn, and the line would
            take that VLAN back.
    """
    kind = _port_names.classify_port_name(iface.name).kind
    if kind in ("svi", "loopback", "mgmt"):
        return []
    out: list[str] = []
    if iface.switchport_mode == "trunk":
        out.append(" switchport mode trunk")
        native = iface.trunk_native_vlan
        untagged = trunk_untagged_vlan(iface.trunk_allowed_vlans, native)
        written = trunk_list_written("dell_os10", iface.trunk_allowed_vlans, native)
        if untagged is not None:
            out.append(f" switchport access vlan {untagged}")
        elif native is not None:
            # Stated and not carried: the list leaves it out.  Written
            # as the access VLAN it would be carried untagged, which
            # is not what the tree says of it.
            out.append(_NATIVE_NOT_CARRIED_REVIEW.format(native=native))
            out.append(" no switchport access vlan")
        elif iface.name not in untagged_stated:
            # No native VLAN: in a tree a parser made, a trunk that
            # carries no VLAN untagged.  With no access line OS10 would
            # make it an untagged member of the switch's default VLAN;
            # the line that takes the access VLAN away is written, under
            # a line that says what Dell's pages say of it -- unless
            # another record of the name states its untagged VLAN.  (The
            # OS10 parser reads both texts as this tree: the line comes
            # back for a trunk that had neither.)
            out.append(_NO_UNTAGGED_VLAN_REVIEW.format(
                vlan_1=_VLAN_1_ON_THE_LIST if 1 in written else "",
            ))
            out.append(" no switchport access vlan")
        # The allowed line names the TAGGED VLANs: the list without
        # the native one.  No VLAN is no line: an OS10 trunk carries
        # no tagged VLAN until a line names one.  Any other list is
        # written as ranges.
        vlist = switchport_trunk_allowed_value(
            "dell_os10", written, coalesce=True,
        )
        if vlist is not None:
            if trunk_list_says(iface.trunk_allowed_vlans) == TRUNK_ALL:
                # Every VLAN, which OS10 cannot be told: it has no
                # word for it, its ids end at 4093, and a VLAN has to
                # exist before a port is put in it.  The range is
                # written as it always was, and the operator is told.
                out.append(_EVERY_VLAN_REVIEW)
            out.append(f" switchport trunk allowed vlan {vlist}")
    elif iface.switchport_mode == "access":
        if iface.access_vlan is not None:
            # A real device prints only this line for an access port —
            # the mode is implied, and the parser infers it back.
            out.append(f" switchport access vlan {iface.access_vlan}")
        else:
            out.append(" switchport mode access")
    elif iface.ipv4_addresses or iface.ipv6_addresses:
        # Routed physical / LAG port — OS10 defaults switched ports to
        # L2, so the routed intent must be stated explicitly.
        out.append(" no switchport")
    return out


def _render_interface(
    iface: CanonicalInterface, lag_mode_by_name: dict,
    untagged_stated: frozenset[str] = frozenset(),
) -> list[str]:
    """Render one interface stanza.

    ``ip vrf forwarding`` precedes ``ip address`` because changing an
    interface's VRF clears its addresses on commit.  *untagged_stated*
    is :func:`_render_switchport_lines`' argument of that name.
    """
    block = [f"interface {iface.name}"]
    if iface.description:
        block.append(f" description {iface.description}")
    block.append(" no shutdown" if iface.enabled else " shutdown")

    if iface.lag_member_of:
        ident = _port_names.classify_port_name(iface.lag_member_of)
        if ident.kind == "lag" and ident.index is not None:
            mode = _CANON_TO_OS10_LAG_MODE.get(
                lag_mode_by_name.get(iface.lag_member_of, "active"), "active",
            )
            block.append(f" channel-group {ident.index} mode {mode}")

    block.extend(_render_switchport_lines(iface, untagged_stated))

    if iface.mtu is not None:
        # The link MTU is a frame size: Dell's example puts "tagged
        # members with Link MTU of 1522 and IP MTU of 1500".  Copied as
        # it stood, IOS-XE ``mtu 1500`` was a link MTU that cuts every
        # 1500-byte packet.
        stated = (
            mtu_written("dell_os10", iface.mtu)
            if _port_names.mtu_is_a_frame(iface.name)
            else iface.mtu
        )
        block.append(f" mtu {stated}")
    if iface.vrf:
        block.append(f" ip vrf forwarding {iface.vrf}")
    for addr in iface.ipv4_addresses:
        line = f" ip address {addr.ip}/{addr.prefix_length}"
        if addr.is_secondary:
            line += " secondary"
        block.append(line)
    for addr in iface.ipv6_addresses:
        block.append(f" ipv6 address {addr.ip}/{addr.prefix_length}")

    # ── VRRP groups (Phase 3b) ──
    # OS10 runs REAL VRRP, so a group renders as itself rather than being
    # normalised into another FHRP family.  A cross-vendor HSRP / CARP
    # group still reinterprets as VRRP here — the redundancy intent for the
    # virtual IP survives but the wire protocol changes, which is why
    # `/interfaces/interface/vrrp-groups/group/mode` is declared lossy.
    #
    # Only NON-DEFAULT values are emitted: OS10 preempts by default and
    # defaults priority to 100, so emitting them unconditionally would add
    # lines a real device never prints while round-tripping identically.
    for group in iface.vrrp_groups:
        block.append(" !")
        block.append(f" vrrp-group {group.group_id}")
        for vip in group.virtual_ips:
            block.append(f"  virtual-address {vip}")
        if group.priority != 100:
            block.append(f"  priority {group.priority}")
        if not group.preempt:
            block.append("  no preempt")
    return block


def _render_static_route(route) -> str:
    """Render one static route.

    A ``management`` route re-emits with OS10's dedicated ``management
    route`` keyword — the inverse of the parse mapping — so it stays out
    of the global RIB.  That grammar is IPv4-only in every capture held,
    so an IPv6 management route falls back to ``ipv6 route vrf
    management``, which re-parses to the same canonical record.
    """
    nexthop = route.gateway or route.interface
    if route.interface and route.gateway:
        # Two-token next-hop: OS10 spells it `<interface> <gateway>`.
        nexthop = f"{route.interface} {route.gateway}"

    is_v6 = ":" in (route.destination or "")
    if route.vrf == "management" and not is_v6:
        # The `management route` grammar carries no administrative
        # distance.  A same-vendor tree can never have one here (OS10
        # emits none, so the parser reads none), and inventing syntax to
        # carry a cross-vendor metric would emit config the device
        # rejects.
        return f"management route {route.destination} {nexthop}"

    keyword = "ipv6 route" if is_v6 else "ip route"
    vrf = f" vrf {route.vrf}" if route.vrf else ""
    out = f"{keyword}{vrf} {route.destination} {nexthop}".rstrip()
    if route.metric:
        out += f" {route.metric}"
    return out
