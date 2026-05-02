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
- `<proto>` enumerates `lacp` / `failover` / `loadbalance` /
  `roundrobin` / `none` (static).  FreeBSD's lagg(4) driver always
  advertises actively when LACP is selected (no separate
  passive mode).
- The lagg device shows up as `<if>lagg0</if>` on a zone interface
  to use it as a routed/firewalled interface.

## Cross-vendor mapping

Canonical fields covered (`CanonicalLAG`):

```
name, members, lacp_mode
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
  proto).  FortiGate `static` ↔ OPNsense `<proto>none</proto>`.
  Cross-pair degrades the active/passive distinction silently.
- The OPNsense codec parses `<laggs>` but its capability matrix
  does NOT currently advertise `/lag/aggregate` under supported;
  render is partial pending wire-up.  CanonicalLAG records from a
  FortiGate source emit a banner / TODO marker on OPNsense.
