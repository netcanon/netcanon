# Interface naming: Juniper Junos versus Cisco IOS-XE

How physical and logical interfaces are named, viewed from the
Junos-source side.

Sources:
- Juniper: https://www.juniper.net/documentation/en_US/junos12.3/topics/concept/interfaces-naming-conventions-qfx-series.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/interfaces-fundamentals/topics/topic-map/interfaces-interface-naming-overview.html (retrieved 2026-04-30)
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/interface/command/ir-cr-book/ir-s7.html (retrieved 2026-04-30)

Citation ids: `junos-iface-naming`, `cisco-interface-cli`.

## Junos form

```
ge-0/0/0       Gigabit Ethernet (FPC 0, PIC 0, port 0)
xe-0/0/0       10-Gigabit Ethernet
et-0/0/48      40 / 100 Gigabit Ethernet
mge-0/0/0      Multi-rate Gigabit Ethernet
fe-0/0/0       Fast Ethernet (legacy)
```

Logical:

- `lo0`, `lo0.0` (loopback with explicit unit)
- `irb.100` (IRB — Junos's L3 SVI analogue)
- `ae0`, `ae0.0` (aggregated Ethernet — LAG)
- `me0`, `em0`, `fxp0` (out-of-band management; vary by platform)

Junos units (`.<N>`) carry per-sub-interface config including VLAN
tags (`set interfaces ge-0/0/0 unit 100 vlan-id 100`).  Unit 0 is
the implicit "untagged" form most operators use.

## Cisco IOS-XE form

```
GigabitEthernet0/0/0
GigabitEthernet1/0/24
TenGigabitEthernet1/0/49
TwentyFiveGigE1/0/49
FortyGigabitEthernet1/0/53
HundredGigE1/0/49
```

Logical:

- `Loopback0`, `Loopback42`
- `Vlan100` (SVI)
- `Tunnel1`
- `Port-channel10` (lower-case `c`)
- `GigabitEthernet1/0/1.100` (sub-interface; encapsulation
  declared via `encapsulation dot1Q 100`)

## Mapping notes

- **Speed-prefix correspondence.** Junos's media prefix (`ge-`,
  `xe-`, `et-`) maps directly to Cisco's speed-encoded media name
  (`GigabitEthernet`, `TenGigabitEthernet`, `HundredGigE`).  Both
  vendors expose speed in the name; round-trip preserves intent.
- **FPC/PIC/port versus slot/sub-slot/port.** Junos's
  `fpc/pic/port` triple maps to Cisco's `slot/sub-slot/port`
  triple.  Indices may not be 1:1 (Junos PIC is a physical
  insertion module; Cisco sub-slot is often a line-card sub-
  module index), but operators routinely substitute via the
  port-rename mesh.
- **Unit collapse on Cisco render.** Junos's per-unit logical
  hierarchy (`unit 0`, `unit 100`, ...) flattens into Cisco's
  flat interface model.  Unit 0 (the bare interface) and units
  with `vlan-id` tags become Cisco sub-interfaces; the codec
  render synthesises the matching `encapsulation dot1Q <N>`
  inline.
- **IRB versus SVI.** Junos's `irb.100` (IRB unit) maps to
  Cisco's `Vlan100` (auto-created SVI).  Both expose L3 config
  on the VLAN; canonical preserves the operator-form name.
- **LAG.** Junos `ae10` -> Cisco `Port-channel10`.

Disposition: **lossy** in the canonical sense (port-rename mesh
preserves intent; the unit-collapse on Cisco render side surfaces
the most common source of nuance loss).
