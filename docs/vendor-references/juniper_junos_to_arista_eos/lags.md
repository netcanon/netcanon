# LAGs (aggregated Ethernet, port-channel)

Link-aggregation group naming and member-binding on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/lag-overview.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/sampling-forwarding-monitoring/topics/example/lag-aggregated-ethernet-link-configuring.html (retrieved 2026-05-01)
- Arista: https://www.arista.com/en/um-eos/eos-port-channels (retrieved 2026-05-01)

Citation ids: `junos-lag-overview`, `junos-ae-example`,
`arista-port-channels`.

## Junos form

```
set chassis aggregated-devices ethernet device-count 4

set interfaces ae0 description "uplink-bundle"
set interfaces ae0 aggregated-ether-options lacp active
set interfaces ae0 aggregated-ether-options minimum-links 1
set interfaces ae0 unit 0 family ethernet-switching interface-mode trunk
set interfaces ae0 unit 0 family ethernet-switching vlan members [ v100 v200 ]

set interfaces ge-0/0/10 ether-options 802.3ad ae0
set interfaces ge-0/0/11 ether-options 802.3ad ae0
```

Junos requires a chassis-wide `aggregated-devices ethernet device-count`
hint declaring how many AE interfaces will exist.  Member binding
uses `set interfaces <member> ether-options 802.3ad ae<N>` (or
`gigether-options 802.3ad ae<N>` on older interface speed shapes).
LACP mode (`active` / `passive`) lives on the LAG itself.

Naming: `ae<N>`, **zero-based** (`ae0`, `ae1`, ...).

## Arista form

```
interface Port-Channel1
   description uplink-bundle
   port-channel lacp mode active
   port-channel min-links 1
   switchport mode trunk
   switchport trunk allowed vlan 100,200

interface Ethernet10
   channel-group 1 mode active

interface Ethernet11
   channel-group 1 mode active
```

Arista has no chassis-wide pre-declaration.  Member binding lives on
the member interface as `channel-group <N> mode <active | passive |
on>`.  LACP mode is per-member (not per-LAG); active/passive must
agree across members.

Naming: `Port-Channel<N>`, **one-based** typically (`Port-Channel1`,
`Port-Channel2`, ...) — though `Port-Channel0` is technically valid.

## Mapping notes

- **Index translation.** Junos `ae0` <-> Arista `Port-Channel1` is
  the documented default convention (zero-based -> one-based).
  Some operators prefer index-preserving (`ae5` -> `Port-Channel5`);
  the codec exposes a per-pane override.  Default rename mesh
  applies the +1 offset.
- **LACP mode.** Junos's per-LAG `aggregated-ether-options lacp
  {active|passive}` collapses onto the per-member
  `channel-group N mode {active|passive}` directives in Arista —
  applied uniformly to all members.  Round-trip preserves the
  active/passive distinction.
- **Static (no LACP) LAG.** Junos LAG without `lacp` block ->
  Arista `channel-group N mode on`.
- **Minimum links.** Junos `aggregated-ether-options minimum-links
  N` -> Arista `port-channel min-links N`.  Direct one-to-one.
- **Chassis-wide device-count.** Junos's `set chassis
  aggregated-devices ethernet device-count N` has no Arista
  parallel — drops on render (Arista provisions LAGs on demand).
  Lossy structural detail; functional equivalence preserved.
- **Per-LAG VLAN membership.** Junos models VLAN membership on the
  LAG's unit (`set interfaces ae0 unit 0 family ethernet-switching
  vlan members ...`).  Arista's `Port-Channel<N>` interface stanza
  carries `switchport` directly.  Canonical layer transposes via
  the same per-VLAN port-list mechanism used for physical
  interfaces.
- **Note on codec capability matrix.** The juniper_junos codec's
  `/lags/lag` capability surface determines whether explicit
  `CanonicalLAG` records populate or whether the
  `CanonicalInterface.lag_member_of` back-pointer is the surviving
  primitive.  Where the explicit list is empty, the back-pointer
  reconstruction on render still produces a valid Arista
  `Port-Channel` stanza.
