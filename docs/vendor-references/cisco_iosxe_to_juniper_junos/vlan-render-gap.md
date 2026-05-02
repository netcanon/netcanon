# VLANs and SVIs — parse-side wire-up gap

Source: [openconfig-vlan YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-vlan.html)
Retrieved: 2026-05-01

Source: [Junos vlans statement reference (QFX bridging)](https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/ref/statement/vlans-bridging-qfx-series.html)
Retrieved: 2026-05-01

Source: [Junos Bridging and VLANs Overview](https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/bridging-and-vlans-overview.html)
Retrieved: 2026-05-01

## What OpenConfig models

The `openconfig-vlan` model carries VLAN declarations at
`/network-instances/network-instance/vlans/vlan`, plus per-interface
VLAN membership via the `switched-vlan` augment under
`/interfaces/interface/ethernet/`.  A real Catalyst NETCONF reply
will populate both subtrees when the device has VLAN config.

## What the cisco_iosxe parser actually reads

Neither.  The parser walks `<interfaces>` only and does not visit
`<network-instances>`, `<vlans>`, nor the `switched-vlan` augment
under `<ethernet>`.  Therefore:

* `intent.vlans` is empty after parse.
* `intent.interfaces[].switchport_mode` is None.
* `intent.interfaces[].access_vlan` is None.
* `intent.interfaces[].trunk_allowed_vlans` is empty list.
* `intent.interfaces[].trunk_native_vlan` is None.
* `intent.interfaces[].voice_vlan` is None.

This is a parse-side wire-up gap.  The codec's CapabilityMatrix
declares `/vlans/vlan/id` and `/vlans/vlan/name` as `supported`
aspirationally, so cross-codec mesh translations don't classify
them as unsupported on the target side — but the parser
implementation does not actually populate them.

## What the Junos target render does with empty input

Nothing for VLANs proper.  The Junos render walks `intent.vlans`
to emit `set vlans <name> vlan-id N` blocks — empty list emits
nothing.  Per-unit `family ethernet-switching` membership is
re-projected from `intent.interfaces[].switchport_mode` and the
related fields — all None, so no `family ethernet-switching`
lines emit either.

If a synthesised SVI interface exists on `intent.interfaces`
(name pattern `Vlan10`), it would survive the interface walk and
emit as `set interfaces irb unit 10 family inet address X/N`
(via the IRB unit pattern).  But the cisco_iosxe parser doesn't
synthesise SVIs — it only carries through interfaces actually
declared in the source `<interfaces>` subtree.  If the source
device's running-config had `interface Vlan10`, the Catalyst
NETCONF agent would emit it as `<interface><name>Vlan10</name>`
and the parser would carry it through.  But the VLAN declaration
itself (`vlan 10 / name Production`) lives under `<vlans>` and
the parser ignores that.

## What WOULD survive a hypothetical wire-up

If the cisco_iosxe parser were extended to walk `<vlans>` and the
`switched-vlan` augment, the Junos target accepts the
corresponding canonical fields (full canonical-stable surface:
id, name, description, port-membership, SVI absorption).  The
dispositions would flip:

| Field | Today | After hypothetical wire-up |
|---|---|---|
| `vlans[].id` | not_applicable | good |
| `vlans[].name` | not_applicable | lossy (Junos sanitises underscores) |
| `vlans[].description` | not_applicable | good |
| `vlans[].tagged_ports` | not_applicable | good |
| `vlans[].untagged_ports` | not_applicable | good |
| `vlans[].ipv4_addresses` | not_applicable | good (via `irb.X` unit) |
| `interfaces[].switchport_mode` | not_applicable | good |
| `interfaces[].access_vlan` | not_applicable | good |
| `interfaces[].trunk_allowed_vlans` | not_applicable | good |
| `interfaces[].trunk_native_vlan` | not_applicable | lossy (Junos `native-vlan-id` lives at parent, not unit) |
| `interfaces[].voice_vlan` | not_applicable | unsupported (Junos has no first-class voice VLAN) |

But none of this happens today.

## Disposition

| Field | Today |
|---|---|
| `vlans` (and all sub-fields) | not_applicable |
| `interfaces[].switchport_mode` | not_applicable |
| `interfaces[].access_vlan` | not_applicable |
| `interfaces[].trunk_allowed_vlans` | not_applicable |
| `interfaces[].trunk_native_vlan` | not_applicable |
| `interfaces[].voice_vlan` | not_applicable |

Junos VLAN naming constraints (letters / digits / hyphens / periods,
255-char limit) only matter once the parser is wired; until then
there's no source data to sanitise.
