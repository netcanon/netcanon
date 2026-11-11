"""
Render path for Cisco IOS-XE CLI (``running-config`` form).

Public function: :func:`render_intent` — :class:`CanonicalIntent`
in, IOS-XE ``show running-config`` text out.

Bidirectional codec — pairs with :func:`parse_intent` from
:mod:`.parse` for round-trip.

Coverage spans every Tier-1 + Tier-2 canonical surface this codec
also parses on the source side: hostname / domain / DNS / NTP /
syslog / interfaces (physical, SVI, Loopback, Port-channel, Tunnel) /
VLANs / static routes / DHCP pools / SNMP (v1/v2c + v3) / local users
/ RADIUS / VRFs / **classic VRRP groups** (single-line ``vrrp N
ip X / priority / preempt / track / description / timers /
authentication``; modern address-family form is lossy) /
**SD-Access anycast-gateway** (per-SVI ``fabric forwarding mode
anycast-gateway`` + system-wide ``fabric forwarding
anycast-gateway-mac`` in dotted-triplet wire form).  Anything outside
the canonical surface (firewall ACLs, QoS policies, BGP/OSPF, IKEv2)
falls through silently — same convention as every other codec.

Output format mirrors the Cisco wire form an operator would paste
into a console: ``!``-delimited stanzas, dotted-decimal netmasks,
``no shutdown``/``shutdown`` on interfaces.  Ordering is intentionally
close to a real ``show running-config`` (banner / hostname / users /
VRFs / interfaces / VLANs / routing / SNMP / etc.) so the diff
against a real capture stays readable.

Extracted verbatim from ``codec.py`` during the parse/render split;
behaviour is identical to the prior in-class implementation.  The
codec module's ``render()`` method is now a one-line delegator to
:func:`render_intent`.

Internal helpers (``_prefix_to_mask``, ``_cidr_to_dest_mask``,
``_extract_lag_number``, ``_split_cisco_hash``) live here because
they are render-only.  The inverse parse helper
(``_mask_to_prefix``) lives in :mod:`.parse` and the two never
cross sibling boundaries.
"""

from __future__ import annotations

import re
from typing import Any

from ..._bonds import ACTIVE_BACKUP, active_backup_review
from ..._derived_values import (
    is_derivation_keyword,
)
from ..._derived_values import (
    review_comment as derived_review_comment,
)
from ..._naming import sanitise_hostname
from ..._one_value import ADDRESSES, left_out, one_value_tree, splits
from ..._radius_secrets import (
    IOSXE_ENVELOPE,
    radius_secret_is_migratable,
    unwrap_native_secret,
)
from ..._radius_secrets import (
    format_review_comment as format_radius_review_comment,
)
from ..._user_secrets import (
    classify_hash,
    format_empty_hash_comment,
    format_review_comment,
    holds_no_secret,
    is_migratable,
)
from ..._usm_keys import (
    PLAINTEXT,
    classify_usm_key,
    user_usm_is_migratable,
    user_usm_kind,
)
from ...canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
)
from ...limits import ticked
from .._helpers import (
    TRUNK_ALL,
    _prefix_to_mask,
    charge_id_lines,
    every_native_vlan_tagged,
    ip_mtu_written,
    native_vlan_stated,
    switchport_trunk_allowed_value,
    switchport_trunk_native_value,
    trunk_list_says,
    wants_no_untagged_vlan,
)
from .._hsrp import V1_GROUP_MAX
from ..base import RenderError
from .dhcp_pools import render_pools

#: The line that carries a port's allowed list, up to its first id
#: (or the word that stands for the list: ``none``, ``all``).
_ALLOWED_VLAN_LEAD = " switchport trunk allowed vlan "

#: Written where a native line would be, on a trunk that carries no
#: VLAN untagged and whose list holds VLAN 1, in an output that cannot
#: say ``vlan dot1q tag native`` of every trunk
#: (:func:`.._helpers.every_native_vlan_tagged`).  What it says of
#: IOS-XE is Cisco's (the vendor reference's VLAN page): the native
#: VLAN is VLAN 1 by default, and the global line tags the native VLAN
#: on all 802.1Q trunk ports.
_NO_UNTAGGED_REVIEW = (
    " ! review: this trunk carries no VLAN untagged in the translated "
    "config; on IOS-XE a trunk with no native line has native VLAN 1, "
    "and this one's allowed list holds VLAN 1; vlan dot1q tag native "
    "would tag it, and tags the native VLAN of every 802.1Q trunk of "
    "the switch -- check what this port is to carry untagged"
)


