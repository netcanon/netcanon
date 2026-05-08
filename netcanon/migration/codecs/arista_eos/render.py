"""
Render path for Arista EOS CLI (``show running-config`` form).

Public function: :func:`render_intent` — :class:`CanonicalIntent`
in, EOS CLI text out.

Emits the same surfaces the parse path consumes: hostname, DNS, NTP,
SNMP (community / location / contact / trap-host / v3 user), local
users, RADIUS servers, VRF instances, VLANs, interfaces (with
IPv4/IPv6 incl. link-local scope, VRF binding, switchport mode, LAG
membership, MTU, shutdown), LAG stub stanzas, DHCP server pools
(``ip dhcp pool`` family — Cluster E.1-A), ``interface Vxlan1``
(with ``vxlan source-interface`` + ``vxlan udp-port`` + per-VNI
mappings + L3-VNI mappings for VRF Type-5), ``router bgp <asn>``
blocks (for L3 VRF RD/RT and EVPN MAC-VRF per-VLAN bindings), and
static routes.

Extracted verbatim from ``codec.py`` during the parse/render
split; behaviour is identical to the prior in-class
implementation.  The codec module's ``render()`` method is now a
one-line delegator to :func:`render_intent`.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from ..._naming import sanitise_hostname
from ..._user_secrets import (
    classify_hash,
    format_review_comment,
    is_migratable,
)
from ...canonical.intent import CanonicalIntent
from ..base import RenderError


# Arista-local emit-form vocabulary: maps the algorithm tokens
# emitted by :func:`classify_hash` to the matching ``secret <N>``
# type-tag tokens for the EOS CLI:
#
#   * ``plaintext`` (no separator) -> ``secret 0 <password>``
#   * ``5`` (Cisco bare-digit form, ``5 $1$..``) -> ``secret 5 $1$..``
#   * ``md5crypt`` (alias used by some sources) -> ``secret 5 $1$..``
#   * ``sha512`` (Arista vendor-tagged or generic ``$6$``)
#     -> ``secret sha512 $6$..``
#
# This table is the codec-LOCAL emit-form dispatch (similar to
# Aruba's ``_AOS_KNOWN_ALGORITHMS``); the cross-vendor migratability
# decision (which algorithms EOS literally cannot consume) lives in
# the shared :mod:`netcanon.migration._user_secrets` module under
# ``_TARGET_ACCEPTS["arista_eos"]``, and is consulted via
# :func:`is_migratable`.  The keys here mirror that accepted set
# exactly — keep them in sync.
#
# Anything outside this set (bcrypt ``$2y$``, Cisco type-7/8/9,
# FortiGate ENC blobs) cannot be re-emitted on Arista — the codec
# has to fall back to a review-comment line so the source hash
# never reaches the wire.  Issue #1 in user_smoke_findings.md
# (CRITICAL security disclosure: bcrypt was leaking through the
# previous opaque ``secret 5 bcrypt:$2y$..`` fallback).
_ARISTA_SECRET_TYPE: dict[str, str] = {
    "plaintext": "0",
    "5":         "5",
    "md5crypt":  "5",
    "sha512":    "sha512",
}


# Native Arista physical-port name shapes.  Used by the empty-stub
# elision predicate to decide whether a content-free canonical
# iface is "really there" (target-vendor-shaped operator stub
# with no body) vs a foreign-vendor leak (e.g. OPNsense ``igc0``
# arriving via a cross-vendor render).  Mirrors the Junos
# ``_IS_JUNOS_PHYSICAL_PORT_RE`` policy from commit ``0fdf7e9``.
_IS_ARISTA_PHYSICAL_PORT_RE = re.compile(
    r"^(?:"
    r"Ethernet\d+(?:/\d+)?"           # Ethernet1, Ethernet50/3 breakout
    r"|Loopback\d+"                   # Loopback0
    r"|Vlan\d+"                       # Vlan10 (SVI)
    r"|Management\d+"                 # Management1
    r"|Port-Channel\d+"               # Port-Channel5
    r"|Vxlan\d+"                      # Vxlan1 (always emitted with body)
    r")$"
)


def _cidr_to_dotted_mask(cidr: str) -> tuple[str, str]:
    """Split a CIDR string into ``(network, dotted_mask)`` for EOS emit.

    Used by the DHCP-pool render to produce the dotted-mask form of
    ``network <ip> <netmask>``.  EOS also accepts the CIDR form, but
    the dotted-mask spelling is the older + universally accepted
    surface (cisco_iosxe_cli render uses the same convention via
    its own ``_cidr_to_dest_mask`` helper).

    Returns ``("", "")`` for malformed input — caller skips emit.
    """
    if "/" not in cidr:
        return "", ""
    try:
        net = ipaddress.IPv4Network(cidr, strict=False)
    except (ipaddress.AddressValueError, ValueError):
        return "", ""
    return str(net.network_address), str(net.netmask)


def _normalise_lag_name_to_arista(name: str) -> str | None:
    """Translate a canonical LAG name to Arista's ``Port-Channel<N>`` form.

    Arista's EOS User Manual ("Channel groups" chapter) requires the
    ``Port-Channel<N>`` syntax (capital ``C``).  Foreign-vendor LAG
    names that arrive on the canonical tree get mapped here:

      * ``Port-Channel<N>``  — already native, returned as-is.
      * ``Port-channel<N>``  — Cisco IOS form; capitalise the ``C``.
      * ``ae<N>``            — Junos form; trailing digits → index.
      * ``Trk<N>`` / ``trk<N>`` — Aruba AOS-S form.
      * ``bond<N>``          — MikroTik / Linux bonding form.
      * ``lagg<N>``          — OPNsense / FreeBSD form.

    Returns ``None`` when the name has no trailing digit (we'd be
    guessing the channel-group index, which would silently misbind
    the LAG to channel 1 in EOS).  Caller MUST handle ``None`` —
    typically by falling back to passing the name verbatim through
    the empty-stub elision policy.
    """
    if re.match(r"^Port-Channel\d+$", name):
        return name
    m = re.match(r"^Port-channel(\d+)$", name)
    if m:
        return f"Port-Channel{m.group(1)}"
    m = re.match(
        r"^(?:ae|[Tt]rk|bond|lagg)(\d+)$", name,
    )
    if m:
        return f"Port-Channel{m.group(1)}"
    return None


def render_intent(tree: Any) -> str:
    """Render a :class:`CanonicalIntent` as Arista EOS CLI text."""
    if not isinstance(tree, CanonicalIntent):
        raise RenderError(
            "arista_eos: tree must be a CanonicalIntent.",
            yang_path="/",
        )

    # Materialise port-centric switchport state from VLAN-centric
    # membership lists.  Required for cross-vendor renders from
    # codecs that emit no per-port stanzas (Aruba AOS-S, OPNsense)
    # — without this, a tree whose only L2 information lives in
    # ``CanonicalVlan.tagged_ports`` / ``untagged_ports`` would
    # render bare ``interface 1/1`` stubs with no
    # ``switchport access vlan N`` lines, dropping every VLAN
    # membership end-to-end.  Idempotent + additive — same-vendor
    # round-trips where iface fields are already populated are
    # no-ops.  Mirrors the same call in the Cisco IOS-XE CLI and
    # Junos render paths.
    from ...canonical.transforms import project_vlan_to_switchport
    project_vlan_to_switchport(tree)

    out: list[str] = []
    out.append("! Generated by netcanon-translator (arista_eos target)")
    out.append("!")
    if tree.hostname:
        # Arista's hostname parser rejects whitespace — ``hostname
        # Quinta Router`` round-trips through the EOS parser as ``""``
        # (regex ``\s*$`` refuses the trailing token).  Sanitise to
        # ``Quinta_Router`` so the emitted wire form is consumable.
        # Single-token names emit unchanged; cross-vendor concern
        # flagged from the mikrotik_routeros Phase 4b agent.
        out.append(f"hostname {sanitise_hostname(tree.hostname)}")
        out.append("!")

    if tree.dns_servers:
        for dns in tree.dns_servers:
            out.append(f"ip name-server vrf default {dns}")
        out.append("!")
    if tree.domain:
        out.append(f"dns domain {tree.domain}")
        out.append("!")
    if tree.ntp_servers:
        for ntp in tree.ntp_servers:
            out.append(f"ntp server {ntp}")
        out.append("!")

    if tree.snmp is not None:
        if tree.snmp.community:
            out.append(f"snmp-server community {tree.snmp.community} ro")
        if tree.snmp.location:
            out.append(f"snmp-server location {tree.snmp.location}")
        if tree.snmp.contact:
            out.append(f"snmp-server contact {tree.snmp.contact}")
        for host in tree.snmp.trap_hosts:
            out.append(f"snmp-server host {host}")
        # SNMPv3 users.  ``aes128`` canonical → ``aes`` on EOS wire
        # (Arista accepts both but the bare form is the
        # platform-natural default); ``aes192`` / ``aes256`` emit
        # one-token form.  Users with no auth / no priv emit the
        # bare ``v3`` line — noAuthNoPriv is a valid USM mode.
        for u in tree.snmp.v3_users:
            parts = [f"snmp-server user {u.name} {u.group or 'v3group'} v3"]
            if u.auth_protocol:
                parts.append(
                    f"auth {u.auth_protocol} {u.auth_passphrase}"
                )
            if u.priv_protocol:
                wire_priv = (
                    "aes" if u.priv_protocol == "aes128"
                    else u.priv_protocol
                )
                parts.append(f"priv {wire_priv} {u.priv_passphrase}")
            out.append(" ".join(parts))
        if (
            tree.snmp.community or tree.snmp.location
            or tree.snmp.contact or tree.snmp.trap_hosts
            or tree.snmp.v3_users
        ):
            out.append("!")

    # --- Local users ---
    #
    # Hash-emit policy (Wave 2, fixes finding #1 in
    # user_smoke_findings.md — CRITICAL security disclosure).
    # Before the fix, foreign hashes from any source vendor were
    # emitted verbatim under an opaque ``secret 5 <blob>`` line,
    # which:
    #
    #   1. Leaked the literal hash payload onto the wire (a
    #      security finding when the source captured a bcrypt
    #      ``$2y$..`` from an OPNsense / pfSense / FreeBSD box).
    #   2. Used the wrong type tag — ``secret 5`` means md5crypt
    #      to EOS; bcrypt is not natively consumable.  EOS would
    #      either reject at commit time or, worse, treat the
    #      literal as opaque junk.
    #
    # Now we consult the shared :func:`is_migratable` policy as the
    # canonical source-of-truth for "can EOS consume this hash";
    # when migratable, :func:`classify_hash` resolves the algorithm
    # token and :data:`_ARISTA_SECRET_TYPE` (the codec-local emit-
    # form vocabulary) supplies the matching ``secret <N>`` tag.
    # The shared accepted-set covers exactly the same algorithms as
    # ``_ARISTA_SECRET_TYPE`` — keeping the dispatch table local
    # documents the EOS CLI grammar that consumes the tag verbatim
    # (similar to Aruba's ``_AOS_KNOWN_ALGORITHMS``).  Unmigratable
    # hashes fall through to a comment-form ``! password manager
    # user-name "X" -- review:`` line so the operator gets an
    # explicit "reset this password" signal and the rendered config
    # commits clean.
    #
    # Round-trip path: native parse stores hashes as
    # ``arista:<alg>:<payload>`` (the vendor-tagged form), which
    # ``classify_hash`` resolves to ``(<alg>, <payload>)`` — so
    # the existing native round-trip stays byte-identical.
    if tree.local_users:
        for user in tree.local_users:
            # Hash-gate: when the shared policy reports the source
            # hash isn't migratable to ``arista_eos`` (i.e. EOS's
            # ``secret`` command can't consume the payload), drop
            # the entire ``username`` declaration and emit ONLY the
            # review comment.  Mirrors the cisco_iosxe_cli pattern
            # (render.py ~line 113): leaving an orphan ``username
            # X role Y`` line with no ``secret`` clause creates a
            # passwordless account on commit, defeating the gate.
            # Finding #16 in user_smoke_findings.md (post-fix
            # re-paste).
            if user.hashed_password:
                algorithm, payload = classify_hash(user.hashed_password)
                if not is_migratable(user.hashed_password, "arista_eos"):
                    review = format_review_comment(
                        user.name, algorithm,
                        comment_syntax="exclamation",
                        target_label="Arista EOS",
                    )
                    out.append(review)
                    continue
                secret_tag = _ARISTA_SECRET_TYPE[algorithm]
            else:
                secret_tag = None
                payload = ""
            parts = [f"username {user.name}"]
            if user.privilege_level and user.privilege_level != 1:
                parts.append(f"privilege {user.privilege_level}")
            if user.role:
                parts.append(f"role {user.role}")
            if user.hashed_password:
                parts.append(f"secret {secret_tag} {payload}")
            else:
                parts.append("nopassword")
            out.append(" ".join(parts))
        out.append("!")

    # --- RADIUS servers (Tier 2) ---
    # Arista accepts the Cisco-derived ``radius-server host <ip>
    # auth-port <N> acct-port <N> key <secret>`` one-liner form
    # (legacy IOS grammar that EOS preserved).  We emit that shape
    # because it's the documented round-trip form for cross-vendor
    # ingest from Aruba AOS-S (``radius-server host <ip>`` +
    # separate ``radius-server key "<secret>"``) — see
    # ``aruba_aoss__arista_eos.yaml`` radius_servers expectation.
    # RADIUS shared secrets are NOT engineID-salted, so cross-
    # vendor migration of the key works without re-keying.
    if tree.radius_servers:
        for server in tree.radius_servers:
            parts = [f"radius-server host {server.host}"]
            if server.auth_port and server.auth_port != 1812:
                parts.append(f"auth-port {server.auth_port}")
            if server.acct_port and server.acct_port != 1813:
                parts.append(f"acct-port {server.acct_port}")
            if server.key:
                parts.append(f'key {server.key}')
            out.append(" ".join(parts))
        out.append("!")

    # --- DHCP server pools (Cluster E.1-A, Tier 2) ---
    # Reference: Arista EOS User Manual, "DHCP and DHCP Relay"
    # (https://www.arista.com/en/um-eos/eos-dhcp-and-dhcp-relay).
    # Pool stanza form:
    #
    #   ip dhcp pool <name>
    #      network <ip> <netmask>
    #      range <start_ip> <end_ip>
    #      default-router <ip>
    #      dns-server <ip> [<ip> ...]
    #      domain-name <name>
    #      lease <days> [<hours>] [<minutes>]
    #
    # Pool-name resolution mirrors the cisco_iosxe_cli render policy:
    # prefer the canonical ``interface`` field (which carries the
    # operator-chosen pool name on Cisco-derived sources), fall back
    # to a network-derived placeholder.  Slashes in the network
    # CIDR are sanitised to underscores so the bare name parses
    # cleanly through EOS's tokenizer.
    if tree.dhcp_servers:
        for pool in tree.dhcp_servers:
            pool_name = (
                pool.interface or pool.network or "POOL"
            ).replace("/", "_")
            out.append(f"ip dhcp pool {pool_name}")
            if pool.network:
                net, mask = _cidr_to_dotted_mask(pool.network)
                if net and mask:
                    out.append(f"   network {net} {mask}")
            if pool.start_ip and pool.end_ip:
                out.append(f"   range {pool.start_ip} {pool.end_ip}")
            if pool.gateway:
                out.append(f"   default-router {pool.gateway}")
            if pool.dns_servers:
                # EOS accepts space-separated DNS servers on one line
                # (Cisco-derived grammar); emit as a single line.
                out.append(
                    "   dns-server " + " ".join(pool.dns_servers)
                )
            if pool.domain_name:
                out.append(f"   domain-name {pool.domain_name}")
            if pool.lease_time and pool.lease_time != 86400:
                if pool.lease_time == 0xFFFFFFFF:
                    out.append("   lease infinite")
                else:
                    days = pool.lease_time // 86400
                    rem = pool.lease_time - days * 86400
                    hours = rem // 3600
                    rem -= hours * 3600
                    minutes = rem // 60
                    # EOS accepts and round-trips the d/h/m triple
                    # even when one or two components are zero
                    # (sample doc: ``lease 0 12 0`` for 12-hour
                    # leases).  Always emit the full triple so a
                    # 12-hour lease doesn't render as bare ``lease 0``.
                    out.append(
                        f"   lease {days} {hours} {minutes}"
                    )
            out.append("!")

    # --- VRF instances (GAP 6) — declare every canonical L3 VRF
    #     via ``vrf instance <name>``.  RD + RTs emit later
    #     under router-bgp / vrf <name>.  GAP-EVPN-1 mac-vrf
    #     entries are NOT L3 VRFs and skip this block — they're
    #     emitted purely under router-bgp / vlan <vid>.
    l3_vrfs = [
        ri for ri in tree.routing_instances
        if ri.instance_type != "mac-vrf"
    ]
    if l3_vrfs:
        for ri in l3_vrfs:
            out.append(f"vrf instance {ri.name}")
        out.append("!")

    # --- VLANs ---
    # Arista's ``name`` clause is whitespace-tokenised — a space in
    # the name causes the tokenizer to treat the trailing word as an
    # unrecognized argument and rejects the line at commit time.  The
    # vendor docs (``EOS User Manual / Virtual LANs (VLANs)``,
    # https://www.arista.com/en/um-eos/eos-virtual-lans-vlans) state
    # explicitly that spaces are not permitted; AVD's style guide
    # uses underscores as the separator (e.g. ``corporate_100``).
    # We sanitise cross-vendor-sourced VLAN names by replacing every
    # whitespace run with a single underscore so canonical names like
    # OPNsense's ``USER VLAN`` render as ``USER_VLAN``.  Single-token
    # names (the same-vendor round-trip case) emit unchanged.
    # Finding #17 in user_smoke_findings.md (post-fix re-paste).
    if tree.vlans:
        for vlan in tree.vlans:
            out.append(f"vlan {vlan.id}")
            if vlan.name:
                safe_name = re.sub(r"\s+", "_", vlan.name.strip())
                out.append(f"   name {safe_name}")
        out.append("!")

    # --- Interfaces ---
    # Build LAG mode lookup so member interfaces can emit the
    # matching ``channel-group N mode <mode>`` line.  Arista LAGs
    # live on the member side — the canonical tree carries
    # `lag_member_of` on each member + a `CanonicalLAG` record in
    # `tree.lags`; render needs both.
    #
    # Cross-vendor LAG-name normalisation: a Junos source renders
    # ``ae<N>`` as the canonical LAG name; Arista syntax requires
    # ``Port-Channel<N>``.  Without translation the render emits
    # ``interface ae1`` stubs that EOS rejects, AND the
    # ``channel-group`` line below skips emission because
    # ``iface.lag_member_of='ae1'`` doesn't match the
    # ``Port-Channel<N>`` regex.  Both paths now route through
    # :func:`_normalise_lag_name_to_arista` so canonical names from
    # Junos (``ae0``), MikroTik (``bond1``), Aruba (``trk1``), etc.
    # land as ``Port-Channel<N>`` in the rendered output.  Verified
    # against the Arista EOS User Manual ("Channel groups" chapter)
    # which mandates ``Port-Channel<N>``; ``Port-channel`` (lower-
    # case c) is the Cisco IOS syntax and would not parse on EOS.
    lag_mode_by_name = {lag.name: (lag.mode or "active") for lag in tree.lags}
    lag_name_to_arista: dict[str, str] = {}
    for lag in tree.lags:
        normalised = _normalise_lag_name_to_arista(lag.name)
        if normalised is not None:
            lag_name_to_arista[lag.name] = normalised
            # Mode lookup must follow the foreign->native rename so
            # the ``channel-group`` emit can find the LAG mode by the
            # post-rename ``Port-Channel<N>`` key as well.
            lag_mode_by_name[normalised] = lag.mode or "active"

    # --- empty-stub elision policy (issue #8 in
    #     user_smoke_findings.md, mirrors Junos commit 0fdf7e9) ---
    #
    # Cross-vendor renders into Arista used to leak foreign-vendor
    # port names like OPNsense's ``igc0`` / ``ixl0`` verbatim,
    # because the canonical tree preserves the source-side iface
    # name and our render walked every entry unconditionally.  The
    # result was a stanza-cluster of empty ``interface igc0\n!``
    # lines which EOS will reject at commit time (igc0 is not a
    # known interface on any Arista platform).
    #
    # Tiered policy: skip empty stubs UNLESS one of the following
    # justifies keeping the bare line —
    #
    #   (a) the iface carries renderable content (description,
    #       IPs, MTU, switchport, LAG membership, disabled, VRF
    #       binding),
    #   (b) the name matches an Arista-native physical port shape
    #       (``Ethernet<N>`` / ``Loopback<N>`` / ``Vlan<N>`` /
    #       ``Management<N>`` / ``Port-Channel<N>``) — preserves
    #       same-vendor round-trip stability for operator-style
    #       empty-port stubs,
    #   (c) the iface is referenced from elsewhere — VRF binding
    #       (``iface.vrf`` set) demands the line so EOS's commit-
    #       time validator finds the interface, and vlan member
    #       lists (``CanonicalVlan.tagged_ports`` /
    #       ``untagged_ports``) keep the L2 graph intact.
    vlan_member_names: set[str] = set()
    for v in tree.vlans:
        for name in v.tagged_ports:
            vlan_member_names.add(name)
        for name in v.untagged_ports:
            vlan_member_names.add(name)

    for iface in tree.interfaces:
        has_renderable_attr = (
            bool(iface.description)
            or bool(iface.ipv4_addresses)
            or bool(iface.ipv6_addresses)
            or bool(iface.dhcp_client_v6)
            or bool(iface.tunnel_type)
            or iface.mtu is not None
            or not iface.enabled
            or iface.switchport_mode is not None
            or iface.access_vlan is not None
            or bool(iface.trunk_allowed_vlans)
            or bool(iface.lag_member_of)
        )
        is_native_port = bool(
            _IS_ARISTA_PHYSICAL_PORT_RE.match(iface.name)
        )
        is_referenced = (
            bool(iface.vrf) or iface.name in vlan_member_names
        )
        if (
            not has_renderable_attr
            and not is_native_port
            and not is_referenced
        ):
            # Foreign-vendor empty stub (e.g. OPNsense ``igc0``
            # leaking through a cross-vendor render).  Skip.
            continue

        out.append(f"interface {iface.name}")
        if iface.description:
            out.append(f"   description {iface.description}")
        # L3 flip needed when we emit an IP address on a port that
        # doesn't already indicate L3 (Ethernet<N> physical).
        if iface.ipv4_addresses and iface.name.lower().startswith(
            "ethernet"
        ):
            out.append("   no switchport")
        # GAP 6: per-interface VRF membership.  Must emit BEFORE
        # ``ip address`` so EOS correctly binds the IP into the
        # VRF's routing table.
        if iface.vrf:
            out.append(f"   vrf {iface.vrf}")
        if iface.switchport_mode == "access":
            out.append("   switchport mode access")
            if iface.access_vlan is not None:
                out.append(
                    f"   switchport access vlan {iface.access_vlan}"
                )
        elif iface.switchport_mode == "trunk":
            out.append("   switchport mode trunk")
            # Phase 4b Wave 7c-C: ``switchport trunk native vlan <N>``
            # — without this, a Cisco IOS-XE source carrying
            # ``switchport trunk native vlan 10`` round-trips through
            # Arista with the native-VLAN signal silently dropped.
            # ``project_switchport_to_vlan`` then sees the trunk
            # member only in tagged_ports (not as the untagged
            # native), corrupting the VLAN-centric port lists on
            # every cross-vendor pass.  Arista EOS syntax mirrors
            # Cisco IOS-XE here (Arista EOS User Manual,
            # "Switchport Configuration" — ``switchport trunk native
            # vlan <vlan-id>``).
            if iface.trunk_native_vlan is not None:
                out.append(
                    f"   switchport trunk native vlan {iface.trunk_native_vlan}"
                )
            if iface.trunk_allowed_vlans:
                vlist = ",".join(str(v) for v in iface.trunk_allowed_vlans)
                out.append(
                    f"   switchport trunk allowed vlan {vlist}"
                )
        for addr in iface.ipv4_addresses:
            out.append(
                f"   ip address {addr.ip}/{addr.prefix_length}"
            )
        # GAP-EVPN-3: IPv6 addresses.  Link-local form re-emits
        # the explicit ``link-local`` keyword; global form emits
        # plain ``ipv6 address X/Y``.
        for v6 in iface.ipv6_addresses:
            if v6.scope == "link-local":
                out.append(
                    f"   ipv6 address {v6.ip}/{v6.prefix_length} link-local"
                )
            else:
                out.append(
                    f"   ipv6 address {v6.ip}/{v6.prefix_length}"
                )
        # IPv6 dynamic-address mode.  Arista EOS mirrors IOS-XE:
        # ``ipv6 address dhcp`` (stateful client) and ``ipv6
        # address autoconfig`` (SLAAC).  Other dhcp_client_v6 values
        # (track6 / 6rd / 6to4 — OPNsense-specific) drop to a review
        # comment.
        if iface.dhcp_client_v6 == "dhcp6":
            out.append("   ipv6 address dhcp")
        elif iface.dhcp_client_v6 == "slaac":
            out.append("   ipv6 address autoconfig")
        elif iface.dhcp_client_v6:
            out.append(
                f"   ! review: dhcp_client_v6={iface.dhcp_client_v6} "
                f"has no Arista EOS equivalent"
            )
        # Tunnel-mode discriminator on ``Tunnel<N>`` stanzas.  Empty
        # tunnel_type falls through to the EOS platform default
        # (GRE), so we suppress the redundant ``tunnel mode gre ip``.
        if iface.tunnel_type and iface.interface_type == "ianaift:tunnel":
            tt = iface.tunnel_type.lower()
            if tt == "gre":
                out.append("   tunnel mode gre")
            elif tt == "ipip":
                out.append("   tunnel mode ipip")
            elif tt == "ipsec":
                out.append("   tunnel mode ipsec")
            elif tt == "vxlan":
                out.append("   tunnel mode vxlan")
            elif tt == "eoip":
                out.append(
                    "   ! review: tunnel_type=eoip has no Arista EOS "
                    "equivalent (MikroTik-only)"
                )
        # LAG membership: ``channel-group N mode <mode>`` on member
        # Ethernet interfaces.  Arista (like Cisco IOS) puts this
        # on the child side, not the Port-Channel stanza.
        #
        # Cross-vendor sources may carry foreign LAG names on
        # ``iface.lag_member_of`` (Junos ``ae1``, Aruba ``trk1``).
        # Route through :func:`_normalise_lag_name_to_arista` so the
        # channel-group ID is recovered in those cases.  Without the
        # rename the regex below failed and the membership line was
        # silently dropped — the symptom that closed the
        # ``ksator_qfx5100`` cell of the Phase 4 Junos→Arista mesh.
        if iface.lag_member_of:
            normalised_member = _normalise_lag_name_to_arista(
                iface.lag_member_of,
            )
            target_lag_name = normalised_member or iface.lag_member_of
            m = re.match(r"^Port-Channel(\d+)$", target_lag_name)
            if m is not None:
                chan_id = m.group(1)
                mode = lag_mode_by_name.get(
                    target_lag_name, "active",
                )
                # Normalise canonical mode strings to EOS CLI tokens.
                if mode == "static":
                    mode_token = "on"
                elif mode == "passive":
                    mode_token = "passive"
                else:
                    mode_token = "active"
                out.append(
                    f"   channel-group {chan_id} mode {mode_token}"
                )
        if iface.mtu is not None:
            out.append(f"   mtu {iface.mtu}")
        if not iface.enabled:
            out.append("   shutdown")
        out.append("!")

    # --- LAGs (channel-group lines live on member interfaces; we
    #     also emit ``interface Port-ChannelN`` stubs so the
    #     config is self-consistent) ---
    #
    # Translate canonical LAG name to ``Port-Channel<N>`` so the
    # stub emit matches the channel-group binding above.  Without
    # the rename the renderer emitted ``interface ae1`` which EOS
    # rejects (``ae`` is not a known interface family on Arista);
    # the cross-vendor finding-table flagged this as a B-bucket
    # rename for Junos→Arista in
    # ``phase4_findings_juniper_junos.md``.  Honouring the rename
    # here turns the cell into a true ALIGNED on
    # ``interfaces[].lag_member_of``.
    existing_names = {i.name for i in tree.interfaces}
    for lag in tree.lags:
        rendered_name = lag_name_to_arista.get(lag.name, lag.name)
        if rendered_name in existing_names:
            continue
        out.append(f"interface {rendered_name}")
        out.append("!")

    # --- Vxlan1 (GAP 6) — EOS carries VLAN-to-VNI + VRF-to-L3-VNI
    #     mappings inside a single ``interface Vxlan1`` stanza.
    #     GAP-EVPN-2: source-interface + udp-port come from the
    #     CanonicalVxlan records (per-switch values stamped on
    #     every VNI mapping at parse-time); fall back to
    #     ``Loopback0`` / ``4789`` when no record carries a non-
    #     default value (e.g. a render of a tree built purely from
    #     a VRF / l3_vni scenario with no L2 VNIs).
    has_l3_vnis = any(
        ri.l3_vni is not None for ri in tree.routing_instances
    )
    if tree.vxlan_vnis or has_l3_vnis:
        src_iface = "Loopback0"
        for v in tree.vxlan_vnis:
            if v.source_interface:
                src_iface = v.source_interface
                break
        udp_port = 4789
        for v in tree.vxlan_vnis:
            if v.udp_port and v.udp_port != 4789:
                udp_port = v.udp_port
                break
        out.append("interface Vxlan1")
        out.append(f"   vxlan source-interface {src_iface}")
        out.append(f"   vxlan udp-port {udp_port}")
        for v in tree.vxlan_vnis:
            out.append(f"   vxlan vlan {v.vlan_id} vni {v.vni}")
        for ri in tree.routing_instances:
            if ri.l3_vni is not None:
                out.append(f"   vxlan vrf {ri.name} vni {ri.l3_vni}")
        out.append("!")

    # --- router bgp blocks (GAP 6 + GAP-EVPN-1) — emit
    #     ``router bgp <asn>`` carrying:
    #       * ``vrf <name> / rd / route-target ...`` for L3 VRFs
    #         (instance_type == "vrf")
    #       * ``vlan <vid> / rd / route-target ...`` for per-VLAN
    #         EVPN MAC-VRF bindings (instance_type == "mac-vrf",
    #         GAP-EVPN-1).  vid is reverse-looked-up from the
    #         routing-instance name → CanonicalVlan.name match.
    #     ASN defaults to a placeholder since CanonicalIntent
    #     doesn't model BGP config beyond what VRFs need;
    #     operators re-emit as needed.
    ris_with_bgp_meta = [
        ri for ri in tree.routing_instances
        if ri.route_distinguisher or ri.rt_imports or ri.rt_exports
    ]
    if ris_with_bgp_meta:
        # Build a name→vlan_id lookup for the MAC-VRF emit path.
        vid_by_name = {
            v.name: v.id for v in tree.vlans if v.name
        }
        out.append("router bgp 65000")
        for ri in ris_with_bgp_meta:
            out.append("   !")
            if ri.instance_type == "mac-vrf":
                # Reverse-lookup the VLAN id by name.  Fall back
                # to parsing ``VLAN<N>`` synthetic-form (the
                # parse path uses this when CanonicalVlan.name
                # is empty).  If neither works, skip — render
                # would emit an invalid ``vlan <name>`` line.
                vid = vid_by_name.get(ri.name)
                if vid is None and ri.name.startswith("VLAN"):
                    try:
                        vid = int(ri.name[len("VLAN"):])
                    except ValueError:
                        vid = None
                if vid is None:
                    # Can't resolve back to a VID — skip the
                    # block rather than emit nonsense.
                    continue
                out.append(f"   vlan {vid}")
            else:
                out.append(f"   vrf {ri.name}")
            if ri.route_distinguisher:
                out.append(f"      rd {ri.route_distinguisher}")
            # Use ``route-target both`` for matched import/export
            # pairs (compact + canonical-friendly); emit separate
            # import/export lines when they diverge.
            if (
                ri.rt_imports == ri.rt_exports and ri.rt_imports
            ):
                for rt in ri.rt_imports:
                    out.append(f"      route-target both {rt}")
            else:
                for rt in ri.rt_imports:
                    out.append(f"      route-target import evpn {rt}")
                for rt in ri.rt_exports:
                    out.append(f"      route-target export evpn {rt}")
            if ri.instance_type == "mac-vrf":
                # ``redistribute learned`` is the canonical EOS
                # default for MAC-VRF blocks — emit it so a
                # round-trip of a fresh-from-Arista MAC-VRF
                # continues to advertise locally-learned MACs.
                out.append("      redistribute learned")
        out.append("!")

    # --- Static routes ---
    if tree.static_routes:
        for route in tree.static_routes:
            if route.gateway:
                out.append(
                    f"ip route {route.destination} {route.gateway}"
                )
        out.append("!")
        out.append("ip routing")
        out.append("!")

    out.append("end")
    return "\n".join(out) + "\n"
