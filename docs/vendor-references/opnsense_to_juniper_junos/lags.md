# Link aggregation (LAGs): OPNsense versus Junos

## OPNsense

Source: [OPNsense Devices manual (LAGG tab)](https://docs.opnsense.org/manual/other-interfaces.html)
Retrieved: 2026-04-30

```xml
<laggs version="1.0.0">
  <lagg uuid="...">
    <laggif>lagg0</laggif>
    <members>opt3,opt4</members>
    <proto>lacp</proto>
    <descr>Bonded uplink to core switch</descr>
  </lagg>
</laggs>
```

OPNsense LAG notes:

- LAG bundle named `lagg<N>` (FreeBSD lagg(4) driver naming;
  zero-based).
- `<members>` is a comma-separated list of interface NAMES (zone
  labels or BSD device names).
- `<proto>` enumerates: `lacp`, `failover`, `loadbalance`,
  `roundrobin`, `none`.  No active/passive distinction — FreeBSD
  always advertises actively when LACP is selected.
- Reverse-link: each member `CanonicalInterface.lag_member_of`
  points to `lagg<N>`.

## Junos

Source: [Junos LAG overview topic-map](https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/lag-overview.html)
Source: [Junos aggregated-Ethernet configuration example](https://www.juniper.net/documentation/us/en/software/junos/sampling-forwarding-monitoring/topics/example/lag-aggregated-ethernet-link-configuring.html)
Retrieved: 2026-05-01

```
set chassis aggregated-devices ethernet device-count 4

set interfaces ge-0/0/2 ether-options 802.3ad ae0
set interfaces ge-0/0/3 ether-options 802.3ad ae0

set interfaces ae0 description "Bonded uplink"
set interfaces ae0 aggregated-ether-options lacp active
set interfaces ae0 unit 0 family inet address 10.1.0.1/31
```

Junos LAG notes:

- LAG bundle named `ae<N>` (zero-based).
- Members declare bundle membership via `set interfaces ge-0/0/X
  ether-options 802.3ad <ae-name>` (back-pointer pattern).
- LACP mode set on the bundle: `aggregated-ether-options lacp
  active` / `passive`.
- Chassis-wide `device-count` must be declared first.

## Cross-vendor mapping

OPNsense -> Junos:

- `lags[].name`: **lossy** — OPNsense `lagg<N>` ↔ Junos `ae<N>`.
  Both zero-based, structurally similar; port-rename mesh handles
  the prefix substitution.
- `lags[].members`: **lossy** — OPNsense's comma-separated
  `<members>` flattens to canonical `members: list[str]`; Junos
  emits per-member `set interfaces X ether-options 802.3ad ae<N>`.
  Member names rename via the port-rename mesh.
- `lags[].mode`: **lossy** — OPNsense `<proto>lacp</proto>` maps
  to Junos `aggregated-ether-options lacp active` (default to
  `active` on render — OPNsense doesn't carry the active/passive
  discriminator).
- Chassis `device-count` synthesis: OPNsense never declares one;
  Junos render synthesises a default value (typically equal to the
  number of `ae<N>` interfaces in the canonical tree).

Caveat: opnsense codec parses `<laggs>` but its capability matrix
doesn't currently advertise `/lag/aggregate`; the canonical
`CanonicalLAG` records may not populate fully.  Marked `lossy`
rather than `good` accordingly.

Disposition: **lossy** — name rename + LACP-mode synthesis +
codec wire-up gap.
