# VXLAN, EVPN, MAC-VRF — render-side gap on cisco_iosxe

Source: [Junos EVPN-VXLAN data-center overview](https://www.juniper.net/documentation/us/en/software/junos/evpn-vxlan/topics/concept/evpn-vxlan-data-center-overview.html)
Retrieved: 2026-05-01

Source: [Junos EVPN-VXLAN Centrally-Routed Bridging Fabric example](https://www.juniper.net/documentation/us/en/software/junos/evpn/topics/example/evpn-vxlan-irb-within-data-center.html)
Retrieved: 2026-05-01

Source: [openconfig-evpn YANG model (GitHub)](https://github.com/openconfig/public/tree/master/release/models/evpn)
Retrieved: 2026-05-01

Source: [OpenConfig network-instance use cases](https://openconfig.net/docs/models/network_instance/)
Retrieved: 2026-05-01

Source: [Catalyst 9000 Series EVPN-VXLAN Configuration Guide](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-15/configuration_guide/vxlan/b_1715_bgp_evpn_vxlan_9300_cg.html)
Retrieved: 2026-05-01

## What the Junos source produces

The juniper_junos codec walks the full Junos EVPN-VXLAN surface
(GAP 6 + GAP-EVPN-2 wired):

* `set vlans <name> vxlan vni <N>` — populates
  `CanonicalVxlan` records with `vlan_id`, `vni`.
* `set switch-options vtep-source-interface lo0.0` — populates
  `source_interface` on every CanonicalVxlan record.
* `set protocols evpn vni-options vni <N> vrf-target target:<rt>`
  — VRF target binding (flows through routing-instance).
* `set routing-instances <vrf> instance-type {vrf | mac-vrf}` —
  populates `CanonicalRoutingInstance.instance_type`.
* `set routing-instances <vrf> protocols evpn ip-prefix-routes
  vni <N>` — populates `CanonicalRoutingInstance.l3_vni` for
  EVPN Type-5 symmetric IRB.

The juniper_junos codec advertises these paths under `supported`
in its CapabilityMatrix:

* `/vxlan-vnis/vni` (GAP 6)
* `/vxlan-vnis/source-interface` (GAP-EVPN-2)
* `/vxlan-vnis/udp-port` (GAP-EVPN-2)
* `/routing-instances/instance` (GAP 6)

## What the cisco_iosxe render emits

Nothing.  The render walks `intent.interfaces` only.
`intent.vxlan_vnis`, `intent.evpn_type5_routes`, and
`intent.routing_instances` are all silently dropped.

The codec's CapabilityMatrix declares
`/vxlan-vnis/vni`, `/vxlan-vnis/source-interface`, and
`/vxlan-vnis/udp-port` under `unsupported` explicitly with
reason "VXLAN not modelled in this NETCONF/OpenConfig stub
codec.  CLI sibling defers VXLAN wire-up until Catalyst demand
arrives; NETCONF stays in lockstep."

This is a doubly-asserted gap: render-side AND matrix-unsupported.

## Disposition

| Field | Disposition | Reason |
|---|---|---|
| `vxlan_vnis` (top-level) | unsupported | matrix-unsupported + render-side gap |
| `vxlan_vnis[].vlan_id` | unsupported | same |
| `vxlan_vnis[].vni` | unsupported | same |
| `vxlan_vnis[].mcast_group` | unsupported | same |
| `vxlan_vnis[].flood_list` | unsupported | same |
| `vxlan_vnis[].source_interface` | unsupported | same |
| `vxlan_vnis[].udp_port` | unsupported | same |
| `evpn_type5_routes` | unsupported | both codecs declare per-prefix list `lossy`; no codec populates today |

EVPN Type-5 in particular: both codecs list
`/evpn-type5-routes/route` under lossy-by-default with rationale
that Type-5 is a VRF-property model
(`CanonicalRoutingInstance.l3_vni`) rather than per-prefix
records.  The Junos source DOES populate `l3_vni` from
`set routing-instances X protocols evpn ip-prefix-routes vni N`,
but the cisco_iosxe target's `routing_instances` render-side gap
means even the property model loses on this direction.

## Repair path

Cisco IOS-XE EVPN-VXLAN configuration involves multiple stanzas:

* `feature nv overlay` (NX-OS) / equivalent on IOS-XE
* `interface nve1 / source-interface Loopback0`
* `interface nve1 / member vni <N>`
* `interface nve1 / member vni <N> associate vrf <name>` (Type-5)
* `vlan <N> / vn-segment <vni>`
* `router bgp <asn> / address-family l2vpn evpn / advertise-all-vni`

The OpenConfig EVPN model (`openconfig-evpn`) covers some of this
surface but Catalyst trains vary in YANG support.  Bridging via
Cisco-IOS-XE-vxlan native YANG would be the most reliable path.

The cisco_iosxe `_render_canonical` would need to:

1. Walk `intent.vxlan_vnis` to emit `<vxlan-vnis>` (or vendor
   native equivalent) plus `<network-instance>` augmentations.
2. Walk `intent.routing_instances` to emit `<network-instances>`
   with `instance_type` mapping (Junos's mac-vrf maps to
   Catalyst MAC-VRF; vrf maps to L3VRF; virtual-router has no
   Cisco analogue and would warn).
3. Walk `intent.routing_instances[].l3_vni` to emit Type-5
   association lines.

This is a substantial render-side wire-up — well beyond the
Phase-0.5 stub's scope.  Operators needing real Catalyst-to-Junos
EVPN migration today should route through `cisco_iosxe_cli`
target (which has the same gap on the EVPN render side, deferred
per its capability matrix) and emit raw CLI rather than NETCONF.

## Forward-direction asymmetry

The forward direction (cisco_iosxe -> juniper_junos) marks these
fields `not_applicable` because the Cisco SOURCE has no data
(parser-side gap PLUS matrix-unsupported).  This direction marks
them `unsupported` because Junos source IS wired but Cisco
target render isn't.  Same operational meaning, different
schematic labelling.