def render_intent(tree: Any) -> str:  # noqa: C901
    """Render a :class:`CanonicalIntent` to IOS-XE
    ``show running-config`` text.

    Raises:
        RenderError: If *tree* is not a :class:`CanonicalIntent`.
    """
    if not isinstance(tree, CanonicalIntent):
        raise RenderError(
            "cisco_iosxe_cli: tree must be a CanonicalIntent.",
            yang_path="/",
        )

    # Materialise port-centric switchport state from VLAN-centric
    # membership lists.  Required for cross-vendor renders from
    # codecs that emit no per-port stanzas (Aruba AOS-S
    # ``vlan N / untagged 1/1-1/47`` form, OPNsense ``<vlans>``-
    # only).  Idempotent + additive — same-vendor round-trips
    # where interfaces are already populated are no-ops.
    from ...canonical.transforms import (
        project_vlan_to_switchport,
        synthesize_svis_from_vlan_l3,
    )
    project_vlan_to_switchport(tree)

    # A name that is not one word where IOS-XE reads one is written as
    # one, at every place it goes; an address is left out.  Both are
    # said.  Policy: :mod:`netcanon.migration._one_value`.
    tree, one_value_said = one_value_tree(
        tree, "IOS-XE",
        names=("hostname", "vlans[].name", "routing_instances[].name",
               "static_routes[].description"),
        addresses=ADDRESSES,
    )

    # A trunk that carries no VLAN untagged and whose list holds VLAN 1
    # is said so by the form Cisco documents for it on the Catalyst 9300
    # and the 9500 alike (the vendor reference's VLAN page) -- which
    # says it of EVERY trunk, and so is written only where it is true
    # of every one.  Elsewhere such a trunk has a review line.
    tag_every_native = every_native_vlan_tagged("cisco_iosxe_cli", tree.interfaces)
    stated = native_vlan_stated(tree.interfaces)

    # Inverse SVI fold: materialise ``interface Vlan<N>`` SVIs for VLANs
    # carrying L3 (``ipv4_addresses``) but with no sibling ``Vlan<N>``
    # interface — the shape a Junos ``irb`` + ``l3-interface`` source
    # produces.  Non-mutating (rendered alongside tree.interfaces, not
    # appended to the possibly-reused intent); empty for same-vendor
    # renders where the ``Vlan<N>`` interface is already present.
    synth_svis = synthesize_svis_from_vlan_l3(tree)

    # An allowed list is written out below id by id (a trunk of
    # every VLAN has no line, and one of no VLAN the word): the
    # lines are counted here, before the first character.
    charge_id_lines(
        [*tree.interfaces, *synth_svis], _ALLOWED_VLAN_LEAD,
        codec="cisco_iosxe_cli", trunks_only=False,
    )

    out: list[str] = []

    # --- header banner ---
    out.append("Building configuration...")
    out.append("")
    out.append("! Generated by netcanon translator (cisco_iosxe_cli)")
    out += [f"! {said}" for said in one_value_said]
    out.append("!")

    # --- service / system globals ---
    out.append("service timestamps debug datetime msec")
    out.append("service timestamps log datetime msec")
    out.append("!")
    if tree.hostname:
        # IOS-XE's hostname parser greedy-matches ``\S+`` and silently
        # drops the trailing tokens — ``hostname Quinta Router`` round-
        # trips as ``Quinta``.  Sanitise whitespace runs to ``_`` so the
        # wire form is consumable.  Single-token names unchanged;
        # cross-vendor concern flagged by mikrotik_routeros Phase 4b.
        out.append(f"hostname {sanitise_hostname(tree.hostname)}")
        out.append("!")
    if tree.domain:
        out.append(f"ip domain name {tree.domain}")
        out.append("!")

    # --- SD-Access anycast-gateway system-wide MAC ---
    # ``fabric forwarding anycast-gateway-mac <MAC>`` declares the
    # chassis-wide MAC every SD-Access SVI shares as its virtual L2
    # next-hop.  IOS-XE / NX-OS use dotted-triplet wire form
    # (``aabb.ccdd.eeff``); we convert from canonical colon-hex.  Per-
    # SVI ``fabric forwarding mode anycast-gateway`` lines are emitted
    # inside the interface stanza below — both surfaces are needed for
    # the SD-Access fabric to function.
    if tree.anycast_gateway_mac:
        dotted = _mac_to_dotted_triplet(tree.anycast_gateway_mac)
        if dotted:
            out.append(f"fabric forwarding anycast-gateway-mac {dotted}")
            out.append("!")

    # --- local users ---
    # Cisco form: `username X privilege N secret <type> <hash>`.
    # Canonical ``hashed_password`` preserves whatever opaque hash the
    # source captured.  Same-vendor (Cisco→Cisco) round-trip carries
    # the type-5 / 8 / 9 marker through verbatim.  Cross-vendor hashes
    # (Arista sha512, OPNsense bcrypt $2y$, FortiGate ENC, ...) are
    # NOT consumable by IOS-XE's ``secret`` parser — IOS-XE only
    # accepts type 0 / 5 / 8 / 9.  Before this gate the renderer
    # leaked the literal foreign hash under ``secret 5`` (security
    # disclosure: the bcrypt hash leaks on the wire) AND tagged
    # bcrypt as md5crypt (wrong type marker).  We now consult the
    # shared :mod:`netcanon.migration._user_secrets` policy and emit
    # a comment-form ``review:`` line in IOS comment syntax (``! ``)
    # when the hash is unmigratable.  An account with no password is
    # a review line too: ``nopassword`` is Cisco's "No password is
    # required for this user to log in".
    for u in tree.local_users:
        if holds_no_secret(u.hashed_password):
            out.append(format_empty_hash_comment(
                u.name, comment_syntax="exclamation",
                target_label="Cisco IOS-XE",
            ))
            continue
        if not is_migratable(
            u.hashed_password, "cisco_iosxe_cli",
        ):
            algorithm, _payload = classify_hash(u.hashed_password)
            out.append(
                format_review_comment(
                    u.name, algorithm, comment_syntax="exclamation",
                    target_label="Cisco IOS-XE",
                )
            )
            continue
        # A name or a typed password that holds white space is not one
        # word here (`username`: "Spaces and quotation marks are not
        # allowed"), and is never altered to fit: the account is left
        # out and said.  Policy: :mod:`netcanon.migration._one_value`.
        if splits(u.name) or (
            u.hashed_password
            and splits(_split_cisco_hash(u.hashed_password)[1])
        ):
            out.append(
                "! " + left_out(f"username {u.name}", "Cisco IOS-XE")
            )
            continue
        parts = [f"username {u.name}"]
        if u.privilege_level and u.privilege_level != 1:
            parts.append(f"privilege {u.privilege_level}")
        # No role is written: an IOS-XE account's rights are its
        # privilege level, and a role the source names is a name of
        # another platform (netcanon/migration/_roles.py; the
        # capability matrix declares the role lossy).
        hash_type, hash_val = _split_cisco_hash(u.hashed_password)
        parts.append(f"secret {hash_type} {hash_val}")
        out.append(" ".join(parts))
    if tree.local_users:
        out.append("!")

    # --- DNS / NTP / syslog ---
    for srv in tree.dns_servers:
        out.append(f"ip name-server {srv}")
    if tree.dns_servers:
        out.append("!")
    for srv in tree.ntp_servers:
        out.append(f"ntp server {srv}")
    if tree.ntp_servers:
        out.append("!")
    for srv in tree.syslog_servers:
        out.append(f"logging host {srv}")
    if tree.syslog_servers:
        out.append("!")

    # --- VRFs (CanonicalRoutingInstance → vrf definition) ---
    # Cisco IOS-XE syntax: ``vrf definition <name>`` with nested
    # rd / route-target / address-family stanzas.  Empty RD/RT lists
    # render the bare definition (still valid; lets per-interface
    # ``vrf forwarding`` references resolve at parse time).
    for vrf in tree.routing_instances:
        if not vrf.name:
            continue
        out.append(f"vrf definition {vrf.name}")
        if vrf.description:
            out.append(f" description {vrf.description}")
        # (#482) IOS-XE's auto-RD keyword is `rd-auto` (hyphenated,
        # 17.12.1+), NOT `rd auto`, and there is no
        # `route-target ... auto` CLI form at all -- the auto-RT is
        # implied by `vnid <n> evpn-instance`.  So a source that wrote
        # `rd auto` / `route-target both auto` (NX-OS, AOS-CX) produced
        # three lines here that IOS-XE cannot parse.  We drop the value
        # and name the native equivalent rather than emit `rd-auto`
        # ourselves: it is gated at 17.12.1 while this codec supports
        # 15.x onward, so emitting it would trade a wrong line on every
        # release for a wrong line on most of them.
        if vrf.route_distinguisher:
            if is_derivation_keyword(vrf.route_distinguisher):
                out.append(
                    " ! " + derived_review_comment(
                        "route-distinguisher",
                        "Cisco IOS-XE",
                        native_form="rd-auto (IOS-XE 17.12.1+)",
                    )
                )
            else:
                out.append(f" rd {vrf.route_distinguisher}")
        rt_imports = [
            rt for rt in vrf.rt_imports if not is_derivation_keyword(rt)
        ]
        rt_exports = [
            rt for rt in vrf.rt_exports if not is_derivation_keyword(rt)
        ]
        if len(rt_imports) != len(vrf.rt_imports) or len(
            rt_exports
        ) != len(vrf.rt_exports):
            out.append(
                " ! " + derived_review_comment(
                    "route-target",
                    "Cisco IOS-XE",
                    native_form="vnid <n> evpn-instance",
                )
            )
        if rt_imports or rt_exports:
            out.append(" address-family ipv4")
            for rt in rt_imports:
                out.append(f"  route-target import {rt}")
            for rt in rt_exports:
                out.append(f"  route-target export {rt}")
            out.append(" exit-address-family")
        out.append("!")

    if tag_every_native:
        out.append("vlan dot1q tag native")
        out.append("!")

    # --- interfaces ---
    # LAG members carry ``lag_member_of=<lag_name>``.  Cisco needs
    # the matching ``interface Port-channel<N>`` declared as a
    # peer top-level stanza, with the member's ``channel-group N
    # mode <mode>`` line inside the physical iface.  We emit
    # Port-channel stanzas FIRST (so they're declared before
    # member references) then the physical / SVI / Loopback /
    # Tunnel interfaces.
    lag_by_name: dict[str, CanonicalLAG] = {
        lag.name: lag for lag in tree.lags
    }
    # Sort: Port-channel first (so they bind before member refs),
    # then by canonical kind (physical, SVI, Loopback, Tunnel,
    # everything else).  Within each kind, sort by NATURAL port-
    # name order so output is operator-natural ("1/0/1" before
    # "1/0/2" before "1/0/10") regardless of the order parse /
    # synthesis populated tree.interfaces.  Without the natural
    # sort, set-iteration-driven synthesis from VLAN-centric
    # source codecs (Aruba "untagged 1/1-1/47" expansion) emitted
    # interfaces in random hash order — visually disorienting
    # for operators reading the rendered config.
    from ...canonical.transforms import _natural_port_sort_key

    def _iface_sort_key(iface: CanonicalInterface):
        n = iface.name.lower()
        if n.startswith("port-channel") or iface.name in lag_by_name:
            kind = 0
        elif n.startswith("vlan"):
            kind = 1
        elif n.startswith("loopback"):
            kind = 2
        elif n.startswith("tunnel"):
            kind = 3
        else:
            kind = 4
        return (kind, _natural_port_sort_key(iface.name))

    ordered_ifaces = sorted(
        [*tree.interfaces, *synth_svis], key=_iface_sort_key
    )

    # Empty-stub elision (mirrors Junos commit `0fdf7e9`, finding #8
    # in tests/fixtures/real/user_smoke_findings.md).  Cross-vendor
    # source codecs preserve the source's port-name verbatim on the
    # canonical CanonicalInterface (OPNsense ``igc0`` / ``ixl0``,
    # MikroTik ``ether1``, etc.).  Without elision the IOS-XE render
    # leaks ``interface igc0`` literal stubs that have no body — pure
    # noise for an operator reading the rendered config and not even
    # accepted as a valid port name on the target device.  We emit
    # the bare ``interface NAME`` line ONLY when one of the following
    # holds:
    #
    #   (a) the canonical record carries any renderable body
    #       (description / IPs / MTU / shutdown / L2 / LAG / VRF),
    #   (b) the interface is referenced from a VLAN port-list
    #       (untagged / tagged) — Cisco needs the iface declared so
    #       the access/trunk binding has somewhere to live, OR
    #   (c) the interface name matches an IOS-XE physical-port shape
    #       (preserves round-trip for same-vendor renders that
    #       capture only Tier-3 grammar on a port).
    #
    # Names referenced from VLAN port lists.
    vlan_referenced_names: set[str] = set()
    for v in tree.vlans:
        for n in v.tagged_ports:
            vlan_referenced_names.add(n)
        for n in v.untagged_ports:
            vlan_referenced_names.add(n)

    for iface in ordered_ifaces:
        body: list[str] = []
        if iface.description:
            body.append(f" description {iface.description}")
        if iface.vrf:
            body.append(f" vrf forwarding {iface.vrf}")
        # IPv4 addresses — Cisco needs dotted-decimal masks.  IOS-XE
        # only accepts ONE primary ``ip address`` per interface; every
        # subsequent address must be tagged ``secondary`` or the device
        # rejects the second line.  Per Cisco IP Addressing Services
        # Configuration Guide, IOS-XE 17.x, "Secondary IP Addressing"
        # — ``ip address ip-address mask [secondary [vrf vrf-name]]``.
        # Round-trips with the parse-side companion that drops the
        # ``secondary`` token before storing in the canonical list.
        # GAP 7: routed sub-interface 802.1Q tag.  Emitted before the IP
        # so the tag precedes the routed address (IOS-XE convention).
        # Capital Q matches Cisco's canonical style.  A Q-in-Q
        # sub-interface's inner tag is ``second-dot1q`` on the same line
        # (IOS-XE 17, "IEEE 802.1Q-in-Q VLAN Tag Termination").  The
        # sub-interface that takes the port's untagged frames says
        # ``native`` (``dot1q_native``; Cisco, "Configuring Layer 3
        # Subinterfaces").
        if iface.dot1q_vlan is not None:
            second = (
                f" second-dot1q {iface.dot1q_inner_vlan}"
                if iface.dot1q_inner_vlan is not None
                else " native" if iface.dot1q_native else ""
            )
            body.append(f" encapsulation dot1Q {iface.dot1q_vlan}{second}")
        for idx, addr in enumerate(iface.ipv4_addresses):
            mask = _prefix_to_mask(addr.prefix_length, vendor="cisco_iosxe_cli")
            suffix = " secondary" if idx > 0 else ""
            body.append(f" ip address {addr.ip} {mask}{suffix}")
        # SD-Access anycast-gateway per-SVI marker.  When any IPv4
        # address on this interface carries a ``virtual_gateway_address``
        # equal to the primary IP (the NX-OS / IOS-XE SD-Access mirror
        # shape — the primary IP IS the anycast gateway), emit the
        # ``fabric forwarding mode anycast-gateway`` line that marks
        # the SVI as a fabric edge.  Idempotent: only emitted ONCE per
        # interface even if multiple addresses carry the flag.  Cross-
        # vendor sources (Junos / Arista VARP) populate
        # ``virtual_gateway_address`` with a SEPARATE virtual IP — those
        # don't trigger the SD-Access marker; that grammar (per-address
        # virtual_gateway_address ≠ ip) has no IOS-XE equivalent and is
        # surfaced via review comment instead.
        emitted_anycast_mode = False
        for addr in iface.ipv4_addresses:
            if (addr.virtual_gateway_address
                    and addr.virtual_gateway_address == addr.ip
                    and not emitted_anycast_mode):
                body.append(" fabric forwarding mode anycast-gateway")
                emitted_anycast_mode = True
            elif (addr.virtual_gateway_address
                    and addr.virtual_gateway_address != addr.ip):
                # Cross-vendor anycast shape (Junos / Arista VARP) —
                # separate virtual IP.  No IOS-XE SD-Access equivalent;
                # surface as a review comment so the operator can
                # decide whether to flip to VRRP or to mirror the
                # virtual IP onto the primary.  Emitted once per such
                # address.
                body.append(
                    f" ! review: virtual_gateway_address="
                    f"{addr.virtual_gateway_address!r} differs from "
                    f"primary IP {addr.ip!r}; IOS-XE SD-Access only "
                    f"supports primary-IP-as-anycast (NX-OS shape)"
                )
        # GAP-EVPN-3: IPv6 addresses — IOS-XE uses CIDR natively
        # (no dotted-mask form for v6).  Link-local re-emits the
        # explicit keyword.
        for v6 in iface.ipv6_addresses:
            if v6.scope == "link-local":
                body.append(
                    f" ipv6 address {v6.ip}/{v6.prefix_length} link-local"
                )
            else:
                body.append(
                    f" ipv6 address {v6.ip}/{v6.prefix_length}"
                )
        # IPv6 dynamic-address mode.  IOS-XE supports the stateful
        # client (``dhcp``) and SLAAC (``autoconfig``).  Other
        # dhcp_client_v6 values that arrive from cross-vendor sources
        # (track6, 6rd, 6to4 — OPNsense-specific) drop to a review
        # comment because IOS-XE has no equivalent native form.
        if iface.dhcp_client_v6 == "dhcp6":
            body.append(" ipv6 address dhcp")
        elif iface.dhcp_client_v6 == "slaac":
            body.append(" ipv6 address autoconfig")
        elif iface.dhcp_client_v6:
            body.append(
                f" ! review: dhcp_client_v6={iface.dhcp_client_v6} "
                f"has no IOS-XE equivalent"
            )
        # Tunnel-mode discriminator on Tunnel<N> stanzas.  The
        # canonical ``tunnel_type`` field disambiguates between GRE
        # (the IOS-XE default), IPIP, IPSEC, and VXLAN encap.  Empty
        # string falls through to the IOS-XE platform default (GRE)
        # so we don't emit a redundant ``tunnel mode gre ip`` line.
        if iface.tunnel_type and iface.interface_type == "ianaift:tunnel":
            tt = iface.tunnel_type.lower()
            if tt == "gre":
                body.append(" tunnel mode gre ip")
            elif tt == "ipip":
                body.append(" tunnel mode ipip")
            elif tt == "ipsec":
                body.append(" tunnel mode ipsec ipv4")
            elif tt == "vxlan":
                body.append(" tunnel mode vxlan")
            elif tt == "eoip":
                # MikroTik-specific Ethernet-over-IP — no IOS-XE
                # equivalent; surface as a review comment.
                body.append(
                    " ! review: tunnel_type=eoip has no IOS-XE "
                    "equivalent (MikroTik-only)"
                )
        # Switchport — emit the mode FIRST (operator-natural
        # ordering), then EVERY captured switchport sub-attribute
        # regardless of mode.  Cisco IOS-XE tolerates declaring
        # ``switchport access vlan`` on a trunk port and
        # ``switchport trunk allowed vlan`` on an access port:
        # both are harmless on the inactive-mode side and become
        # active if the operator later flips the mode.  Real
        # captures from production switches sometimes carry both
        # (e.g. a port pre-configured for both possible modes
        # before deployment) — gating the render by mode would
        # silently drop the inactive-mode declarations and break
        # canonical-stable round-trip on those captures.
        if iface.switchport_mode in ("access", "trunk"):
            body.append(f" switchport mode {iface.switchport_mode}")
        if iface.access_vlan is not None:
            body.append(
                f" switchport access vlan {iface.access_vlan}"
            )
        if iface.voice_vlan is not None:
            body.append(
                f" switchport voice vlan {iface.voice_vlan}"
            )
        # No native line for VLAN 1 on a TRUNK whose list holds it:
        # that is the platform's default, and no real capture prints
        # the line.  A native VLAN the list leaves out is written
        # whatever its id (stated, and not carried).  On a port in
        # another mode the line is written as it stands: the parser
        # puts no default for a port that does not say it is a
        # trunk, so a line left out there would not come back.
        native_vlan = iface.trunk_native_vlan
        if iface.switchport_mode == "trunk":
            native_vlan = switchport_trunk_native_value(
                "cisco_iosxe_cli", iface.trunk_allowed_vlans, native_vlan,
            )
        if native_vlan is not None:
            body.append(f" switchport trunk native vlan {native_vlan}")
        elif (
            iface.switchport_mode == "trunk" and not tag_every_native
            and iface.name not in stated and wants_no_untagged_vlan(
                "cisco_iosxe_cli", iface.trunk_allowed_vlans,
                iface.trunk_native_vlan,
            )
        ):
            body.append(_NO_UNTAGGED_REVIEW)
        if iface.switchport_mode == "trunk":
            # On a trunk the list means what it says.  No VLAN is
            # ``none``.  Every VLAN is no line at all: it is the
            # default, it is what the device prints, and the ids
            # spelled out are one line of some 19,000 characters.
            # Any other list is written as it stands.
            vlan_list = switchport_trunk_allowed_value(
                "cisco_iosxe_cli", iface.trunk_allowed_vlans,
                coalesce=False,
            )
            if vlan_list is not None:
                body.append(f"{_ALLOWED_VLAN_LEAD}{vlan_list}")
        elif iface.trunk_allowed_vlans:
            # A list stated on a port that is not a trunk (see the
            # comment above the mode line): kept for the day the mode
            # is flipped.  Every id is the word for it there.
            if trunk_list_says(iface.trunk_allowed_vlans) == TRUNK_ALL:
                vlan_list = "all"
            else:
                vlan_list = ",".join(
                    str(v) for v in iface.trunk_allowed_vlans
                )
            body.append(f"{_ALLOWED_VLAN_LEAD}{vlan_list}")
        if iface.mtu is not None:
            body.append(f" mtu {iface.mtu}")
        ip_mtu = ip_mtu_written("cisco_iosxe_cli", iface)
        if ip_mtu is not None:
            body.append(f" ip mtu {ip_mtu}")
        # LAG-membership marker.  Mode normalisation: canonical
        # ``active`` → LACP active; ``passive`` → LACP passive;
        # ``static`` → mode ``on`` (no LACP).
        if iface.lag_member_of:
            lag = lag_by_name.get(iface.lag_member_of)
            lag_num = _extract_lag_number(iface.lag_member_of)
            mode = (lag.mode if lag else "active") or "active"
            wire_mode = {
                "active": "active",
                "passive": "passive",
                "static": "on",
                "on": "on",
                # No active-backup bond here: a static aggregate, said
                # in a review line (netcanon.migration._bonds).
                ACTIVE_BACKUP: "on",
            }.get(mode.lower(), "active")
            if lag_num is not None:
                body.append(
                    f" channel-group {lag_num} mode {wire_mode}"
                )
                if mode == ACTIVE_BACKUP:
                    body.append(
                        f" ! {active_backup_review(f'Port-channel{lag_num}')}"
                    )
        # Enabled state — Cisco default is ``no shutdown`` so
        # we only emit when explicitly disabled.  Parsers that
        # didn't see ``shutdown`` leave enabled=True.
        if not iface.enabled:
            body.append(" shutdown")
        if iface.dhcp_client:
            body.append(" ip address dhcp")

        # VRRP groups.  Emit classic single-line per-attribute form —
        # broadest IOS-XE compatibility (15.x onward).  Modern address-
        # family form (17.12+) is declared lossy in the capability
        # matrix; cross-vendor groups round-trip through the classic
        # form.  An HSRP group is written as ``standby`` lines
        # (:func:`_standby_lines`), after ``standby version 2`` where a
        # group needs it.  A mode that has no IOS-XE equivalent
        # (``carp``) surfaces as a review comment.
        if any(_needs_hsrp_version_2(g) for g in iface.vrrp_groups):
            body.append(" standby version 2")
        for group in iface.vrrp_groups:
            gid = group.group_id
            if group.mode == "hsrp":
                body.extend(_standby_lines(group))
                continue
            if group.mode and group.mode != "vrrp":
                body.append(
                    f" ! review: vrrp_groups[{gid}].mode="
                    f"{group.mode!r} has no IOS-XE equivalent"
                )
                continue
            # Primary virtual IP — first element is the canonical
            # primary; secondaries get the ``secondary`` trailer.
            for idx, vip in enumerate(group.virtual_ips):
                if idx == 0:
                    body.append(f" vrrp {gid} ip {vip}")
                else:
                    body.append(f" vrrp {gid} ip {vip} secondary")
            for vip6 in group.virtual_ipv6s:
                body.append(f" vrrp {gid} ipv6 {vip6}")
            if group.priority != 100:
                body.append(f" vrrp {gid} priority {group.priority}")
            # Preemption is written either way, the default included:
            # Cisco's VRRP guide says "By default, a preemptive scheme
            # is enabled" and gives ``vrrp group preempt [delay minimum
            # seconds]``, so the line is valid at the default, and it
            # puts the setting in the output where a reader sees it.
            # The device's own printout leaves it out at the default
            # (the BR1 capture has no preempt line), so a round trip of
            # a capture gains it.  Pinned by
            # ``test_preempt_default_round_trips``.
            if group.preempt:
                body.append(f" vrrp {gid} preempt")
            else:
                body.append(f" no vrrp {gid} preempt")
            if group.description:
                body.append(
                    f" vrrp {gid} description {group.description}"
                )
            if group.authentication.startswith(("md5:", "plain:")) and splits(
                group.authentication.split(":", 1)[1]
            ):
                # The key is one word (`text`: "up to eight alphanumeric
                # characters"); the group is kept without it.
                body.append(
                    " ! " + left_out(
                        f"vrrp {gid} authentication", "Cisco IOS-XE",
                    )
                )
            elif group.authentication.startswith("md5:"):
                body.append(
                    f" vrrp {gid} authentication md5 key-string "
                    f"{group.authentication[4:]}"
                )
            elif group.authentication.startswith("plain:"):
                body.append(
                    f" vrrp {gid} authentication text "
                    f"{group.authentication[6:]}"
                )
            elif group.authentication and ":" not in group.authentication:
                # Untagged blob — emit a review comment rather than
                # guessing the scheme.
                # The blob is a secret: the line says where, never what.
                body.append(
                    f" ! vrrp {gid} authentication -- review: the source's "
                    f"authentication value names no scheme, so it could "
                    f"not be cleanly emitted"
                )
            for tracked in group.track_interfaces:
                body.append(f" vrrp {gid} track {tracked}")
            # ``timers advertise N`` — only emit when the canonical
            # value differs from the IOS-XE default of 1 second.
            if group.advertisement_interval not in (0, 1):
                body.append(
                    f" vrrp {gid} timers advertise "
                    f"{group.advertisement_interval}"
                )

        # Elision predicate.
        is_native_port = bool(_IS_CISCO_PHYSICAL_PORT_RE.match(iface.name))
        is_vlan_referenced = iface.name in vlan_referenced_names
        if not body and not is_native_port and not is_vlan_referenced:
            # Foreign port name with no body and no incoming reference —
            # skip entirely.  Suppresses ``interface igc0`` /
            # ``interface ether1`` etc. from cross-vendor renders.
            continue
        if not body and is_vlan_referenced and not is_native_port:
            # Foreign port referenced from a VLAN port list — keep the
            # bare ``interface NAME`` line so the membership has a
            # binding target, but flag for operator review.
            out.append(f"interface {iface.name}")
            out.append(
                f"! interface {iface.name} -- review: foreign port "
                f"name preserved from source vendor; rename to a "
                f"native IOS-XE port before deploy"
            )
            out.append("!")
            continue
        out.append(f"interface {iface.name}")
        out.extend(body)
        out.append("!")

    # --- VLANs ---
    # Cisco form: ``vlan N`` + ``  name X``.  Port membership is
    # carried on the per-interface ``switchport access vlan`` /
    # ``trunk allowed vlan`` lines above; this block is just the
    # VLAN-database declaration.
    for vlan in tree.vlans:
        out.append(f"vlan {vlan.id}")
        if vlan.name:
            out.append(f" name {vlan.name}")
    if tree.vlans:
        out.append("!")

    # --- VXLAN / EVPN overlay (promotion #16) ---
    # L2 VLAN↔VNI bindings render as ``vlan configuration <vlan_id> /
    # member evpn-instance 1 vni <vni>`` (the ``evpn-instance`` number is
    # not carried canonically — 1 matches the single ``l2vpn evpn instance
    # 1`` most IOS-XE EVPN leaves declare, and re-parse maps it back to the
    # same vlan_id).  The VTEP source-interface, per-VNI multicast group,
    # and L3VNI→VRF bindings render under ``interface nve1`` — the same
    # stanza the parser intercepts.  Mirrors the cisco_nxos VTEP emitter.
    l3vnis = sorted(
        (ri.l3_vni, ri.name)
        for ri in tree.routing_instances
        if ri.l3_vni is not None and ri.name
    )
    ordered_vx = sorted(tree.vxlan_vnis, key=lambda x: x.vni)
    if ordered_vx or l3vnis:
        for vx in ordered_vx:
            out.append(f"vlan configuration {vx.vlan_id}")
            out.append(f" member evpn-instance 1 vni {vx.vni}")
        if ordered_vx:
            out.append("!")
        source_iface = next(
            (x.source_interface for x in ordered_vx if x.source_interface), "",
        ) or "Loopback0"
        out.append("interface nve1")
        out.append(" no ip address")
        out.append(f" source-interface {source_iface}")
        out.append(" host-reachability protocol bgp")
        for vx in ordered_vx:
            if vx.mcast_group:
                out.append(f" member vni {vx.vni} mcast-group {vx.mcast_group}")
            else:
                out.append(f" member vni {vx.vni}")
        for l3vni, vrf_name in l3vnis:
            out.append(f" member vni {l3vni} vrf {vrf_name}")
        out.append("!")

    # --- static routes ---
    for route in tree.static_routes:
        tail = ""
        if route.metric and route.metric > 0:
            tail = f" {route.metric}"
        target = route.gateway or route.interface
        if not target:
            continue
        # Two-token next-hop ``<iface> <gateway>`` (directly-attached egress
        # with an explicit forwarding address): emit BOTH, interface first, to
        # match the ``ip route <dest> <mask> <iface> <gateway>`` grammar.
        # Without this a route carrying both fields drops the interface — the
        # render half of the two-token round-trip (HEAD-review L1-8).
        if route.interface and route.gateway:
            target = f"{route.interface} {route.gateway}"
        # ``name <NAME>`` route label (run3): IOS-XE route names are a
        # single whitespace-free token.  A multi-word description (e.g. a
        # Junos free-text route description) reaches this line already
        # written as one word, with a review line (``one_value_tree``
        # above; the matrix declares /routing/static-route/description
        # lossy for that case).  Single-token names round-trip losslessly.
        name_tail = ""
        if route.description:
            name_tail = f" name {route.description}"
        # Per-VRF routes carry the ``vrf <NAME>`` qualifier between the
        # ``ip route`` keyword and the destination (v0.2.0 — graduated
        # /routing/static-route/vrf from unsupported to supported).
        vrf_prefix = f"vrf {route.vrf} " if route.vrf else ""
        # IPv6 destinations use the ``ipv6 route`` keyword with the prefix
        # form (no dotted mask) — forcing them through the IPv4
        # ``ip route <dest> <mask>`` path raised RenderError on the >32
        # prefix length.  IOS-XE: ``ipv6 route [vrf X] <prefix>/<len> <nh>``.
        if ":" in (route.destination or ""):
            out.append(
                f"ipv6 route {vrf_prefix}{route.destination} "
                f"{target}{tail}{name_tail}",
            )
            continue
        dest, mask = _cidr_to_dest_mask(route.destination)
        out.append(f"ip route {vrf_prefix}{dest} {mask} {target}{tail}{name_tail}")
    if tree.static_routes:
        out.append("!")

    # --- DHCP server pools ---
    # A pool's range is written as the exclusions on either side of it,
    # and where it is served is checked against the interfaces this
    # output holds (:mod:`.dhcp_pools`, which cites Cisco's guide).
    out.extend(render_pools(
        tree.dhcp_servers, [*tree.interfaces, *synth_svis], _cidr_to_dest_mask,
    )[0])

    # --- RADIUS servers ---
    for server in tree.radius_servers:
        out.append(f"radius server {server.host}")
        out.append(f" address ipv4 {server.host} auth-port "
                   f"{server.auth_port} acct-port {server.acct_port}")
        # (#482) See netcanon/migration/_radius_secrets.py — a secret
        # encrypted under the SOURCE device's key cannot be re-used
        # here, and IOS-XE reads this slot as the literal secret.
        if server.key:
            if radius_secret_is_migratable(
                server.key, tree.source_vendor, "cisco_iosxe_cli",
            ):
                out.append(f" key {_radius_key_text(server.key)}")
            else:
                out.append(
                    format_radius_review_comment(
                        server.host,
                        comment_syntax="exclamation",
                        target_label="Cisco IOS-XE",
                        secret=server.key,
                    )
                )
        out.append("!")

    # --- SNMP block ---
    if tree.snmp is not None:
        s = tree.snmp
        # A community is one word ("Blank spaces are not permitted"):
        # one that holds white space is left out, with every trap host
        # that would carry it -- a second word would be read as the
        # next argument (an ACL), not refused.
        community_splits = splits(s.community)
        if community_splits:
            out.append("! " + left_out("an SNMP community", "Cisco IOS-XE"))
        elif s.community:
            out.append(f"snmp-server community {s.community} RO")
        if s.location:
            out.append(f"snmp-server location {s.location}")
        if s.contact:
            out.append(f"snmp-server contact {s.contact}")
        # IOS-XE requires the community (or v3 user) as the trailing
        # argument; a bare `snmp-server host <ip>` is rejected AND
        # silently discarded s.community.  Authentic corpus form:
        # `snmp-server host 10.1.2.3 version 2c dummycommunity`.
        for host in s.trap_hosts:
            if community_splits:
                out.append(
                    "! " + left_out(f"snmp-server host {host}", "Cisco IOS-XE")
                )
                continue
            community = s.community or "public"
            out.append(f"snmp-server host {host} version 2c {community}")
            if not s.community:
                out.append(
                    f"! snmp-server host {host} -- review: the source "
                    f"carried no SNMP community, so `public` was "
                    f"synthesised to keep the trap target valid; set the "
                    f"real community or convert this host to v3"
                )
        # SNMPv3 USM users.  Cisco syntax pairs auth/priv with
        # the v3 keyword; ``aes128`` canonical → ``aes 128`` two
        # tokens; ``aes192``/``aes256`` similarly split.
        for u in s.v3_users:
            # ⚠️ This slot takes the operator's PASSPHRASE -- IOS-XE derives
            # the localised USM key from it.  A value that is ALREADY a key
            # (NX-OS `localizedkey`, Junos `authentication-key`, VyOS
            # `encrypted-password`, AOS-CX ciphertext, FortiGate `ENC`) run
            # through that derivation a second time yields a user that commits
            # cleanly and authenticates nobody.  Refuse it; a passphrase source
            # was already correct and is untouched.
            # Policy: :mod:`netcanon.migration._usm_keys`.
            if (u.auth_protocol or u.priv_protocol) and not user_usm_is_migratable(
                u, tree.source_vendor, "cisco_iosxe_cli",
            ):
                kind = user_usm_kind(u, tree.source_vendor)
                out.append(
                    f"! snmpv3 user {u.name} -- review: a {kind} USM key "
                    f"belongs to the source agent, so IOS-XE cannot re-derive "
                    f"it; re-create this user and re-key it on the target"
                )
                continue
            # Name, group and both passphrases are one word each on this
            # line; a second word is read as the next argument.
            if any(
                splits(v) for v in (
                    u.name, u.group, u.auth_passphrase, u.priv_passphrase,
                )
            ):
                out.append(
                    "! " + left_out(f"snmpv3 user {u.name}", "Cisco IOS-XE")
                )
                continue
            line = [
                f"snmp-server user {u.name} {u.group or 'v3group'} v3",
            ]
            # Recovering an already-derived key is only half the job: the bare
            # slot takes a PASSPHRASE and IOS-XE derives from it, so a stored
            # key must go back out behind its own ``encrypted`` keyword or the
            # device derives a key from a key (same-vendor re-render).
            if classify_usm_key(
                u.auth_passphrase, tree.source_vendor, u.auth_kind,
            ) != PLAINTEXT:
                line.append("encrypted")
            if u.auth_protocol:
                line.append(
                    f"auth {u.auth_protocol} {u.auth_passphrase}"
                )
            if u.priv_protocol:
                if u.priv_protocol == "aes128":
                    line.append(f"priv aes 128 {u.priv_passphrase}")
                elif u.priv_protocol == "aes192":
                    line.append(f"priv aes 192 {u.priv_passphrase}")
                elif u.priv_protocol == "aes256":
                    line.append(f"priv aes 256 {u.priv_passphrase}")
                elif u.priv_protocol == "aes":
                    line.append(f"priv aes 128 {u.priv_passphrase}")
                else:
                    line.append(
                        f"priv {u.priv_protocol} {u.priv_passphrase}"
                    )
            out.append(" ".join(line))
        if (s.community or s.location or s.contact
                or s.trap_hosts or s.v3_users):
            out.append("!")

    # --- raw_sections passthrough ---
    # Tier-3 raw blocks the source carried through.  Emit as-is
    # under ``! raw_section: <name>`` markers so the operator can
    # see what didn't auto-translate.  Skipped if empty.
    for name, body in tree.raw_sections.items():
        out.append(f"! raw_section: {name}")
        for ln in ticked(body.splitlines()):
            out.append(ln)
        out.append("!")

    out.append("end")
    return "\n".join(out) + "\n"


