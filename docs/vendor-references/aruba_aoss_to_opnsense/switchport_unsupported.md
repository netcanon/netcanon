# Switchport / spanning-tree / voice-VLAN unsupported on OPNsense

OPNsense is a FreeBSD-based router/firewall with no switching fabric.
Aruba AOS-S is an enterprise campus switch.  The Aruba switching
state has no first-class destination on OPNsense.

## What Aruba carries

Source: [Aruba AOS-S 16.10 Multicast and Routing Guide — STP /
LLDP-MED](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MRG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
spanning-tree
spanning-tree 1-24 admin-edge-port
spanning-tree 1-24 bpdu-protection
no spanning-tree A1-A2 admin-edge-port

dhcp-snooping
dhcp-snooping vlan 10 20
dhcp-snooping trust 23-24

vlan 20
   voice
   exit
```

- Per-port spanning-tree state (admin-edge / BPDU protection / loop
  protection) is configured via `spanning-tree <ports> <mode>`
  directives.
- `dhcp-snooping` is a fabric-level DHCP guard with per-VLAN scoping
  and per-port trust marking.
- `voice` inside a VLAN stanza tags the VLAN as the voice-VLAN
  signalled via LLDP-MED to attached IP phones.

None of these concepts are modelled in `CanonicalIntent` today —
they live in `raw_sections` (Tier 3) on the Aruba side, parse-and-
ignore on canonical.

## What OPNsense models

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-04-30

OPNsense interfaces have only L3 attributes:

- IP addressing (v4 / v6 / DHCP / SLAAC / track6 / 6rd / 6to4).
- MTU.
- Enable / disable.
- Description.
- Block private / bogon / RFC1918 (firewall-policy attributes).

There is no `switchport access` / `switchport trunk` directive
because OPNsense doesn't bridge its NICs as a switch — every
interface is a routed L3 endpoint.  STP, dhcp-snooping, and voice-
VLAN signalling are out of scope.

## Cross-vendor disposition

Canonical fields affected:

- `interfaces[].switchport_mode`
- `interfaces[].access_vlan`
- `interfaces[].trunk_allowed_vlans`
- `interfaces[].trunk_native_vlan`
- `interfaces[].voice_vlan`
- `vlans[].tagged_ports`
- `vlans[].untagged_ports`

All marked **unsupported** on OPNsense as the target — the OPNsense
render path emits no per-port switchport XML and no per-VLAN
membership lists.  Aruba-source switching state is preserved on the
canonical tree but drops at the OPNsense render boundary.
