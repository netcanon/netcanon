# VLAN configuration: Aruba AOS-S versus Arista EOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Advanced Traffic Management Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

VLAN definition is **VLAN-centric** with absorbed SVI L3:

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
(`25,26`), and chassis-letter forms (`A1-A4,B1`).  Port lists are
expanded by the codec's `_parse_port_list` helper into individual
port names.

The L3 SVI address (`ip address ...`) is part of the VLAN stanza
— there is no separate `interface Vlan100` directive on AOS-S.
This is the codec's `absorbs_svi_into_vlan: true` class-var.

## Arista EOS

Source: [Arista EOS — Virtual LANs (VLANs)](https://www.arista.com/en/um-eos/eos-virtual-lans-vlans)
Retrieved: 2026-05-01

Arista EOS is **port-centric** and follows Cisco-style grammar:

```
vlan 100
   name USERS
!
interface Vlan100
   description "USERS SVI"
   ip address 192.168.10.1/24
!
interface Ethernet1
   switchport mode access
   switchport access vlan 100
!
interface Ethernet25
   switchport mode trunk
   switchport trunk allowed vlan 100,200
```

The `vlan N / name X` stanza never lists ports; membership is
per-port via `switchport access vlan` / `switchport trunk allowed
vlan`.  SVI L3 lives on a separate `interface Vlan<N>` block.
Arista's CIDR `ip address X/N` form matches Aruba's syntax exactly
(both vendors avoid Cisco's dotted-mask form).

## Cross-vendor mapping

The canonical model is VLAN-centric (design principle 1).  The
projection transforms bridge:

* Aruba parse: native VLAN-centric form populates
  `CanonicalVlan.tagged_ports` / `untagged_ports` directly.
* Arista render: `project_vlan_to_switchport` re-projects the
  VLAN-centric membership onto per-port `switchport_mode` +
  `access_vlan` + `trunk_allowed_vlans` before the EOS renderer
  walks the interface list.  When Aruba's source had VLAN
  membership but no explicit `interface 1` stanza, the transform
  synthesises a minimal `CanonicalInterface` so the EOS renderer
  has something to emit (same projection pattern as Aruba ->
  Cisco IOS-XE).

SVI absorption:

* Aruba parse: `vlan 100 / ip address X/N` populates
  `CanonicalVlan.ipv4_addresses` directly.
* Arista render: emits `interface Vlan100 / ip address X/N`
  alongside the bare `vlan 100 / name ...` stanza.  CIDR form is
  preserved verbatim — no dotted-mask conversion needed (unlike
  the Cisco IOS-XE path).

The Aruba synthetic kitchen-sink at
`tests/fixtures/synthetic/aruba_aoss/kitchen_sink.cfg` exercises
this with VLANs 1, 10, 20, 30, 40 — each carrying tagged/untagged
port lists plus `ip address X/N` SVI absorption.

Round-trip lossless for VLAN id, name, member ports, SVI v4
address.

Disposition: **good**.
