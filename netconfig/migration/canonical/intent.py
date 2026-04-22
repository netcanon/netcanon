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


class CanonicalSNMP(BaseModel):
    """SNMP configuration."""

    community: str = ""
    location: str = ""
    contact: str = ""
    trap_hosts: list[str] = Field(default_factory=list)


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

    # ── Tier 3 — informational only (never auto-rendered) ──
    raw_sections: dict[str, str] = Field(default_factory=dict)

    # ── Metadata ──
    source_vendor: str = ""         # vendor_id of the codec that produced this
    source_format: str = ""         # input_format of the codec
    source_version: str = ""        # OS version hint from the parser
