# LAGs (aggregated-Ethernet / Trk): Juniper Junos versus Aruba AOS-S

How link aggregation groups are declared on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/lag-overview.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/sampling-forwarding-monitoring/topics/example/lag-aggregated-ethernet-link-configuring.html (retrieved 2026-05-01)
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm (retrieved 2026-05-01)

Citation ids: `junos-lag-overview`, `junos-ae-example`,
`aruba-lags`.

## Junos form

LAGs are aggregated-Ethernet (`ae<N>`) interfaces; chassis-wide
device-count is allocated explicitly:

```
set chassis aggregated-devices ethernet device-count 2

set interfaces ge-0/0/2 ether-options 802.3ad ae0
set interfaces ge-0/0/3 ether-options 802.3ad ae0

set interfaces ae0 description "Bonded uplink to spine"
set interfaces ae0 aggregated-ether-options lacp active
set interfaces ae0 unit 0 family inet address 10.1.0.1/31
```

LACP modes: `active` / `passive` (LACP).  Static LAG is achieved by
omitting the `lacp` block.

## Aruba AOS-S form

```
trunk 1-4 trk1 lacp
trunk A1,A2 trk2 trunk
trunk 25,26 trk3 dt-lacp
```

Trunk-type values map to canonical mode: `lacp` -> `"active"`,
`trunk` -> `"static"`, `fec` -> `"static"` (legacy), `dt-lacp` ->
`"active"` (multi-chassis).

## Cross-vendor mapping

Canonical `CanonicalLAG(name, members, mode)`.

Junos -> Aruba specifics (per the Junos codec's parse-side state):

* `name`: Junos `ae0` -> Aruba `Trk1` (zero-based -> one-based
  default mapping; codec render maps `ae<N>` -> `Trk<N+1>`).
  Operators may override via the port-rename surface.
* `members`: the juniper_junos codec parses LAG membership via the
  per-member `ether-options 802.3ad ae<N>` line and stores the
  back-pointer on `CanonicalInterface.lag_member_of`.  Aruba render
  emits a `trunk <port-list> trk<N> lacp|trunk` line with the
  members reconstructed from the back-pointer list.
* `mode`: Junos's `lacp active` / `lacp passive` -> Aruba `lacp` (a
  single LACP token; Aruba does not distinguish active/passive at
  the trunk-type level).  Static (no `lacp` block) -> Aruba `trunk`.
* Junos's chassis-wide `aggregated-devices ethernet device-count`
  has no Aruba parallel — it drops on render (Aruba does not
  require explicit device-count allocation).

Note: the juniper_junos codec capability matrix today does NOT
explicitly list `/lags/lag` under supported, so LAG canonical
records may not populate from Junos parse in v1 — the
`CanonicalInterface.lag_member_of` back-pointer is the surviving
primitive.  Aruba render reconstructs `trunk` lines from the back-
pointer.  Lossy by deferral on the explicit `CanonicalLAG` list
shape.

Disposition: **lossy** (LACP active/passive collapse + index
translation + canonical-list parse gap on Junos).