# Cisco IOS-XE physical-port name shapes.  Used by the empty-stub
# elision predicate (mirrors the Junos pattern in
# ``juniper_junos/render.py::_IS_JUNOS_PHYSICAL_PORT_RE``) to decide
# whether a content-free canonical iface is "really there" (same-
# vendor source where the parser captured only Tier-3 grammar) or a
# foreign port name leaking through from a cross-vendor source
# (OPNsense ``igc0``, MikroTik ``ether1``, etc.) that should be
# elided from the rendered config.  Covers the IOS-XE families an
# operator would expect to see on real hardware (including the
# wide-and-weird Batfish-corpus families like ``Crypto-Engine``,
# ``Wideband-Cable``, ``Wlan-GigabitEthernet``, ``Dot11Radio``).
# Match is case-insensitive because real IOS-XE accepts both
# ``Vlan100`` and ``vlan100`` (parse-side treats them identically).
_CISCO_PORT_PREFIX_ALTS = "|".join((
    # Ethernet families.
    r"FastEthernet",
    r"GigabitEthernet",
    r"TenGigabitEthernet",
    r"TwentyFiveGigE",
    r"FortyGigabitEthernet",
    r"HundredGigE",
    r"AppGigabitEthernet",
    r"Ethernet",
    # Aggregate / virtual.
    r"Port-channel",
    r"Loopback",
    r"Vlan",
    r"Tunnel-ip6",
    r"Tunnel-ip",
    r"Tunnel",
    r"Management",
    r"BDI",
    r"Serial",
    r"Async",
    r"Null",
    r"VirtualPortGroup",
    r"Multilink",
    r"Dialer",
    r"Group-Async",
    r"BVI",
    r"pseudowire",
    r"nve",
    r"GMPLS",
    r"Voice",
    # Wireless / Cable / WiFi families.
    r"Dot11Radio",
    r"Wlan-GigabitEthernet",
    r"Wlan-ap",
    r"Wideband-Cable",
    r"Modular-Cable",
    r"Cable",
    r"Crypto-Engine",
))
_IS_CISCO_PHYSICAL_PORT_RE = re.compile(
    rf"^(?:{_CISCO_PORT_PREFIX_ALTS})[\s\d/.:]*$",
    re.IGNORECASE,
)


