# LAGs: OPNsense `lagg(4)` versus Aruba `Trk<N>`

## OPNsense

Source: [OPNsense Devices manual — LAGG tab](https://docs.opnsense.org/manual/other-interfaces.html)
Retrieved: 2026-04-30
Source: [FreeBSD lagg(4)](https://man.freebsd.org/cgi/man.cgi?query=lagg&sektion=4)

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
- `<proto>` values: `lacp` (FreeBSD always advertises actively);
  `failover` (by default accepts traffic only on the active port,
  and needs no aggregate on the peer); `fec`, `loadbalance`,
  `roundrobin` (static aggregates: the peer's ports are grouped,
  with no LACP); `none` (passes no traffic, per lagg(4)).

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

- `lags[].name`: **lossy** — OPNsense `lagg<N>` ↔ Aruba `Trk<N>`.  The
  port translator keeps the number (`lagg5` is `Trk5`); `lagg0`,
  which AOS-S has no number for, is written `Trk1`, so `lagg0` beside
  `lagg1` is two LAGs on one name: the job is `partial` and lists
  both, and an entry in the port map settles it.  There is no +1
  offset.  The bare pipeline (`run_plan`) translates no port names,
  and writes `lagg0`'s members as `trunk <ports> trk0`.
- `lags[].members`: **lossy** — OPNsense's BSD device names map to
  Aruba's bare-numeric / letter-uplink form via the rename mesh.
- `lags[].mode`: **lossy** — OPNsense `proto=lacp` →
  Aruba `lacp`; `loadbalance` / `fec` / `roundrobin` → Aruba
  `trunk` (static); so does `proto=none`, which passes no traffic
  on OPNsense (a known limitation: the tree has no value for it).
  OPNsense `failover` needs no aggregate on the peer, and AOS-S has
  no such bond: it is written `trunk <ports> trk<N> trunk` with a
  review line beside it and a job warning, and the switch's ports
  must then be configured as that static trunk (or the host bond
  re-designed).
- `interfaces[].lag_member_of`: **lossy** — back-pointer
  round-trips via `lag_member_of`, but the LAG name itself differs
  across the rename mesh.
