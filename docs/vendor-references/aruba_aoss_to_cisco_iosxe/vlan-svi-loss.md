# VLANs and SVIs — AOS-S source to OpenConfig NETCONF target

Source: [Aruba ArubaOS-Switch 16.10 Advanced Traffic Management Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-05-01

Source: [openconfig-vlan YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-vlan.html)
Retrieved: 2026-05-01

Source: [openconfig-network-instance use cases](https://openconfig.net/docs/models/network_instance/)
Retrieved: 2026-05-01

## What AOS-S source carries

The aruba_aoss parser populates `intent.vlans` with full VLAN-centric
records: id, name, description, tagged_ports, untagged_ports, and
SVI L3 state (ipv4_addresses absorbed from `vlan N / ip address X/N`).
A typical AOS-S running-config has 3-15 VLANs each with port
membership and SVI addressing.

## What the cisco_iosxe target render emits

Nothing.  The cisco_iosxe codec's `_render_canonical()` walks
`intent.interfaces` only and never reads `intent.vlans`.  No
`<vlans>` element appears in the emitted XML regardless of source
content.  The codec's CapabilityMatrix declares
`/vlans/vlan/id` and `/vlans/vlan/name` under `supported`, but the
declaration is aspirational — the render path does not emit them.

The `openconfig-vlan` model defines a top-level `vlans/vlan/{id, name,
config/status, members/member/...}` list under `network-instances`.
Wire-up would require:

1. Walking `intent.vlans` in `_render_canonical()`.
2. Building the `<vlans>` element with namespace
   `http://openconfig.net/yang/vlan`.
3. Emitting `<vlan><vlan-id>N</vlan-id><config><name>X</name></config></vlan>`
   per record.

This is a 30-line addition to the codec but has not landed in
the Phase-0.5 stub.

## SVI absorption — additional asymmetry

AOS-S absorbs SVI L3 into the VLAN stanza
(`absorbs_svi_into_vlan: true` codec class-var).  The aruba_aoss
parser does TWO things with `vlan 100 / ip address 10.0.0.1/24`:

1. Populates `CanonicalVlan.ipv4_addresses` for the VLAN.
2. Synthesises a `CanonicalInterface(name="Vlan100",
   interface_type="l2vlan", ipv4_addresses=[...])` so target codecs
   that don't absorb SVI (Cisco / Junos / Arista) see a normal SVI
   interface to render from.

When the cisco_iosxe NETCONF render walks `intent.interfaces`, it
DOES find the synthesised `Vlan100` interface and emits an
`<interface><name>Vlan100</name>...<ipv4>...</ipv4></interface>`
block.  So the SVI addressing DOES survive the round-trip — at the
INTERFACE level only.  The VLAN-level `<vlans>` declaration that
SHOULD accompany an SVI still drops.

A downstream OpenConfig consumer of the rendered XML would see an
SVI interface with an IP address, but no top-level VLAN declaration
binding the SVI to an L2 broadcast domain.  This is a partially-
incomplete render that may cause a Cisco device receiving the
edit-config to reject the SVI ("VLAN 100 not configured").

## Disposition

* `vlans`: **unsupported** — target render gap (declared `supported`
  in matrix, but `_render_canonical()` doesn't walk).
* `vlans[].id`, `vlans[].name`, `vlans[].description`,
  `vlans[].tagged_ports`, `vlans[].untagged_ports`,
  `vlans[].ipv4_addresses`: same as parent — **unsupported**.
* SVI addressing on `interfaces[].ipv4_addresses` for synthesised
  `VlanN`: **good** (does survive via the interfaces walk).
