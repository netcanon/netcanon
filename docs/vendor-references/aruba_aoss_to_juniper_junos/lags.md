# LAGs (Trk / aggregated-Ethernet): Aruba AOS-S versus Juniper Junos

How link aggregation groups are declared on each platform.

Sources:
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/lag-overview.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/sampling-forwarding-monitoring/topics/example/lag-aggregated-ethernet-link-configuring.html (retrieved 2026-05-01)

Citation ids: `aruba-lags`, `junos-lag-overview`, `junos-ae-example`.

## Aruba AOS-S form

AOS-S uses a single global `trunk` declaration:

```
trunk 1-4 trk1 lacp
trunk A1,A2 trk2 trunk
trunk 25,26 trk3 dt-lacp
trunk 5,6 trk4 fec
```

Trunk-type values:

- `lacp` — 802.3ad dynamic LACP -> canonical `mode="active"`.
- `trunk` — static / manual aggregation -> canonical `mode="static"`.
- `fec` — HP-proprietary Fast EtherChannel (legacy, dead grammar)
  -> canonical `mode="static"`.
- `dt-lacp` — distributed-trunk LACP (multi-chassis, AOS-S
  stack-only feature) -> canonical `mode="active"`.

The aggregated logical interface name takes the form `Trk<N>`.

## Junos form

Junos LAGs are aggregated-Ethernet (`ae<N>`) interfaces; chassis-wide
device-count must be allocated explicitly:

```
set chassis aggregated-devices ethernet device-count 2

set interfaces ge-0/0/2 ether-options 802.3ad ae0
set interfaces ge-0/0/3 ether-options 802.3ad ae0
set interfaces ge-0/0/4 ether-options 802.3ad ae1
set interfaces ge-0/0/5 ether-options 802.3ad ae1

set interfaces ae0 description "Bonded uplink to spine"
set interfaces ae0 aggregated-ether-options lacp active
set interfaces ae0 unit 0 family inet address 10.1.0.1/31

set interfaces ae1 aggregated-ether-options lacp passive
```

LACP modes: `active` / `passive` (LACP).  Static LAG is achieved
by omitting the `lacp` block (membership only via 802.3ad).

## Cross-vendor mapping

The canonical model is `CanonicalLAG(name, members, mode)`.

Aruba -> Junos specifics:

* `name`: Aruba `Trk1` -> Junos `ae0` (zero-based default mapping).
  Junos's per-LAG numeric index is independent of the Aruba `Trk<N>`
  suffix; the codec render maps `Trk1` -> `ae0`, `Trk2` -> `ae1`,
  preserving sequential ordering.  Operators may override via the
  port-rename surface.
* `members`: list of Aruba member ports (e.g. `1-4`) expands to four
  canonical port records on parse via `_parse_port_list`; Junos
  render emits `set interfaces <renamed> ether-options 802.3ad ae<N>`
  per member, plus a chassis-wide
  `set chassis aggregated-devices ethernet device-count <N>` based
  on the number of distinct LAGs in the tree.
* `mode`: `active` round-trips cleanly.  `static` flattens to "no
  LACP" on Junos render (membership without
  `aggregated-ether-options lacp`).  Aruba's `dt-lacp`
  (multi-chassis) collapses to `active` with a
  `! NOTE: source dt-lacp ...` comment — Junos has no MC-LAG
  parallel on EX/QFX without dedicated Virtual Chassis or MC-LAG
  configuration that lives outside this LAG primitive.
* `fec` (Fast EtherChannel, dead grammar) collapses to `static`.

Note: the juniper_junos codec does NOT populate `CanonicalLAG`
records on parse today — LAG membership lives on
`CanonicalInterface.lag_member_of` (the back-pointer per the
`channel-group` pattern).  Junos source -> Aruba render reconstructs
LAG records from the back-pointer; Aruba source -> Junos render
walks the explicit `CanonicalLAG` list.  This asymmetry is internal
to each codec and does not affect cross-vendor round-trip when both
sides preserve the back-pointer.

Disposition: **lossy** (LAG name index translation + Aruba-unique
`dt-lacp` / `fec` modes collapse + Junos `device-count` synthesis).
