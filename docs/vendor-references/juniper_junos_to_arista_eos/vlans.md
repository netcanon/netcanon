# VLANs (id, name, port membership, SVI)

How VLANs are declared and how port membership is expressed on each
platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/ref/statement/vlans-bridging-qfx-series.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/bridging-and-vlans-overview.html (retrieved 2026-05-01)
- Arista: https://www.arista.com/en/um-eos/eos-vlan-configuration (retrieved 2026-05-01)

Citation ids: `junos-vlans-statement`, `junos-bridging-overview`,
`arista-vlan-cg`.

## Junos form

```
set vlans v100 vlan-id 100
set vlans v100 description "user-vlan"
set vlans v100 l3-interface irb.100

set interfaces ge-0/0/0 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/0 unit 0 family ethernet-switching vlan members v100

set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members [ v100 v200 v300 ]
set interfaces ge-0/0/1 native-vlan-id 1
```

VLAN names are **required** (not optional) on Junos: a VLAN is keyed
by name (`v100`), with the bridge-id encoded as `vlan-id N`.  Names
are restricted to letters, digits, hyphens, and periods; max 255
chars.  Port membership is **per-interface** (not per-VLAN): each
interface declares which VLANs it carries via
`family ethernet-switching vlan members`.

## Arista form

```
vlan 100
   name user-vlan

interface Ethernet1
   switchport mode access
   switchport access vlan 100

interface Ethernet2
   switchport mode trunk
   switchport trunk allowed vlan 100,200,300
   switchport trunk native vlan 1

interface Vlan100
   ip address 10.100.0.1/24
```

VLANs are keyed by **id** (bare integer); name is optional and
liberal (underscores, mixed case, special chars allowed within length
limits).  Port membership is **per-interface** (same shape as Junos
on this axis).  SVI is a separate `interface Vlan<id>` stanza, not
linked from the VLAN definition.

## Mapping notes

- **VLAN id.** Direct round-trip (`set vlans v100 vlan-id 100` ->
  `vlan 100`).
- **VLAN name.** Junos name constraints (letters / digits / hyphens /
  periods only) are a strict subset of Arista's allowed set, so
  Junos -> Arista is **lossless** on the name string.  Reverse
  direction (Arista -> Junos) sanitises underscores etc.; this
  inverse direction does not have that loss.
- **VLAN description.** Junos's `set vlans NAME description X` is a
  first-class field; Arista has no VLAN-level description (only
  per-interface descriptions).  Canonical carries the description;
  Arista render emits as a `!` comment after the `vlan <id>` header.
- **Port membership transposition.** Both vendors model port
  membership per-interface; the canonical model also carries
  per-VLAN port lists (`tagged_ports` / `untagged_ports`) which the
  codec projects on parse (Junos -> canonical) and consumes on
  render (canonical -> Arista).  Round-trip preserves semantics.
- **Native VLAN.** Junos's `set interfaces X native-vlan-id N` lives
  at the parent-interface hierarchy (not the unit).  Arista's
  `switchport trunk native vlan N` lives in the interface stanza.
  Different syntax, identical semantics; canonical preserves the
  integer.
- **SVI / IRB.** Junos's `set interfaces irb unit 100 family inet
  address X/N` + `set vlans v100 l3-interface irb.100` maps to
  Arista's `interface Vlan100` + `ip address X/N`.  The canonical
  model carries the SVI address on `CanonicalVlan.ipv4_addresses`
  via the `l3-interface` link.
