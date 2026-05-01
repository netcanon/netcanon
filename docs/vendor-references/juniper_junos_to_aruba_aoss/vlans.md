# VLANs and switchport membership: Juniper Junos versus Aruba AOS-S

How VLAN definitions, port membership, and SVI L3 are declared on
each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/ref/statement/vlans-bridging-qfx-series.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/bridging-and-vlans-overview.html (retrieved 2026-05-01)
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm (retrieved 2026-05-01)

Citation ids: `junos-vlans-statement`, `junos-bridging-overview`,
`aruba-vlans`.

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
```

VLAN names allow letters, digits, hyphens, periods only (no
underscores, up to 255 chars).  Junos VLANs also support VXLAN
binding (`set vlans NAME vxlan vni N`) — see
`vxlan_evpn_unsupported.md`.

## Aruba AOS-S form

VLAN-centric with absorbed SVI (no separate `interface Vlan100`
stanza):

```
vlan 100
   name "USERS"
   untagged 1-24
   tagged 25-26
   ip address 192.168.10.1/24
   exit
```

Aruba VLAN names accept underscores, spaces (quoted), and a wider
character set than Junos.

## Cross-vendor mapping

The canonical model is VLAN-centric (`tagged_ports` / `untagged_ports`
on `CanonicalVlan`).  Junos parse transposes per-interface
`family ethernet-switching vlan members` back to VLAN-centric port
lists; Aruba render emits the lists directly inside the
`vlan <id>` stanza.

Specifics:

* `id`: Junos's `vlan-id N` populates `CanonicalVlan.id`.
* `name`: Junos VLAN name -> Aruba name (Junos's name set is a
  subset of Aruba's allowed character set, so Junos -> Aruba is
  lossless).
* `description`: Junos's `set vlans NAME description X` lands on
  `CanonicalVlan.description`.  Aruba does not model VLAN-level
  description natively; the codec render emits it as a `;` comment
  immediately after the `vlan <id>` header — informational only.
* `tagged_ports` / `untagged_ports`: Junos's per-interface vlan
  members transposes back to per-VLAN port lists on parse via the
  codec's projection helper.  Aruba render emits the lists as
  `tagged <ports>` / `untagged <ports>` directly under the VLAN
  stanza.
* `ipv4_addresses` (SVI absorption): Junos's `set interfaces irb
  unit 100 family inet address X/N` + `set vlans NAME l3-interface
  irb.100` lands on `CanonicalVlan.ipv4_addresses`; Aruba render
  emits `vlan 100 / ip address X/N` directly inside the VLAN
  stanza.

Note: Junos's VLAN-aware bridge mode (`bridge-domains` with
`interface-mode trunk-bridge`) is parse-recognised but render emits
the conventional `vlans` form on Junos same-vendor.  Cross-vendor to
Aruba uses the canonical VLAN-centric form regardless.

Disposition: **good** on id, name (Junos subset), description, member
ports, SVI v4 address.