def _needs_hsrp_version_2(group: Any) -> bool:
    """Whether *group* is an HSRP group that version 1 cannot hold.

    "The group number range is from 0 to 255 for HSRP version 1 and
    from 0 to 4095 for HSRP version 2", and "HSRP version 2 must be
    enabled on an interface before HSRP IPv6 can be configured"
    (Cisco's HSRP guides).
    """
    return group.mode == "hsrp" and (
        group.group_id > V1_GROUP_MAX or bool(group.virtual_ipv6s)
    )


def _standby_lines(group: Any) -> list[str]:
    """An HSRP group as IOS-XE writes it: a ``standby <group>`` line for
    each statement (Cisco's HSRP guide: ``standby [group-number] ip
    [ip-address [secondary]]``, ``priority``, ``preempt``,
    ``authentication text`` / ``md5 key-string``, ``mac-address``).

    What is not written is said in a review line: a key that is not one
    word, a key of another scheme, and the fields an HSRP group of
    IOS-XE has no statement for (a description; tracked interfaces,
    which IOS-XE tracks as objects).
    """
    gid = group.group_id
    lines = [
        f" standby {gid} ip {vip}" + (" secondary" if idx else "")
        for idx, vip in enumerate(group.virtual_ips)
    ]
    lines.extend(f" standby {gid} ipv6 {vip6}" for vip6 in group.virtual_ipv6s)
    if group.priority != 100:
        lines.append(f" standby {gid} priority {group.priority}")
    # Preemption is off by default in HSRP ("that router will not become
    # the active router, even if its priority is higher"), so only the
    # statement that turns it on is written.
    if group.preempt:
        lines.append(f" standby {gid} preempt")
    scheme, _, key = group.authentication.partition(":")
    if group.authentication and scheme in ("md5", "plain") and splits(key):
        lines.append(" ! " + left_out(f"standby {gid} authentication", "Cisco IOS-XE"))
    elif scheme == "md5" and key:
        lines.append(f" standby {gid} authentication md5 key-string {key}")
    elif scheme == "plain" and key:
        lines.append(f" standby {gid} authentication text {key}")
    elif group.authentication:
        # The value is a secret: the line says where, never what.
        lines.append(
            f" ! standby {gid} authentication -- review: the source's "
            f"authentication is not a key IOS-XE takes as typed, so the "
            f"group is written with none"
        )
    mac = _mac_to_dotted_triplet(group.virtual_mac)
    if mac:
        lines.append(f" standby {gid} mac-address {mac}")
    # An HSRP hello is not a VRRP advertisement (their defaults are 3 and
    # 1 seconds, and HSRP pairs it with a hold time), so an interval
    # other than the canonical default is said, not converted.
    unwritten = [
        name for name, value in (
            ("description", group.description),
            ("track_interfaces", group.track_interfaces),
            ("advertisement_interval", group.advertisement_interval != 1),
        ) if value
    ]
    if unwritten:
        lines.append(
            f" ! review: vrrp_groups[{gid}] (HSRP): {', '.join(unwritten)} "
            f"not written"
        )
    if not lines:
        # A group at every default with no address has no line: IOS-XE
        # writes a group only by its statements.
        lines.append(
            f" ! review: HSRP group {gid} has no virtual address and no "
            f"other statement to write, so it is not written"
        )
    return lines


