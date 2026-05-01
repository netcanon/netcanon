# Port naming: Aruba AOS-S versus Cisco IOS-XE

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Basic Operation Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/BOG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S uses bare numeric port identifiers — **no speed prefix**:

```
interface 1
interface A1                        ; 5400R chassis: module A, port 1
interface 1/1                       ; 2930M stack: stack-member 1, port 1
interface Trk1                      ; LAG (link-aggregation) trunk
```

LAG names take the literal form `Trk<N>` (capital T, three-letter
prefix).

The codec's `port_names.py` classifies the form via:

* Bare integer `<N>` -> standalone-switch ethernet port.
* Letter+integer `<L><N>` -> chassis-module ethernet port.
* `<stack>/<port>` -> stack-member ethernet port.
* `Trk<N>` -> aggregated logical port.

## Cisco IOS-XE

Source: [Cisco IOS Interface and Hardware Component Command Reference](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/interface/command/ir-cr-book/ir-s7.html)
Retrieved: 2026-04-30

Cisco encodes link speed in the keyword prefix:

```
interface FastEthernet0/1
interface GigabitEthernet1/0/1
interface TenGigabitEthernet1/0/49
interface TwentyFiveGigE1/0/49
interface FortyGigabitEthernet1/0/53
interface HundredGigE1/0/49
```

Logical/virtual: `Loopback0`, `Vlan100`, `Port-channel1`,
`Tunnel0`.

## Cross-vendor mapping

The canonical model carries `CanonicalInterface.name` as the
vendor-native string.  Cross-vendor translation depends on the
per-pane port-rename mesh:

* Aruba `1` -> Cisco `GigabitEthernet1/0/1` (standalone-switch
  default; operator-overridable).
* Aruba `A1` -> Cisco `GigabitEthernet1/0/1` (5400R chassis
  default).
* Aruba `1/1` -> Cisco `GigabitEthernet1/0/1` (2930M stack
  default).
* Aruba `Trk1` -> Cisco `Port-channel1`.

Speed-hint inference:

* Aruba source -> Cisco render: codec defaults to
  `GigabitEthernet` since AOS-S carries no speed hint on the
  port name.  10G/25G/100G ports require operator override via
  the per-pane port-name surface.

Disposition: **lossy** for the speed hint (canonical does not
model it; rename mesh defaults to `GigabitEthernet`).
