# Interface naming: Cisco IOS-XE versus Juniper Junos

How physical and logical interfaces are named on each platform.

Sources:
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/interface/command/ir-cr-book/ir-s7.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/en_US/junos12.3/topics/concept/interfaces-naming-conventions-qfx-series.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/interfaces-fundamentals/topics/topic-map/interfaces-interface-naming-overview.html (retrieved 2026-04-30)

Citation ids: `cisco-interface-cli`, `junos-iface-naming`.

## Cisco IOS-XE form

Speed-encoded media-type prefixes plus a slot/sub-slot/port triple
(or pair, on smaller chassis):

```
GigabitEthernet0/0/0
GigabitEthernet1/0/24
TenGigabitEthernet1/0/49
TwentyFiveGigE1/0/49
FortyGigabitEthernet1/0/53
HundredGigE1/0/49
FastEthernet0/0
```

Logical:

- `Loopback0`, `Loopback42` (flat numeric ID)
- `Vlan100` (SVI)
- `Tunnel1`, `Tunnel0`
- `Port-channel10` (lower-case `c` — distinct from Arista's
  `Port-Channel10`)

The `running-config` always emits the canonical long form even when
operators type the abbreviated `int gi1/0/1`.

## Junos form

Junos encodes media + FPC + PIC + port (+ optional unit) in the
physical-interface name:

```
ge-0/0/0       Gigabit Ethernet, FPC 0, PIC 0, port 0
xe-0/0/0       10-Gigabit Ethernet
et-0/0/48      40 / 100 Gigabit Ethernet
mge-0/0/0      Multi-rate Gigabit Ethernet
fe-0/0/0       Fast Ethernet (legacy)
```

Logical:

- `lo0`, `lo0.0` (loopback; unit 0 is implicit but commonly named
  explicitly)
- `irb.100` (Integrated Routing and Bridging — the Junos analogue of
  a Cisco SVI)
- `ae0`, `ae0.0` (aggregated Ethernet — LAG)
- `me0`, `em0`, `fxp0` (out-of-band management; varies by platform)
- `unit <N>` per physical interface — every Junos interface carries
  at least one logical unit; routed sub-interfaces are
  `ge-0/0/0.100`, etc.

## Mapping notes

- **Speed-prefix translation.** Cisco `GigabitEthernet1/0/1` and
  Junos `ge-0/0/0` carry the same speed semantic; canonical model
  preserves the source string, and the port-rename mesh
  (`netconfig/migration/codecs/cisco_iosxe_cli/port_names.py`) is
  the operator-facing remediation surface.
- **Slot/PIC synthesis.** Cisco's `<slot>/<subslot>/<port>` triple
  maps to Junos's `<fpc>/<pic>/<port>` triple; the indices are
  not always 1:1 (Cisco subslot is typically a line-card sub-module
  index, Junos PIC is a physical insertion module).  Operators
  override via the per-pane port-rename surface for non-default
  mappings.
- **Loopback unit.** Cisco `Loopback0` maps to Junos `lo0.0` (unit
  0 implicit in Cisco's flat name, explicit in Junos).
- **SVI versus IRB.** Cisco `Vlan100` (an L3 SVI auto-created by
  the VLAN stanza) maps to Junos `irb.100` (an IRB unit explicitly
  declared and bound to the VLAN via `set vlans NAME l3-interface
  irb.100`).
- **LAG.** Cisco `Port-channel10` (or `Port-Channel10` on Arista)
  maps to Junos `ae10`.  Both use a sequential index.
- **Sub-interface model.** Cisco's `interface
  GigabitEthernet1/0/1.100` (dot-encapsulation sub-interface) maps
  to Junos `ge-0/0/0.100` (logical unit 100); both encode VLAN
  tagging in the unit, but Cisco binds the encapsulation type via
  `encapsulation dot1Q 100` and Junos via `vlan-id 100` under the
  unit.

Disposition: **lossy** in the canonical sense (port-rename mesh
preserves intent; speed-hint preservation is opaque per the
`CanonicalInterface.name` schema).
