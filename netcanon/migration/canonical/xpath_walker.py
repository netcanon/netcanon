"""Canonical-tree xpath walker — the shared ``iter_xpaths`` source.

Every codec's :meth:`iter_xpaths` yields from :func:`_walk_canonical`,
which emits a schema xpath for each populated field of a
:class:`CanonicalIntent`.  The walker is the sole input to
``migration_validate.validate_against``, so the honesty contract
("loss is visible in the report, not hidden") depends on it yielding
an xpath for every populated surface.

Relocated here from ``codecs/cisco_iosxe_cli/codec.py`` (run3
``walk-canonical-vendor-leaf``) so the shared walker no longer lives
inside a single vendor codec; ``cisco_iosxe_cli.codec`` re-exports it
for the historical import path.
"""

from __future__ import annotations

from collections.abc import Iterable

from .intent import CanonicalIntent


def _walk_canonical(intent: CanonicalIntent) -> Iterable[str]:  # noqa: C901
    """Yield schema xpaths for every populated field of a CanonicalIntent.

    This is the input to :func:`netcanon.services.migration_validate.
    validate_against` — the validator classifies each yielded xpath
    against the *target* codec's :class:`CapabilityMatrix` so the
    interactive migration report can surface lossy / unsupported
    surfaces before the operator commits.  The honesty contract
    ("loss is visible in the report, not hidden") therefore depends on
    this walker yielding an xpath for **every** populated surface — a
    field the walker skips can never be flagged, no matter how the
    target declares it.  So the walker covers all of Tier 1 + Tier 2:
    system scalars, every interface sub-field, VLANs, static routes,
    SNMP (incl. v3 sub-fields), DHCP pools, LAGs, local users, RADIUS
    servers, VXLAN VNIs, EVPN Type-5 routes, and routing-instances.

    Each yield is guarded on the field being populated, so the walker
    emits xpaths only for data the source config actually carried — an
    empty surface yields nothing and so classifies as neither lossy nor
    unsupported (there is nothing to lose).

    The xpath vocabulary is the granular hyphenated shape the codec
    capability matrices declare (e.g. ``/lags/lag/mode``,
    ``/local-users/user/role``); :meth:`CapabilityMatrix.classify` is
    exact-string-match, so the walker and the matrices must speak the
    same strings for a declaration to be reachable.

    Kept at module level (rather than relocating to :mod:`.parse` or
    :mod:`.render`) so that the
    ``from netcanon.migration.codecs.cisco_iosxe_cli.codec import _walk_canonical``
    import surface every cross-codec ``iter_xpaths`` consumer relies
    on stays intact.  Used by the OPNsense / Aruba / FortiGate / Arista /
    Juniper / MikroTik / Cisco-NETCONF codecs.

    Note: ``run_full_mesh.py``'s cross-mesh field-disposition matrix
    does NOT consume this walker — it compares ``model_dump()`` output
    and reads each matrix's ``unsupported`` declarations directly — so
    expanding this walker affects only the live validation report.
    """
    # ── Tier 1 — system scalars ──
    if intent.hostname:
        yield "/system/hostname"
    if intent.domain:
        yield "/system/domain"
    for _ in intent.dns_servers:
        yield "/system/dns-server"
    for _ in intent.ntp_servers:
        yield "/system/ntp-server"
    if intent.timezone:
        yield "/system/timezone"
    for _ in intent.syslog_servers:
        yield "/system/syslog-server"
    for iface in intent.interfaces:
        yield "/interfaces/interface/name"
        if iface.description:
            yield "/interfaces/interface/config/description"
        yield "/interfaces/interface/config/enabled"
        if iface.interface_type:
            yield "/interfaces/interface/config/type"
        for idx, addr in enumerate(iface.ipv4_addresses):
            yield "/interfaces/interface/ipv4/address/ip"
            yield "/interfaces/interface/ipv4/address/prefix-length"
            # Additional addresses: single-address platforms (FortiGate /
            # OPNsense) render only the primary and silently drop every
            # extra address — a whole-subnet reachability loss.  The
            # discriminator is CARDINALITY, not the is_secondary flag:
            # IPv4 sources that don't model a primary/secondary distinction
            # (Junos / OPNsense parse) leave is_secondary False on every
            # address, so a flag-gated walk emitted nothing for a genuinely
            # multi-address interface and the loss reported 'ok' (audit
            # 276eaeb T0-1).  Walk the secondary xpath for every address
            # beyond the first so those codecs' unsupported declaration
            # fires regardless of whether the flag was set.
            if idx > 0 or addr.is_secondary:
                yield "/interfaces/interface/ipv4/address/secondary-ip"
            if addr.virtual_gateway_address:
                yield (
                    "/interfaces/interface/ipv4/address/"
                    "virtual-gateway-address"
                )
            if addr.virtual_gateway_mac:
                yield (
                    "/interfaces/interface/ipv4/address/"
                    "virtual-gateway-mac"
                )
        for idx6, addr6 in enumerate(iface.ipv6_addresses):   # GAP-EVPN-3
            yield "/interfaces/interface/ipv6/address/ip"
            yield "/interfaces/interface/ipv6/address/prefix-length"
            # link-local vs global scope discriminator (audit e5b77d7,
            # PR-2c walk-expansion).  scope defaults "global" (always
            # populated), so a codec that renders the address but hardcodes
            # the scope (FortiGate / VyOS pin "global") or drops it on the
            # NETCONF stub declares it lossy -- losing the link-local marker
            # is no longer silently 'ok'.  Codecs that re-infer scope from
            # the fe80::/10 prefix on parse round-trip it and stay supported.
            if addr6.scope:
                yield "/interfaces/interface/ipv6/address/scope"
            # Cardinality discriminator (see the IPv4 note above): IPv6 has
            # no `secondary` keyword at all, so is_secondary is structurally
            # never set — only the address count reveals the drop (audit
            # 276eaeb T0-1).
            if idx6 > 0 or addr6.is_secondary:
                yield "/interfaces/interface/ipv6/address/secondary-ip"
            if addr6.virtual_gateway_address:
                yield (
                    "/interfaces/interface/ipv6/address/"
                    "virtual-gateway-address"
                )
            if addr6.virtual_gateway_mac:
                yield (
                    "/interfaces/interface/ipv6/address/"
                    "virtual-gateway-mac"
                )
        if iface.dhcp_client_v6:
            yield "/interfaces/interface/dhcp-client-v6"
        if iface.tunnel_type:
            yield "/interfaces/interface/tunnel-type"
        if iface.mtu is not None:
            yield "/interfaces/interface/config/mtu"
        if iface.vrf:
            yield "/interfaces/interface/config/vrf"
        if iface.lag_member_of:
            yield "/interfaces/interface/lag-member-of"
        if iface.dhcp_client:
            yield "/interfaces/interface/dhcp-client"
        # Per-interface switchport view (the transpose of the VLAN-centric
        # ``/vlans/vlan/{tagged,untagged}-ports`` surface).  Switch codecs
        # declare these ``supported``; router / firewall codecs that drop
        # them declare ``unsupported`` — so walking them surfaces the L2
        # loss when a switch config is migrated to a routed target.  The
        # spelling matches the existing nxos / aoscx matrix declarations
        # (no ``config/`` segment).
        if iface.switchport_mode:
            yield "/interfaces/interface/switchport-mode"
        if iface.access_vlan is not None:
            yield "/interfaces/interface/access-vlan"
        if iface.dot1q_vlan is not None:
            yield "/interfaces/interface/dot1q-vlan"
        if iface.trunk_allowed_vlans:
            yield "/interfaces/interface/trunk-allowed-vlans"
        if iface.trunk_native_vlan is not None:
            yield "/interfaces/interface/trunk-native-vlan"
        if iface.voice_vlan is not None:
            yield "/interfaces/interface/voice-vlan"
        for grp in iface.vrrp_groups:
            yield "/interfaces/interface/vrrp-groups/group"
            # FHRP family discriminator + election / timer params (audit
            # e5b77d7, PR-2b walk-expansion).  mode/priority/preempt/advert
            # are always populated (schema defaults), so a target codec that
            # renders only its native FHRP family (or no FHRP at all) declares
            # them lossy/unsupported -- a cross-family downgrade or a dropped
            # election parameter is no longer silently 'ok'.
            yield "/interfaces/interface/vrrp-groups/group/mode"
            yield "/interfaces/interface/vrrp-groups/group/priority"
            yield "/interfaces/interface/vrrp-groups/group/preempt"
            yield "/interfaces/interface/vrrp-groups/group/advertisement-interval"
            if grp.authentication:
                yield "/interfaces/interface/vrrp-groups/group/authentication"
            if grp.virtual_ipv6s:
                yield "/interfaces/interface/vrrp-groups/group/virtual-ipv6s"
            if grp.description:
                yield "/interfaces/interface/vrrp-groups/group/description"
            # Sub-field losses several codecs declare lossy (FortiGate /
            # AOS-S keep one VIP + drop secondaries / virtual-mac / track
            # objects).  Walk them only when the loss condition holds, so
            # the lossy declaration actually fires in the live report
            # instead of being unreachable (2026-06 adversarial review #9).
            if len(grp.virtual_ips) > 1:
                yield "/interfaces/interface/vrrp-groups/group/virtual-ips"
            if grp.virtual_mac:
                yield "/interfaces/interface/vrrp-groups/group/virtual-mac"
            if grp.track_interfaces:
                yield "/interfaces/interface/vrrp-groups/group/track-interfaces"
    for vlan in intent.vlans:
        yield "/vlans/vlan/id"
        yield "/vlans/vlan/name"
        if vlan.description:
            yield "/vlans/vlan/description"
        for _ in vlan.tagged_ports:
            yield "/vlans/vlan/tagged-ports"
        for _ in vlan.untagged_ports:
            yield "/vlans/vlan/untagged-ports"
        # VLAN SVI / management L3 address (the VLAN-record IP, distinct from
        # interfaces[].ipv4_addresses).  The Junos ``irb`` + Aruba SVI-on-VLAN
        # shapes fold the SVI's L3 here via project_svi_to_vlan, and only the
        # SVI-model renderers (arista_eos, cisco_iosxe_cli) reconstruct it via
        # synthesize_svis_from_vlan_l3.  Codecs that render L3 only from a
        # sibling interface drop it on render — so this MUST be walked, else
        # validate_against classifies the unwalked path as "supported" and
        # reports severity:ok while the SVI/management IP silently vanishes
        # (the same fail-surfaced principle as the {tagged,untagged}-ports
        # twin above; blind-audit 3ec11f3 T0-2).  Droppers declare it lossy.
        for addr in vlan.ipv4_addresses:
            yield "/vlans/vlan/ipv4/address/ip"
            # VLAN-SVI L3 sub-fields — the twin of the interface-mount walk
            # above.  Previously the VLAN-SVI mount yielded ONLY .../ip while
            # the interface mount walked all five, so a dropped secondary IP /
            # anycast virtual-gateway-address / virtual-gateway-mac carried on
            # a VLAN record rode the classify() default to "supported" and
            # validate_against reported severity:ok while the value vanished
            # (blind-audit f92e97a T0-2).  Walk them (conditionally, mirroring
            # the interface loop) so the loss surfaces; droppers declare them
            # lossy/unsupported per the per-codec capability matrix.
            if addr.is_secondary:
                yield "/vlans/vlan/ipv4/address/secondary-ip"
            if addr.virtual_gateway_address:
                yield "/vlans/vlan/ipv4/address/virtual-gateway-address"
            if addr.virtual_gateway_mac:
                yield "/vlans/vlan/ipv4/address/virtual-gateway-mac"
    for route in intent.static_routes:
        yield "/routing/static-route"
        # Next-hop gateway (audit e5b77d7, PR-2c walk-expansion).  Walk it
        # when populated so a codec that renders no <staticroutes> at all
        # (OPNsense) or no static routes whatsoever (the NETCONF stub) has
        # its lossy/unsupported declaration fire instead of classify()
        # fail-opening the dropped next-hop to 'supported'.
        if route.gateway:
            yield "/routing/static-route/gateway"
        if route.vrf:
            yield "/routing/static-route/vrf"
        # Sub-field losses (run3 audit): several codecs render only the
        # destination + next-hop and silently drop the admin distance
        # (metric), the operator route name (description), and/or
        # interface-nexthop (connected) routes.  Walk them only when
        # populated so the per-codec lossy/unsupported declaration fires
        # in the live report instead of classify() defaulting to
        # 'supported' (a silent loss reported severity: ok).
        if route.metric:
            yield "/routing/static-route/metric"
        if route.description:
            yield "/routing/static-route/description"
        if route.interface:
            yield "/routing/static-route/interface"
    if intent.anycast_gateway_mac:
        yield "/anycast-gateway-mac"
    # ── Tier 2 — emit only what's populated ──
    if intent.snmp is not None:
        if intent.snmp.community:
            yield "/snmp/community"
        if intent.snmp.location:
            yield "/snmp/location"
        if intent.snmp.contact:
            yield "/snmp/contact"
        for _ in intent.snmp.trap_hosts:
            yield "/snmp/trap-host"
        for v3 in intent.snmp.v3_users:
            yield "/snmp/v3-user"
            # Sub-field losses (audit e5b77d7, PR-2a walk-expansion): codecs
            # that render the v3-user but DOWNGRADE the auth/priv algorithm,
            # re-key the opaque passphrase, or drop the VACM group declare
            # these lossy/unsupported.  Walk them only when populated so the
            # declaration fires in the live report instead of classify()
            # fail-opening to 'supported' (a silent crypto downgrade).
            if v3.auth_protocol:
                yield "/snmp/v3-user/auth-protocol"
            if v3.auth_passphrase:
                yield "/snmp/v3-user/auth-passphrase"
            if v3.priv_protocol:
                yield "/snmp/v3-user/priv-protocol"
            if v3.priv_passphrase:
                yield "/snmp/v3-user/priv-passphrase"
            if v3.group:
                yield "/snmp/v3-user/group"
            if v3.engine_id:
                yield "/snmp/v3-user/engine-id"
    for _ in intent.dhcp_servers:
        yield "/dhcp-servers/pool"
    for _ in intent.lags:
        yield "/lags/lag/name"
        yield "/lags/lag/members"
        yield "/lags/lag/mode"
    for user in intent.local_users:
        yield "/local-users/user/name"
        if user.role:
            yield "/local-users/user/role"
        if user.hashed_password:
            yield "/local-users/user/hashed-password"
        yield "/local-users/user/privilege-level"
    for _ in intent.radius_servers:
        yield "/radius-servers/server/host"
        yield "/radius-servers/server/key"
    for vx in intent.vxlan_vnis:
        yield "/vxlan-vnis/vni"
        if vx.source_interface:
            yield "/vxlan-vnis/source-interface"
        if vx.mcast_group:
            yield "/vxlan-vnis/mcast-group"
        if vx.flood_list:
            yield "/vxlan-vnis/flood-list"
        yield "/vxlan-vnis/udp-port"
        yield "/vxlan-vnis/vlan-id"
    for _ in intent.evpn_type5_routes:
        yield "/evpn-type5-routes/route"
    for inst in intent.routing_instances:
        yield "/routing-instances/instance"
        yield "/routing-instances/instance/name"
        # Instance-type discriminator (audit e5b77d7, PR-2c walk-expansion):
        # mac-vrf vs vrf.  Defaults "vrf" (always populated), so a codec that
        # renders the routing-instance anchor but cannot represent the type
        # (most CLI VRF renderers emit a plain `vrf NAME`) declares it lossy,
        # and a codec that renders no routing-instance at all declares it
        # unsupported -- only Arista (mac-vrf/vrf branch) and Junos (explicit
        # `instance-type`) round-trip it and stay supported.
        if inst.instance_type:
            yield "/routing-instances/instance/instance-type"
        if inst.description:
            yield "/routing-instances/instance/description"
        if inst.route_distinguisher:
            yield "/routing-instances/instance/route-distinguisher"
        if inst.rt_imports:
            yield "/routing-instances/instance/rt-imports"
        if inst.rt_exports:
            yield "/routing-instances/instance/rt-exports"
        if inst.l3_vni is not None:
            yield "/routing-instances/instance/l3-vni"
