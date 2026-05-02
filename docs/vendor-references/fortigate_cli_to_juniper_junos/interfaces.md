# Interfaces (naming / IP / MTU / IPv6 / DHCP-client): FortiGate FortiOS versus Juniper Junos

## FortiGate FortiOS

Source: [FortiGate / FortiOS Administration Guide — Interface settings](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings).
Source: FortiOS CLI Reference — `config system interface`.
Retrieved: 2026-05-01.

FortiOS uses a **flat namespace** for interfaces under `config system
interface`, with the interface name as the edit ID:

```
config system interface
    edit "port1"
        set alias "WAN-uplink"
        set ip 198.51.100.2 255.255.255.252
        set ip6-address 2001:db8:cafe::2/64
        set allowaccess ping https ssh
        set mtu-override enable
        set mtu 1500
        set status up
    next
    edit "loopback0"
        set type loopback
        set ip 10.255.255.1 255.255.255.255
    next
    edit "agg1.100"
        set type vlan
        set vlanid 100
        set interface "agg1"
        set ip 10.100.0.1 255.255.255.0
    next
end
```

Notable FortiOS specifics:

- **Flat namespace**: names are operator-chosen (`port1`, `wan1`,
  `internal`, `LAG_INTERNAL`, `loopback0`).  No speed / slot / port
  encoding.
- **IP addressing**: `set ip A.B.C.D MASK` (dotted-quad mask, NOT CIDR).
- **IPv6**: `set ip6-address X/N` (CIDR form).  No explicit
  link-local scope keyword — `fe80::/10` prefix indicates link-local.