def _mac_to_dotted_triplet(mac: str) -> str:
    """Convert canonical colon-hex MAC to Cisco dotted-triplet form.

    Cisco IOS-XE / NX-OS emit MAC addresses in ``aabb.ccdd.eeff`` form;
    the canonical model stores them in colon-hex
    (``aa:bb:cc:dd:ee:ff``).  Returns empty string for malformed input
    so the caller skips the emit rather than poisoning the wire with
    garbage.
    """
    if not mac:
        return ""
    hex_only = re.sub(r"[^0-9a-fA-F]", "", mac).lower()
    if len(hex_only) != 12:
        return ""
    return f"{hex_only[0:4]}.{hex_only[4:8]}.{hex_only[8:12]}"


def _cidr_to_dest_mask(cidr: str) -> tuple[str, str]:
    """Split a ``X.X.X.X/N`` CIDR into ``(network, dotted_mask)``.

    Used by render() for ``ip route DEST MASK GATEWAY`` and
    ``network DEST MASK`` inside DHCP pools — both Cisco syntaxes
    expect dotted-decimal masks.  Tolerates inputs that are already
    in ``DEST MASK`` form (returns them unchanged) and treats
    ``"default"`` / ``"0.0.0.0/0"`` as default-route shorthand.
    """
    if not cidr:
        return ("0.0.0.0", "0.0.0.0")
    if cidr.lower() == "default":
        return ("0.0.0.0", "0.0.0.0")
    if "/" not in cidr:
        # Plain IP — assume host route.
        return (cidr, "255.255.255.255")
    dest, _, prefix_str = cidr.partition("/")
    try:
        prefix = int(prefix_str)
    except ValueError:
        return (dest, "255.255.255.255")
    return (dest, _prefix_to_mask(prefix, vendor="cisco_iosxe_cli"))


