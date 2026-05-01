# LAGs: Aruba AOS-S `Trk<N>` versus OPNsense `lagg(4)`

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 Advanced Traffic Management Guide —
Trunking](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
trunk 23-24 trk1 lacp
trunk A3-A4 trk2 trunk
```

- `trunk <ports> trk<N> <mode>` is the LAG declaration.  Members
  appear as a port-list on the same line; the LAG itself is named
  `Trk<N>` (note: the keyword is lowercase `trk` in the directive
  but the `show` output and `interface Trk<N>` reference use a
  capital T).
- Modes:
  - `lacp` — active LACP.
  - `trunk` — Aruba's static-trunk mode (no LACP negotiation).
  - `dt-lacp` — distributed-trunk LACP (multi-chassis on stacks).
  - `fec` — Fast EtherChannel, HP-proprietary; deprecated.

## OPNsense

Source: [OPNsense Devices manual — LAGG tab](https://docs.opnsense.org/manual/other-interfaces.html)
Retrieved: 2026-04-30

OPNsense uses the FreeBSD `lagg(4)` driver with `<laggs>` /
`<lagg>` elements:

```xml
<opnsense>
  <laggs>
    <lagg>
      <laggif>lagg0</laggif>
      <members>em2,em3</members>
      <proto>lacp</proto>
      <descr>Uplink to core</descr>
    </lagg>
  </laggs>
</opnsense>
```

- `<laggif>` — synthesised device name (`lagg0`, `lagg1`, …).
- `<members>` — comma-separated list of member NIC device names.
- `<proto>` — protocol; values include `lacp`, `failover`,
  `loadbalance`, `roundrobin`, `none`.  FreeBSD always advertises
  LACP actively when `proto=lacp`; there is no passive variant.

## Cross-vendor mapping

Canonical fields (`CanonicalLAG`):

```
name: str
members: list[str]
mode: str       # "active" | "passive" | "static"
```

Plus the back-pointer on each member interface:
`CanonicalInterface.lag_member_of`.

Aruba -> OPNsense:

- `lags[].name`: **lossy** — Aruba `Trk1` ↔ OPNsense `lagg0`.  The
  port-rename mesh handles the conversion via the codec's
  port-naming delegates.  Aruba's one-based numbering versus
  FreeBSD's zero-based numbering means a literal `Trk1` does not
  match `lagg1` — operators expect `Trk1` ↔ `lagg0`.
- `lags[].members`: **lossy** — Aruba's bare-numeric port list
  (`23-24`) maps to OPNsense's BSD device names (`em22,em23`) via
  the rename mesh.  Aruba's range-syntax expansion (`23-24` → two
  members) lands as a comma-separated list on render.
- `lags[].mode`: **lossy** — Aruba `lacp` / `dt-lacp` / `fec` /
  `trunk` collapse to OPNsense `<proto>lacp</proto>` /
  `<proto>none</proto>` (static).  FreeBSD has no PAgP / passive-LACP
  / Cisco-equivalent variants; mode degrades.
- `interfaces[].lag_member_of`: **lossy** — both codecs round-trip
  the back-pointer but the LAG name itself differs (`Trk1` versus
  `lagg0`).
- The OPNsense codec capability matrix does not currently advertise
  `/lag/aggregate` in its supported set; render is partial pending
  wire-up.
