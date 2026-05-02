# Interfaces (naming / IP / MTU / IPv6 / DHCP-client): Juniper Junos versus FortiGate FortiOS

## Juniper Junos

Source: [Junos Understanding Interface Naming Conventions](https://www.juniper.net/documentation/en_US/junos12.3/topics/concept/interfaces-naming-conventions-qfx-series.html).
Source: [Junos Protocol Family and Interface Address Properties](https://www.juniper.net/documentation//us/en/software/junos/interfaces-fundamentals/topics/topic-map/protocol-family-interface-address-properties.html).
Source: [Junos `family inet6`](https://www.juniper.net/documentation/en_US/junos/topics/reference/configuration-statement/interfaces-edit-family-inet6.html).
Retrieved: 2026-05-01.

Junos uses media-prefix names with FPC/PIC/port indices and per-unit
sub-interface decomposition:

```
set interfaces ge-0/0/0 description "WAN uplink"
set interfaces ge-0/0/0 mtu 1500
set interfaces ge-0/0/0 unit 0 family inet address 198.51.100.2/30
set interfaces ge-0/0/0 unit 0 family inet address 198.51.100.6/30   # secondary
set interfaces ge-0/0/0 unit 0 family inet6 address 2001:db8:cafe::2/64
#
set interfaces ge-0/0/1 description "Trunk"
set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members USERS
set interfaces ge-0/0/1 unit 0 family ethernet-switching native-vlan-id 1
#
set interfaces ge-0/0/1 unit 100 vlan-id 100
set interfaces ge-0/0/1 unit 100 family inet address 10.100.0.1/24
#
set interfaces lo0 unit 0 family inet address 172.16.0.1/32
set interfaces lo0 unit 0 family inet6 address fe80::1/64    # link-local
#
set interfaces ae0 description "Bonded uplink"
set interfaces ae0 aggregated-ether-options lacp active
set interfaces ae0 unit 0 family inet address 10.1.0.1/31
set interfaces ge-0/0/2 ether-options 802.3ad ae0
```

Notable Junos specifics:

- **Hierarchical name + unit**: `<media>-<fpc>/<pic>/<port>` plus
  optional `unit N` for sub-interfaces.  `unit 0` is implicit primary.
- **Stacked addresses per unit**: multiple `set address` lines
  permitted (canonical IPv4 / IPv6 lists).
- **IPv6 link-local** auto-detected by `fe80::/10` prefix; no
  explicit keyword.
- **Switchport surface**: `family ethernet-switching interface-mode
  access | trunk` plus `vlan members <name>` and `native-vlan-id N`.
- **MTU at parent scope**.
- **Disable**: `set interfaces X disable`.
- **DHCP client**: `set interfaces X unit 0 family inet dhcp`.
- **VRF binding**: `set routing-instances X interface ge-0/0/0.0`
  (the back-pointer; Junos codec parses this into
  `CanonicalInterface.vrf` per GAP 6).

## FortiGate FortiOS

Source: [FortiGate / FortiOS Administration Guide — Interface settings](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings).
Retrieved: 2026-05-01.

FortiGate uses a flat namespace with the interface name as the edit
ID under `config system interface`:

```
config system interface
    edit "port1"
        set ip 198.51.100.2 255.255.255.252
        set ip6-address 2001:db8:cafe::2/64
        set mtu-override enable
        set mtu 1500
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

- **Flat namespace**: operator-chosen names; no slot/port encoding.
- **IP form**: dotted-quad mask (`set ip A.B.C.D MASK`).
- **IPv6 form**: CIDR (`set ip6-address X/N`).
- **MTU override**: `set mtu-override enable` toggle.
- **VLAN child**: `set type vlan` + `set vlanid N` + `set interface
  "<parent>"`.
- **Aggregate**: `set type aggregate` + `set member ...` + `set
  lacp-mode ...`.
- **DHCP client**: `set mode dhcp` (replaces `set ip`).
- **Secondary IPs**: `set secondary-IP enable` + `config secondaryip`
  table; the FortiGate codec does not emit secondaries in v1.

## Cross-vendor mapping (Junos -> FortiGate)

Canonical surface (`CanonicalInterface`).

- **name** — `lossy`.  Junos slashes are illegal in FortiGate edit
  IDs; the rename mesh sanitises (`ge-0/0/0` -> `port1` typically).
  Junos per-unit form (`ge-0/0/1 unit 100`) materialises in canonical
  as a child interface (e.g. `ge-0/0/1.100`); FortiGate render must
  emit a `type vlan` child with `set vlanid 100` + `set interface
  "ge-0-0-1"`.
- **description** — `lossy`.  Junos accepts arbitrary-length strings;
  FortiOS `set alias` caps at 25 — long Junos descriptions truncate
  with a banner.
- **enabled** — `good`.  `disable` <-> `set status down`.
- **interface_type** — `lossy`.  Both vendors heuristically detect
  from name prefix; aggregation and loopback survive, tunnel
  subtypes drift.
- **mtu** — `good`.
- **ipv4_addresses** — `lossy`.  Junos's stacked `set address` lines
  populate canonical `ipv4_addresses` list; FortiGate render emits
  only the primary address (FortiGate codec doesn't emit
  secondaries in v1).
- **ipv6_addresses** — `lossy`.  Single-address surface round-trips;
  multi-address drops to first.  Link-local scope discriminator may
  not survive FortiGate normalisation.
- **switchport_*** — `unsupported` (Junos populates the canonical L2
  fields; FortiGate has no canonical render path).
- **lag_member_of** — `good`.  Junos `ether-options 802.3ad ae<N>`
  parses to `lag_member_of=ae<N>`; FortiGate render emits the
  member as `set member "<X>"` under the renamed aggregate.
- **dhcp_client** — `lossy`.  Junos `family inet dhcp` parses to
  `dhcp_client=True`; FortiGate render emits `set mode dhcp`.
- **vrf** — `unsupported`.  Junos GAP 6 source-side wired; FortiGate
  render-side does not emit VRF binding (per-interface integer VRF
  in FortiOS 7.0+ is parse-and-render-ignore in v1).

## Cross-vendor mapping (FortiGate -> Junos)

Reverse direction (see also `../fortigate_cli_to_juniper_junos/interfaces.md`):

- **switchport_*** — `not_applicable` (FortiGate parse never
  populates).
- **ipv4_addresses** — `good` for primary; FortiGate parser drops
  secondaries before reaching canonical.
- The other fields share asymmetric details.
