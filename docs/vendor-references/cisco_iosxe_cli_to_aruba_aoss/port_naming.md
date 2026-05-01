# Port naming: Cisco IOS-XE versus Aruba AOS-S

## Cisco IOS-XE

Source: [Cisco IOS Interface and Hardware Component Command Reference](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/interface/command/ir-cr-book/ir-s7.html)
Retrieved: 2026-04-30

Cisco physical port names encode the link speed in the keyword
prefix and use slash-separated module/sub-module/port indices:

```
interface FastEthernet0/1
interface GigabitEthernet1/0/1
interface TenGigabitEthernet1/0/49
interface TwentyFiveGigE1/0/49
interface FortyGigabitEthernet1/0/53
interface HundredGigE1/0/49
```

Logical / virtual interface names share the same convention:
`Loopback0`, `Vlan100`, `Port-channel1`, `Tunnel0`.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Basic Operation Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/BOG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S uses bare numeric port identifiers — the slot/module structure
is implicit in the digits and there is **no speed prefix** on the
port name.  Verbatim shapes seen in the manual and real captures:

```
interface 1                         ; standalone 24-port 2930F
interface A1                        ; 5400R chassis: module A, port 1
interface 1/1                       ; 2930M stack: stack-member 1, port 1
interface Trk1                      ; LAG (link-aggregation) trunk
interface vlan 100                  ; SVI is implicit on the VLAN stanza,
                                    ; not a separate interface stanza
```

The exact form depends on the platform family:

* Standalone 2930F / 5406zl-style switches without stacking:
  bare integers (`1`, `2`, ..., `48`).
* 5400R / 8200 chassis: letter-prefixed (`A1`-`A24`, `B1`-`B24`).
* 2930M / Aruba CX-precursor stacks: slash-form
  `<stack-member>/<port>` (`1/1`-`1/48`, `2/1`-`2/48`).

The codec's `port_names.py` module classifies these forms and
the per-pane port-rename mesh handles re-mapping to/from Cisco
shapes.

## Cross-vendor mapping

The canonical model stores `CanonicalInterface.name` as the
vendor-native string verbatim (design principle 2: "opaque
interface IDs ... mapping between naming schemes is the
`rename_interfaces` transform's job").  Cross-vendor translation
therefore depends on the per-pane port-rename overrides surfaced in
the migration UI:

* Cisco `GigabitEthernet1/0/1` -> Aruba `1/1` (default rename mesh
  guess, operator-overridable).
* Aruba `A1` -> Cisco `GigabitEthernet1/0/1` (chassis-letter to
  slot/port heuristic, operator-overridable).

The speed hint encoded in Cisco's keyword prefix
(`GigabitEthernet` -> `TenGigabitEthernet`) is **lost** on
round-trip through Aruba — AOS-S has no speed prefix, so a
Cisco -> Aruba -> Cisco round-trip degrades the speed inference
to the rename mesh's default (typically `GigabitEthernet`).

Disposition: **lossy** (speed prefix is informational rather than
structural; canonical does not model it).