def _extract_lag_number(lag_name: str) -> int | None:
    """Pull the numeric tail off a LAG name (``Port-channel10`` → 10,
    ``Trk5`` → 5, ``ae0`` → 0).  Used by render() to emit the
    ``channel-group N mode <X>`` line on member interfaces — Cisco's
    LAG syntax is integer-keyed regardless of the source vendor's
    naming convention.  Returns None for names with no trailing
    digits."""
    # ``(?<!\d)``: see the note in arista_eos/port_names.py.
    m = re.search(r"(?<!\d)(\d+)\s*$", lag_name or "")
    if m is None:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _radius_key_text(key: str) -> str:
    """What follows ``key`` for a secret the RADIUS policy let through.

    A value behind ``IOSXE_ENVELOPE`` goes back as the device wrote it
    (``7 <blob>``).  A secret as typed is written as it is, unless it
    begins with digits and white space, which the device and the parser
    read as a type: then ``0`` says that what follows is the secret.
    """
    if key.startswith(IOSXE_ENVELOPE):
        return key[len(IOSXE_ENVELOPE):]
    if re.match(r"^\d+\s", key):
        return f"0 {key}"
    return unwrap_native_secret(key)


def _split_cisco_hash(hashed: str) -> tuple[str, str]:
    """Map a canonical ``hashed_password`` blob into Cisco's
    ``secret <type> <hash>`` two-token form.

    Cisco encrypted-password types:
      * 0 — plaintext (rare; used when operator pastes plaintext)
      * 5 — MD5-crypt
      * 7 — Cisco's reversible XOR (legacy; weak)
      * 8 — PBKDF2-SHA-256
      * 9 — scrypt

    Canonical hashed_password preserves whatever shape the source
    parser captured.  This helper assumes the caller has ALREADY
    consulted :func:`netcanon.migration._user_secrets.is_migratable`
    and confirmed the hash is consumable by IOS-XE — the un-
    migratable path emits a review-comment line above instead of
    calling this function.  Recognised migratable shapes:

      * ``"<type-digit> <hash>"`` (digits 5 / 8 / 9) — round-trip
        form produced by the Cisco parser.  Honours the captured
        type marker.
      * ``"<vendor>:<alg>:<payload>"`` / ``"<alg>:<payload>"`` —
        normalised tagged form.  ``5`` / ``md5crypt`` / ``8`` / ``9``
        map to their corresponding type digit.
      * ``$1$...`` raw — md5crypt → emit ``5 $1$...``
      * ``$8$...`` / ``$9$...`` raw — emit ``8 ..`` / ``9 ..``
      * Anything else — treat as plaintext → ``secret 0 <literal>``.
    """
    if not hashed:
        return ("0", "")
    # Vendor-tagged forms (``cisco:5:$1$..``, ``md5crypt:$1$..``,
    # ``9:$9$..``).  Use classify_hash for normalisation so we don't
    # duplicate parsing logic.
    algorithm, payload = classify_hash(hashed)
    if algorithm in {"5", "md5crypt"}:
        return ("5", payload or hashed)
    if algorithm == "7":
        return ("7", payload or hashed)
    if algorithm == "8":
        return ("8", payload or hashed)
    if algorithm == "9":
        return ("9", payload or hashed)
    # ``classify_hash`` returns ``("plaintext", ...)`` for raw $1$..
    # blobs (no leading ``5 `` marker, no vendor tag).  Detect and
    # promote to type-5 here so cross-vendor sources that store md5
    # crypt as a bare ``$1$..`` still emit under the right tag.
    if hashed.startswith("$9$"):
        return ("9", hashed)
    if hashed.startswith("$8$"):
        return ("8", hashed)
    if hashed.startswith("$1$"):
        return ("5", hashed)
    # Plaintext literal (only path reachable via the migratable-gate
    # for non-empty values that weren't algorithm-tagged).  IOS-XE
    # ``secret 0`` is the documented form for unhashed passwords; the
    # device hashes on commit.
    return ("0", hashed)
