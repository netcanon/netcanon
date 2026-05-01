# LAGs / aggregated Ethernet: Juniper Junos versus Cisco IOS-XE

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/lag-overview.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/sampling-forwarding-monitoring/topics/example/lag-aggregated-ethernet-link-configuring.html (retrieved 2026-04-30)
- Cisco: https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-9/configuration_guide/lyr2/b_179_lyr2_9300_cg/configuring_etherchannels.html (retrieved 2026-04-30)

Citation ids: `junos-lag-overview`, `junos-ae-example`, `cisco-etherchannel`.

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

LACP modes: `active`, `passive`.  Static (no LACP): omit the
`aggregated-ether-options lacp` line.

Junos requires explicit chassis-wide
`device-count` allocation for `ae` interfaces.

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

LACP modes: `active`, `passive`, `on` (static).  Legacy PAgP
modes (`auto`, `desirable`) are Cisco-only.

## Mapping notes

- **Naming.** Junos `ae10` -> Cisco `Port-channel10`.  Canonical
  `CanonicalLAG.name` carries the source form.
- **Member binding.** Junos's `gigether-options 802.3ad aeN` on
  the member side maps to Cisco's `channel-group N mode <m>` on
  the member side.  Canonical
  `CanonicalInterface.lag_member_of` is the back-pointer.
- **LACP mode.** Junos's `active` / `passive` / (omitted-static)
  -> Cisco's `active` / `passive` / `on`.  Junos has no PAgP
  analogue; Junos source never populates PAgP modes.
- **Device-count.** Junos's `chassis aggregated-devices
  ethernet device-count <N>` is an explicit allocation requirement
  Cisco doesn't have.  Junos -> Cisco render simply drops the
  directive (Cisco auto-allocates).
- **Sub-units.** Junos LAG units carry their own
  `family ethernet-switching` (or `family inet`) hierarchy; Cisco
  treats the `Port-channel<N>` as a regular interface.  Both
  flatten to the same canonical `lags[]` + per-interface
  `switchport_mode` shape.

Disposition: **good** on member list, name, LACP mode (active /
passive / static); **lossy** on Junos's `device-count`
allocation (drops on Junos -> Cisco render).
