# VLANs and switchport membership: Aruba AOS-S versus Juniper Junos

How VLAN definitions, port membership, and SVI L3 are declared on
each platform.

Sources:
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/ref/statement/vlans-bridging-qfx-series.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/bridging-and-vlans-overview.html (retrieved 2026-05-01)

Citation ids: `aruba-vlans`, `junos-vlans-statement`,
`junos-bridging-overview`.

## Aruba AOS-S form

VLAN-centric with absorbed SVI:

```
vlan 100
   name "USERS"
   untagged 1-24
   tagged 25-26
   ip address 192.168.10.1/24
   ipv6 address 2001:db8::1/64
   exit
```

Port lists accept ranges (`1-24`), comma-separated lists
(`25,26`), and chassis-letter forms (`A1-A4,B1`).  The L3 SVI
address lives directly on the VLAN stanza — there is no separate
`interface Vlan100` directive (the `absorbs_svi_into_vlan: true`
codec convention).

## Junos form

Name-keyed VLAN definitions; per-interface membership lives on the
`family ethernet-switching` surface:

```
set vlans USERS vlan-id 100
set vlans USERS description "User VLAN"
set vlans USERS l3-interface irb.100

set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members USERS

set interfaces ge-0/0/24 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/24 unit 0 family ethernet-switching vlan members [ USERS VOICE ]
set interfaces ge-0/0/24 native-vlan-id 1
```

The SVI is a separate IRB unit:

```
set interfaces irb unit 100 family inet address 192.168.10.1/24
set interfaces irb unit 100 family inet6 address 2001:db8::1/64
```

VLAN names allow letters, digits, hyphens, periods only (no
underscores, no spaces, up to 255 chars).

## Cross-vendor mapping

The canonical model is VLAN-centric (`tagged_ports` / `untagged_ports`
on `CanonicalVlan`).  Aruba parse populates these directly; Junos
render transposes back to per-interface
`family ethernet-switching vlan members`.

Specifics:

* `id`: Aruba `vlan 100` -> Junos `set vlans <name> vlan-id 100`.
  Junos addresses the VLAN by name; the codec render synthesises a
  default name (typically `vlan<N>`) when the source had no explicit
  name.
* `name`: Aruba names allow underscores, spaces (quoted), and a wider
  character set than Junos.  Junos rejects underscores; sanitisation
  (underscore -> hyphen) on render.  AOS-S `"DEFAULT_VLAN"` becomes
  `DEFAULT-VLAN` on Junos.
* `description`: Aruba does not model a VLAN-level description (only
  interface descriptions); the canonical field is empty on parse, so
  Junos render emits no `set vlans <name> description` line.
* `tagged_ports` / `untagged_ports`: Aruba's `untagged 1-24` populates
  the canonical lists directly; Junos render transposes to
  per-interface `vlan members <name>`.
* `ipv4_addresses` (SVI absorption): Aruba `vlan 100 / ip address X/N`
  lands on `CanonicalVlan.ipv4_addresses`; Junos render emits a
  separate `set interfaces irb unit 100 family inet address X/N`
  block plus `set vlans <name> l3-interface irb.100`.

Disposition: **good** on id, member ports, SVI v4 address; **lossy**
on name (sanitisation when underscores present); **lossy** on
description (Aruba has no VLAN-level description to populate, so
Junos source -> Aruba render drops the description with a comment).
