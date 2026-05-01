"""
``CiscoIOSXECLICodec`` — parse ``show running-config`` text.

Direction: ``parse_only``.  No ``render()`` — generating syntactically
valid IOS CLI from a tree is substantially harder than parsing it and
is deferred to a future phase.

Parser strategy
---------------
IOS ``show running-config`` is a line-oriented, indentation-significant
format.  Interfaces are delimited by ``interface <name>`` lines and
terminated by ``!`` comment lines.  The parser:

1. Scans for ``interface <name>`` lines.
2. Captures indented sub-commands until the next ``!`` or un-indented
   line.
3. Extracts known keywords: ``description``, ``shutdown`` / ``no
   shutdown``, ``ip address <ip> <mask>``.
4. Builds the same nested dict shape as ``CiscoIOSXECodec`` so the
   two codecs are interchangeable as pipeline SOURCEs.

Limitations (``experimental`` certainty):
    * Only parses interface stanzas — routing protocols, ACLs, VLANs,
      AAA, crypto, and everything else is silently skipped.
    * Subnet mask → prefix-length conversion handles standard masks
      only (``255.255.255.0`` → ``/24``).  Non-contiguous masks are
      rejected.
    * ``secondary`` IP addresses are ignored (first address only).
    * ``switchport`` interfaces are treated as having no IP.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any, ClassVar, Iterable

from ....models.migration import (
    CapabilityMatrix,
    DeviceClass,
    LossyPath,
    UnsupportedPath,
)
from ...canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIPv4Address,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
    CanonicalLocalUser,
    CanonicalRADIUSServer,
    CanonicalSNMP,
    CanonicalStaticRoute,
    CanonicalVlan,
)
from ..base import CodecBase, ParseError, RenderError
from ..registry import register
from . import port_names as _port_names

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Cisco port-prefix ↔ speed-hint mappings + port-name helpers moved
# to :mod:`.port_names`.  See that module for the pure classify /
# format primitives — the class methods below delegate to it.
# ----------------------------------------------------------------------


@register
class CiscoIOSXECLICodec(CodecBase):
    """Parse-only codec for Cisco IOS-XE ``show running-config`` output.

    Shares ``vendor_id=cisco_iosxe`` with the NETCONF codec — both
    target the same vendor YAML.
    """

    name: ClassVar[str] = "cisco_iosxe_cli"
    version_hint: ClassVar[str | None] = "15.x / 16.x / 17.x"
    input_format: ClassVar[str] = "cli-ios"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "certified"
    canonical_model: ClassVar[str] = "openconfig-lite"
    description: ClassVar[str] = (
        "Paste the output of `show running-config`.  This is the text "
        "your existing backup collector already captures — you can also "
        "pick a stored Cisco config from the dropdown."
    )
    sample_input: ClassVar[str] = (
        '!\n'
        'version 17.9\n'
        'hostname Router\n'
        '!\n'
        'interface GigabitEthernet0/0/0\n'
        ' description WAN uplink\n'
        ' ip address 198.51.100.1 255.255.255.252\n'
        ' no shutdown\n'
        '!\n'
        'interface Loopback0\n'
        ' description Router-ID\n'
        ' ip address 10.255.0.1 255.255.255.255\n'
        '!\n'
        'end\n'
    )
    output_extension: ClassVar[str] = "cfg"

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="cisco_iosxe_cli",
        vendor_id="cisco_iosxe",
        version_range="15.x+",
        device_classes=[DeviceClass.router, DeviceClass.switch],
        supported=[
            "/system/hostname",
            "/interfaces/interface/name",
            "/interfaces/interface/config/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/routing/static-route",
            # Tier 2 — SNMP
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/trap-host",
            "/snmp/v3-user",
        ],
        lossy=[
            LossyPath(
                path="/interfaces/interface/config/type",
                reason=(
                    "CLI parser infers interface type from the name prefix "
                    "(GigabitEthernet → ethernetCsmacd, Loopback → "
                    "softwareLoopback) but cannot detect all IANA types."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/evpn-type5-routes/route",
                reason=(
                    "EVPN Type-5 per-prefix records are a VRF-"
                    "property canonical model via "
                    "CanonicalRoutingInstance.l3_vni; IOS-XE would "
                    "derive Type-5 intent from ``router bgp / "
                    "address-family l2vpn evpn`` + per-VRF route-"
                    "target configuration.  No codec populates per-"
                    "prefix records today — lossy-by-default "
                    "extension point pending future route-map "
                    "parsing."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            UnsupportedPath(
                path="/interfaces/interface/subinterfaces/subinterface/ipv6",
                reason="Phase 0.5 scope — IPv4 only.",
            ),
            UnsupportedPath(
                path="/vxlan-vnis/vni",
                reason=(
                    "IOS-XE VXLAN mappings (`interface nve1 / member "
                    "vni <N> associate vrf <name>`) parse-and-ignore "
                    "in v1.  CanonicalVxlan schema exists; wire-up "
                    "deferred until demand arrives for Catalyst-to-"
                    "Arista migrations."
                ),
            ),
            UnsupportedPath(
                path="/routing-instances/instance",
                reason=(
                    "VRF declarations (`vrf definition <name>` with "
                    "`rd` + `address-family ipv4` + "
                    "`route-target import/export`) and per-interface "
                    "`vrf forwarding <name>` parse-and-ignore in "
                    "v1.  CanonicalRoutingInstance + "
                    "CanonicalInterface.vrf schema exists; IOS-XE "
                    "wire-up deferred."
                ),
            ),
        ],
    )

    @property
    def capabilities(self) -> CapabilityMatrix:
        return self._CAPS

    # -----------------------------------------------------------------
    # Parse
    # -----------------------------------------------------------------

    def parse(self, raw: str) -> CanonicalIntent:
        """Parse IOS-XE ``show running-config`` output into a
        :class:`CanonicalIntent`.

        Raises:
            ParseError: If the input doesn't look like IOS config at all
                (e.g. XML or JSON).
        """
        if not raw.strip():
            raise ParseError(
                "cisco_iosxe_cli: empty input",
                snippet="",
            )
        # Quick sanity: if it starts with '<' it's XML, not CLI.
        stripped = raw.lstrip()
        if stripped.startswith("<") or stripped.startswith("{"):
            raise ParseError(
                "cisco_iosxe_cli: input looks like XML or JSON, not IOS CLI. "
                "Use the cisco_iosxe (NETCONF) codec for XML input.",
                snippet=stripped[:120],
            )

        intent = CanonicalIntent(
            source_vendor="cisco_iosxe",
            source_format="cli-ios",
        )

        # System-level fields
        intent.hostname = _extract_hostname(raw)

        # Interfaces
        intent.interfaces = _parse_interfaces(raw)

        # VLANs (top-level `vlan N / name X` stanzas)
        intent.vlans = _parse_vlans(raw)

        # Synthesize VLAN records for any `interface Vlan<N>` SVIs that
        # didn't have a matching top-level stanza.  Without this, VLAN-
        # centric downstream codecs (Aruba, OPNsense) can't find the
        # SVI's IP and silently drop it.  See translator-plans.txt
        # "KNOWN DATA-LOSS BUGS / BUG 1".
        _synthesize_vlans_from_svis(intent)

        # Static routes
        intent.static_routes = _parse_static_routes(raw)

        # SNMP (Tier 2)
        intent.snmp = _parse_snmp(raw)

        # Local users (Tier 2).
        intent.local_users = _parse_local_users(raw)

        # DHCP server pools (Tier 2).
        intent.dhcp_servers = _parse_dhcp_pools(raw)

        # RADIUS servers (Tier 2).  Handles both modern named-server
        # syntax and legacy `radius-server host` one-liner.
        intent.radius_servers = _parse_radius_servers(raw)

        # LAGs (Tier 2) — both the `interface Port-channelN` declaration
        # and the per-member `channel-group N mode M` lines contribute.
        # See translator-plans.txt BUG 2.
        intent.lags = _parse_lags(raw, intent)

        # Bug 3 transpose: mirror per-port switchport state into the
        # VLAN-centric tagged_ports / untagged_ports lists so VLAN-
        # centric renderers (Aruba, OPNsense) can emit the membership.
        # Without this, per-interface `switchport access vlan 20` /
        # `switchport trunk allowed vlan 11,20` never reaches the
        # target config.  See translator-plans.txt BUG 3.
        from ...canonical.transforms import project_switchport_to_vlan
        project_switchport_to_vlan(intent)

        # Parse-end summary: lets ops answer "did parse succeed?" from
        # a debug-level log line without needing to inspect the
        # response JSON.  Zero counts across the board on a non-empty
        # input usually mean a grammar the codec doesn't handle —
        # same signal the real-capture harness enforces at test time.
        logger.debug(
            "cisco_iosxe_cli parsed: hostname=%r ifaces=%d vlans=%d "
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

    # -----------------------------------------------------------------
    # Render — emit IOS-XE running-config text
    # -----------------------------------------------------------------

    def render(self, tree: Any) -> str:
        """Render a :class:`CanonicalIntent` to IOS-XE
        ``show running-config`` text.

        Coverage spans every Tier-1 + Tier-2 canonical surface this
        codec also parses on the source side: hostname / domain /
        DNS / NTP / syslog / interfaces (physical, SVI, Loopback,
        Port-channel, Tunnel) / VLANs / static routes / DHCP pools /
        SNMP (v1/v2c + v3) / local users / RADIUS / VRFs.  Anything
        outside the canonical surface (firewall ACLs, QoS policies,
        BGP/OSPF, IKEv2) falls through silently — same convention as
        every other codec.

        Output format mirrors the Cisco wire form an operator would
        paste into a console: `!`-delimited stanzas, dotted-decimal
        netmasks, ``no shutdown``/``shutdown`` on interfaces.
        Ordering is intentionally close to a real ``show running-
        config`` (banner / hostname / users / VRFs / interfaces /
        VLANs / routing / SNMP / etc.) so the diff against a real
        capture stays readable.

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
        from ...canonical.transforms import project_vlan_to_switchport
        project_vlan_to_switchport(tree)

        out: list[str] = []

        # --- header banner ---
        out.append("Building configuration...")
        out.append("")
        out.append("! Generated by netconfig translator (cisco_iosxe_cli)")
        out.append("!")

        # --- service / system globals ---
        out.append("service timestamps debug datetime msec")
        out.append("service timestamps log datetime msec")
        out.append("!")
        if tree.hostname:
            out.append(f"hostname {tree.hostname}")
            out.append("!")
        if tree.domain:
            out.append(f"ip domain name {tree.domain}")
            out.append("!")

        # --- local users ---
        # Cisco form: `username X privilege N secret <type> <hash>`.
        # Canonical hashed_password preserves whatever opaque hash the
        # source emitted.  Same-vendor (Cisco→Cisco) round-trip carries
        # the type-5/9 marker through verbatim; cross-vendor sources
        # (Aruba sha1, FortiGate ENC, OPNsense bcrypt) emit under a
        # generic ``5`` marker — Cisco will reject at config-push but
        # the data is preserved for the operator to reconcile.  Empty
        # password renders ``nopassword`` (legitimate Cisco form).
        for u in tree.local_users:
            parts = [f"username {u.name}"]
            if u.privilege_level and u.privilege_level != 1:
                parts.append(f"privilege {u.privilege_level}")
            if u.role and u.role not in ("admin", "operator"):
                # Cisco supports `role <name>` only on platforms that
                # enabled `aaa new-model` — emit only when the role is
                # non-canonical (admin/operator are derived defaults
                # from privilege; emitting them as roles would be
                # noisy and frequently wrong).
                pass
            if not u.hashed_password:
                parts.append("nopassword")
            else:
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
            if vrf.route_distinguisher:
                out.append(f" rd {vrf.route_distinguisher}")
            if vrf.rt_imports or vrf.rt_exports:
                out.append(" address-family ipv4")
                for rt in vrf.rt_imports:
                    out.append(f"  route-target import {rt}")
                for rt in vrf.rt_exports:
                    out.append(f"  route-target export {rt}")
                out.append(" exit-address-family")
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

        ordered_ifaces = sorted(tree.interfaces, key=_iface_sort_key)
        for iface in ordered_ifaces:
            out.append(f"interface {iface.name}")
            if iface.description:
                out.append(f" description {iface.description}")
            if iface.vrf:
                out.append(f" vrf forwarding {iface.vrf}")
            # IPv4 addresses — Cisco needs dotted-decimal masks.
            for addr in iface.ipv4_addresses:
                mask = _prefix_to_mask(addr.prefix_length)
                out.append(f" ip address {addr.ip} {mask}")
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
                out.append(f" switchport mode {iface.switchport_mode}")
            if iface.access_vlan is not None:
                out.append(
                    f" switchport access vlan {iface.access_vlan}"
                )
            if iface.voice_vlan is not None:
                out.append(
                    f" switchport voice vlan {iface.voice_vlan}"
                )
            if iface.trunk_native_vlan is not None:
                out.append(
                    f" switchport trunk native vlan "
                    f"{iface.trunk_native_vlan}"
                )
            if iface.trunk_allowed_vlans:
                vlan_list = ",".join(
                    str(v) for v in iface.trunk_allowed_vlans
                )
                out.append(
                    f" switchport trunk allowed vlan {vlan_list}"
                )
            if iface.mtu is not None:
                out.append(f" mtu {iface.mtu}")
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
                }.get(mode.lower(), "active")
                if lag_num is not None:
                    out.append(
                        f" channel-group {lag_num} mode {wire_mode}"
                    )
            # Enabled state — Cisco default is ``no shutdown`` so
            # we only emit when explicitly disabled.  Parsers that
            # didn't see ``shutdown`` leave enabled=True.
            if not iface.enabled:
                out.append(" shutdown")
            if iface.dhcp_client:
                out.append(" ip address dhcp")
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

        # --- static routes ---
        for route in tree.static_routes:
            dest, mask = _cidr_to_dest_mask(route.destination)
            tail = ""
            if route.metric and route.metric > 0:
                tail = f" {route.metric}"
            target = route.gateway or route.interface
            if not target:
                continue
            out.append(f"ip route {dest} {mask} {target}{tail}")
        if tree.static_routes:
            out.append("!")

        # --- DHCP server pools ---
        for pool in tree.dhcp_servers:
            pool_name = (pool.interface or pool.network or "POOL").replace(
                "/", "_",
            )
            out.append(f"ip dhcp pool {pool_name}")
            if pool.network:
                net, mask = _cidr_to_dest_mask(pool.network)
                out.append(f" network {net} {mask}")
            if pool.gateway:
                out.append(f" default-router {pool.gateway}")
            for d in pool.dns_servers:
                out.append(f" dns-server {d}")
            if pool.domain_name:
                out.append(f" domain-name {pool.domain_name}")
            if pool.lease_time and pool.lease_time != 86400:
                hours = pool.lease_time // 3600
                out.append(f" lease 0 {hours}")
            out.append("!")

        # --- RADIUS servers ---
        for server in tree.radius_servers:
            out.append(f"radius server {server.host}")
            out.append(f" address ipv4 {server.host} auth-port "
                       f"{server.auth_port} acct-port {server.acct_port}")
            if server.key:
                out.append(f" key {server.key}")
            out.append("!")

        # --- SNMP block ---
        if tree.snmp is not None:
            s = tree.snmp
            if s.community:
                out.append(f"snmp-server community {s.community} RO")
            if s.location:
                out.append(f"snmp-server location {s.location}")
            if s.contact:
                out.append(f"snmp-server contact {s.contact}")
            for host in s.trap_hosts:
                out.append(f"snmp-server host {host}")
            # SNMPv3 USM users.  Cisco syntax pairs auth/priv with
            # the v3 keyword; ``aes128`` canonical → ``aes 128`` two
            # tokens; ``aes192``/``aes256`` similarly split.
            for u in s.v3_users:
                line = [
                    f"snmp-server user {u.name} {u.group or 'v3group'} v3",
                ]
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
            for ln in body.splitlines():
                out.append(ln)
            out.append("!")

        out.append("end")
        return "\n".join(out) + "\n"

    # -----------------------------------------------------------------
    # iter_xpaths — same shape as the NETCONF codec
    # -----------------------------------------------------------------

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        """Yield schema xpaths from a :class:`CanonicalIntent`."""
        if isinstance(tree, CanonicalIntent):
            yield from _walk_canonical(tree)
        elif isinstance(tree, dict):
            # Back-compat fallback for old-shape trees.
            from ..cisco_iosxe.codec import _walk
            yield from _walk(tree, "")

    # -----------------------------------------------------------------
    # Cross-vendor port-name translation
    # -----------------------------------------------------------------

    # -----------------------------------------------------------------
    # Cross-vendor port-name translation
    # -----------------------------------------------------------------
    # Implementation extracted to :mod:`.port_names` (see that
    # module's docstring for the full form-by-form reference).
    # These methods delegate so the codec class stays focused on
    # parse/render.

    def classify_port_name(self, name: str):
        return _port_names.classify_port_name(name)

    def format_port_identity(self, identity) -> str | None:
        return _port_names.format_port_identity(identity)

    # -----------------------------------------------------------------
    # Auto-detection probe (R5)
    # -----------------------------------------------------------------

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Detect Cisco IOS CLI ``show running-config`` text.

        Strong signals (all Cisco-specific; ``show running-config`` is
        intentionally NOT one of them — that phrase is the command
        operators run on Aruba, Arista, and others, so its presence in
        a paste means "this is some vendor's running-config" rather
        than "this is Cisco's running-config"):

          * ``Building configuration...`` banner
          * ``Current configuration : <N> bytes`` banner
          * ``! Last configuration change at ...`` banner line
          * ``service timestamps`` directive (Cisco-specific syntax)
          * ``interface GigabitEthernet`` / ``TenGigabitEthernet`` /
            etc. — Cisco interface naming
          * ``ip address X.X.X.X Y.Y.Y.Y`` (dotted-decimal mask form;
            Aruba uses CIDR ``/24`` form)
          * ``switchport`` mode keyword (Cisco specific)
          * ``no shutdown`` form

        Weaker signals: ``!`` stanza delimiter, leading ``hostname``.
        """
        lowered = raw_prefix.lower()
        # XML or JSON - not IOS CLI.
        stripped = raw_prefix.lstrip()
        if stripped.startswith("<") or stripped.startswith("{"):
            return None

        # If the input carries a recognisable Aruba banner anywhere in
        # the first few KiB, defer to Aruba's probe.  This guards the
        # common paste case where the operator copies a full session
        # transcript including the prompt + `show running-config` echo
        # — the string "show running-config" is the OPERATOR'S
        # COMMAND, not an IOS-specific banner, so reasoning from its
        # presence alone produced false positives.  Aruba's own probe
        # will still claim the input via its own banner match.
        if re.search(
            r"^;\s*(J[A-Z]?\d+[A-Z]*|hpStack_\w+)\s+Configuration",
            raw_prefix, re.MULTILINE,
        ):
            return None

        # Cisco-specific banners — each unambiguous on its own.  The
        # ``show running-config`` echo is now ONLY a confidence
        # multiplier alongside one of these; on its own it's not
        # diagnostic.  See _IOS_BANNER_HITS for the full list.
        cisco_banner_hits = 0
        for pattern, weight in _IOS_BANNER_HITS:
            if pattern in lowered:
                cisco_banner_hits += weight
        if cisco_banner_hits >= 4:
            return (
                98,
                "multiple IOS-specific banners "
                "(Building / Current / Last change / service timestamps)",
            )
        if cisco_banner_hits >= 2:
            return (
                95,
                "IOS-specific banner sequence detected",
            )
        # Strong IOS-shape markers (one enough for medium confidence).
        strong_hits = 0
        if re.search(r"^interface\s+(gigabit|fastether|tengigabit|"
                     r"loopback|vlan|port-channel|tunnel|serial)",
                     raw_prefix, re.IGNORECASE | re.MULTILINE):
            strong_hits += 1
        if re.search(r"^\s+ip\s+address\s+\d+\.\d+\.\d+\.\d+\s+\d+\.",
                     raw_prefix, re.IGNORECASE | re.MULTILINE):
            strong_hits += 1
        if re.search(r"^\s+(no\s+)?shutdown\s*$",
                     raw_prefix, re.IGNORECASE | re.MULTILINE):
            strong_hits += 1
        if re.search(r"^\s+switchport\s+",
                     raw_prefix, re.IGNORECASE | re.MULTILINE):
            strong_hits += 1
        # If the operator's prompt-echo carries ``show running-config``
        # AND we see at least one Cisco-shape structural marker, we
        # have stronger evidence than structure alone.  This is the
        # path that previously fired at 95 on bare ``show running-
        # config`` text.
        if "show running-config" in lowered and strong_hits >= 1:
            return (
                90,
                f"'show running-config' header + "
                f"{strong_hits} IOS structural marker(s)",
            )
        if strong_hits >= 2:
            return (90, f"{strong_hits} strong IOS CLI markers present")
        if strong_hits == 1:
            return (70, "one IOS CLI marker present")
        # Weakest fallback — `hostname` + `!` is plausible IOS but also
        # plausible many other CLI dialects.  Keep the score low.
        if (re.search(r"^hostname\s+\S+", raw_prefix, re.IGNORECASE | re.MULTILINE)
                and "!" in raw_prefix):
            return (45, "leading 'hostname' + '!' delimiters — possible IOS")
        return None


# ---------------------------------------------------------------------------
# CLI parser internals
# ---------------------------------------------------------------------------

_IFACE_RE = re.compile(r"^interface\s+(\S+)", re.IGNORECASE)
_DESC_RE = re.compile(r"^\s+description\s+(.+)", re.IGNORECASE)
_IP_RE = re.compile(
    r"^\s+ip\s+address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)",
    re.IGNORECASE,
)
_SHUTDOWN_RE = re.compile(r"^\s+shutdown\s*$", re.IGNORECASE)
_NO_SHUTDOWN_RE = re.compile(r"^\s+no\s+shutdown\s*$", re.IGNORECASE)
_MTU_RE = re.compile(r"^\s+mtu\s+(\d+)\s*$", re.IGNORECASE)

#: Interface-name prefix → IANA ifType hint.
_TYPE_HINTS: dict[str, str] = {
    "gigabitethernet": "ianaift:ethernetCsmacd",
    "fastethernet": "ianaift:ethernetCsmacd",
    "tengigabitethernet": "ianaift:ethernetCsmacd",
    "twentyfivegige": "ianaift:ethernetCsmacd",
    "fortygigabitethernet": "ianaift:ethernetCsmacd",
    "hundredgige": "ianaift:ethernetCsmacd",
    "ethernet": "ianaift:ethernetCsmacd",
    "loopback": "ianaift:softwareLoopback",
    "vlan": "ianaift:l3ipvlan",
    "port-channel": "ianaift:ieee8023adLag",
    "tunnel": "ianaift:tunnel",
    "bdi": "ianaift:l3ipvlan",
}


def _infer_type(iface_name: str) -> str:
    """Best-effort IANA ifType from the interface name prefix."""
    lower = iface_name.lower()
    for prefix, iftype in _TYPE_HINTS.items():
        if lower.startswith(prefix):
            return iftype
    return "ianaift:other"


def _prefix_to_mask(prefix: int) -> str:
    """Convert a CIDR prefix length to a dotted-decimal subnet mask.

    Inverse of :func:`_mask_to_prefix`.  Used by render() because Cisco
    IOS-XE's ``ip address X Y`` form requires dotted-decimal — every
    other shipped codec uses CIDR natively, so the canonical tree
    holds prefix lengths and we expand on render.
    """
    if not (0 <= prefix <= 32):
        raise RenderError(
            f"cisco_iosxe_cli: prefix length {prefix} out of range",
            yang_path="/interfaces/interface/ipv4/address/prefix-length",
        )
    mask_int = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF if prefix else 0
    return str(ipaddress.IPv4Address(mask_int))


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
    return (dest, _prefix_to_mask(prefix))


def _extract_lag_number(lag_name: str) -> int | None:
    """Pull the numeric tail off a LAG name (``Port-channel10`` → 10,
    ``Trk5`` → 5, ``ae0`` → 0).  Used by render() to emit the
    ``channel-group N mode <X>`` line on member interfaces — Cisco's
    LAG syntax is integer-keyed regardless of the source vendor's
    naming convention.  Returns None for names with no trailing
    digits."""
    m = re.search(r"(\d+)\s*$", lag_name or "")
    if m is None:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


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
    parser captured.  Two recognised input shapes (per the Cisco
    parser convention in :func:`_parse_local_users`):

      * ``"<type-digit> <hash>"`` — produced by Cisco's own parser
        when the source was ``secret <N> <hash>``.  Round-trip case;
        emits verbatim with the captured type preserved.
      * Foreign-vendor hash bytes — Aruba sha1, FortiGate ENC,
        OPNsense bcrypt, etc.  Tag as type-5 (MD5-crypt) so the
        emitted line is syntactically valid Cisco; deploy-time the
        device will reject the foreign hash and the operator
        re-keys.  Same policy as every other codec's
        cross-vendor-hash handling (lossless on canonical, lossy on
        deploy).

    Heuristic detection:

      * Leading ``"<digit> "`` — round-trip form, split on first
        space; honour the captured type.
      * ``$1$...`` — Cisco type-5 raw → emit ``5 $1$...``
      * ``$8$...`` / ``$9$...`` — Cisco type-8/9 raw → emit verbatim
        under their corresponding type digit.
      * Anything else — foreign-vendor hash, tag as type-5.
    """
    if not hashed:
        return ("0", "")
    # Round-trip form ``<digit> <rest>`` (Cisco parser stored
    # ``f"{type} {hash}"`` to preserve the source's type marker).
    if (len(hashed) >= 2 and hashed[0].isdigit() and hashed[1] == " "):
        return (hashed[0], hashed[2:])
    if hashed.startswith("$9$"):
        return ("9", hashed)
    if hashed.startswith("$8$"):
        return ("8", hashed)
    if hashed.startswith("$1$"):
        return ("5", hashed)
    # Foreign-vendor hash — best-effort tag as type-5 so the syntax
    # is valid.  Deploy-time rejection is the intended failure mode.
    return ("5", hashed)


