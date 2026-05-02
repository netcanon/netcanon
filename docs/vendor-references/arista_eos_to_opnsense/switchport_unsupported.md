# Switchport / spanning-tree / voice-VLAN unsupported on OPNsense

OPNsense is a FreeBSD-based router/firewall with no switching
fabric.  Arista EOS is a DC-class L2/L3 switch.  Arista's switching
state has no first-class destination on OPNsense.

## What Arista carries

Source: [Arista EOS User Manual — Spanning Tree](https://www.arista.com/en/um-eos/eos-spanning-tree-protocol)
and [Switchport](https://www.arista.com/en/um-eos/eos-vlan-configuration)
Retrieved: 2026-05-01

```
spanning-tree mode mstp
spanning-tree mst configuration
   name "lab-mst"
   instance 1 vlan 10,20

interface Ethernet2
   switchport mode access
   switchport access vlan 10
!
interface Ethernet3
   switchport mode trunk
   switchport trunk native vlan 1
   switchport trunk allowed vlan 10,20,100,200
!
interface Ethernet8
   switchport voice vlan 20
```

- `switchport mode {access|trunk}` declares the L2 forwarding
  role.  `no switchport` (the inverse) promotes the port to L3.
- `switchport access vlan <N>`, `switchport trunk allowed vlan
  <list>`, `switchport trunk native vlan <N>` carry the per-port
  VLAN intent.
- `switchport voice vlan <N>` advertises a voice-VLAN via
  LLDP-MED to attached IP phones.
- Spanning-tree mode (`mstp` / `rstp` / `pvst`) and per-instance
  configuration live at the global level; per-port `spanning-tree
  portfast` / `bpduguard` knobs are interface-level.

None of these are modelled in `CanonicalIntent` v1 — they live in
`raw_sections` (Tier 3) on the Arista side, parse-and-ignore on
canonical for the spanning-tree surface; switchport state IS
captured on `CanonicalInterface` but has no destination on the
OPNsense side.

## What OPNsense models

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-04-30

OPNsense interfaces have only L3 attributes:

- IP addressing (v4 / v6 / DHCP / SLAAC / track6 / 6rd / 6to4).
- MTU.
- Enable / disable.
- Description.
- Block-private / bogon / RFC1918 (firewall-policy attributes).

There is no `switchport access` / `switchport trunk` directive
because OPNsense doesn't bridge its NICs as a switch — every
interface is a routed L3 endpoint.  STP, voice-VLAN signalling,
and port-fast / BPDU-guard knobs are out of scope.

## Cross-vendor disposition

Canonical fields affected:

- `interfaces[].switchport_mode`
- `interfaces[].access_vlan`
- `interfaces[].trunk_allowed_vlans`
- `interfaces[].trunk_native_vlan`
- `interfaces[].voice_vlan`
- `vlans[].tagged_ports`
- `vlans[].untagged_ports`

All marked **unsupported** on OPNsense as the target — the
OPNsense render path emits no per-port switchport XML and no
per-VLAN membership lists.  Arista-source switching state is
preserved on the canonical tree but drops at the OPNsense render
boundary.
