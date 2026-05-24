"""
Canonical Intent Dict — the shared tree shape for cross-vendor translation.

Every codec's ``parse()`` emits this shape; every codec's ``render()``
consumes it.  This module defines the schema as pydantic models so the
shape is documented, validated, and JSON-serialisable.

Design principles (from vendor-config-research.txt):

1.  **VLAN-centric membership.**  VLANs carry their port lists (tagged /
    untagged), NOT the other way around.  Aruba AOS-S and OPNsense work
    this way natively; Cisco's per-interface ``switchport`` assignment
    gets transposed on parse.

2.  **Opaque interface IDs.**  Each vendor uses a different naming scheme
    (``GigabitEthernet0/0/0``, ``port1``, ``em0``, ``ether1``, ``1``).
    The canonical dict stores the vendor-native name as-is; mapping
    between naming schemes is the ``rename_interfaces`` transform's job.

3.  **Tier-tagged sections.**  Each top-level section declares its
    translation tier (1 = auto-translatable, 2 = needs-review,
    3 = informational-only).  The pipeline uses this to drive the
    validation report and the UI's "MANUAL REVIEW REQUIRED" banner.

4.  **Lossless round-trip within a vendor.**  ``parse(render(tree)) == tree``
    for the supported subset.  Cross-vendor translation is inherently
    lossy (different feature sets); the canonical dict preserves
    everything the source had so the loss is visible in the report,
    not hidden.

Scope (Tier 1 — auto-translatable):
    hostname, domain, dns_servers, ntp_servers, timezone, syslog_servers,
    interfaces (name, description, enabled, ipv4 + ipv6 addresses, vrf
    binding), vlans (id, name, port membership), static_routes.

Scope (Tier 2 — auto-translate with review banner):
    dhcp_servers, snmp, lags, local_users, radius_servers, vxlan_vnis,
    evpn_type5_routes, routing_instances.

Scope (Tier 3 — parse for display, never auto-render):
    firewall_rules, nat_rules, vpn, routing_protocols (informational).
    Per-codec parsers ALSO surface a ``dropped_tier3_sections`` list on
    :class:`CanonicalIntent` — best-effort heuristic detection of
    Tier-3 stanza headers in the source bytes (see
    :mod:`netcanon.migration._tier3_detection`).  This is a notification
    surface only: the migrate page renders it as a "detected but not
    translated" banner so operators see what was silently dropped.  It
    is NEVER read by render-side code or any transform.

Schema extensions (ship-before-wire):
    ``vxlan_vnis`` and ``evpn_type5_routes`` are top-level Tier 2 lists
    added to support EVPN-VXLAN fabric migrations (Arista ↔ NX-OS ↔
    Junos).  ``routing_instances`` + :attr:`CanonicalInterface.vrf`
    are the cross-vendor VRF primitive (Junos ``routing-instances``,
    Cisco ``vrf definition``, Arista ``vrf instance``).  No codec
    populates any of these in v1 — each codec's
    :class:`CapabilityMatrix` lists them under ``unsupported`` until
    wired up.  This lets the UI's Unsupported-path banner surface the
    gap even before any codec knows how to parse the bytes.

Schema extensions (wire-through in same commit as schema):
    :class:`CanonicalSNMPv3User` + :attr:`CanonicalSNMP.v3_users`
    — the SNMPv3 User-based Security Model surface.  Wired on every
    bidirectional codec that has a documented v3 grammar (Arista
    EOS, Aruba AOS-S, FortiGate, MikroTik RouterOS, Juniper Junos)
    as well as the Cisco IOS-XE CLI parse-only codec.  OPNsense's
    SNMPv3 story is Tier-3 (raw ``snmpd.conf`` snippet) and not in
    scope; its capability matrix lists ``/snmp/v3-user`` as
    unsupported.  Rename surface (fifth per-pane category) lives
    in :mod:`netcanon.migration.canonical.snmpv3_user_names`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Tier 1 — auto-translatable
# ---------------------------------------------------------------------------


class CanonicalIPv4Address(BaseModel):
    """A single IPv4 address + prefix on an interface (Tier 1 — auto-translatable IP primitive).

    Attributes:
        ip: Dotted-quad form (e.g. ``"10.1.1.1"``).
        prefix_length: Subnet prefix length (0-32).
        is_secondary: True if this address is a secondary (additional)
            address on the interface rather than the primary.  Cisco /
            Arista mark these with a ``secondary`` trailer; Junos
            permits multiple ``family inet address`` lines per unit.
            ``False`` for the primary address (the common case).
            Ship-before-wire (v0.2.0) — codecs that haven't been
            updated still treat all addresses as primary.
        virtual_gateway_address: Anycast-gateway virtual IP companion
            to this address.  Junos ``family inet address X/M
            virtual-gateway-address Y`` and Arista VARP
            (``ip address virtual Y/M``) populate this with ``Y``;
            NX-OS DAG ``ip address X/M anycast`` mirrors the address
            into this field (``X == virtual_gateway_address``).
            Empty string means no anycast companion.  Ship-before-
            wire (v0.2.0) — every codec's ``CapabilityMatrix`` lists
            ``/interfaces/interface/ipv4/address/virtual-gateway-
            address`` as ``unsupported`` until the per-codec wire-
            up lands.  Anycast is a sibling concept to VRRP
            (:class:`CanonicalVRRPGroup`) and lives on the address
            record because it is a property of the IP, not a
            router-group election — see ``docs/v0.2.0-planning/``
            for the design rationale.
        virtual_gateway_mac: Optional MAC override for the anycast
            gateway.  Junos per-unit ``virtual-gateway-v4-mac``
            populates this; system-wide MAC overrides (Arista
            ``ip virtual-router mac-address``, NX-OS
            ``fabric forwarding anycast-gateway-mac``) cascade into
            every address record on parse and hoist back to the
            top-level :attr:`CanonicalIntent.anycast_gateway_mac` on
            render.  Empty string means "use vendor default".
    """

    ip: str
    prefix_length: int = Field(ge=0, le=32)
    is_secondary: bool = False
    virtual_gateway_address: str = ""
    virtual_gateway_mac: str = ""


class CanonicalIPv6Address(BaseModel):
    """Single IPv6 address declaration on a CanonicalInterface (Tier 1 — auto-translatable IP primitive).

    Mirrors the :class:`CanonicalIPv4Address` shape; differs only in
    the address type (RFC 4291 colon-hex form rather than dotted-quad)
    and the optional ``scope`` discriminator that distinguishes
    global / link-local addresses on the wire.

    Attributes:
        ip: Address in RFC 4291 colon-hex form (e.g.
            ``"2001:db8::1"``, ``"fe80::1"``).  No prefix-length
            suffix here; that lives on ``prefix_length``.
        prefix_length: Subnet prefix length (0-128).
        scope: Address scope discriminator.  ``"global"`` (the
            default) for routable addresses; ``"link-local"`` for
            ``fe80::/10`` addresses that must not leave the
            attached link.  Vendors emit link-local explicitly via
            different keywords (Cisco / Arista ``link-local``,
            Junos ``family inet6 address X/Y`` then auto-detect by
            prefix); the canonical model normalises to this enum.
        is_secondary: True if this address is a secondary address
            (Cisco / Arista trailer; Junos multi-address per unit).
            See :attr:`CanonicalIPv4Address.is_secondary`.
        virtual_gateway_address: IPv6 anycast-gateway companion.
            Junos ``family inet6 address X/M virtual-gateway-
            address Y`` populates this.  Empty string = no anycast
            companion.  Ship-before-wire (v0.2.0).  See
            :attr:`CanonicalIPv4Address.virtual_gateway_address`.
        virtual_gateway_mac: Optional MAC override; Junos per-unit
            ``virtual-gateway-v6-mac`` populates this.  See
            :attr:`CanonicalIPv4Address.virtual_gateway_mac`.
    """

    ip: str
    prefix_length: int = Field(ge=0, le=128)
    scope: str = "global"  # 'global' | 'link-local'
    is_secondary: bool = False
    virtual_gateway_address: str = ""
    virtual_gateway_mac: str = ""


class CanonicalInterface(BaseModel):
    """A network interface — physical, VLAN SVI, LAG, loopback, tunnel (Tier 1 — auto-translatable cross-vendor primitive).

    Attributes:
        name: Vendor-native name (opaque).  For renamed MikroTik ports
            this is the renamed name (e.g. ``"Access Point"``), not the
            factory default (``ether2``).
        default_name: MikroTik factory default-name (``ether1``,
            ``sfp-sfpplus1``) — used by the renderer to emit the
            ``set [ find default-name=X ]`` lookup.  Empty for vendors
            / interface types where the concept doesn't apply.
        description: Free-text interface description.
        enabled: ``True`` if the interface is administratively up.
        interface_type: IANA-ifType discriminator (e.g.
            ``"ethernetCsmacd"``, ``"softwareLoopback"``).
        mtu: Interface MTU in bytes; ``None`` = use vendor default.
        ipv4_addresses: IPv4 address records on this interface.
        ipv6_addresses: IPv6 address records on this interface.
        switchport_mode: Switchport state.  ``"access"`` | ``"trunk"`` |
            ``None`` (means "not a switchport" — routed port).
        access_vlan: VLAN ID for access mode.
        trunk_allowed_vlans: VLAN IDs allowed on trunk.
        trunk_native_vlan: Native (untagged) VLAN ID on trunk.
        voice_vlan: Voice VLAN ID for IP phone traffic.
        lag_member_of: LAG / port-channel name if this interface is
            bundled, otherwise ``None``.
        dhcp_client: ``True`` if the interface acquires its IPv4 via
            DHCP rather than static configuration.
        dhcp_client_v6: IPv6 dynamic-address mode.  ``""`` = static /
            unset; otherwise one of:

            * ``"dhcp6"`` — stateful DHCPv6
            * ``"slaac"`` — router-advert autoconfiguration
            * ``"track6"`` — OPNsense ``track interface``
            * ``"6rd"`` — RFC 5969 6rd tunnel
            * ``"6to4"`` — RFC 3056 6to4 tunnel

            OPNsense surfaces every value via ``<ipaddrv6>``; Cisco
            IOS-XE / Arista EOS populate ``"dhcp6"`` from ``ipv6
            address dhcp`` and ``"slaac"`` from ``ipv6 address
            autoconfig``; Junos populates ``"dhcp6"`` from ``family
            inet6 dhcpv6-client``; FortiGate populates from ``set
            ip6-mode``; MikroTik RouterOS populates from ``/ipv6
            dhcp-client``.  String literal (not enum) to keep the
            schema simple and round-trip-safe; valid values are
            documented here.
        tunnel_type: Tunnel encapsulation discriminator for vendor-
            specific tunnel sub-types.  ``""`` = unset (renderers
            fall back to a sensible default, typically GRE);
            otherwise one of:

            * ``"gre"`` — RFC 2784 GRE
            * ``"eoip"`` — MikroTik Ethernet-over-IP
            * ``"ipip"`` — RFC 2003 IP-in-IP
            * ``"ipsec"`` — transport-mode IPsec tunnel
            * ``"vxlan"`` — RFC 7348

            Disambiguates which RouterOS section the MikroTik render
            emits (``/interface gre`` vs ``/interface eoip`` vs
            ``/interface ipip``); Cisco IOS-XE / Arista populate
            from ``tunnel mode {gre ip|ipip|ipsec|vxlan}``; Junos
            populates from interface-name prefix (``gr-`` → gre,
            ``ip-`` → ipip, ``st0`` → ipsec).  Only meaningful when
            ``interface_type == 'ianaift:tunnel'``.
        vrf: VRF / routing-instance membership; empty = global /
            default VRF.  Matches a
            :attr:`CanonicalRoutingInstance.name` declared at the
            top level.
        kind: Logical role override.  ``""`` (default) means "infer
            from name via the codec's ``classify_port_name``"; any
            other value (matches :data:`PortKind`) overrides the
            inferred kind during cross-vendor port-name translation.
            Used when the source vendor encodes the role in CONTEXT
            rather than in the interface name — e.g. Cisco IOS-XE
            ``GigabitEthernet0/0`` with ``vrf forwarding Mgmt-vrf``
            is semantically a mgmt port, but the name alone
            classifies as ``physical``.  The parser sets
            ``kind="mgmt"`` so the rename mesh can cascade to every
            target's existing kind=mgmt handling (Aruba ``oobm``
            block, Junos management VRF, etc).
        vrrp_groups: Ship-before-wire (v0.2.0).  Classic FHRP
            redundancy groups (VRRP / HSRP / CARP) on this
            interface.  Anycast-gateway is NOT here — it lives on
            :attr:`CanonicalIPv4Address.virtual_gateway_address`
            (anycast is an IP property, not a router-group
            election).  See :class:`CanonicalVRRPGroup` for full
            grammar / cross-vendor mapping.  Codecs without per-
            codec wire-up still declare ``/interfaces/interface/
            vrrp-groups/group`` as ``unsupported`` in their
            CapabilityMatrix.
    """

    name: str
    default_name: str = ""
    description: str = ""
    enabled: bool = True
    interface_type: str = ""
    mtu: int | None = None
    ipv4_addresses: list[CanonicalIPv4Address] = Field(default_factory=list)
    ipv6_addresses: list[CanonicalIPv6Address] = Field(default_factory=list)
    switchport_mode: str | None = None
    access_vlan: int | None = None
    trunk_allowed_vlans: list[int] = Field(default_factory=list)
    trunk_native_vlan: int | None = None
    voice_vlan: int | None = None
    lag_member_of: str | None = None
    dhcp_client: bool = False
    dhcp_client_v6: str = ""
    tunnel_type: str = ""
    vrf: str = ""
    kind: str = ""
    vrrp_groups: list[CanonicalVRRPGroup] = Field(default_factory=list)


class CanonicalVlan(BaseModel):
    """A VLAN definition with membership (Tier 1 — auto-translatable L2 primitive).

    Membership is VLAN-centric (which ports are in this VLAN) per the
    canonical convention — see module docstring.
    """

    id: int = Field(ge=1, le=4094)
    name: str = ""
    description: str = ""
    # Port lists use vendor-native interface names (opaque strings).
    tagged_ports: list[str] = Field(default_factory=list)
    untagged_ports: list[str] = Field(default_factory=list)
    # SVI addressing (the VLAN interface's L3 config).
    ipv4_addresses: list[CanonicalIPv4Address] = Field(default_factory=list)


class CanonicalStaticRoute(BaseModel):
    """A single static route entry (Tier 1 — auto-translatable routing primitive).

    Attributes:
        destination: CIDR notation: "10.0.0.0/24" or "0.0.0.0/0".
        gateway: Next-hop IP; empty for connected/blackhole.
        interface: Outgoing interface name (vendor-native).
        metric: Administrative distance / metric.
        description: Operator-supplied description (Cisco ``ip route
            ... name X``, Junos ``static route ... description X``).
        vrf: VRF / routing-instance the route belongs to.  Empty
            string = global routing table (the common case).
            Populated by codecs that emit per-VRF static routes
            (Cisco IOS-XE ``ip route vrf <NAME> ...``, Junos
            ``set routing-instances <NAME> routing-options static
            route ...``, NX-OS ``vrf context <NAME> / ip route
            ...``).  Ship-before-wire (v0.2.0) — codecs without the
            wire-up still emit all routes with ``vrf=""`` and
            declare the per-VRF surface ``unsupported`` in their
            capability matrix until updated.  Adding this field
            also closes the existing IOS-XE ``/routing-instances/
            instance`` lossy declaration's per-VRF-static-route
            sub-surface.
    """

    destination: str
    gateway: str = ""
    interface: str = ""
    metric: int = 0
    description: str = ""
    vrf: str = ""


# ---------------------------------------------------------------------------
# Tier 2 — auto-translate with review banner
# ---------------------------------------------------------------------------


class CanonicalDHCPPool(BaseModel):
    """A DHCP server pool (Tier 2 — translate-with-review; cross-vendor option grammar diverges).

    Attributes:
        interface: Interface serving this pool.
        network: Subnet served, in CIDR form (e.g.
            ``"192.168.10.0/24"``).
        start_ip: First IP in the dynamic range.
        end_ip: Last IP in the dynamic range.
        gateway: Default gateway advertised to clients.
        dns_servers: DNS resolvers advertised to clients.
        lease_time: Lease duration in seconds (default 86400 = 1 day).
        domain_name: DNS search domain advertised to clients.
    """

    interface: str = ""
    network: str = ""
    start_ip: str = ""
    end_ip: str = ""
    gateway: str = ""
    dns_servers: list[str] = Field(default_factory=list)
    lease_time: int = 86400
    domain_name: str = ""


class CanonicalSNMPv3User(BaseModel):
    """An SNMPv3 User-based Security Model (USM) user (Tier 2 — translate-with-review; per-vendor hash + key grammar diverges).

    The v3 identity unit — where SNMPv1/v2c identity is a shared
    community string, v3 identity is a named user with per-user
    authentication + privacy keys.  Vendors diverge on grammar but
    converge on the same USM surface:

    * Cisco IOS / IOS-XE CLI / Arista EOS:
      ``snmp-server user <name> <group> v3 auth {md5|sha} <pass>
      priv {des|aes {128|192|256} | 3des} <pass>``
    * Aruba AOS-S:
      ``snmpv3 user <name> auth {md5|sha} <pass> priv {aes|des}
      <pass>`` (+ ``snmpv3 group <group> user <name> sec-model ver3``).
    * FortiGate:
      ``config system snmp user / edit <name> / set security-level
      {no-auth-no-priv|auth-no-priv|auth-priv} / set auth-proto
      {md5|sha|sha224|sha256|sha384|sha512} / set auth-pwd ENC <hash>
      / set priv-proto {aes|aes256|aes256cisco|des} / set priv-pwd
      ENC <hash>``
    * MikroTik RouterOS:
      ``/snmp community / add name=<name> authentication-protocol=
      {MD5|SHA1} authentication-password="<pass>" encryption-protocol=
      {AES|DES} encryption-password="<pass>"`` (RouterOS overloads
      its ``/snmp community`` section for both v1/v2c and v3).
    * Juniper Junos:
      ``set snmp v3 usm local-engine user <name> authentication-
      {md5|sha|sha224|sha256} authentication-key "<key>"`` +
      ``set snmp v3 usm local-engine user <name> privacy-{des|aes128|
      aes192|aes256} privacy-key "<key>"`` +
      ``set snmp v3 vacm security-to-group security-model usm
      security-name <name> group <group>``.

    Only the cross-vendor-stable surface lives on this model.
    Per-vendor extras (Cisco views, Junos VACM access rules,
    FortiGate trap/query ports) belong in the codec's render-path
    logic or in ``raw_sections`` if they carry no cross-vendor
    semantic.

    Password handling mirrors :class:`CanonicalLocalUser.hashed_password`:
    codecs preserve whatever opaque hash / encrypted blob the source
    emitted and pass it through verbatim to the target.  Same-vendor
    round-trip is lossless; cross-vendor migration typically
    requires re-keying on the target device (hashes are salted with
    vendor-specific constants).  Plaintext passwords from the source
    are NEVER accepted — operators inject secrets via their
    credentials manager, not via the migration tree.

    Attributes:
        name: USM securityName / username.  Opaque identity string.
        group: SNMP group the user belongs to for VACM access
            control.  Optional; Aruba and Cisco require a group,
            Junos carries it via ``security-to-group``, RouterOS
            doesn't model groups.  Empty string = "no group"
            (codec renders a default group or omits the VACM line).
        auth_protocol: Authentication hash algorithm.  Normalised
            to lower-case short form: ``""`` (no auth), ``"md5"``,
            ``"sha"`` (= SHA-1), ``"sha224"``, ``"sha256"``,
            ``"sha384"``, ``"sha512"``.  Empty = no-auth-no-priv.
        auth_passphrase: Opaque pre-hashed / encrypted
            authentication key from the source config.  Never
            plaintext.
        priv_protocol: Privacy cipher.  Normalised to lower-case
            short form: ``""`` (no priv), ``"des"``, ``"3des"``,
            ``"aes"`` (= AES-128 default), ``"aes128"``,
            ``"aes192"``, ``"aes256"``.  Empty with a non-empty
            auth_protocol = auth-no-priv.
        priv_passphrase: Opaque pre-hashed / encrypted privacy
            key.  Never plaintext.
        engine_id: Optional SNMPv3 engineID (hex string).  Most
            vendors derive the engineID from the device; operators
            override only in specialised environments.  Empty =
            vendor-default engineID.
    """

    name: str
    group: str = ""
    auth_protocol: str = ""                         # "" | "md5" | "sha" | ...
    auth_passphrase: str = ""                       # opaque hash, never plaintext
    priv_protocol: str = ""                         # "" | "des" | "aes" | ...
    priv_passphrase: str = ""                       # opaque hash, never plaintext
    engine_id: str = ""                             # hex; empty = vendor default


class CanonicalSNMP(BaseModel):
    """SNMP configuration (Tier 2 — translate-with-review; v3 USM key grammar diverges).

    Models both SNMPv1/v2c (the ``community`` string surface) and
    SNMPv3 (the :attr:`v3_users` USM list).  The two are
    independent — a device can carry v2c community-string
    configuration alongside one or more v3 users — and codecs
    parse / render them independently.
    """

    community: str = ""
    location: str = ""
    contact: str = ""
    trap_hosts: list[str] = Field(default_factory=list)
    #: SNMPv3 User-based Security Model users.  Empty list means the
    #: source config had no v3 users (pure v1/v2c).  See
    #: :class:`CanonicalSNMPv3User` for the per-user schema.  Rename
    #: surface lives in
    #: :mod:`netcanon.migration.canonical.snmpv3_user_names` (fifth
    #: per-pane category after ports / vlans / local_users /
    #: snmp_community).
    v3_users: list[CanonicalSNMPv3User] = Field(default_factory=list)


class CanonicalLAG(BaseModel):
    """A LAG / port-channel / trunk / bonding group (Tier 2 — translate-with-review; LACP mode + naming diverge).

    Attributes:
        name: Vendor-native LAG name (e.g. ``Port-Channel1``,
            ``ae0``, ``bond0``, ``Trk1``).
        members: Member interface names, vendor-native.
        mode: LACP negotiation mode.  ``"active"`` (default — LACP
            active), ``"passive"`` (LACP passive), or ``"static"``
            (no LACP, manual aggregation).
    """

    name: str
    members: list[str] = Field(default_factory=list)
    mode: str = "active"


class CanonicalVRRPGroup(BaseModel):
    """A classic FHRP redundancy group on an interface — VRRP / HSRP / CARP (Tier 2 — FHRP redundancy; cross-vendor grammar diverges).

    Models the universal L3 redundancy primitive across the shipped
    bidirectional codecs.  Every vendor has equivalent grammar; the
    canonical surface stores the shared semantics + a ``mode``
    discriminator that lets cross-vendor migration translate between
    wire protocols where the operator's intent ("provide redundancy
    for this IP") survives even when the underlying protocol differs.

    Distinct from anycast-gateway, which lives on
    :attr:`CanonicalIPv4Address.virtual_gateway_address` and friends.
    Classic FHRP is a router-group election (group ID, priority,
    preempt); anycast is an IP-address property (every leaf has it,
    no election).  The two surfaces co-exist on the same
    :class:`CanonicalInterface` for fabrics that combine both.

    Cross-vendor grammar reference (the canonical fields here map
    to all of these forms):

    * Cisco IOS-XE ``interface X / vrrp 10 ip 192.168.1.254 /
      vrrp 10 priority 110 / vrrp 10 preempt``.
    * Arista EOS ``interface VlanN / vrrp 10 ipv4 192.168.1.254 /
      vrrp 10 priority 110`` (modern multi-line).
    * Juniper Junos ``set interfaces irb unit N family inet
      address X vrrp-group 10 virtual-address Y / priority 110 /
      preempt``.
    * Aruba AOS-S ``vlan N / ip vrrp vrid 10 / virtual-ip-address
      Y / priority 110 / preempt / enable``.
    * FortiGate ``config system interface / edit X / config vrrp /
      edit 10 / set vrip Y / set priority 110 / set preempt enable
      / next / end``.
    * MikroTik RouterOS ``/interface vrrp add interface=ether1
      vrid=10 priority=110 v3-protocol=ipv4``.
    * OPNsense (BSD CARP) ``<virtualip><vip><mode>carp</mode>
      <vhid>10</vhid><advskew>0</advskew><password>...
      </password><subnet>Y</subnet></vip></virtualip>`` — modelled
      via ``mode="carp"`` discriminator (semantically related but
      wire-protocol-distinct from IETF VRRP).

    Attributes:
        group_id: VRRP VRID (1-255) or CARP VHID (1-255).  Required.
        mode: Wire-protocol discriminator.  String literal (not enum)
            so codecs can extend it without a schema change.  Known
            values: ``"vrrp"`` (default — IETF VRRPv2 / VRRPv3),
            ``"hsrp"`` (Cisco proprietary, used on NX-OS and IOS
            classic), ``"carp"`` (BSD Common Address Redundancy
            Protocol, OPNsense / pfSense).  Anycast is NOT a mode
            here — see :attr:`CanonicalIPv4Address.
            virtual_gateway_address` for that surface.
        virtual_ips: IPv4 virtual addresses (>= 1 required).  Most
            vendors permit one; IOS-XE permits repeated ``vrrp N
            ip X`` for secondaries.  Junos accepts ``virtual-address
            [ X Y Z ]``.  AOS-S takes one IP (codec must surface
            ``Lossy`` if length > 1).
        virtual_ipv6s: IPv6 virtual addresses for VRRPv3 / anycast-v6
            fallback.  Empty list = IPv4-only group (classic VRRPv2).
        virtual_mac: Optional MAC override for the virtual gateway.
            Junos ``virtual-gateway-v4-mac`` populates this directly
            on the group.  Arista's chassis-wide
            ``ip virtual-router mac-address`` cascades into every
            group on parse and hoists back to top-level on render.
            Empty string = vendor-default (``00:00:5E:00:01:<VRID>``
            for IETF VRRP; ``00:00:0C:07:AC:<group>`` for HSRP).
        priority: VRRP priority (1-254).  Higher wins the election.
            Vendor default is 100.
        preempt: Whether a higher-priority router preempts the
            current master.  Vendor defaults vary (Cisco: true,
            Junos: false); the canonical default mirrors the most
            common operator intent.
        advertisement_interval: Election heartbeat interval in
            seconds.  VRRPv2 default is 1; VRRPv3 supports
            sub-second values which we round to the nearest second.
        authentication: Opaque authentication token in
            ``<scheme>:<value>`` form (e.g. ``"plain:secret123"``,
            ``"md5:hash"``, ``"carp-key:bytes"``).  Empty string =
            no authentication.  Mirrors the hash-portability policy
            in :mod:`netcanon.migration.canonical.local_user_names`:
            same-vendor render passes through, cross-vendor render
            surfaces a review comment rather than re-deriving.
        track_interfaces: Vendor-native interface names whose state
            decrements the priority on failure.  IOS-XE ``track``
            objects, Junos ``track interface``, Arista
            ``vrrp N track Ethernet1 decrement 10``.  The
            priority-decrement value is per-vendor lossy.
        description: Operator-supplied description.

    Ship-before-wire (v0.2.0): every codec's
    :class:`CapabilityMatrix` lists ``/interfaces/interface/
    vrrp-groups/group`` as ``unsupported`` until the per-codec wire-
    up lands (Wave B of the v0.2.0 plan documented in
    ``docs/v0.2.0-planning/``).
    """

    group_id: int = Field(ge=1, le=255)
    mode: str = "vrrp"  # "vrrp" | "hsrp" | "carp"
    virtual_ips: list[str] = Field(default_factory=list)
    virtual_ipv6s: list[str] = Field(default_factory=list)
    virtual_mac: str = ""
    priority: int = Field(default=100, ge=1, le=254)
    preempt: bool = True
    advertisement_interval: int = 1
    authentication: str = ""
    track_interfaces: list[str] = Field(default_factory=list)
    description: str = ""


class CanonicalLocalUser(BaseModel):
    """A local user account (Tier 2 — translate-with-review; password hash format is vendor-specific).

    Attributes:
        name: Username (opaque identity string).
        privilege_level: Vendor-specific privilege number.  ``15`` =
            admin on Cisco IOS / IOS-XE / NX-OS; default ``1`` =
            read-only on those platforms.  Other vendors map this
            into their native role model.
        hashed_password: Opaque pre-hashed / encrypted password from
            the source config.  Never plaintext — operators inject
            secrets via their credentials manager, not via the
            migration tree.
        role: Role/group name in the vendor's native authorisation
            model (e.g. ``"manager"``, ``"operator"``, ``"admin"``,
            ``"super-user"``).
    """

    name: str
    privilege_level: int = 1
    hashed_password: str = ""
    role: str = ""


class CanonicalRADIUSServer(BaseModel):
    """A RADIUS server definition (Tier 2 — translate-with-review; key hash format is vendor-specific).

    Attributes:
        host: RADIUS server IP address or hostname.
        key: Shared secret (opaque) — pre-hashed / encrypted by the
            source vendor's storage format; never plaintext.
        auth_port: Authentication UDP port (RFC 2865 default 1812).
        acct_port: Accounting UDP port (RFC 2866 default 1813).
    """

    host: str
    key: str = ""
    auth_port: int = 1812
    acct_port: int = 1813


class CanonicalVxlan(BaseModel):
    """A VLAN-to-VNI mapping for an EVPN-VXLAN overlay (Tier 2 — ship-before-wire; cross-vendor VTEP grammar diverges).

    Models the association between a Layer-2 VLAN and the VXLAN Network
    Identifier (VNI) that carries its broadcast/unknown-unicast/multicast
    traffic across a fabric.  Vendors diverge sharply on grammar:

    * Arista EOS declares mappings on the VLAN (``vlan 100 vxlan vni
      10100``) or inside an ``interface Vlan``-to-VTEP binding.
    * Cisco NX-OS uses ``vn-segment <vni>`` inside the VLAN stanza and
      declares the VTEP under ``interface nve1``.
    * Junos declares ``vxlan vni <vni>`` inside ``vlans <name>`` plus
      a separate ``switch-options`` or ``routing-instance`` VRF target.

    Only the cross-vendor-stable fields live on this model.  Vendor-
    native extras (ingress-replication protocol choice, learning mode,
    source-interface) belong in the codec's render-path logic or in
    ``raw_sections`` if they carry no cross-vendor semantic.

    Attributes:
        vlan_id: The VLAN the VNI maps to.  Matches
            :attr:`CanonicalVlan.id` for discoverability; codecs that
            emit VNI mappings should keep both records in sync.
        vni: The 24-bit VXLAN Network Identifier (1-16777215).
        mcast_group: Underlay multicast group for BUM replication, or
            empty string for head-end / ingress replication.  Stored as
            dotted-quad (e.g. ``"239.1.1.100"``).
        flood_list: Explicit VTEP IPs for head-end replication, in
            preference order.  Empty when multicast-only.
        source_interface: VTEP source interface name in operator-form
            (Arista ``Loopback0``, Junos ``lo0.0``, NX-OS ``loopback0``).
            Opaque string — cross-vendor renders accept whatever the
            source codec emitted; operators rename via the existing
            port-rename pane when crossing platforms.  Empty string
            means undeclared and codecs should fall back to a sensible
            default (typically ``Loopback0`` on Arista, ``lo0.0`` on
            Junos).  This is a switch-level / global attribute on the
            VTEP — codecs populate it on EVERY CanonicalVxlan record
            for that switch so the value survives even when only a
            subset of VNIs is consumed downstream.
        udp_port: VXLAN UDP destination port.  Defaults to 4789 (the
            IANA-assigned standard); operators occasionally override
            (e.g. legacy 8472 from early Linux VXLAN deployments).
            Same per-switch broadcast model as ``source_interface``.
    """

    vlan_id: int = Field(ge=1, le=4094)
    vni: int = Field(ge=1, le=16777215)
    mcast_group: str = ""                           # empty = no mcast; use flood_list
    flood_list: list[str] = Field(default_factory=list)
    source_interface: str = ""                      # opaque per-vendor name (Loopback0 / lo0.0 / loopback0)
    udp_port: int = 4789                            # IANA default; rare operator override


class CanonicalRoutingInstance(BaseModel):
    """A VRF / routing-instance declaration (Tier 2 — ship-before-wire; per-vendor RD/RT grammar diverges).

    Cross-vendor model for the L3 isolation primitive that every
    enterprise router + DC switch carries under a different name:

    * Cisco IOS / IOS-XE: ``vrf definition <name>`` with
      ``rd <rd>`` + ``address-family ipv4 / route-target import/export``.
    * Cisco NX-OS: ``vrf context <name>`` with the same sub-commands.
    * Arista EOS: ``vrf instance <name>`` + ``ip routing vrf <name>``
      (RD + RTs live under ``router bgp`` per address-family).
    * Juniper Junos: ``set routing-instances <name> instance-type
      vrf`` + ``route-distinguisher <rd>`` + ``vrf-target target:<rt>``
      + ``interface <iface>``.

    Per-interface VRF membership lives on :attr:`CanonicalInterface.vrf`
    rather than a redundant ``interfaces`` list here — matches the
    ``lag_member_of`` pattern (interface carries the back-pointer;
    codec render walks ``tree.interfaces`` to synthesise the parent-
    side stanza).  Empty ``CanonicalRoutingInstance.name`` means
    global / default VRF (never emitted as a record).

    Attributes:
        name: VRF / routing-instance identifier (opaque string).
        instance_type: Junos-facing classification — ``vrf``,
            ``virtual-router``, ``l2vpn``, ``mac-vrf``.  Defaults to
            ``"vrf"`` (the cross-vendor baseline).  Codecs that don't
            model the variants emit / accept only ``"vrf"``.
        route_distinguisher: BGP RD (``<asn>:<nn>`` or ``<ip>:<nn>``
            form), or empty if the VRF is local (no MP-BGP export).
        rt_imports: BGP Route-Target import communities.
        rt_exports: BGP Route-Target export communities.
        description: Free-text description; preserved verbatim on
            round-trip for vendors that support it (Junos, Cisco).
    """

    name: str
    instance_type: str = "vrf"
    route_distinguisher: str = ""
    rt_imports: list[str] = Field(default_factory=list)
    rt_exports: list[str] = Field(default_factory=list)
    description: str = ""
    # Layer-3 VNI for EVPN Type-5 (symmetric IRB) routing.  Arista
    # emits this as ``vxlan vrf <name> vni <N>`` inside the Vxlan
    # interface stanza; Junos emits it as ``set routing-instances
    # <name> protocols evpn ip-prefix-routes vni <N>``.  None = no
    # L3 VNI (the VRF doesn't participate in Type-5 announcements).
    l3_vni: int | None = None


class CanonicalEvpnType5Route(BaseModel):
    """An EVPN Type-5 (IP Prefix) advertisement (Tier 2 — ship-before-wire; per-vendor BGP grammar diverges).

    Type-5 routes carry L3 prefix advertisements across an EVPN fabric
    and are the cross-vendor primitive for "advertise this VRF's subnets
    through BGP-EVPN".  Type-2 (MAC/IP) is emitted automatically from
    VLAN-to-VNI bindings and does not need its own canonical record.

    Vendors diverge on where the intent is expressed:

    * Arista EOS:  ``router bgp <asn> / vrf <name> / neighbor ...
      activate`` + ``router bgp <asn> / address-family evpn / neighbor
      ... activate`` + per-VRF RT import/export under ``vrf``.
    * Cisco NX-OS:  ``vrf context <name>`` carries ``address-family
      ipv4 unicast`` with ``route-target import/export evpn`` lines.
    * Junos:  ``routing-instances <vrf>`` with ``vrf-target target:...``
      plus ``protocols evpn``.

    This record stores the minimum common surface.  Richer semantics
    (ECMP, next-hop-unchanged, route-filter rewrites) stay in each
    codec's raw path until a concrete cross-vendor need surfaces.

    Attributes:
        vrf: The VRF / routing-instance / tenant name the prefix
            belongs to (opaque string; matches the VRF name declared
            elsewhere in the tree).
        prefix: The IPv4 CIDR being advertised (e.g. ``"10.1.0.0/16"``).
            IPv6 prefixes are accepted as-is; codecs decide how to
            emit them based on the address-family stanza they own.
        rt_imports: BGP Route-Target import communities (e.g.
            ``["65001:100", "65001:200"]``).
        rt_exports: BGP Route-Target export communities.
    """

    vrf: str
    prefix: str                                     # CIDR; IPv4 or IPv6
    rt_imports: list[str] = Field(default_factory=list)
    rt_exports: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level canonical intent dict
# ---------------------------------------------------------------------------


class CanonicalIntent(BaseModel):
    """The complete canonical intent tree (root container — translation tiers apply to its child surfaces).

    This is what every codec's ``parse()`` returns and every codec's
    ``render()`` consumes.  The pydantic model validates the shape at
    the codec boundary so malformed trees fail loudly.

    Tier 3 (informational) data lives in ``raw_sections`` — a dict of
    section-name → raw text that the pipeline carries through for
    display but never auto-renders.

    Attributes:
        hostname: Tier 1 — device hostname.
        domain: Tier 1 — DNS domain name.
        dns_servers: Tier 1 — DNS resolver IPs in operator-stated
            order.
        ntp_servers: Tier 1 — NTP peer IPs / hostnames.
        timezone: Tier 1 — operator-stated timezone string (vendor-
            specific format; e.g. ``"PST -8"``, ``"Europe/London"``).
        syslog_servers: Tier 1 — syslog destination IPs / hostnames.
        interfaces: Tier 1 — per-interface configuration records.
        vlans: Tier 1 — VLAN definitions with port membership.
        static_routes: Tier 1 — static route entries.
        dhcp_servers: Tier 2 — DHCP server pool definitions.
        snmp: Tier 2 — SNMPv1/v2c + v3 USM configuration.  ``None``
            when source config had no SNMP block.
        lags: Tier 2 — LAG / port-channel definitions.
        local_users: Tier 2 — local user accounts.
        radius_servers: Tier 2 — RADIUS server definitions.
        vxlan_vnis: Tier 2 (ship-before-wire) — VLAN-to-VNI mappings
            for EVPN-VXLAN overlay.  No codec populates these in v1;
            each codec's CapabilityMatrix lists them under
            ``unsupported`` until wired up per-vendor.
        evpn_type5_routes: Tier 2 (ship-before-wire) — EVPN Type-5
            IP-prefix advertisements.  Same wire-up status as
            ``vxlan_vnis``.
        routing_instances: Tier 2 (ship-before-wire) — cross-vendor
            VRF model; see :class:`CanonicalRoutingInstance`
            docstring for the vendor-shape comparison.  Per-interface
            membership lives on :attr:`CanonicalInterface.vrf`, not
            a redundant list here.
        anycast_gateway_mac: Ship-before-wire (v0.2.0) — system-wide
            anycast-gateway MAC.  Vendors that declare it at chassis
            scope populate this from their grammar:

            * Arista EOS: ``ip virtual-router mac-address
              00:1c:73:00:dc:01``
            * Cisco NX-OS DAG: ``fabric forwarding anycast-gateway-
              mac 0001.c73a.0000``
            * Cisco IOS-XE SD-Access: same as NX-OS form
            * Junos: no system-wide MAC; per-unit MAC overrides live
              on :attr:`CanonicalIPv4Address.virtual_gateway_mac`
              instead.

            Empty string = "use vendor default" (Arista:
            ``00:00:00:00:00:00`` implicit until operator sets one;
            NX-OS / IOS-XE SD-Access: required by commit-time
            validator before any SVI can use anycast).  Stored in
            colon-hex canonical form (``00:1c:73:00:dc:01``); per-
            vendor renderers re-emit in their native format (NX-OS
            dotted-quad ``0001.c73a.0000``, etc).  Per-address
            overrides on
            :attr:`CanonicalIPv4Address.virtual_gateway_mac` take
            precedence (Junos per-unit override pattern).  Ship-
            before-wire: every codec's CapabilityMatrix lists
            ``/anycast-gateway-mac`` as ``unsupported`` until the
            per-codec wire-up lands (Wave C of the v0.2.0 plan
            documented in ``docs/v0.2.0-planning/``).
        raw_sections: Tier 3 — informational-only stanzas
            (section-name → raw text).  Carried through for display
            but never auto-rendered.
        dropped_tier3_sections: Tier-3 stanza HEADERS detected in
            source but not modelled by the canonical schema.
            Populated by every codec's ``parse()`` via the per-
            vendor detector in
            :mod:`netcanon.migration._tier3_detection`.  Surfaced to
            the operator via the migrate page's "Detected in source
            but not translated" banner so the silent-drop is
            visible.  Empty list means the parser saw nothing
            Tier-3 in the input.  This is a NOTIFICATION-ONLY
            surface — render-side code MUST NOT read it.
        source_vendor: ``vendor_id`` of the codec that produced this
            tree (metadata, populated by parse).
        source_format: ``input_format`` of the source codec
            (metadata).
        source_version: OS version hint from the parser (metadata;
            empty when undetectable).
        apply_groups: Vendor-provenance hint (ship-before-wire for
            most codecs).  GAP 9b (Junos): preserve the apply-groups
            STATEMENT on parse so render emits an equivalent
            structure to what the operator originally wrote.
        group_content: Vendor-provenance hint paired with
            :attr:`apply_groups`.  GAP 9b (Junos): preserve the
            GROUP CONTENT on parse so render emits an equivalent
            structure.  Content is flattened into the canonical
            tree by GAP 8's two-pass parse AND stored here as the
            original group-scoped set-line tails; render uses the
            content-bucket to emit ``set groups <G> ...`` and
            suppresses the top-level emission of the same data to
            avoid duplicate semantics on re-parse.
    """

    # ── Tier 1 — auto-translatable ──
    hostname: str = ""
    domain: str = ""
    dns_servers: list[str] = Field(default_factory=list)
    ntp_servers: list[str] = Field(default_factory=list)
    timezone: str = ""
    syslog_servers: list[str] = Field(default_factory=list)
    interfaces: list[CanonicalInterface] = Field(default_factory=list)
    vlans: list[CanonicalVlan] = Field(default_factory=list)
    static_routes: list[CanonicalStaticRoute] = Field(default_factory=list)

    # ── Tier 2 — auto-translate with review ──
    dhcp_servers: list[CanonicalDHCPPool] = Field(default_factory=list)
    snmp: CanonicalSNMP | None = None
    lags: list[CanonicalLAG] = Field(default_factory=list)
    local_users: list[CanonicalLocalUser] = Field(default_factory=list)
    radius_servers: list[CanonicalRADIUSServer] = Field(default_factory=list)
    # ── Tier 2 (ship-before-wire) — EVPN-VXLAN fabric schema ──
    vxlan_vnis: list[CanonicalVxlan] = Field(default_factory=list)
    evpn_type5_routes: list[CanonicalEvpnType5Route] = Field(default_factory=list)
    # ── Tier 2 (ship-before-wire) — VRF / routing-instance schema ──
    routing_instances: list[CanonicalRoutingInstance] = Field(default_factory=list)

    # ── Ship-before-wire (v0.2.0) — anycast-gateway system MAC ──
    anycast_gateway_mac: str = ""

    # ── Tier 3 — informational only (never auto-rendered) ──
    raw_sections: dict[str, str] = Field(default_factory=dict)
    dropped_tier3_sections: list[str] = Field(default_factory=list)

    # ── Metadata ──
    source_vendor: str = ""
    source_format: str = ""
    source_version: str = ""

    # ── Vendor-provenance hints (ship-before-wire for most codecs) ──
    apply_groups: list[str] = Field(default_factory=list)
    group_content: dict[str, list[list[str]]] = Field(default_factory=dict)