def _mask_to_prefix(mask_str: str) -> int:
    """Convert a dotted-decimal subnet mask to a CIDR prefix length.

    Raises ParseError for non-contiguous masks.
    """
    try:
        addr = ipaddress.IPv4Address(mask_str)
    except ipaddress.AddressValueError:
        raise ParseError(
            f"cisco_iosxe_cli: invalid subnet mask {mask_str!r}",
            snippet=mask_str,
        )
    bits = bin(int(addr))[2:]
    if "01" in bits:
        raise ParseError(
            f"cisco_iosxe_cli: non-contiguous subnet mask {mask_str!r}",
            snippet=mask_str,
        )
    return bits.count("1")


#: Cisco-specific IOS banner / directive substrings used by the
#: detection probe.  Each entry is ``(lowered_substring, weight)``.
#: When the cumulative weight reaches a threshold the probe returns a
#: high-confidence detection.  Curated to be Cisco-unique (Aruba /
#: Arista / Junos do NOT emit any of these strings):
#:
#:   * ``Building configuration...`` — Cisco IOS / IOS-XE banner
#:     emitted by the device when ``show running-config`` runs
#:   * ``Current configuration : <N> bytes`` — second-line Cisco
#:     banner companion to ``Building configuration...``
#:   * ``! Last configuration change at`` — Cisco's commit-history
#:     comment (Aruba uses ``;`` for comments, not ``!``)
#:   * ``service timestamps`` — Cisco-specific top-of-config
#:     directive controlling logging/debug message formatting
#:
#: Each contributes weight 2.  The 95 threshold is "two banners
#: present"; 98 is "all four / kitchen sink".
_IOS_BANNER_HITS: tuple[tuple[str, int], ...] = (
    ("building configuration", 2),
    ("current configuration :", 2),
    ("! last configuration change at", 2),
    ("service timestamps", 2),
)


