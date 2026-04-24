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
    interfaces (name, description, enabled, ipv4), vlans (id, name,
    port membership), static_routes.

Scope (Tier 2 — auto-translate with review banner):
    dhcp_servers, snmp, lags, local_users, radius_servers.

Scope (Tier 3 — parse for display, never auto-render):
    firewall_rules, nat_rules, vpn, routing_protocols (informational).

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
    in :mod:`netconfig.migration.canonical.snmpv3_user_names`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Tier 1 — auto-translatable
# ---------------------------------------------------------------------------


class CanonicalIPv4Address(BaseModel):
    """A single IPv4 address + prefix on an interface."""

    ip: str
    prefix_length: int = Field(ge=0, le=32)


class CanonicalInterface(BaseModel):
    """A network interface — physical, VLAN SVI, LAG, loopback, tunnel."""

    name: str                                   # vendor-native name (opaque);
                                                # for renamed MikroTik ports
                                                # this is the renamed name
                                                # (e.g. "Access Point"), not
                                                # the factory default (ether2)
    default_name: str = ""                      # MikroTik: factory default-name
                                                # (ether1, sfp-sfpplus1) — used
                                                # by the renderer to emit the
                                                # `set [ find default-name=X ]`
                                                # lookup.  Empty for vendors/
                                                # interface types where the
                                                # concept doesn't apply.
    description: str = ""
    enabled: bool = True
    interface_type: str = ""                    # e.g. "ethernetCsmacd", "softwareLoopback"
    mtu: int | None = None
    ipv4_addresses: list[CanonicalIPv4Address] = Field(default_factory=list)
    # Switchport state — None means "not a switchport" (routed port).
    switchport_mode: str | None = None          # "access" | "trunk" | None
    access_vlan: int | None = None              # for access mode
    trunk_allowed_vlans: list[int] = Field(default_factory=list)
    trunk_native_vlan: int | None = None
    voice_vlan: int | None = None
    lag_member_of: str | None = None            # LAG/port-channel name if bundled
    dhcp_client: bool = False
    vrf: str = ""                               # VRF / routing-instance membership;
                                                # empty = global / default VRF.
                                                # Matches a
                                                # ``CanonicalRoutingInstance.name``
                                                # declared at the top level.


class CanonicalVlan(BaseModel):
    """A VLAN definition with membership.

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
    """A single static route entry."""

    destination: str        # CIDR notation: "10.0.0.0/24" or "0.0.0.0/0"
    gateway: str = ""       # next-hop IP; empty for connected/blackhole
    interface: str = ""     # outgoing interface name (vendor-native)
    metric: int = 0
    description: str = ""


# ---------------------------------------------------------------------------
# Tier 2 — auto-translate with review banner
# ---------------------------------------------------------------------------


class CanonicalDHCPPool(BaseModel):
    """A DHCP server pool."""

    interface: str = ""             # interface serving this pool
    network: str = ""               # e.g. "192.168.10.0/24"
    start_ip: str = ""
    end_ip: str = ""
    gateway: str = ""
    dns_servers: list[str] = Field(default_factory=list)
    lease_time: int = 86400         # seconds
    domain_name: str = ""


class CanonicalSNMPv3User(BaseModel):
    """An SNMPv3 User-based Security Model (USM) user.

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
    """SNMP configuration.

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
    #: :mod:`netconfig.migration.canonical.snmpv3_user_names` (fifth
    #: per-pane category after ports / vlans / local_users /
    #: snmp_community).
    v3_users: list[CanonicalSNMPv3User] = Field(default_factory=list)


class CanonicalLAG(BaseModel):
    """A LAG / port-channel / trunk / bonding group."""

    name: str                       # vendor-native name
    members: list[str] = Field(default_factory=list)   # member interface names
    mode: str = "active"            # "active" (LACP) | "passive" | "static"


class CanonicalLocalUser(BaseModel):
    """A local user account."""

    name: str
    privilege_level: int = 1        # vendor-specific; 15 = admin on Cisco
    hashed_password: str = ""       # opaque hash, never plaintext
    role: str = ""                  # "manager" / "operator" / "admin" etc.


class CanonicalRADIUSServer(BaseModel):
    """A RADIUS server definition."""

    host: str
    key: str = ""                   # shared secret (opaque)
    auth_port: int = 1812
    acct_port: int = 1813


class CanonicalVxlan(BaseModel):
    """A VLAN-to-VNI mapping for an EVPN-VXLAN overlay.

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
    """

    vlan_id: int = Field(ge=1, le=4094)
    vni: int = Field(ge=1, le=16777215)
    mcast_group: str = ""                           # empty = no mcast; use flood_list
    flood_list: list[str] = Field(default_factory=list)


class CanonicalRoutingInstance(BaseModel):
    """A VRF / routing-instance declaration.

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
    """An EVPN Type-5 (IP Prefix) advertisement.

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
    """The complete canonical intent tree.

    This is what every codec's ``parse()`` returns and every codec's
    ``render()`` consumes.  The pydantic model validates the shape at
    the codec boundary so malformed trees fail loudly.

    Tier 3 (informational) data lives in ``raw_sections`` — a dict of
    section-name → raw text that the pipeline carries through for
    display but never auto-renders.
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
    # No codec populates these in v1; each codec's CapabilityMatrix
    # lists them under ``unsupported`` until wired up per-vendor.
    vxlan_vnis: list[CanonicalVxlan] = Field(default_factory=list)
    evpn_type5_routes: list[CanonicalEvpnType5Route] = Field(default_factory=list)
    # ── Tier 2 (ship-before-wire) — VRF / routing-instance schema ──
    # Cross-vendor VRF model; see CanonicalRoutingInstance docstring
    # for the vendor-shape comparison.  Per-interface membership
    # lives on CanonicalInterface.vrf, not a redundant list here.
    routing_instances: list[CanonicalRoutingInstance] = Field(default_factory=list)

    # ── Tier 3 — informational only (never auto-rendered) ──
    raw_sections: dict[str, str] = Field(default_factory=dict)

    # ── Metadata ──
    source_vendor: str = ""         # vendor_id of the codec that produced this
    source_format: str = ""         # input_format of the codec
    source_version: str = ""        # OS version hint from the parser

    # ── Vendor-provenance hints (ship-before-wire for most codecs) ──
    # GAP 9b (Junos): preserve both the apply-groups STATEMENT and
    # the GROUP CONTENT on parse so render emits an equivalent
    # structure to what the operator originally wrote.  Content is
    # flattened into the canonical tree by GAP 8's two-pass parse
    # AND stored here as the original group-scoped set-line tails;
    # render uses the content-bucket to emit `set groups <G> ...`
    # and suppresses the top-level emission of the same data to
    # avoid duplicate semantics on re-parse.
    apply_groups: list[str] = Field(default_factory=list)
    group_content: dict[str, list[list[str]]] = Field(default_factory=dict)
