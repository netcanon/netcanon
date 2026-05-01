# VLANs and switchport membership: Juniper Junos versus Cisco IOS-XE

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/ref/statement/vlans-bridging-qfx-series.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/bridging-and-vlans-overview.html (retrieved 2026-04-30)
- Cisco: https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-9/configuration_guide/vlan/b_179_vlan_9300_cg/configuring_vlans.html (retrieved 2026-04-30)

Citation ids: `junos-vlans-statement`, `junos-bridging-overview`, `cisco-vlan-cg`.

## Junos form

```
set vlans Production-Servers vlan-id 100
set vlans Production-Servers description "User VLAN"
set vlans Production-Servers l3-interface irb.100
set vlans VoIP vlan-id 200

set interfaces ge-0/0/0 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/0 unit 0 family ethernet-switching vlan members Production-Servers
set interfaces ge-0/0/0 native-vlan-id 1

set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members [ Production-Servers VoIP ]
```

Junos VLANs are addressed by name, not id; the
`vlan-id <N>` integer is the dot1Q tag value bound to the named
VLAN.  Allowed-character set for VLAN names is letters, digits,
hyphens, periods (no underscores; up to 255 chars).

VLAN-aware bridge mode (an alternative QFX/MX configuration) uses
a single `bridge-domains` hierarchy with `interface-mode
trunk-bridge`; this is structurally distinct from the
`vlans <NAME>` form above and translates differently — the codec
defaults to the conventional `vlans` form for Junos -> Cisco
round-trips.

## Cisco IOS-XE form

```
vlan 100
 name Production-Servers
!
vlan 200
 name VoIP
!
interface GigabitEthernet1/0/1
 switchport mode access
 switchport access vlan 100
 switchport voice vlan 200
!
interface GigabitEthernet1/0/2
 switchport mode trunk
 switchport trunk allowed vlan 100,200,300
 switchport trunk native vlan 1
```

Cisco addresses VLANs by id; the `name` is informational.
VLAN-name allowed-character set is wider than Junos's (Cisco
accepts underscores and most printable ASCII).

## Mapping notes

- **Name-keyed versus id-keyed.** Junos's VLAN-name addressing
  flattens to canonical `CanonicalVlan{id, name, ...}` (id is
  primary); Cisco's id-keyed addressing maps directly.  Junos
  -> Cisco render uses the integer id; the name is preserved as
  the Cisco `name` directive.
- **Allowed-character difference.** Junos VLAN names are stricter
  (no underscores).  Junos -> Cisco round-trip is lossless
  (Cisco accepts the Junos-allowed subset).  Cisco -> Junos may
  require sanitisation (underscore -> hyphen) — see
  `vlan-name-constraints.md` in the Arista -> Junos cache.
- **Native VLAN hierarchy.** Junos's `native-vlan-id` lives at
  the parent-interface hierarchy; Cisco's `switchport trunk
  native vlan` lives inline.  Round-trip preserves the integer.
- **Voice VLAN.** Junos has no first-class voice-VLAN construct;
  on Junos -> Cisco round-trip, the voice_vlan field is empty
  (Junos source does not populate it).  Cisco -> Junos drops the
  field with a comment.
- **VLAN-aware bridge mode.** Some QFX / MX deployments use
  `bridge-domains` instead of `vlans`; the codec parser
  recognises both shapes (see the Junos parse module) but renders
  to the conventional `vlans` form.

Disposition: **good** on switchport_mode / access_vlan / trunk
allowed-list / native VLAN; **lossy** on Junos VLAN
description (Cisco has no VLAN-level description, only interface
descriptions); **unsupported** on voice_vlan (no Junos source
populates it; Cisco -> Junos drops it).
