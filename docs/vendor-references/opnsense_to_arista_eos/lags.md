# LAGs: OPNsense `lagg(4)` versus Arista EOS `Port-Channel<N>`

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

- `<laggif>` — synthesised device name (`lagg0`, `lagg1`, …;
  zero-based).
- `<members>` — comma-separated list of member NIC device names.
- `<proto>` values: `lacp` (always advertises actively),
  `failover`, `loadbalance`, `roundrobin`, `none` (static).

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
  passive LACP is unreachable).  OPNsense `<proto>none</proto>`
  ↔ Arista `mode on` (static).  Failover / loadbalance /
  roundrobin variants have no Arista equivalent and collapse to
  static with a comment.
- `interfaces[].lag_member_of`: **lossy** — both codecs
  round-trip the back-pointer but the LAG name itself differs;
  port-rename mesh canonicalises.
- The OPNsense codec capability matrix does not currently
  advertise `/lag/aggregate` in its supported set; round-trip
  is partial pending wire-up.
