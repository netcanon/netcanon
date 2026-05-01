# Switchport state: structurally absent on OPNsense source

OPNsense is a router/firewall — its interfaces have no switching
state on parse.  Aruba AOS-S as the target accepts switchport-
equivalent state (per-VLAN tagged/untagged port lists, voice-VLAN,
spanning-tree) but on this direction there is nothing to render.

## What OPNsense carries

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-04-30

OPNsense's `config.xml` does NOT model:

- per-port access / trunk modes
- 802.1Q tagged-VLAN port lists
- LLDP-MED voice-VLAN signalling
- spanning-tree state or per-port BPDU protection
- DHCP snooping

These are switching concepts that don't apply to a router/firewall.

The opnsense codec parse path therefore never populates:

- `interfaces[].switchport_mode`
- `interfaces[].access_vlan`
- `interfaces[].trunk_allowed_vlans`
- `interfaces[].trunk_native_vlan`
- `interfaces[].voice_vlan`
- `vlans[].tagged_ports`
- `vlans[].untagged_ports`

## What Aruba would accept

Source: [Aruba AOS-S 16.10 Advanced Traffic Management Guide](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba AOS-S models all of the above.  The aruba_aoss render path
emits per-VLAN `tagged` / `untagged` lines when the canonical lists
are populated, applies `voice` to a VLAN when `voice_vlan` is set,
and uses `_svi_absorption.py` to fold per-VLAN L3 addresses inline.

## Cross-vendor disposition

All switchport-related fields disposition as **not_applicable** on
this direction — the canonical fields are structurally empty after
an OPNsense parse, so the Aruba target render emits nothing related
to them.  Operators that want a meaningful Aruba switching topology
must construct VLAN port-membership manually post-migration.
