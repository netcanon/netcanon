# VLANs and switchport membership: Cisco IOS-XE versus Juniper Junos

How VLANs are declared and how interfaces are bound to them.

Sources:
- Cisco: https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-9/configuration_guide/vlan/b_179_vlan_9300_cg/configuring_vlans.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/ref/statement/vlans-bridging-qfx-series.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/bridging-and-vlans-overview.html (retrieved 2026-04-30)

Citation ids: `cisco-vlan-cg`, `junos-vlans-statement`, `junos-bridging-overview`.

## Cisco IOS-XE form

VLAN declarations live under the global `vlan <N>` stanza; per-port
membership lives under the `interface` stanza:

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

VLAN 1 is the implicit default on every switchport.  Voice VLAN is a
first-class field surfaced via LLDP-MED.

## Junos form

Junos declares VLANs and per-interface membership independently;
membership is expressed on the unit-side:

```
set vlans Production-Servers vlan-id 100
set vlans VoIP vlan-id 200

set interfaces ge-0/0/0 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/0 unit 0 family ethernet-switching vlan members Production-Servers
set interfaces ge-0/0/0 native-vlan-id 1

set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members [ Production-Servers VoIP ]
```

VLANs are referenced by name, NOT by id, on the per-unit `vlan
members` line.  The native VLAN id lives at the parent interface
hierarchy (`native-vlan-id`), NOT under the unit.  Voice VLAN is not
a first-class Junos construct — operators surface it through
`protocols lldp-med` or via dedicated VLAN names that map to the
voice phone tag.

## Mapping notes

- **Stanza-form versus set-form.** Cisco's per-stanza grammar
  (`interface ... / switchport ...`) parses into the same canonical
  shape as Junos's per-line set grammar (`set interfaces ... family
  ethernet-switching ...`).  The codec parsers normalise; the
  canonical model is `CanonicalVlan` (vlan-centric) plus
  `CanonicalInterface.{switchport_mode, access_vlan,
  trunk_allowed_vlans, trunk_native_vlan}`.
- **VLAN naming.** Junos's `vlan members <NAME>` requires the VLAN
  to be addressed by name; the codec render path synthesises a
  default name (typically `vlan<N>`) when the source VLAN had no
  explicit name.  Junos VLAN names are constrained to letters,
  digits, hyphens, and periods (see `vlan-name-constraints.md`).
- **Native VLAN hierarchy.** Junos splits the native VLAN id away
  from the unit (`native-vlan-id` at the parent), where Cisco keeps
  it inline as `switchport trunk native vlan <N>`.  Round-trip
  preserves the integer; the structural difference is internal to
  each codec's render path.
- **Voice VLAN.** Cisco's `switchport voice vlan <N>` has no clean
  Junos equivalent; the canonical
  `CanonicalInterface.voice_vlan` field carries the value but the
  Junos render emits a comment (informational) rather than a real
  config line.
- **Trunk allowed-VLAN list.** Cisco's `switchport trunk allowed
  vlan add 200` (incremental form) vs `switchport trunk allowed
  vlan 100,200,300` (replace form) both flatten to the same
  `CanonicalInterface.trunk_allowed_vlans` list; canonical doesn't
  preserve the order or the add/remove semantic.

Disposition: **lossy** on `voice_vlan`, **good** on
`switchport_mode` / `access_vlan` / `trunk_allowed_vlans` / VLAN
declarations.
