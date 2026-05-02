# VRFs / routing-instances — OpenConfig NETCONF source to Arista EOS target

Source: [OpenConfig network-instance use cases](https://openconfig.net/docs/models/network_instance/)
Retrieved: 2026-05-01

Source: [Arista EOS Configuring EVPN (4.35.2F)](https://www.arista.com/en/um-eos/eos-configuring-evpn)
Retrieved: 2026-05-01

## Why this is a parse-side gap, not a render-side gap

Unlike the forward direction (`arista_eos -> cisco_iosxe`) where the
target render silently drops VRF data, on this reverse direction the
source PARSER never populates VRF data.  The arista_eos target codec
renders `intent.routing_instances` and `intent.interfaces[].vrf`
correctly; it just receives an empty canonical tree.

## What the cisco_iosxe parser does NOT extract

The cisco_iosxe codec walks `<interfaces>` only.  It does not walk:

* `<network-instances>` — the OpenConfig top-level subtree
  containing VRFs / routing-instances and protocols including
  static routes.
* The `<network-instance>` per-instance interface back-pointers
  (the OpenConfig idiom for VRF interface membership puts the
  list under `network-instance/interfaces` rather than on the
  interface itself).

`intent.routing_instances` is empty regardless of source content.
`intent.interfaces[].vrf` stays at the default empty-string for
every interface.

The codec capability matrix does NOT declare
`/routing-instances/instance` or `/interfaces/interface/config/vrf`
explicitly under either `supported` or `unsupported` — those paths
are absent from the matrix entirely, while the CLI sibling lists
`/routing-instances/instance` under `unsupported`.

## What the arista_eos target render does

The arista_eos render walks:

* `intent.routing_instances` and emits `vrf instance <name>` plus
  per-VRF `ip routing vrf <name>` plus per-VRF
  `router bgp / vrf <name>` blocks with RD + RTs.
* `intent.interfaces[].vrf` and emits `vrf <name>` inside each
  interface stanza.

When both are empty, the Arista render emits no VRF declarations.
SVIs and L3 interfaces from the source `<interfaces>` walk land in
the default VRF on the target Arista device.

## Concrete demonstration

For a Cisco IOS-XE source NETCONF datastore carrying a `TENANT_A`
VRF with multiple interface members, a route-distinguisher,
import/export route-targets, and a per-VRF static-route table:

* The cisco_iosxe parser produces a `CanonicalIntent` with the
  L3 interfaces in the default VRF (their source XML doesn't carry
  the `vrf` field through the parser; even if it did, the field is
  not extracted today).
* The arista_eos render produces `interface <name>` blocks in the
  default VRF for those L3 interfaces.  No `vrf instance TENANT_A`
  declaration; no per-VRF BGP block; no per-VRF static routes.

A device commit on the Arista output puts what was originally
TENANT_A traffic into the global table — silent L3 isolation
breakage.

## Operator implication

For Cisco IOS-XE sources with any VRF state, this NETCONF source is
unusable.  Route through `cisco_iosxe_cli` (the certified CLI
source) instead.  The CLI source codec also currently treats
`/routing-instances/instance` as `unsupported` on its parse side
(matrix declaration), so the same migration limitation applies
there — but CLI source has the advantage of being amenable to
manual VRF reconstruction since the operator has the
`running-config` text to reference.

## Disposition

| Field | Disposition | Reason |
|---|---|---|
| `routing_instances` | not_applicable | Parse-side gap: cisco_iosxe parser doesn't walk `<network-instances>` |
| `routing_instances[].name` | not_applicable | Same |
| `routing_instances[].instance_type` | not_applicable | Same |
| `routing_instances[].route_distinguisher` | not_applicable | Same |
| `routing_instances[].rt_imports` | not_applicable | Same |
| `routing_instances[].rt_exports` | not_applicable | Same |
| `routing_instances[].description` | not_applicable | Same |
| `routing_instances[].l3_vni` | not_applicable | Doubly: VRF parser gap PLUS VXLAN matrix-unsupported on source |
| `interfaces[].vrf` | not_applicable | Parse-side gap: per-interface VRF binding not extracted |
| `static_routes` | not_applicable | Same root cause: OpenConfig models static routes as a per-instance protocol under `<network-instances>`; parser doesn't walk |

## When this flips

Once the cisco_iosxe parser walks `<network-instances>`, the
`routing_instances` rows flip to `good` (canonical-stable surface)
for `name`, `route_distinguisher`, `rt_imports`, `rt_exports`,
`description`, with `instance_type` becoming `lossy` because Cisco
has no per-VRF instance-type discriminator (always `vrf`) while
Junos / Arista MAC-VRF richer.  `interfaces[].vrf` flips to `good`.
`l3_vni` stays `not_applicable` until VXLAN parser wire-up also
lands.  `static_routes` flips to `good` for default-VRF routes,
`lossy` until `CanonicalStaticRoute` gains a `vrf` field for
per-VRF routes.
