# Port naming: Juniper Junos versus Aruba AOS-S

How physical and logical interfaces are named on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/en_US/junos12.3/topics/concept/interfaces-naming-conventions-qfx-series.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/interfaces-fundamentals/topics/topic-map/interfaces-interface-naming-overview.html (retrieved 2026-05-01)
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/BOG/2930F-3810-5400/index.htm (retrieved 2026-05-01)

Citation ids: `junos-iface-naming`, `aruba-port-naming`.

## Junos form

Junos encodes media + FPC + PIC + port (+ optional unit):

```
ge-0/0/0       Gigabit Ethernet, FPC 0, PIC 0, port 0
xe-0/0/0       10-Gigabit Ethernet
et-0/0/48      40 / 100 Gigabit Ethernet
mge-0/0/0      Multi-rate Gigabit Ethernet
fe-0/0/0       Fast Ethernet (legacy)
```

Logical:

- `lo0`, `lo0.0` (loopback)
- `irb.100` (Integrated Routing and Bridging — SVI)
- `ae0`, `ae0.0` (aggregated Ethernet — LAG)
- `me0`, `em0`, `fxp0` (out-of-band management)
- Sub-interface units like `ge-0/0/1.100` (logical unit 100 with
  per-unit `vlan-id` for tagged sub-interfaces)

## Aruba AOS-S form

Bare numeric port identifiers — no speed prefix:

```
interface 1                          ; standalone-switch port 1
interface A1                         ; 5400R chassis: module A, port 1
interface 1/1                        ; 2930M stack: stack-member 1, port 1
interface Trk1                       ; LAG (link-aggregation) trunk
```

There is no SVI port-name on Aruba — the L3 address absorbs into the
VLAN stanza.  There is also no out-of-band management interface
type (the management VLAN is just another VLAN).

## Cross-vendor mapping

The canonical model carries `CanonicalInterface.name` as the
vendor-native string.  Cross-vendor translation depends on the
per-pane port-rename mesh:

* Junos `ge-0/0/0` -> Aruba `1` (default).
* Junos `xe-0/0/0` -> Aruba `1` (Aruba carries no speed hint, so the
  10G prefix is dropped).
* Junos `ae0` -> Aruba `Trk1` (LAG index translates).
* Junos `lo0.0` -> no Aruba equivalent; AOS-S has no first-class
  loopback construct (the management VLAN serves as the
  device-self-IP host).  The codec render emits a `;` comment.
* Junos `irb.100` -> Aruba VLAN-absorbed SVI.  The canonical model
  records the IRB addresses on `CanonicalVlan.ipv4_addresses` (via
  the `l3-interface irb.<id>` link); Aruba render emits the `ip
  address` directive directly inside the matching `vlan <id>`
  stanza, NOT as a separate interface.
* Junos sub-interface `ge-0/0/1.100` (with `unit 100 vlan-id 100`
  + `family inet address`) materialises as a distinct
  `CanonicalInterface` named `ge-0/0/1.100` with `access_vlan=100`
  populated; Aruba render emits the address directly on the renamed
  parent port as a routed L3 port.  Sub-interface tagging is lossy
  (Aruba has no first-class tagged-sub-interface model).

Speed-hint inference:

* Junos source -> Aruba render: Junos's prefix carries the speed
  hint (`xe-` = 10G, `et-` = 40/100G); Aruba's bare-numeric form
  drops it.  Operators must remember the original speed when
  configuring uplink modules.

LAG name index:

* Junos `ae0` -> Aruba `Trk1` (Junos zero-based, Aruba one-based).
  Codec render maps `ae<N>` -> `Trk<N+1>` to preserve sequential
  ordering.

Disposition: **lossy** for the speed hint, sub-interface tagging,
and loopback (no Aruba equivalent).
