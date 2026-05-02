# VLANs and SVIs — render-side wire-up gap

Source: [Junos vlans statement reference (QFX bridging)](https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/ref/statement/vlans-bridging-qfx-series.html)
Retrieved: 2026-05-01

Source: [Junos Bridging and VLANs Overview](https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/bridging-and-vlans-overview.html)
Retrieved: 2026-05-01

Source: [openconfig-vlan YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-vlan.html)
Retrieved: 2026-05-01

## What the Junos source produces

The juniper_junos codec walks `set vlans <name> vlan-id N` and
`set vlans <name> description X` and synthesises
`CanonicalVlan` records with id, name, description, and
port-membership (transposed from per-interface
`family ethernet-switching vlan members <name>` lines).
SVI absorption pulls L3 addressing from `set interfaces irb unit
N family inet address X/N` plus `set vlans <name> l3-interface
irb.N` into the matching `CanonicalVlan.ipv4_addresses`.

`intent.vlans` is populated with full canonical records on parse.

## What the cisco_iosxe render emits

Nothing for VLANs.  The render walks `intent.interfaces` only.
`intent.vlans` and the `switched-vlan` augment data on
`intent.interfaces[].switchport_mode` / `access_vlan` /
`trunk_allowed_vlans` / `trunk_native_vlan` are silently dropped.

The codec's CapabilityMatrix declares `/vlans/vlan/id` and
`/vlans/vlan/name` as `supported` aspirationally — present so
cross-codec mesh translations don't classify them as unsupported
on this codec, but the actual emit path is narrow.

## Synthesised SVI interfaces

When the Junos source carries `set interfaces irb unit 100`, the
parser creates a `CanonicalInterface` with `name="irb.100"` (or
similar; the rename mesh handles the cross-vendor naming).  This
interface DOES survive the cisco_iosxe render's interface walk.
A downstream OpenConfig consumer would see the SVI interface but
NOT the `<vlans><vlan id=100>` declaration that should accompany
it.  The consumer can't correlate the `irb.100` interface to a
VLAN id because the VLAN declaration is missing.

## Disposition

| Field | Disposition | Reason |
|---|---|---|
| `vlans` (top-level) | unsupported | render-side wire-up gap |
| `vlans[].id` | unsupported | render-side gap |
| `vlans[].name` | unsupported | render-side gap |
| `vlans[].description` | unsupported | render-side gap |
| `vlans[].tagged_ports` | unsupported | render-side gap |
| `vlans[].untagged_ports` | unsupported | render-side gap |
| `vlans[].ipv4_addresses` | unsupported | render-side gap (SVI absorption stays in source canonical but doesn't emit on Cisco render — except via the synthesised interface) |
| `interfaces[].switchport_mode` | unsupported | render-side gap (no `switched-vlan` augment) |
| `interfaces[].access_vlan` | unsupported | render-side gap |
| `interfaces[].trunk_allowed_vlans` | unsupported | render-side gap |
| `interfaces[].trunk_native_vlan` | unsupported | render-side gap |
| `interfaces[].voice_vlan` | not_applicable | Junos has no voice-VLAN |

## Repair path

The cisco_iosxe `_render_canonical` would need to:

1. Emit a top-level `<vlans>` element under
   `<network-instances><network-instance><vlans>` with
   `<vlan><vlan-id>` and `<config><name>` children.
2. Emit per-interface switchport state via the
   `openconfig-vlan:switched-vlan` augment under `<ethernet>`.

Both are mechanical extensions; the canonical input from Junos
would round-trip cleanly through the new render code.  The
forward direction (cisco_iosxe -> juniper_junos) would also
benefit because parser-side wire-up could feed parse-side dual
of the same XPath structures.

## Junos VLAN naming

Junos VLAN names are restricted to letters, digits, hyphens, and
periods (255-char limit).  Underscores, asterisks, and other
characters are rejected.  When the Junos source is wired and the
cisco_iosxe render eventually emits `<vlans>`, the OpenConfig
output would carry the Junos-sanitised name verbatim — no further
sanitisation needed (OpenConfig accepts any non-empty string).