- **MTU**: `set mtu-override enable` (default off; uses interface
  type's default) + `set mtu N`.
- **Type discriminator**: `set type {vlan|aggregate|loopback|tunnel|...}`
  on non-physical interfaces.  Physical ports (`port1`) have no
  explicit type.
- **VLAN child interfaces**: `type vlan` + `set vlanid N` + `set
  interface "<parent>"`.  No inline trunking on parent.
- **Aggregates (LAGs)**: `type aggregate` + `set member "p1" "p2"` +
  `set lacp-mode active|passive|static`.
- **DHCP client**: `set mode dhcp` (replaces `set ip`).

## Juniper Junos

Source: [Junos Understanding Interface Naming Conventions](https://www.juniper.net/documentation/en_US/junos12.3/topics/concept/interfaces-naming-conventions-qfx-series.html).
Source: [Junos Protocol Family and Interface Address Properties](https://www.juniper.net/documentation//us/en/software/junos/interfaces-fundamentals/topics/topic-map/protocol-family-interface-address-properties.html).
Source: [Junos `family inet6`](https://www.juniper.net/documentation/en_US/junos/topics/reference/configuration-statement/interfaces-edit-family-inet6.html).
Retrieved: 2026-05-01.

Junos uses **media-prefix names** with FPC/PIC/port indices:

```
set interfaces ge-0/0/0 description "WAN uplink"
set interfaces ge-0/0/0 mtu 1500
set interfaces ge-0/0/0 unit 0 family inet address 198.51.100.2/30
set interfaces ge-0/0/0 unit 0 family inet6 address 2001:db8:cafe::2/64
#
set interfaces ge-0/0/1 unit 100 vlan-id 100
set interfaces ge-0/0/1 unit 100 family inet address 10.100.0.1/24
#
set interfaces ae0 description "Bonded uplink"
set interfaces ae0 aggregated-ether-options lacp active
set interfaces ae0 unit 0 family inet address 10.1.0.1/31
set interfaces ge-0/0/2 ether-options 802.3ad ae0
```

Notable Junos specifics:

- **Hierarchical name + unit**: `<media>-<fpc>/<pic>/<port>` plus
  optional `unit N` for sub-interfaces.  `unit 0` is the implicit
  primary unit.
- **Address form**: CIDR (`A.B.C.D/N`), under `family inet` (IPv4) or
  `family inet6` (IPv6).
- **MTU**: `set interfaces X mtu N` at the parent scope (applies to
  all units; per-unit MTU not common).
- **Multiple addresses per unit**: stacked `set address` lines.
- **VLAN child**: `unit N vlan-id M` then per-unit family.  Or, for
  L2 switching, `family ethernet-switching vlan members <name>`.
- **LAGs (aggregated-ethernet)**: `ae<N>` interface + members declare
  `ether-options 802.3ad ae<N>`.
- **DHCP client**: `set interfaces X unit 0 family inet dhcp`.
- **Disable**: `set interfaces X disable` (admin-down).
- **Link-local IPv6**: auto-detected by `fe80::/10` prefix; no
  explicit keyword.

## Cross-vendor mapping (FortiGate -> Junos)

Canonical surface (from `CanonicalInterface`):

```
class CanonicalInterface(BaseModel):
    name: str
    description: str = ""
    enabled: bool = True
    interface_type: str = ""
    mtu: int | None = None
    ipv4_addresses: list[CanonicalIPv4Address]
    ipv6_addresses: list[CanonicalIPv6Address]
    switchport_mode: str | None = None
    access_vlan: int | None = None
    trunk_allowed_vlans: list[int]
    trunk_native_vlan: int | None = None
    voice_vlan: int | None = None
    lag_member_of: str | None = None
    dhcp_client: bool = False
    vrf: str = ""
```

- **name** — `lossy`.  FortiOS flat namespace -> Junos media-prefix
  requires the rename mesh.  Without operator overrides, the Junos
  render defaults to `ge-0/0/N` for sequentially-numbered ports.
  FortiGate child VLAN names (`port4.300`, `agg1.100`) need
  sanitisation on Junos (slashes invalid in unit-less form;
  consider rewriting to `ge-0/0/X unit 300`).
- **description** — `good`.  FortiOS `set alias` (25 char cap)
  parses to canonical `description`; Junos `set interfaces X
  description` accepts longer strings — truncation already
  happened on FortiGate parse.
- **enabled** — `good`.  FortiOS `set status up|down` <-> Junos
  `[delete] interfaces X disable`.
- **interface_type** — `lossy`.  FortiOS has no IANA ifType (codec
  matrix lossy entry); Junos infers from name prefix.  Aggregation
  and loopback survive; tunnel subtypes drift.
- **mtu** — `good`.  Integer round-trips.
- **ipv4_addresses** — `good` for primary; FortiGate parser drops
  secondaries (under `config secondaryip`) before reaching canonical,
  so multi-IP intent loses the tail.
- **ipv6_addresses** — `lossy` on link-local scope.  FortiGate parse
  doesn't auto-detect scope; Junos source side does.
- **switchport_*** — `not_applicable` from FortiGate (no L2 surface
  populated on canonical).
- **lag_member_of** — `good`.  FortiOS `set member` list resolves
  on parse; Junos render emits `ether-options 802.3ad ae<N>`.
- **dhcp_client** — `lossy`.  FortiOS `set mode dhcp` parses to
  `dhcp_client=True`; Junos render emits `family inet dhcp`.  IPv6
  DHCP / RA / SLAAC alternatives not modelled.
- **vrf** — `unsupported`.  FortiGate codec doesn't parse `set vrf
  <id>` into canonical in v1.

## Cross-vendor mapping (Junos -> FortiGate)

Reverse direction (see also `../juniper_junos_to_fortigate_cli/interfaces.md`):

- **name** — `lossy`.  Junos slashes need sanitisation on FortiOS
  (rename mesh maps `ge-0/0/0` -> `port1` typically).
- **description** — `lossy`.  Junos longer strings truncate at 25
  chars on FortiOS render.
- **ipv4_addresses** — `lossy`.  Junos's stacked `set address` lines
  drop to first on FortiOS render (FortiGate codec doesn't emit
  secondary IPs in v1).
- **switchport_*** — `unsupported` because Junos populates the
  canonical L2 fields but FortiGate has no canonical render path.
- **vrf** — `unsupported`.  Junos GAP 6 source-side wired; FortiGate
  render-side unwired.
