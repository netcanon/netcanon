# Interfaces (naming, families, units)

Physical and logical interface naming conventions; per-unit family
detail; the structural mismatch between Junos's per-unit model and
Arista's flat-interface model.

Sources:
- Juniper: https://www.juniper.net/documentation/en_US/junos12.3/topics/concept/interfaces-naming-conventions-qfx-series.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation//us/en/software/junos/interfaces-fundamentals/topics/topic-map/protocol-family-interface-address-properties.html (retrieved 2026-05-01)
- Arista: https://www.arista.com/en/um-eos/eos-ethernet-ports (retrieved 2026-05-01)
- Arista: https://www.arista.com/en/um-eos/eos-interface-configuration (retrieved 2026-05-01)

Citation ids: `junos-iface-naming`, `junos-iface-fundamentals`,
`arista-ethernet-ports`, `arista-iface-cg`.

## Junos form

```
set interfaces ge-0/0/0 description "uplink to spine1"
set interfaces ge-0/0/0 mtu 9216
set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30
set interfaces ge-0/0/0 unit 0 family inet6 address 2001:db8::1/64
set interfaces xe-0/0/47 description "10G uplink"
set interfaces et-0/0/49 description "100G fabric"
set interfaces ae0 aggregated-ether-options lacp active
set interfaces irb unit 100 family inet address 10.100.0.1/24
set interfaces lo0 unit 0 family inet address 10.255.255.1/32
```

Naming convention: `<media>-<fpc>/<pic>/<port>[.<unit>]`:
- `ge-` (Gigabit Ethernet), `xe-` (10GE), `et-` (40GE/100GE),
  `mge-` (multi-rate GE), `fe-` (legacy FE) — speed in the prefix.
- `ae<N>` aggregated Ethernet (LAG).
- `irb.<unit>` Integrated Routing and Bridging (Junos's SVI form).
- `lo0`, `lo0.0` loopback (always with explicit unit).
- `me0`, `em0`, `fxp0` management variants by platform line.

Per-unit families: each unit (sub-interface) carries an independent
`family inet` / `family inet6` / `family ethernet-switching` block.
Multiple units on one physical interface are independently addressable.

## Arista form

```
interface Ethernet1
   description uplink to spine1
   mtu 9216
   ip address 10.0.0.1/30
   ipv6 address 2001:db8::1/64
interface Ethernet48
   description 10G uplink
interface Port-Channel1
   port-channel lacp mode active
interface Vlan100
   ip address 10.100.0.1/24
interface Loopback0
   ip address 10.255.255.1/32
```

Naming convention: flat speed-agnostic numeric form.
- `Ethernet<N>` — non-modular boxes; `Ethernet<slot>/<port>` modular.
- `Ethernet<port>/<lane>` — QSFP breakout child.
- `Port-Channel<N>` LAG.
- `Vlan<id>` SVI.
- `Loopback<N>`, `Vxlan1`, `Management1`.

No per-unit hierarchy: each interface is a single addressable entity.
Sub-interfaces exist (`Ethernet1.100` for L3-routed sub-interfaces)
but are uncommon in DC-leaf deployments and have a different shape
than Junos's per-unit family model.

## Mapping notes

- **Speed prefix collapse.** Junos's `xe-0/0/47` (10G), `et-0/0/49`
  (100G) collapse to bare `Ethernet48` / `Ethernet50` on Arista
  render — the speed hint is encoded in the Arista hardware profile,
  not the name.  Lossless if the operator's intent is "the port at
  this slot/port" but lossy if the operator was using the name as
  documentation.  Per-pane port-rename surface lets the operator
  override.
- **Slot/PIC/port collapse.** `ge-0/0/0` -> `Ethernet1` (FPC 0, PIC 0,
  port 0 -> 1-indexed `Ethernet1`).  Multi-FPC chassis (Junos
  `ge-1/0/0` from the second FPC) typically map to Arista
  `Ethernet1/1` modular form; default rename mesh handles the
  common single-chassis case.
- **Per-unit -> flat collapse.** Junos's `unit 0` round-trips as the
  parent Arista interface's primary IP.  `unit 1+` (extra
  sub-interfaces with independent families) have no clean Arista
  analogue at the `Ethernet1` level — Arista's L3-routed
  sub-interface form (`Ethernet1.<unit>`) is the closest match but
  semantics differ.  Operators with multi-unit Junos configs see a
  validation banner.
- **IRB -> SVI.** `irb.100` (Junos) <-> `Vlan100` (Arista).  The unit
  number is the VLAN id by convention.
- **Loopback.** `lo0.0` (Junos) <-> `Loopback0` (Arista).  Junos
  always carries the unit; Arista doesn't.  Round-trip via the
  port-rename mesh.
- **MTU.** Both accept integer MTU; Junos's `set interfaces X mtu N`
  -> Arista's `mtu N` directly.
- **DHCP client.** Junos's `family inet dhcp` -> Arista's
  `ip address dhcp` — semantic equivalence; per-platform option
  semantics drop.
