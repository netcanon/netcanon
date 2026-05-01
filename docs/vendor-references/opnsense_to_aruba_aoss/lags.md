# LAGs: OPNsense `lagg(4)` versus Aruba `Trk<N>`

## OPNsense

Source: [OPNsense Devices manual — LAGG tab](https://docs.opnsense.org/manual/other-interfaces.html)
Retrieved: 2026-04-30

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

OPNsense LAG notes:

- FreeBSD `lagg(4)` driver synthesises `lagg<N>` device names
  (zero-based).
- `<members>` is a comma-separated list of BSD NIC device names.
- `<proto>` values: `lacp` (FreeBSD always advertises actively),
  `failover`, `loadbalance`, `roundrobin`, `none` (static).

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 Advanced Traffic Management Guide —
Trunking](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
trunk 23-24 trk1 lacp
trunk A3-A4 trk2 trunk
```

Aruba LAG notes:

- One-based naming: `Trk1`, `Trk2`, …
- Modes: `lacp` (active LACP), `trunk` (static), `dt-lacp`
  (distributed-trunk on stacks), `fec` (HP-proprietary, deprecated).

## Cross-vendor mapping

Canonical fields (`CanonicalLAG`):

```
name, members: list[str], mode
```

Plus `CanonicalInterface.lag_member_of` back-pointer.

OPNsense -> Aruba:

- `lags[].name`: **lossy** — OPNsense `lagg0` ↔ Aruba `Trk1`.
  Zero-based vs one-based numbering means a literal name does NOT
  match — operators expect `lagg0` ↔ `Trk1`.  The port-rename
  mesh handles the conversion.
- `lags[].members`: **lossy** — OPNsense's BSD device names map to
  Aruba's bare-numeric / letter-uplink form via the rename mesh.
- `lags[].mode`: **lossy** — OPNsense `proto=lacp` →
  Aruba `lacp`; `proto=none` → Aruba `trunk` (static).  OPNsense
  `failover` / `loadbalance` / `roundrobin` have no Aruba LACP
  equivalent and collapse to `trunk` with a comment in the
  validation report.
- `interfaces[].lag_member_of`: **lossy** — back-pointer
  round-trips via `lag_member_of`, but the LAG name itself differs
  across the rename mesh.
