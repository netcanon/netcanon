# LAGs: OPNsense `lagg(4)` versus Arista EOS `Port-Channel<N>`

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

- `<laggif>` — synthesised device name (`lagg0`, `lagg1`, …;
  zero-based).
- `<members>` — comma-separated list of member NIC device names.
- `<proto>` values: `lacp` (always advertises actively);
  `failover` (by default accepts traffic only on the active port,
  and needs no aggregate on the peer); `fec`, `loadbalance`,
  `roundrobin` (static aggregates: the peer's ports are grouped,
  with no LACP); `none` (passes no traffic, per lagg(4)).

## Arista EOS

Source: [Arista EOS User Manual — Port Channels and LACP](https://www.arista.com/en/um-eos/eos-port-channels-and-lacp)
Retrieved: 2026-05-01

```
interface Ethernet4
   channel-group 10 mode active
!
interface Ethernet5
   channel-group 10 mode active
!
interface Port-Channel10
   description "Bonded uplink to core"
   no switchport
   ip address 10.0.1.1/31
```

- `channel-group <N> mode {active|passive|on}` — `active` and
  `passive` are LACP variants; `on` is static.
- The LAG-level interface uses Capital-C `Port-Channel`.
- One-based numbering.

## Cross-vendor mapping (OPNsense -> Arista EOS)

Canonical fields (`CanonicalLAG`).

- `lags[].name`: **lossy** — OPNsense `lagg<N>` ↔ Arista
  `Port-Channel<N>`, a textual-prefix swap.  The port translator
  keeps the number (`lagg5` is `Port-Channel5`); `lagg0`, which EOS
  has no number for, is written `Port-Channel1`, so `lagg0` beside
  `lagg1` is two LAGs on one name: the job is `partial` and lists
  both, and an entry in the port map settles it.  There is no +1
  offset.  The bare pipeline (`run_plan`) translates no port names,
  and writes `lagg0` as `Port-Channel0`.
- `lags[].members`: **lossy** — OPNsense BSD device names
  (`em2`, `igb1`, …) versus Arista `Ethernet<N>`; rename mesh
  translates.
- `lags[].mode`: **lossy** — OPNsense `<proto>lacp</proto>` ↔
  Arista `mode active` (FreeBSD always advertises actively, so
  passive LACP is unreachable).  OPNsense `loadbalance`, `fec` and
  `roundrobin` are read as a static aggregate and written Arista
  `mode on`; so is `none`, which passes no traffic on OPNsense (a
  known limitation: the tree has no value for it).  `failover`
  needs no aggregate on the peer, and Arista has no such bond: it
  is written `channel-group N mode on` with a `! review:` line and
  a job warning, and the switch's ports must then be configured as
  that static aggregate (or the host bond re-designed).
- `interfaces[].lag_member_of`: **lossy** — both codecs
  round-trip the back-pointer but the LAG name itself differs;
  port-rename mesh canonicalises.
- The OPNsense codec capability matrix classifies `/lags/lag/name` and
  `/lags/lag/members` as supported and `/lags/lag/mode` as lossy.