_HOSTNAME_RE = re.compile(r"^hostname\s+(\S+)", re.IGNORECASE | re.MULTILINE)
_VLAN_RE = re.compile(r"^vlan\s+(\d+)", re.IGNORECASE)
_VLAN_NAME_RE = re.compile(r"^\s+name\s+(.+)", re.IGNORECASE)
_STATIC_ROUTE_RE = re.compile(
    r"^ip\s+route\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s+(\S+)",
    re.IGNORECASE,
)
# ``ip default-gateway X`` is the L2-switch form of a default route.
# Common on Catalyst switches that have no routing enabled — the switch
# itself still needs a gateway for its management SVI.  We map it to the
# same CanonicalStaticRoute shape the Aruba renderer already uses for
# 0.0.0.0/0 destinations.
_DEFAULT_GATEWAY_RE = re.compile(
    r"^ip\s+default-gateway\s+(\d+\.\d+\.\d+\.\d+)",
    re.IGNORECASE,
)
_SWITCHPORT_ACCESS_RE = re.compile(
    r"^\s+switchport\s+access\s+vlan\s+(\d+)", re.IGNORECASE
)
_SWITCHPORT_TRUNK_ALLOWED_RE = re.compile(
    r"^\s+switchport\s+trunk\s+allowed\s+vlan\s+(.+)", re.IGNORECASE
)
_SWITCHPORT_TRUNK_NATIVE_RE = re.compile(
    r"^\s+switchport\s+trunk\s+native\s+vlan\s+(\d+)", re.IGNORECASE
)
_SWITCHPORT_MODE_RE = re.compile(
    r"^\s+switchport\s+mode\s+(\S+)", re.IGNORECASE
)
# ``channel-group N mode M`` declares this physical port as a member of
# LAG ``Port-channelN``.  Cisco's mode vocabulary:
#   active  -> LACP active  (canonical: "active")
#   passive -> LACP passive (canonical: "passive")
#   on      -> static        (canonical: "static")
#   auto/desirable -> PAgP (Cisco-proprietary; we fold to "active")
_CHANNEL_GROUP_RE = re.compile(
    r"^\s+channel-group\s+(\d+)\s+mode\s+(\S+)", re.IGNORECASE,
)
_CISCO_LAG_MODE_MAP = {
    "active": "active",
    "passive": "passive",
    "on": "static",
    "auto": "active",       # PAgP → best-effort equivalent
    "desirable": "active",  # PAgP → best-effort equivalent
}
# ``username NAME privilege N [secret|password] [HASHTYPE] HASH``
# Captures:
#   group 1 = user name
#   group 2 = privilege level (digits; optional — defaults to 1)
#   group 3 = secret/password keyword (drives hash interpretation)
#   group 4 = hash-type digit (optional — Cisco uses 0=plaintext,
#             5=MD5, 7=reversible, 8=PBKDF2, 9=scrypt).  We preserve
#             it verbatim so the target codec can tell a plaintext
#             default from a real hash.
#   group 5 = hash payload itself
# ``secret`` is preferred on IOS-XE (strong hashing); ``password`` is
# legacy + reversible and should trigger a lossy-path warning on
# render targets that refuse weak hashes.
_LOCAL_USER_RE = re.compile(
    r"^username\s+(\S+)"
    r"(?:\s+privilege\s+(\d+))?"
    r"\s+(secret|password)\s+(?:(\d+)\s+)?(\S.*)$",
    re.IGNORECASE,
)


