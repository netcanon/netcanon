# LAGs: Arista EOS `Port-Channel<N>` versus OPNsense `lagg(4)`

## Arista EOS

Source: [Arista EOS User Manual — Port Channels and LACP](https://www.arista.com/en/um-eos/eos-port-channels-and-lacp)
Retrieved: 2026-05-01

Arista declares LAG membership per-member-port via `channel-group`;
the LAG itself appears as `interface Port-Channel<N>` with its own
L3 / switchport state:

```
interface Ethernet4
   description "LAG member 1"
   channel-group 10 mode active
!
interface Ethernet5
   description "LAG member 2"
   channel-group 10 mode active
!
interface Port-Channel10
   description "Bonded uplink to core"
   no switchport
   ip address 10.0.1.1/31
```

Arista LAG notes:

- `channel-group <N> mode {active|passive|on}` — `active` and
  `passive` are LACP variants; `on` is static (no LACP frames).
- The LAG-level interface uses Capital-C `Port-Channel` (Arista
  convention), distinguishing from Cisco's `Port-channel`.
- LAGs accept the same switchport / L3 / VRF / IP address
  attributes as physical interfaces.
- Arista has no PAgP equivalent (PAgP is Cisco-proprietary).

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

- `<laggif>` — synthesised device name (`lagg0`, `lagg1`, …);
  zero-based.
- `<members>` — comma-separated list of member NIC device names.
- `<proto>` values: `lacp` (always advertises actively),
  `failover`, `loadbalance`, `roundrobin`, `none` (static).
- A member is an UNASSIGNED interface: "Only unassigned interfaces can
  be added to LAGG" (same page, Other Types).  So a member is named in
  `<laggs>` and in no zone of `<interfaces>`, and has no description,
  MTU, address or `<enable/>` of its own in the config.  Netcanon
  writes a LAG member onto OPNsense in `<members>` alone, and says in a
  comment in the `<lagg>` which elements the source gave the member
  that are not written (added 2026-10-20).

## Cross-vendor mapping (Arista -> OPNsense)

Canonical fields (`CanonicalLAG`):

```
name: str
members: list[str]
mode: str       # "active" | "passive" | "static"
```

Plus the back-pointer on each member interface:
`CanonicalInterface.lag_member_of`.

- `lags[].name`: **lossy** — Arista `Port-Channel10` ↔ OPNsense
  `lagg0`.  Arista is one-based and uses a textual prefix;
  FreeBSD is zero-based.  Port-rename mesh handles
  canonicalisation via the codec's port-naming delegates.
- `lags[].members`: **lossy** — Arista members are
  `Ethernet<N>` device names; OPNsense members are BSD device
  names (`em2`, `igb1`, …).  Rename mesh translates.
- `lags[].mode`: **lossy** — Arista `active` / `passive` collapse
  to OPNsense `<proto>lacp</proto>` (FreeBSD always advertises
  actively); Arista `on` (static) maps to `<proto>none</proto>`.
  Passive variant does not survive.
- `interfaces[].lag_member_of`: **lossy** — both codecs
  round-trip the back-pointer but the LAG name itself differs
  (`Port-Channel10` versus `lagg0`).
- The OPNsense codec capability matrix does not currently
  advertise `/lag/aggregate` in its supported set; render is
  partial pending wire-up.
