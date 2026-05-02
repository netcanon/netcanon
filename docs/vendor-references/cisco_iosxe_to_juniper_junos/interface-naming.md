# Interface naming — Cisco speed-encoded vs Junos media-prefix

Source: [Cisco IOS XE 17 Interface and Hardware Component Configuration Guide](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/int-hw/b-int-hw.html)
Retrieved: 2026-05-01

Source: [Junos Understanding Interface Naming Conventions (QFX)](https://www.juniper.net/documentation/en_US/junos12.3/topics/concept/interfaces-naming-conventions-qfx-series.html)
Retrieved: 2026-05-01

## Cisco form

Cisco IOS-XE encodes interface speed in the type prefix:

```
GigabitEthernet1/0/1     # 1G, slot 1, sub-slot 0, port 1
TenGigE1/0/49             # 10G
HundredGigE1/0/49         # 100G
FortyGigE1/0/49           # 40G
TwentyFiveGigE1/0/49      # 25G
Loopback0
Vlan100                   # SVI
Port-channel1             # LAG
```

The OpenConfig NETCONF source carries these as `<interface><name>`
verbatim — the parser stores them on `CanonicalInterface.name` as-is.

## Junos form

Junos uses a media-prefix form that encodes speed implicitly via
the prefix abbreviation:

```
ge-0/0/0       # 1G ethernet, FPC 0, PIC 0, port 0
xe-0/0/0       # 10G
et-0/0/48      # 40G+ (et = "ethernet trunk")
mge-0/0/0      # multi-gig 2.5G/5G (Junos 19.x+)
lo0            # loopback (logical only via unit 0)
ae0            # aggregated ethernet (LAG)
irb            # integrated routing & bridging (SVI replacement)
```

FPC = Flexible PIC Concentrator, PIC = Physical Interface Card,
port = port within PIC.  The triple maps to Cisco's slot/sub-slot/
port but not 1:1 — Cisco modular chassis (Catalyst 9600) have
different PIC granularity than QFX line cards.

## Mapping notes

* **Speed-prefix mismatch.** Cisco's `GigabitEthernet1/0/1` vs
  Junos's `ge-0/0/0` carry the same speed semantic but the prefix
  shape and slot-numbering convention differ.  The port-rename mesh
  handles the cross-vendor mapping; operators override
  index-mismatches via the per-pane port-rename surface.
* **SVI form.** Cisco's `Vlan100` (a switched virtual interface
  with its own L3 config) maps to Junos's `irb.100` (an integrated
  routing & bridging unit on the `irb` parent interface).  The
  rename mesh handles `Vlan` -> `irb.`; the unit number matches the
  VLAN id by convention.
* **LAG form.** Cisco's `Port-channel1` -> Junos's `ae1`.  The
  rename mesh handles the prefix swap.
* **Loopback.** Cisco's `Loopback0` -> Junos's `lo0` plus Junos
  adds a unit suffix (`lo0.0`).  Same operational unit, different
  shape.
* **MTU on parent vs unit.** Cisco's `mtu` lives directly on the
  interface stanza; Junos's `mtu` lives at the parent-interface
  hierarchy (parent of unit-0).  Both codecs collapse to the
  parent-MTU view canonically.

## What the cisco_iosxe parser does

Stores the source name verbatim on `CanonicalInterface.name`.  The
port-rename mesh runs downstream (in the migration pipeline) and
translates `GigabitEthernet1/0/1` to `ge-0/0/1` (or whatever the
operator overrides via the per-pane rename surface).

## What the Junos target render does

Renders `set interfaces <name>` with whatever name the canonical
record carries — which is the post-rename name on the cross-vendor
path.  Without the rename mesh, the literal Cisco name reaches
the Junos target and a real device would reject the syntax.

## Disposition

`interfaces[].name` is **good** with note about port-rename mesh
handling the cross-vendor mapping.  The slot/sub-slot/port to FPC/
PIC/port index mapping is operator-overridable; the canonical
field round-trips losslessly through the mesh.

## Edge cases

* **Cisco sub-interfaces.** `GigabitEthernet1/0/1.10` (dot1Q
  sub-interface on a routed port) maps to `ge-0/0/1.10` (Junos
  unit 10).  Both codecs handle the dotted-suffix form; the
  unit-number maps to the dot1Q tag by convention.
* **Cisco service-instance.** `service instance 100 ethernet`
  inside an interface stanza is Cisco-EVC syntax with no clean
  Junos analogue.  parse-and-ignore on the canonical layer; raw
  text drops on cross-vendor render.