def _extract_hostname(raw: str) -> str:
    m = _HOSTNAME_RE.search(raw)
    return m.group(1) if m else ""


def _parse_interfaces(raw: str) -> list[CanonicalInterface]:
    """Extract interface stanzas from IOS config text."""
    lines = raw.splitlines()
    interfaces: list[CanonicalInterface] = []
    current: dict[str, Any] | None = None

    for line in lines:
        m = _IFACE_RE.match(line)
        if m:
            if current is not None:
                interfaces.append(_build_canonical_interface(current))
            iface_name = m.group(1)
            current = {
                "name": iface_name,
                "description": "",
                "enabled": True,
                "type": _infer_type(iface_name),
                "ipv4": [],
                "switchport_mode": None,
                "access_vlan": None,
                "trunk_allowed": [],
                "trunk_native": None,
                "lag_member_of": None,
                "mtu": None,
            }
            continue

        if current is None:
            continue

        if line.startswith("!") or (line and not line[0].isspace()):
            interfaces.append(_build_canonical_interface(current))
            current = None
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

        im = _IP_RE.match(line)
        if im:
            ip_str = im.group(1)
            mask_str = im.group(2)
            prefix_len = _mask_to_prefix(mask_str)
            if not current["ipv4"]:  # primary only
                current["ipv4"].append({"ip": ip_str, "prefix_length": prefix_len})
            continue

        sm = _SWITCHPORT_MODE_RE.match(line)
        if sm:
            current["switchport_mode"] = sm.group(1).lower()
            continue

        am = _SWITCHPORT_ACCESS_RE.match(line)
        if am:
            current["access_vlan"] = int(am.group(1))
            continue

        tm = _SWITCHPORT_TRUNK_ALLOWED_RE.match(line)
        if tm:
            current["trunk_allowed"] = _parse_vlan_list(tm.group(1).strip())
            continue

        nm = _SWITCHPORT_TRUNK_NATIVE_RE.match(line)
        if nm:
            current["trunk_native"] = int(nm.group(1))
            continue

        cgm = _CHANNEL_GROUP_RE.match(line)
        if cgm:
            current["lag_member_of"] = f"Port-channel{int(cgm.group(1))}"
            continue

    if current is not None:
        interfaces.append(_build_canonical_interface(current))

    return interfaces


