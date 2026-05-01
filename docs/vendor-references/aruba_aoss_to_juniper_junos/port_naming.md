# Port naming: Aruba AOS-S versus Juniper Junos

How physical and logical interfaces are named on each platform.

Sources:
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/BOG/2930F-3810-5400/index.htm (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/en_US/junos12.3/topics/concept/interfaces-naming-conventions-qfx-series.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/interfaces-fundamentals/topics/topic-map/interfaces-interface-naming-overview.html (retrieved 2026-05-01)

Citation ids: `aruba-port-naming`, `junos-iface-naming`.

## Aruba AOS-S form

AOS-S uses bare numeric port identifiers — **no speed prefix**:

```
interface 1                          ; standalone-switch port 1
interface A1                         ; 5400R chassis: module A, port 1
interface 1/1                        ; 2930M stack: stack-member 1, port 1
interface Trk1                       ; LAG (link-aggregation) trunk
```

The codec's `port_names.py` classifies the form via:

* Bare integer `<N>` -> standalone-switch ethernet port.
* Letter+integer `<L><N>` -> chassis-module ethernet port.
* `<stack>/<port>` -> stack-member ethernet port.
* `Trk<N>` -> aggregated logical port.

There is no SVI port-name — the L3 address absorbs into the VLAN
stanza (see `vlans.md`).

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
  an Aruba VLAN-absorbed SVI)
- `ae0`, `ae0.0` (aggregated Ethernet — LAG)
- `me0`, `em0`, `fxp0` (out-of-band management; varies by platform)

## Cross-vendor mapping

The canonical model carries `CanonicalInterface.name` as the
vendor-native string.  Cross-vendor translation depends on the
per-pane port-rename mesh:

* Aruba `1` -> Junos `ge-0/0/0` (standalone-switch default;
  operator-overridable).
* Aruba `A1` -> Junos `ge-0/0/0` (5400R chassis default).
* Aruba `1/1` -> Junos `ge-0/0/0` (2930M stack default).
* Aruba `Trk1` -> Junos `ae0` (LAG index translates).

Speed-hint inference:

* Aruba source -> Junos render: AOS-S carries no speed hint on the
  port name, so the rename mesh defaults to `ge-` (gigabit).  10G /
  25G / 100G ports require operator override via the per-pane
  port-name surface (typically `xe-` / `mge-` / `et-`).
* Junos source -> Aruba render: the Junos prefix carries the speed
  hint; Aruba's bare-numeric form drops it.  The render emits a
  bare `1` regardless of source speed.

Logical-interface mapping:

* Aruba VLAN-absorbed SVI -> Junos `irb.<vlan-id>` unit.  Aruba does
  not have a port-named SVI; the canonical model records the SVI
  addresses on `CanonicalVlan.ipv4_addresses` and the Junos render
  synthesises the `irb` parent + per-VLAN unit.

Disposition: **lossy** for the speed hint and SVI synthesis; the
`name` round-trips via the rename mesh.
