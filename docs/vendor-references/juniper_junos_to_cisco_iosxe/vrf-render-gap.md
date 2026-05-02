# VRF / routing-instances — render-side gap on cisco_iosxe

Source: [Junos L3 VPN topic-map](https://www.juniper.net/documentation/us/en/software/junos/vpn-l3/topics/topic-map/l3vpns-overview.html)
Retrieved: 2026-05-01

Source: [Junos instance-type statement reference](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/instance-type-edit-routing-instances.html)
Retrieved: 2026-05-01

Source: [OpenConfig network-instance use cases](https://openconfig.net/docs/models/network_instance/)
Retrieved: 2026-05-01

## What the Junos source produces

The juniper_junos codec walks `set routing-instances <name> ...`
and populates `CanonicalRoutingInstance` records with:

* `name` — opaque Junos identifier.
* `instance_type` — `vrf` / `virtual-router` / `mac-vrf` / `l2vpn`
  / `evpn` from `set routing-instances X instance-type Y`.
* `route_distinguisher` — from `set routing-instances X
  route-distinguisher <RD>`.
* `rt_imports` / `rt_exports` — from `set routing-instances X
  vrf-target target:<RT>` (which expands to symmetric import +
  export) or per-direction `vrf-target import target:<RT>` /
  `vrf-target export target:<RT>`.
* `description` — from `set routing-instances X description X`.
* `l3_vni` — from `set routing-instances X protocols evpn
  ip-prefix-routes vni <N>` (EVPN Type-5 symmetric IRB).

Per-interface VRF binding is captured on
`CanonicalInterface.vrf` from `set routing-instances X interface
ge-0/0/0.0` (back-pointer; Junos stores membership on the
routing-instance, the codec transposes to the interface).

The juniper_junos codec advertises `/routing-instances/instance`
and `/interfaces/interface/config/vrf` under `supported` (GAP 6
wired).

## What the cisco_iosxe render emits

Nothing.  The render walks `intent.interfaces` only.
`intent.routing_instances` is silently dropped.  Even the
`CanonicalInterface.vrf` back-pointer is dropped because the
render doesn't emit `<network-instances>` membership annotations
on interfaces.

The codec's CapabilityMatrix does not declare any
`/routing-instances/*` paths — they're implicitly unsupported.

## Disposition

| Field | Disposition | Reason |
|---|---|---|
| `routing_instances` (top-level) | unsupported | render-side gap on `<network-instances>` |
| `routing_instances[].name` | unsupported | render-side gap |
| `routing_instances[].instance_type` | unsupported | render-side gap (Junos enum richer than Cisco supports) |
| `routing_instances[].route_distinguisher` | unsupported | render-side gap |
| `routing_instances[].rt_imports` | unsupported | render-side gap |
| `routing_instances[].rt_exports` | unsupported | render-side gap |
| `routing_instances[].description` | unsupported | render-side gap |
| `routing_instances[].l3_vni` | unsupported | render-side gap (Type-5 VRF-property model needs nve1 emit) |
| `interfaces[].vrf` | unsupported | render-side gap on `<network-instances>` membership |

## Repair path

The cisco_iosxe `_render_canonical` would need to:

1. Emit `<network-instances><network-instance>` records with
   `<name>`, `<config><type>` (mapping Junos `vrf` to OpenConfig
   `L3VRF`, `mac-vrf` to `MAC_VRF`, `l2vpn` to `L2VSI`), and
   `<config><route-distinguisher>`.
2. Emit per-VRF `<protocols><protocol identifier=BGP>` augments
   carrying `route-target import` / `export` lists (per
   address-family).
3. Emit `<network-instance><interfaces><interface>` references
   to mark per-interface VRF membership.
4. For L3 VNI (Type-5), emit the appropriate
   `<network-instance><config>` augment OR vendor-native
   `member vni N associate vrf X` under `interface nve1`.

This is a substantial render-side wire-up — well beyond the
Phase-0.5 stub's scope.  Junos source `instance_type` values
beyond `vrf` would need careful handling (Cisco has no first-
class `virtual-router` analogue; `evpn` instance-type maps to
MAC-VRF on Catalyst with EVPN feature license).

## Junos vs Cisco instance-type mapping

| Junos `instance-type` | Cisco analogue | Notes |
|---|---|---|
| `vrf` | `vrf definition` (L3VRF) | Default cross-vendor case |
| `mac-vrf` | MAC-VRF (EVPN feature) | Requires EVPN license + nve1 |
| `virtual-router` | (none, Cisco PE-CE only via VRF-Lite) | No clean analogue |
| `l2vpn` | (none on Catalyst; ASR9K has L2VPN) | Junos-only on most Cisco platforms |
| `evpn` | EVPN bridge-domain | Maps to MAC-VRF on Catalyst |

Cross-vendor render of non-`vrf` instance types would emit a
comment / warning rather than a real config block.  Even after
render-side wire-up, the `instance_type` field stays `lossy`
because the Junos enum is richer than what Cisco models cleanly.

## Per-VRF static routes

`CanonicalStaticRoute` lacks a `vrf` field today, so per-VRF
static routes (Junos's `set routing-instances X routing-options
static route ...`) parse-and-ignore on the canonical layer.
This is a schema gap deferred to a subsequent canonical-model
pass; even with cisco_iosxe render-side VRF wire-up, per-VRF
static routes wouldn't survive until the schema gap closes.
