# VLAN configuration: Aruba AOS-S versus Cisco IOS-XE

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

The L3 SVI address (`ip address ... `) is part of the VLAN stanza
— there is no separate `interface Vlan100` directive on AOS-S.
This is the `absorbs_svi_into_vlan: true` codec class-var.

## Cisco IOS-XE

Source: [Cisco IOS XE 17.14 VLAN Configuration Guide — Configuring VLANs (Catalyst 9400)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-14/configuration_guide/vlan/b_1714_vlan_9400_cg/configuring_vlans.html)
Retrieved: 2026-04-30

Cisco is **port-centric** with separate SVI stanza:

```
vlan 100
 name engineering
!
interface Vlan100
 ip address 192.168.10.1 255.255.255.0
!
interface GigabitEthernet1/0/1
 switchport mode access
 switchport access vlan 100
```

The VLAN stanza never lists ports; membership is per-port.

## Cross-vendor mapping

The canonical model is VLAN-centric (design principle 1).  The
projection transforms bridge:

* Aruba parse: Aruba's native VLAN-centric form populates
  `CanonicalVlan.tagged_ports` / `untagged_ports` directly.
* Cisco render: `project_vlan_to_switchport` re-projects the
  VLAN-centric membership back onto per-port `switchport_mode` +
  `access_vlan` + `trunk_allowed_vlans` before the Cisco renderer
  walks the interface list.  When Aruba's source had VLAN
  membership but no explicit `interface 1` stanza, the transform
  synthesises a minimal `CanonicalInterface` so the Cisco renderer
  has something to emit (per the docstring: "Required for cross-
  vendor renders into a port-centric target codec ... the bug
  shape that surfaced when an Aruba 2930M stack rendered to IOS-XE
  with only VLAN declarations and no interfaces").

SVI absorption:

* Aruba parse: `vlan 100 / ip address X/N` populates
  `CanonicalVlan.ipv4_addresses` directly.
* Cisco render: emits `interface Vlan100 / ip address X N`
  alongside the bare `vlan 100 / name ...` stanza.

Round-trip lossless for VLAN id, name, member ports, SVI v4
address.

Disposition: **good**.
