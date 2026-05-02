# VRF / routing-instances — parse-side gap on cisco_iosxe; supported on Junos

Source: [OpenConfig network-instance use cases](https://openconfig.net/docs/models/network_instance/)
Retrieved: 2026-05-01

Source: [Junos L3 VPN topic-map](https://www.juniper.net/documentation/us/en/software/junos/vpn-l3/topics/topic-map/l3vpns-overview.html)
Retrieved: 2026-05-01

Source: [Junos instance-type statement reference](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/instance-type-edit-routing-instances.html)
Retrieved: 2026-05-01

## What OpenConfig models

The `openconfig-network-instance` model carries VRF / virtual-router
/ L2VPN / L3VPN declarations under `/network-instances/network-
instance/<name>` with `type`, `route-distinguisher`, route-targets
(via the BGP augment), and per-instance interface bindings.
Network-instance type is one of the OpenConfig identityref values:
`DEFAULT_INSTANCE`, `L3VRF`, `L2VSI`, `L2L3`, `MAC_VRF`.

## What the cisco_iosxe parser actually reads

Nothing.  The parser walks `<interfaces>` only and does not visit
`<network-instances>`.  `intent.routing_instances` is empty after
parse, and `intent.interfaces[].vrf` stays empty string.

This is a parse-side wire-up gap.  The codec's CapabilityMatrix
does not declare any `/routing-instances/*` paths — they're
implicitly unsupported (declared neither supported nor lossy nor
unsupported, falling through to the matrix's default-unsupported
classification for cross-codec mesh purposes).

## What the Junos target render does with empty input

Nothing.  The render walks `intent.routing_instances` to emit
`set routing-instances <name> instance-type {vrf | virtual-router |
mac-vrf | l2vpn}` blocks plus `route-distinguisher`,
`vrf-target target:...`, and per-interface bindings — empty list
emits nothing.

The juniper_junos codec is among the richest on this surface:
`/routing-instances/instance` declared `supported` (GAP 6 wired).
The codec parses `set routing-instances X instance-type vrf` /
`route-distinguisher` / `vrf-target target:...` / `interface
ge-0/0/0.0` and synthesises `CanonicalRoutingInstance` records
plus `CanonicalInterface.vrf` back-pointers.  Render emits the
same shape on round-trip.

## What WOULD survive a hypothetical wire-up

If the cisco_iosxe parser were extended to walk `<network-instances>`,
the dispositions would flip:

| Field | Today | After hypothetical wire-up |
|---|---|---|
| `interfaces[].vrf` | not_applicable | good |
| `routing_instances[].name` | not_applicable | good |
| `routing_instances[].instance_type` | not_applicable | lossy (Cisco source typically only `vrf`; Junos enum richer) |
| `routing_instances[].route_distinguisher` | not_applicable | good |
| `routing_instances[].rt_imports` | not_applicable | good |
| `routing_instances[].rt_exports` | not_applicable | good |
| `routing_instances[].description` | not_applicable | good |
| `routing_instances[].l3_vni` | not_applicable | lossy (Cisco's `vrf X / member vni N` under nve1 needs cross-stanza correlation) |

OpenConfig's network-instance model carries the per-AF route-
target lists under the BGP augment rather than under
`network-instance` directly, so the canonical
`rt_imports` / `rt_exports` lists need cross-stanza correlation
on parse.  Even with parser wire-up, Cisco's "address-family ipv4
vrf X / route-target import / route-target export" living under
`router bgp` rather than under `vrf definition` means the parser
needs to walk both subtrees and stitch.

## Disposition

| Field | Today |
|---|---|
| `routing_instances` (top-level) | not_applicable |
| `routing_instances[].name` | not_applicable |
| `routing_instances[].instance_type` | not_applicable |
| `routing_instances[].route_distinguisher` | not_applicable |
| `routing_instances[].rt_imports` | not_applicable |
| `routing_instances[].rt_exports` | not_applicable |
| `routing_instances[].description` | not_applicable |
| `routing_instances[].l3_vni` | not_applicable |
| `interfaces[].vrf` | not_applicable |

## Operational implication

A Catalyst customer running multi-VRF (VRF-Lite) and using NETCONF
as the snapshot path will lose ALL VRF declarations and interface-
binding context on cross-pair migration to Junos.  The Junos
target receives a single-VRF (default) view.  For real multi-VRF
migrations from Cisco IOS-XE to Junos, route through the
`cisco_iosxe_cli` codec instead — its CLI parser walks the
`vrf definition` / `address-family` / `vrf forwarding` triplet
correctly (or queues it for matrix-tracked deferral).
