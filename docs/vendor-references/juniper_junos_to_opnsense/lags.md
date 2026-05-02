# Link aggregation (LAGs): Junos versus OPNsense

## Junos

Source: [Junos LAG overview topic-map](https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/lag-overview.html)
Source: [Junos aggregated-Ethernet configuration example](https://www.juniper.net/documentation/us/en/software/junos/sampling-forwarding-monitoring/topics/example/lag-aggregated-ethernet-link-configuring.html)
Retrieved: 2026-05-01

```
set chassis aggregated-devices ethernet device-count 4

set interfaces ge-0/0/2 description "LAG ae0 member 1"
set interfaces ge-0/0/2 ether-options 802.3ad ae0
set interfaces ge-0/0/3 description "LAG ae0 member 2"
set interfaces ge-0/0/3 ether-options 802.3ad ae0

set interfaces ae0 description "Bonded uplink to spine"
set interfaces ae0 mtu 9192
set interfaces ae0 aggregated-ether-options lacp active
set interfaces ae0 unit 0 family inet address 10.1.0.1/31
```

Junos LAG notes:

- LAG bundle named `ae<N>` (zero-based, `ae0`, `ae1`, ...).
- Members declare bundle membership via `set interfaces ge-0/0/X
  ether-options 802.3ad <ae-name>` (back-pointer pattern).
- LACP mode set on the bundle: `aggregated-ether-options lacp active`
  / `passive`.  Static (no-LACP) bundling is supported by omitting
  the `lacp` line.
- Chassis-wide `device-count` must be declared first (Junos doesn't
  auto-allocate `ae` interfaces).

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
- `<proto>` enumerates: `lacp` (the common case), `failover`,
  `loadbalance`, `roundrobin`, `none`.  No active/passive
  distinction — FreeBSD always advertises actively.
- No chassis-wide allocation step — `<lagg>` elements are added
  ad-hoc.

## Cross-vendor mapping

Junos -> OPNsense:

- `lags[].name`: **lossy** — Junos `ae<N>` ↔ OPNsense `lagg<N>`.
  Both are zero-based and structurally similar but the prefix
  differs; port-rename mesh handles the substitution.
- `lags[].members`: **lossy** — Junos populates members via the
  per-member `ether-options 802.3ad` back-pointer; canonical
  `CanonicalLAG.members` lists the member-interface names.
  OPNsense `<members>` round-trips the list as a comma-separated
  string.  Member names themselves rename via the port-rename
  mesh (Junos `ge-0/0/2` → some OPNsense zone label).
- `lags[].mode`: **lossy** — Junos's three-way `active` / `passive` /
  static collapses to OPNsense's single `<proto>lacp</proto>`
  (FreeBSD always advertises actively).  Static-mode Junos LAGs
  cross-pair degrades to LACP on OPNsense.
- LACP timeout (`fast` / `slow`) is not modelled canonically; drops.

Caveat: the juniper_junos codec parses LAG members today (the
`ae0` interface still materialises as a `CanonicalInterface`),
but `CanonicalLAG.members` population from `ether-options 802.3ad`
back-pointers depends on codec wire-up.

Disposition: **lossy** — name rename + LACP-mode collapse +
codec wire-up gap in the OPNsense capability matrix
(`/lag/aggregate` is not advertised on either side; render
is partial).