def _build_canonical_interface(raw: dict[str, Any]) -> CanonicalInterface:
    """Convert the parse-time dict into a CanonicalInterface."""
    return CanonicalInterface(
        name=raw["name"],
        description=raw.get("description", ""),
        enabled=raw.get("enabled", True),
        interface_type=raw.get("type", ""),
        ipv4_addresses=[
            CanonicalIPv4Address(ip=a["ip"], prefix_length=a["prefix_length"])
            for a in raw.get("ipv4", [])
        ],
        switchport_mode=raw.get("switchport_mode"),
        access_vlan=raw.get("access_vlan"),
        trunk_allowed_vlans=raw.get("trunk_allowed", []),
        trunk_native_vlan=raw.get("trunk_native"),
        lag_member_of=raw.get("lag_member_of"),
        mtu=raw.get("mtu"),
    )


def _parse_vlan_list(text: str) -> list[int]:
    """Parse a Cisco VLAN list like '10,20,30-40' into a flat list of ints."""
    result: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            result.extend(range(int(lo.strip()), int(hi.strip()) + 1))
        elif part.isdigit():
            result.append(int(part))
    return result


def _parse_vlans(raw: str) -> list[CanonicalVlan]:
    """Extract VLAN definitions from IOS config text.

    Looks for ``vlan <id>`` stanzas followed by indented ``name``
    sub-commands.
    """
    lines = raw.splitlines()
    vlans: list[CanonicalVlan] = []
    current_id: int | None = None
    current_name: str = ""

    for line in lines:
        vm = _VLAN_RE.match(line)
        if vm:
            if current_id is not None:
                vlans.append(CanonicalVlan(id=current_id, name=current_name))
            current_id = int(vm.group(1))
            current_name = ""
            continue

        if current_id is not None:
            nm = _VLAN_NAME_RE.match(line)
            if nm:
                current_name = nm.group(1).strip()
                continue
            if line.startswith("!") or (line and not line[0].isspace()):
                vlans.append(CanonicalVlan(id=current_id, name=current_name))
                current_id = None
                current_name = ""

    if current_id is not None:
        vlans.append(CanonicalVlan(id=current_id, name=current_name))

    return vlans


