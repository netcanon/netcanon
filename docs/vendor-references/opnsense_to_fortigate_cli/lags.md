# LAGs: OPNsense versus FortiGate FortiOS

Reverse direction.  Forward direction in
`../fortigate_cli_to_opnsense/lags.md`.

## OPNsense

Source: [OPNsense Devices manual — LAGG
tab](https://docs.opnsense.org/manual/other-interfaces.html)
Retrieved: 2026-05-01
Source: [FreeBSD lagg(4)](https://man.freebsd.org/cgi/man.cgi?query=lagg&sektion=4)

```xml
<opnsense>
  <laggs>
    <lagg uuid="...">
      <laggif>lagg0</laggif>
      <members>em2,em3</members>
      <proto>lacp</proto>
      <lacptimeout>slow</lacptimeout>
      <descr>Core Bond</descr>
    </lagg>
  </laggs>
</opnsense>
```

OPNsense notes:

- LAGs use FreeBSD `lagg(4)` driver naming (`lagg0`, `lagg1`, ...).
  Numbering is ZERO-based.
- `<members>` is comma-separated string of BSD device names.
- `<proto>` enumerates `lacp` / `failover` / `fec` / `loadbalance` /
  `roundrobin` / `none`.  `fec`, `loadbalance` and `roundrobin` are
  static (`loadbalance` "does not negotiate aggregation with the
  peer"); `failover` by default accepts traffic only on the active
  port and needs no aggregate on the peer; `none` passes no traffic
  (lagg(4)).  FreeBSD's lagg(4) driver always advertises actively
  when LACP is selected.
- The lagg device shows up as `<if>lagg0</if>` on a zone interface.

## FortiGate FortiOS

See `../fortigate_cli_to_opnsense/lags.md` for the FortiGate-side
shape.  Key points:

- LAGs are interfaces of `set type aggregate`.
- Members declared as `set member "port3" "port4"` (space-separated
  quoted list).
- `set lacp-mode {active|passive|static}`.
- `set type redundant`: "traffic only goes over one interface at any
  time" ([FortiOS Administration Guide — Aggregation and
  redundancy](https://docs.fortinet.com/document/fortigate/7.0.1/administration-guide/567758),
  retrieved 2026-11-11).
- Aggregate names are operator-named (no fixed prefix).

## Cross-vendor mapping (OPNsense -> FortiGate)

Canonical fields covered (`CanonicalLAG`):

```
name, members, mode   # mode: active | passive | static | active-backup
```

- **lossy** — Aggregate naming collision: OPNsense FreeBSD `lagg<N>`
  (zero-based) versus FortiGate operator-named aggregates.  The port
  translator writes `LAG<N>`, keeping the number (`lagg5` is `LAG5`)
  and writing `lagg0` as `LAG1`, so `lagg0` beside `lagg1` is two
  aggregates on one name (the job is `partial`).  Any other name
  (`agg1`, or any operator-chosen one) is an entry in the port map.
- Members preserve via the rename mesh applied to each member name
  (OPNsense BSD `em2` -> FortiGate `port3`).  Comma-separated string
  on OPNsense becomes space-separated quoted on FortiOS — both codecs
  handle the normalisation.
- LACP mode: OPNsense `<proto>lacp</proto>` → FortiGate `set lacp-mode
  active` (FreeBSD lagg(4) always advertises actively, so the
  FortiGate target gets `active` rather than `passive`).  OPNsense
  `loadbalance` / `fec` / `roundrobin` → FortiGate `set lacp-mode
  static`; so does `<proto>none</proto>`, which passes no traffic on
  OPNsense (a known limitation: the tree has no value for it).
  OPNsense `failover` needs no aggregate on the peer, and is
  written as a FortiOS redundant interface (`set type redundant`),
  which sends through one member at a time as `failover` does.
- The OPNsense codec's capability matrix classifies `/lags/lag/name` and
  `/lags/lag/members` as supported and `/lags/lag/mode` as lossy.
