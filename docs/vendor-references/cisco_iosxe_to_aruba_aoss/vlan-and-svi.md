# VLANs and SVIs — Cisco NETCONF source to AOS-S CLI target

Source: [openconfig-vlan YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-vlan.html)
Retrieved: 2026-05-01

Source: [openconfig-network-instance use cases](https://openconfig.net/docs/models/network_instance/)
Retrieved: 2026-05-01

Source: [Aruba ArubaOS-Switch 16.10 Advanced Traffic Management Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-05-01

## What OpenConfig models for VLANs

The `openconfig-vlan` model defines a top-level `<vlans><vlan>`
list under `<network-instances>` with id / name / status / member
ports.  The `openconfig-vlan:switched-vlan` augment under
`<ethernet>` carries the per-port access/trunk membership.

## What the cisco_iosxe parser reads

Nothing in this category.  The parser walks `<interfaces>` only;
`<vlans>` and `<network-instances>` are skipped entirely.
`intent.vlans` stays empty after parse, and the per-interface
`switchport_mode` / `access_vlan` / `trunk_allowed_vlans` /
`trunk_native_vlan` / `voice_vlan` fields remain at their None /
empty defaults.

## What AOS-S target accepts

The aruba_aoss codec parses VLANs and switchport state from the
running-config and renders the same on emit.  It declares
`/vlans/vlan/*` under `supported`, so the target would accept any
canonical VLAN content the source provided.

The AOS-S render does its own
`project_vlan_to_switchport`-equivalent work on the inbound side
(SVI absorption inverts the per-interface model into VLAN-centric
membership).

## What the render actually emits given empty input

No VLAN declarations at all.  The aruba_aoss render walks
`intent.vlans` to produce `vlan N / name "X" / untagged ... /
tagged ...` stanzas, but `intent.vlans == []` after cisco_iosxe
parse, so nothing is emitted.

If the cisco source happened to carry a `<interface><name>Vlan10</name>`
record (a synthesised SVI, but more typically a
Catalyst-style `interface Vlan10` with IP), the cisco_iosxe parser
DOES populate that as a `CanonicalInterface(name="Vlan10",
interface_type="l2vlan", ipv4_addresses=[...])`.  The aruba_aoss
render then absorbs it back into a `vlan 10 / ip address X/N`
stanza via the SVI absorption code path — but with empty port
membership.  The resulting AOS-S CLI declares VLAN 10 as a
broadcast domain with no ports, which is syntactically valid but
operationally hollow.

## Disposition

| Field | Disposition | Reason |
|---|---|---|
| `vlans` | not_applicable | source parser doesn't walk `<vlans>` |
| `vlans[].id` | not_applicable | same |
| `vlans[].name` | not_applicable | same |
| `vlans[].description` | not_applicable | same |
| `vlans[].tagged_ports` | not_applicable | same |
| `vlans[].untagged_ports` | not_applicable | same |
| `vlans[].ipv4_addresses` | partial — synthesised SVI may carry | not_applicable as a `vlans` field; flows through `interfaces[].ipv4_addresses` if a Vlan-named interface is present in source |
| `interfaces[].switchport_mode` | not_applicable | source parser doesn't walk `switched-vlan` |

All flips to `good` once the cisco_iosxe parser is extended to
walk `<vlans>` and the `switched-vlan` augment.