_SVI_NAME_RE = re.compile(r"^Vlan(\d+)$", re.IGNORECASE)


def _synthesize_vlans_from_svis(intent: CanonicalIntent) -> None:
    """Post-parse pass that derives VLAN records from ``interface
    Vlan<N>`` stanzas.

    On Cisco IOS, a VLAN can exist two ways:

    1. Explicit L2 database entry — ``vlan 11 / name Users``
    2. Implicit, via the SVI alone — ``interface Vlan11 / ip address
       X / description Users``

    :func:`_parse_vlans` only catches form (1).  Without this helper
    the L3 data attached to form (2) would get silently dropped by
    any VLAN-centric downstream codec (Aruba, OPNsense) because its
    renderer looks for the IP under ``tree.vlans``, not under the
    ``Vlan<N>`` interface itself.

    Behaviour:
        * SVI with no existing VLAN record → create one with the
          SVI's IPs attached.
        * SVI with an existing VLAN record (matching id) → merge
          the SVI's IPs in.  The top-level stanza's ``name`` wins
          over the SVI's (they're semantically different — VLAN
          name is an L2 tag, SVI description is an L3 interface
          hint — but with no better info we keep whichever came
          first).
        * SVI with no IP (e.g. ``interface Vlan1 / no ip address``)
          still creates/touches a VLAN record so "this VLAN exists"
          is preserved end-to-end.
    """
    existing_by_id: dict[int, CanonicalVlan] = {
        v.id: v for v in intent.vlans
    }
    for iface in intent.interfaces:
        m = _SVI_NAME_RE.match(iface.name)
        if not m:
            continue
        vid = int(m.group(1))
        existing = existing_by_id.get(vid)
        if existing is None:
            synthesised = CanonicalVlan(
                id=vid,
                # SVI description is a reasonable fallback for the
                # VLAN name when no explicit stanza was present.
                name=iface.description,
                ipv4_addresses=list(iface.ipv4_addresses),
            )
            intent.vlans.append(synthesised)
            existing_by_id[vid] = synthesised
            continue
        # Merge SVI IPs into existing VLAN record.  De-dupe in case
        # the same IP was declared both places.
        for addr in iface.ipv4_addresses:
            if addr not in existing.ipv4_addresses:
                existing.ipv4_addresses.append(addr)


def _parse_lags(raw: str, intent: CanonicalIntent) -> list[CanonicalLAG]:
    """Build :class:`CanonicalLAG` records from Cisco CLI.

    Sources of truth in a Cisco config:
      * ``interface Port-channelN`` stanza declares the LAG exists
        (and carries the LAG's description / switchport / IP state
        via the existing interface parse path — that's already on
        ``intent.interfaces``).
      * ``channel-group N mode M`` under a physical interface declares
        that physical port a member of Port-channelN.

    A LAG must exist if EITHER signal is present (Cisco allows defining
    Port-channelN explicitly OR lazily via member channel-group lines).

    Mode is whatever the members agree on; if members disagree, the
    first member's mode wins (rare in practice, but pathological
    configs shouldn't crash us).  If no physical members exist (empty
    LAG stanza), mode defaults to ``CanonicalLAG.mode`` default.
    """
    # Scan: for each `interface X` stanza, note its channel-group (if any).
    members_by_lag: dict[str, list[str]] = {}
    mode_by_lag: dict[str, str] = {}
    declared_lag_names: set[str] = set()

    current_iface: str | None = None
    for line in raw.splitlines():
        m = _IFACE_RE.match(line)
        if m:
            current_iface = m.group(1)
            if current_iface.lower().startswith("port-channel"):
                declared_lag_names.add(current_iface)
            continue
        if current_iface is None:
            continue
        if line.startswith("!") or (line and not line[0].isspace()):
            current_iface = None
            continue
        cgm = _CHANNEL_GROUP_RE.match(line)
        if cgm:
            lag_name = f"Port-channel{int(cgm.group(1))}"
            cisco_mode = cgm.group(2).lower()
            canonical_mode = _CISCO_LAG_MODE_MAP.get(cisco_mode, "active")
            # Real configs (and Batfish's grammar-kitchen-sink fixtures)
            # can stack multiple `channel-group N mode M` lines on a
            # single physical interface — either as a historical artefact
            # of mode changes or as test-config variants.  Dedupe so the
            # member list has one entry per physical port.
            members = members_by_lag.setdefault(lag_name, [])
            if current_iface not in members:
                members.append(current_iface)
            # First member's mode wins.
            mode_by_lag.setdefault(lag_name, canonical_mode)

    all_lag_names = declared_lag_names | set(members_by_lag)
    lags: list[CanonicalLAG] = []
    for lag_name in sorted(all_lag_names, key=_lag_sort_key):
        lag = CanonicalLAG(
            name=lag_name,
            members=list(members_by_lag.get(lag_name, [])),
        )
        if lag_name in mode_by_lag:
            lag.mode = mode_by_lag[lag_name]
        lags.append(lag)
    return lags


def _lag_sort_key(name: str) -> tuple[str, int, str]:
    """Stable sort key that groups ``Port-channel<N>`` numerically."""
    m = re.match(r"^(port-channel|trk|bond|lag|lagg)(\d+)$", name, re.IGNORECASE)
    if m:
        return (m.group(1).lower(), int(m.group(2)), "")
    return ("", 0, name)


def _parse_static_routes(raw: str) -> list[CanonicalStaticRoute]:
    """Extract ``ip route`` and ``ip default-gateway`` lines from IOS config text."""
    routes: list[CanonicalStaticRoute] = []
    for line in raw.splitlines():
        m = _STATIC_ROUTE_RE.match(line)
        if m:
            dest_ip = m.group(1)
            mask = m.group(2)
            gw_or_iface = m.group(3)
            prefix_len = _mask_to_prefix(mask)
            dest = f"{dest_ip}/{prefix_len}"
            # Gateway could be an IP or an interface name.
            gateway = ""
            iface = ""
            try:
                ipaddress.IPv4Address(gw_or_iface)
                gateway = gw_or_iface
            except ipaddress.AddressValueError:
                iface = gw_or_iface
            routes.append(CanonicalStaticRoute(
                destination=dest,
                gateway=gateway,
                interface=iface,
            ))
            continue
        m = _DEFAULT_GATEWAY_RE.match(line)
        if m:
            # ``ip default-gateway X`` -> 0.0.0.0/0 via X.  Aruba's
            # renderer re-collapses this back to the native
            # ``ip default-gateway`` form.
            routes.append(CanonicalStaticRoute(
                destination="0.0.0.0/0",
                gateway=m.group(1),
            ))
    return routes


