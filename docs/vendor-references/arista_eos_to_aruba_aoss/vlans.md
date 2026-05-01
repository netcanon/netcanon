# VLAN configuration: Arista EOS versus Aruba AOS-S

## Arista EOS

Source: [Arista EOS — Virtual LANs (VLANs)](https://www.arista.com/en/um-eos/eos-virtual-lans-vlans)
Retrieved: 2026-05-01

Arista EOS is **port-centric** (Cisco-style):

```
vlan 100
   name USERS
!
interface Vlan100
   description "Tenant A data SVI"
   vrf TENANT_A
   ip address 10.100.0.1/24
   ipv6 address 2001:db8:100:100::1/64
!
interface Ethernet2
   switchport mode access
   switchport access vlan 10
!
interface Ethernet3
   switchport mode trunk
   switchport trunk native vlan 1
   switchport trunk allowed vlan 10,20,100,200
```

The `vlan N / name X` stanza never lists ports; membership is
per-port via `switchport access vlan` / `switchport trunk allowed
vlan`.  SVI L3 lives on a separate `interface Vlan<N>` block —
which can carry a `vrf <name>` line for L3 isolation.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Advanced Traffic Management Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba is **VLAN-centric** with absorbed SVI L3:

```
vlan 100
   name "USERS"
   untagged 1-24
   tagged 25-26
   ip address 192.168.10.1/24
   exit
```

The L3 SVI address (`ip address ...`) is part of the VLAN stanza
— there is no separate `interface Vlan100` directive on AOS-S.

## Cross-vendor mapping

The canonical model is VLAN-centric (design principle 1).

Arista -> Aruba round-trip:

* Arista parse: `interface Ethernet2 / switchport access vlan 10`
  populates a port-centric record.  The
  `project_switchport_to_vlan` transform re-projects to the
  canonical VLAN-centric form (`tagged_ports` /
  `untagged_ports`) before the Aruba renderer walks the VLAN
  list.
* Arista parse: `interface Vlan100 / ip address X/N` populates
  `CanonicalVlan.ipv4_addresses` directly via the SVI-absorption
  helper (mirror of Aruba's parse-side absorption — both vendors
  end up with the same canonical shape regardless of where the
  L3 originally lived).
* Aruba render: emits `vlan N / name "X" / untagged ... / tagged
  ... / ip address X/N`.  Quote-tolerant on the name field.

VRF on the SVI is the asymmetric loss — Arista's `interface
Vlan100 / vrf TENANT_A` carries data Aruba has no concept of (see
`vrf_unsupported.md`).  The `vrf` field on the canonical interface
silently drops on Aruba render.

The Arista synthetic kitchen-sink (`ks-leaf-01`) carries:

```
vlan 10 / name USERS
vlan 20 / name VOICE
vlan 100 / name TENANT_A_DATA
vlan 200 / name TRANSIT
interface Vlan100 / vrf TENANT_A / ip address 10.100.0.1/24
interface Vlan200 / ip address 10.200.0.1/24
```

— the bare VLANs and SVI absorption land cleanly; the `vrf
TENANT_A` line drops on the Aruba target with a banner.

Round-trip lossless for VLAN id, name, member ports, SVI v4
address (when SVI is in the default VRF).

Disposition: **good** for non-VRF VLANs / SVIs; **lossy** for
VLAN SVIs with `vrf` membership.
