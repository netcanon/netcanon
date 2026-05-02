# LAGs: OPNsense versus FortiGate FortiOS

Reverse direction.  Forward direction in
`../fortigate_cli_to_opnsense/lags.md`.

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

OPNsense notes:

- LAGs use FreeBSD `lagg(4)` driver naming (`lagg0`, `lagg1`, ...).
  Numbering is ZERO-based.
- `<members>` is comma-separated string of BSD device names.
- `<proto>` enumerates `lacp` / `failover` / `loadbalance` /
  `roundrobin` / `none` (static).  FreeBSD's lagg(4) driver always
  advertises actively when LACP is selected.
- The lagg device shows up as `<if>lagg0</if>` on a zone interface.

## FortiGate FortiOS

See `../fortigate_cli_to_opnsense/lags.md` for the FortiGate-side
shape.  Key points:

- LAGs are interfaces of `set type aggregate`.
- Members declared as `set member "port3" "port4"` (space-separated
  quoted list).
- `set lacp-mode {active|passive|static}`.
- Aggregate names are operator-named (no fixed prefix).

## Cross-vendor mapping (OPNsense -> FortiGate)

Canonical fields covered (`CanonicalLAG`):

```
name, members, lacp_mode
```

- **lossy** — Aggregate naming collision: OPNsense FreeBSD `lagg<N>`
  (zero-based) versus FortiGate operator-named aggregates requires
  the rename mesh.  `lagg0` ↔ FortiGate `agg1` (or any operator-
  chosen name) is operator-driven.
- Members preserve via the rename mesh applied to each member name
  (OPNsense BSD `em2` -> FortiGate `port3`).  Comma-separated string
  on OPNsense becomes space-separated quoted on FortiOS — both codecs
  handle the normalisation.
- LACP mode: OPNsense `<proto>lacp</proto>` → FortiGate `set lacp-mode
  active` (FreeBSD lagg(4) always advertises actively, so the
  FortiGate target gets `active` rather than `passive`).  OPNsense
  `<proto>none</proto>` ↔ FortiGate `set lacp-mode static`.
  OPNsense's `failover` / `loadbalance` / `roundrobin` protos have
  no FortiGate LACP equivalent and collapse to `static` with a
  comment.
- The OPNsense codec parses `<laggs>` but its capability matrix does
  not currently advertise `/lag/aggregate`; round-trip is partial
  pending wire-up.