def _walk_canonical(intent: CanonicalIntent) -> Iterable[str]:
    """Yield schema xpaths from a CanonicalIntent for validation."""
    if intent.hostname:
        yield "/system/hostname"
    for _ in intent.dns_servers:
        yield "/system/dns-server"
    for _ in intent.ntp_servers:
        yield "/system/ntp-server"
    for iface in intent.interfaces:
        yield "/interfaces/interface/name"
        if iface.description:
            yield "/interfaces/interface/config/description"
        yield "/interfaces/interface/config/enabled"
        if iface.interface_type:
            yield "/interfaces/interface/config/type"
        for _ in iface.ipv4_addresses:
            yield "/interfaces/interface/ipv4/address/ip"
            yield "/interfaces/interface/ipv4/address/prefix-length"
    for _ in intent.vlans:
        yield "/vlans/vlan/id"
        yield "/vlans/vlan/name"
    for _ in intent.static_routes:
        yield "/routing/static-route"
    # Tier 2 — emit only what's populated
    if intent.snmp is not None:
        if intent.snmp.community:
            yield "/snmp/community"
        if intent.snmp.location:
            yield "/snmp/location"
        if intent.snmp.contact:
            yield "/snmp/contact"
        for _ in intent.snmp.trap_hosts:
            yield "/snmp/trap-host"
        for _ in intent.snmp.v3_users:
            yield "/snmp/v3-user"


# -- SNMP parse helpers (shared via re-export for sibling codecs if needed)

_SNMP_COMMUNITY_RE = re.compile(
    r'^snmp-server\s+community\s+(\S+)', re.IGNORECASE | re.MULTILINE,
)
_SNMP_LOCATION_RE = re.compile(
    r'^snmp-server\s+location\s+(.+)$', re.IGNORECASE | re.MULTILINE,
)
_SNMP_CONTACT_RE = re.compile(
    r'^snmp-server\s+contact\s+(.+)$', re.IGNORECASE | re.MULTILINE,
)
_SNMP_HOST_RE = re.compile(
    r'^snmp-server\s+host\s+(\d+\.\d+\.\d+\.\d+)',
    re.IGNORECASE | re.MULTILINE,
)
# SNMPv3 user line.  Canonical shape on Cisco IOS-XE CLI:
#
#   snmp-server user <name> <group> v3 [auth {md5|sha} <pass>]
#                                     [priv {des|3des|aes {128|192|256}} <pass>]
#
# The ``auth`` and ``priv`` clauses are both optional (noAuthNoPriv
# is expressible).  ``priv aes 128/192/256`` uses two tokens for the
# cipher; every other cipher name is a single token.  The pre-hashed
# form ``auth sha <encrypted_hex> encrypted`` is captured verbatim via
# lazy greedy match — the operator's ``encrypted`` trailer lands in
# the passphrase bucket and round-trips back out on render.
_SNMP_V3_USER_RE = re.compile(
    r"^snmp-server\s+user\s+(\S+)\s+(\S+)\s+v3"
    r"(?:\s+auth\s+(md5|sha|sha224|sha256|sha384|sha512)\s+(\S+))?"
    r"(?:\s+priv\s+(des|3des|aes)(?:\s+(128|192|256))?\s+(\S+))?"
    r"\s*$",
    re.IGNORECASE | re.MULTILINE,
)


_DHCP_POOL_HEADER_RE = re.compile(
    r"^ip\s+dhcp\s+pool\s+(\S+)", re.IGNORECASE,
)
_DHCP_NETWORK_RE = re.compile(
    r"^\s+network\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)",
    re.IGNORECASE,
)
_DHCP_DEFAULT_ROUTER_RE = re.compile(
    r"^\s+default-router\s+(\d+\.\d+\.\d+\.\d+)",
    re.IGNORECASE,
)
_DHCP_DNS_SERVER_RE = re.compile(
    r"^\s+dns-server\s+(.+)$", re.IGNORECASE,
)
_DHCP_DOMAIN_NAME_RE = re.compile(
    r"^\s+domain-name\s+(\S+)", re.IGNORECASE,
)
# Cisco lease syntax: `lease <days> [hours] [minutes]` or `lease infinite`
_DHCP_LEASE_RE = re.compile(
    r"^\s+lease\s+(\S+)(?:\s+(\d+))?(?:\s+(\d+))?", re.IGNORECASE,
)


def _parse_dhcp_pools(raw: str) -> list[CanonicalDHCPPool]:
    """Extract ``ip dhcp pool`` stanzas into CanonicalDHCPPool records.

    Cisco pools are defined as a named stanza with indented sub-commands.
    Each pool defines one network and its associated options.  Real
    configs commonly have multiple pools (one per user VLAN).

    Cisco DHCP doesn't use start/end IP ranges natively — instead, the
    pool serves ALL non-excluded IPs in the ``network`` statement, and
    ``ip dhcp excluded-address`` at the global level carves out
    reservations.  We populate ``network`` from the pool stanza and
    leave ``start_ip``/``end_ip`` empty; a future pass can derive them
    from excluded-address lines if needed.
    """
    pools: list[CanonicalDHCPPool] = []
    current: CanonicalDHCPPool | None = None

    for line in raw.splitlines():
        header = _DHCP_POOL_HEADER_RE.match(line)
        if header:
            if current is not None:
                pools.append(current)
            current = CanonicalDHCPPool()
            continue
        if current is None:
            continue
        if line.startswith("!") or (line and not line[0].isspace()):
            pools.append(current)
            current = None
            continue

        nm = _DHCP_NETWORK_RE.match(line)
        if nm:
            ip_str, mask = nm.group(1), nm.group(2)
            prefix = _mask_to_prefix(mask)
            current.network = f"{ip_str}/{prefix}"
            continue
        gm = _DHCP_DEFAULT_ROUTER_RE.match(line)
        if gm:
            current.gateway = gm.group(1)
            continue
        dm = _DHCP_DNS_SERVER_RE.match(line)
        if dm:
            # Cisco allows multiple DNS servers space-separated.
            servers = dm.group(1).split()
            current.dns_servers.extend(servers)
            continue
        dnm = _DHCP_DOMAIN_NAME_RE.match(line)
        if dnm:
            current.domain_name = dnm.group(1)
            continue
        lm = _DHCP_LEASE_RE.match(line)
        if lm:
            lease_val = lm.group(1).lower()
            if lease_val == "infinite":
                # Max uint32 seconds is DHCP's "infinite" marker.
                current.lease_time = 0xFFFFFFFF
            else:
                try:
                    days = int(lease_val)
                    hours = int(lm.group(2) or 0)
                    minutes = int(lm.group(3) or 0)
                    current.lease_time = (
                        days * 86400 + hours * 3600 + minutes * 60
                    )
                except ValueError:
                    pass  # Unparseable; leave default

    if current is not None:
        pools.append(current)
    return pools


# Modern IOS-XE RADIUS: named stanza
#   radius server <name>
#    address ipv4 <ip> auth-port <N> acct-port <N>
#    key [7] <secret>
_RADIUS_SERVER_HEADER_RE = re.compile(
    r"^radius\s+server\s+(\S+)", re.IGNORECASE,
)
_RADIUS_ADDRESS_RE = re.compile(
    r"^\s+address\s+ipv4\s+(\d+\.\d+\.\d+\.\d+)"
    r"(?:\s+auth-port\s+(\d+))?"
    r"(?:\s+acct-port\s+(\d+))?",
    re.IGNORECASE,
)
_RADIUS_KEY_RE = re.compile(
    r"^\s+key\s+(?:(\d+)\s+)?(\S.*)$",
    re.IGNORECASE,
)
# Legacy IOS: single line
#   radius-server host <ip> [auth-port <N>] [acct-port <N>] [key <secret>]
_RADIUS_HOST_LEGACY_RE = re.compile(
    r"^radius-server\s+host\s+(\d+\.\d+\.\d+\.\d+)"
    r"(?:\s+auth-port\s+(\d+))?"
    r"(?:\s+acct-port\s+(\d+))?"
    r"(?:\s+key\s+(?:\d+\s+)?(\S+.*))?",
    re.IGNORECASE,
)


