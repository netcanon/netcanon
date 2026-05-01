# LAGs / aggregated Ethernet: Cisco IOS-XE versus Juniper Junos

How port-channels (Cisco) and aggregated-Ethernet bundles (Junos)
are declared.

Sources:
- Cisco: https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-9/configuration_guide/lyr2/b_179_lyr2_9300_cg/configuring_etherchannels.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/lag-overview.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/sampling-forwarding-monitoring/topics/example/lag-aggregated-ethernet-link-configuring.html (retrieved 2026-04-30)

Citation ids: `cisco-etherchannel`, `junos-lag-overview`, `junos-ae-example`.

## Cisco IOS-XE form

```
interface Port-channel10
 description Uplink-LAG
 switchport mode trunk
 switchport trunk allowed vlan 100,200

interface GigabitEthernet1/0/1
 channel-group 10 mode active

interface GigabitEthernet1/0/2
 channel-group 10 mode active
```

LACP modes: `active`, `passive`, `on` (static), `auto` / `desirable`
(legacy PAgP — Cisco-only).

## Junos form

```
set chassis aggregated-devices ethernet device-count 16

set interfaces ae10 description Uplink-LAG
set interfaces ae10 aggregated-ether-options lacp active
set interfaces ae10 unit 0 family ethernet-switching interface-mode trunk
set interfaces ae10 unit 0 family ethernet-switching vlan members [ v100 v200 ]

set interfaces ge-0/0/0 gigether-options 802.3ad ae10
set interfaces ge-0/0/1 gigether-options 802.3ad ae10
```

LACP modes on the parent: `active`, `passive`.  Static (no LACP):
omit the `aggregated-ether-options lacp` line entirely.  Junos
requires explicit `device-count` allocation for `ae` interfaces.

## Mapping notes

- **Naming.** Cisco `Port-channel10` (lower-case `c`) <-> Junos
  `ae10`.  Canonical `CanonicalLAG.name` preserves the source
  form; the port-rename mesh translates.
- **Member binding.** Cisco's `channel-group <N> mode <m>` on the
  member side maps to Junos's `gigether-options 802.3ad ae<N>` on
  the member side.  Canonical
  `CanonicalInterface.lag_member_of` is the back-pointer.
- **LACP mode.** Cisco's `active` / `passive` / `on` -> Junos's
  `active` / `passive` / (omitted, for static).  PAgP modes
  (`auto` / `desirable`) are Cisco-only; canonical preserves the
  string but Junos render emits a comment for unsupported modes.
- **Device-count.** Junos's required `set chassis
  aggregated-devices ethernet device-count <N>` allocation has no
  Cisco equivalent (Cisco auto-allocates).  Junos render must
  emit a sensible default (typically 16 or 32) on Cisco -> Junos.
- **Sub-units.** Junos LAG units carry their own
  `family ethernet-switching` (or `family inet`) hierarchy; Cisco
  treats the `Port-channel<N>` as a regular interface with all
  switchport / IP config inline.  Both flatten to the same
  canonical `lags[]` + per-interface `switchport_mode` shape.

Disposition: **good** on member list, name, mode (active /
passive); **lossy** on PAgP modes (Cisco-only) and on the implicit
device-count allocation.
