# LAGs: FortiGate FortiOS versus OPNsense

## FortiGate FortiOS

Source: [FortiGate / FortiOS 7.4 Administration Guide — Interface
settings (aggregate
type)](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings)
Retrieved: 2026-05-01

```
config system interface
    edit "agg1"
        set vdom "root"
        set type aggregate
        set member "port3" "port4"
        set lacp-mode active
        set lacp-speed slow
        set ip 10.0.0.1 255.255.255.0
        set role lan
        set alias "Core Bond"
    next
end
```

Notes:

- LAGs are interfaces of `set type aggregate` — same edit-table
  as physical / VLAN / loopback interfaces.
- `set member "port3" "port4"` declares the bundle members as a
  space-separated quoted list.
- `set lacp-mode {active|passive|static}` — FortiOS only supports
  these three modes (no PAgP, no HP-style modes).
- The aggregate IS the parent for VLAN-children (`agg1.10` etc.)
  the same way a physical port is.
- Aggregate names are operator-named (`agg1`, `LAG_INTERNAL`, etc.).

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

Notes:

- LAGs live under `<laggs>/<lagg>` and use the FreeBSD `lagg(4)`
  driver naming (`lagg0`, `lagg1`, ...).  Numbering is ZERO-based.
- `<members>` is a comma-separated string of BSD device names
  (`em2,em3` not space-separated).
- A member is an UNASSIGNED interface: "Only unassigned interfaces can
  be added to LAGG" (same page, Other Types).  So a member is named in
  `<laggs>` and in no zone of `<interfaces>`, and has no description,
  MTU, address or `<enable/>` of its own in the config.  Netcanon
  writes a LAG member onto OPNsense in `<members>` alone, and says in a
  comment in the `<lagg>` which elements the source gave the member
  that are not written (added 2026-10-20).
- `<proto>` enumerates `lacp` / `failover` / `fec` / `loadbalance` /
  `roundrobin` / `none`.  `fec`, `loadbalance` and `roundrobin` are
  static (`loadbalance` "does not negotiate aggregation with the
  peer"); `failover` by default accepts traffic only on the active
  port and needs no aggregate on the peer; `none` passes no traffic
  (lagg(4)).  FreeBSD's lagg(4) driver always advertises actively
  when LACP is selected (no separate passive mode).
- The lagg device shows up as `<if>lagg0</if>` on a zone interface
  to use it as a routed/firewalled interface.

## Cross-vendor mapping

Canonical fields covered (`CanonicalLAG`):

```
name, members, mode   # mode: active | passive | static | active-backup
```

FortiGate -> OPNsense:

- **lossy** — Aggregate naming collision: FortiGate operator-named
  (`agg1` / `LAG_INTERNAL`) versus OPNsense FreeBSD `lagg<N>`
  (zero-based) requires the rename mesh.
- Members preserve via the rename mesh applied to each member name
  (FortiGate `port3` -> OPNsense BSD device `em2`).  Members are
  emitted as comma-separated on OPNsense versus space-separated
  quoted on FortiOS — both codecs handle the normalisation.
- LACP mode: FortiGate `active` / `passive` ↔ OPNsense
  `<proto>lacp</proto>` (the FreeBSD driver always advertises
  actively, so both Forti modes collapse to the single `lacp`
  proto).  FortiGate `static` → OPNsense `<proto>loadbalance</proto>`.
  Cross-pair degrades the active/passive distinction silently.
  A FortiOS redundant interface (`set type redundant`), in which
  "traffic only goes over one interface at any time" (FortiOS
  Administration Guide, "Aggregation and redundancy"), reads as
  `active-backup` and is written `<proto>failover</proto>`; in the
  inverse direction OPNsense `failover` reads as `active-backup` and
  is written as a redundant interface.
- The OPNsense codec's capability matrix classifies `/lags/lag/name` and
  `/lags/lag/members` as supported and `/lags/lag/mode` as lossy.