def _parse_radius_servers(raw: str) -> list[CanonicalRADIUSServer]:
    """Extract RADIUS server definitions from IOS CLI text.

    Handles both the modern named-stanza form (``radius server NAME`` /
    ``address ipv4 ...`` / ``key ...``) and the legacy one-liner
    (``radius-server host X auth-port N key SECRET``).
    """
    servers: list[CanonicalRADIUSServer] = []
    current: CanonicalRADIUSServer | None = None

    for line in raw.splitlines():
        # Modern header opens a new stanza.
        header = _RADIUS_SERVER_HEADER_RE.match(line)
        if header:
            if current is not None and current.host:
                servers.append(current)
            current = CanonicalRADIUSServer(host="")
            continue

        # Legacy single-line form.
        legacy = _RADIUS_HOST_LEGACY_RE.match(line)
        if legacy:
            # Flush any in-progress modern stanza before recording legacy.
            if current is not None and current.host:
                servers.append(current)
                current = None
            host = legacy.group(1)
            auth_port = int(legacy.group(2) or 1812)
            acct_port = int(legacy.group(3) or 1813)
            key = (legacy.group(4) or "").strip()
            servers.append(CanonicalRADIUSServer(
                host=host,
                auth_port=auth_port,
                acct_port=acct_port,
                key=key,
            ))
            continue

        if current is None:
            continue

        # Modern-stanza body.
        if line.startswith("!") or (line and not line[0].isspace()):
            if current.host:
                servers.append(current)
            current = None
            continue
        am = _RADIUS_ADDRESS_RE.match(line)
        if am:
            current.host = am.group(1)
            if am.group(2):
                current.auth_port = int(am.group(2))
            if am.group(3):
                current.acct_port = int(am.group(3))
            continue
        km = _RADIUS_KEY_RE.match(line)
        if km:
            key_type = km.group(1) or ""
            key_val = km.group(2).strip()
            # Preserve the type digit prefix so a lossless render
            # back to Cisco can reconstruct it; other codecs can
            # strip the prefix.
            current.key = f"{key_type} {key_val}" if key_type else key_val

    if current is not None and current.host:
        servers.append(current)
    return servers


def _parse_local_users(raw: str) -> list[CanonicalLocalUser]:
    """Extract ``username NAME privilege N secret|password ...`` lines.

    Cisco IOS privilege scale is 1-15 (15 = full admin).  We map that
    to CanonicalLocalUser.privilege_level verbatim and set the
    canonical ``role`` to ``admin`` for privilege 15, ``operator`` for
    anything else — gives VLAN-centric target codecs (Aruba AOS-S
    manager/operator distinction) a deterministic mapping without
    guessing.

    Hashed passwords are preserved verbatim including the Cisco
    type-digit prefix (``5 $1$..``, ``7 091C08``, ``9 $9$..``) so a
    lossless round-trip back to a Cisco target can reconstruct the
    original command.  Other codecs that render plaintext or BCrypt
    hashes can reject these as lossy.
    """
    users: list[CanonicalLocalUser] = []
    seen_names: set[str] = set()
    for line in raw.splitlines():
        m = _LOCAL_USER_RE.match(line)
        if not m:
            continue
        name = m.group(1)
        # Cisco sometimes emits multiple lines per user (e.g. adding
        # ssh pubkeys).  Dedupe by name — first wins.
        if name in seen_names:
            continue
        seen_names.add(name)
        privilege_str = m.group(2)
        privilege = int(privilege_str) if privilege_str else 1
        kw = m.group(3).lower()          # "secret" or "password"
        hash_type = m.group(4) or ""
        hash_payload = m.group(5).strip()
        # Preserve the type digit as part of the opaque hash so the
        # target codec's render can reconstruct if needed.
        if hash_type:
            hashed = f"{hash_type} {hash_payload}"
        else:
            hashed = hash_payload
        # Annotate reversible-type-7 secrets so downstream codecs can
        # warn / refuse.  A `password 7 ...` or `secret 7 ...` is
        # weak and should be flagged.
        if kw == "password":
            # `password` keyword implies legacy weak encoding unless
            # explicitly typed strong.  We just carry it through; the
            # render side can decide policy.
            pass
        users.append(CanonicalLocalUser(
            name=name,
            privilege_level=privilege,
            hashed_password=hashed,
            role="admin" if privilege == 15 else "operator",
        ))
    return users


def _parse_snmp(raw: str) -> CanonicalSNMP | None:
    """Extract SNMP server config from IOS CLI text.

    Returns None when no snmp-server lines are present so the
    downstream canonical tree doesn't carry an empty stub.
    """
    community_m = _SNMP_COMMUNITY_RE.search(raw)
    location_m = _SNMP_LOCATION_RE.search(raw)
    contact_m = _SNMP_CONTACT_RE.search(raw)
    hosts = _SNMP_HOST_RE.findall(raw)
    # SNMPv3 users — each match is (name, group, auth_proto, auth_pass,
    # priv_proto, priv_keybits, priv_pass).  Last three are empty when
    # the user is auth-no-priv; middle two empty when no-auth-no-priv.
    v3_matches = list(_SNMP_V3_USER_RE.finditer(raw))
    if not (community_m or location_m or contact_m or hosts or v3_matches):
        return None
    from ...canonical.intent import CanonicalSNMPv3User  # lazy local import
    snmp = CanonicalSNMP()
    if community_m:
        snmp.community = community_m.group(1).strip()
    if location_m:
        snmp.location = location_m.group(1).strip().strip('"')
    if contact_m:
        snmp.contact = contact_m.group(1).strip().strip('"')
    snmp.trap_hosts = list(hosts)
    for m in v3_matches:
        name, group, auth_p, auth_pw, priv_p, priv_bits, priv_pw = m.groups()
        # Cisco spells ``aes 128`` / ``aes 192`` / ``aes 256`` as two
        # tokens; canonicalise to the single-token form.  ``3des`` /
        # ``des`` are single tokens; preserved.  Missing priv_bits
        # with ``aes`` falls back to aes128 (Cisco default).
        if priv_p and priv_p.lower() == "aes":
            priv_p_norm = f"aes{priv_bits}" if priv_bits else "aes128"
        elif priv_p:
            priv_p_norm = priv_p.lower()
        else:
            priv_p_norm = ""
        snmp.v3_users.append(CanonicalSNMPv3User(
            name=name,
            group=group,
            auth_protocol=(auth_p or "").lower(),
            auth_passphrase=auth_pw or "",
            priv_protocol=priv_p_norm,
            priv_passphrase=priv_pw or "",
        ))
    return snmp
