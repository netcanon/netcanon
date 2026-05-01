# VRF / routing-instances: Cisco IOS-XE versus Juniper Junos

How each platform declares the L3 isolation primitive (VRF / routing
instance).

Sources:
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/mp_l3_vpns/configuration/xe-3s/mp-l3-vpns-xe-3s-book/mp-vpn-ipv4-ipv6.html (retrieved 2026-04-30)
- Cisco: https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-9/configuration_guide/rtng/b_179_rtng_9400_cg/configuring_vrf_lite.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/vpn-l3/topics/topic-map/l3vpns-overview.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/instance-type-edit-routing-instances.html (retrieved 2026-04-30)

Citation ids: `cisco-vrf-cli`, `cisco-vrf-lite-cg`, `junos-l3vpn`, `junos-instance-type`.

## Cisco IOS-XE form

Modern multi-AF VRF declaration:

```
vrf definition TENANT_A
 description "Tenant A"
 rd 65001:100
 address-family ipv4
  route-target export 65001:100
  route-target import 65001:100
 exit-address-family
 address-family ipv6
  route-target export 65001:100
  route-target import 65001:100
 exit-address-family
```

The legacy `ip vrf X` form is deprecated in favour of the multi-AF
`vrf definition` form (see Cisco's MPLS L3 VPN configuration guide).

Per-interface VRF binding:

```
interface GigabitEthernet1/0/1
 vrf forwarding TENANT_A
 ip address 10.1.0.1 255.255.255.0
```

Per-VRF static routes live in the global `ip route vrf X` form (see
`static-routes.md`).

## Junos form

Routing-instance declaration:

```
set routing-instances TENANT_A instance-type vrf
set routing-instances TENANT_A description "Tenant A"
set routing-instances TENANT_A route-distinguisher 65001:100
set routing-instances TENANT_A vrf-target target:65001:100
set routing-instances TENANT_A interface ge-0/0/0.0
```

Junos's `vrf-target` shorthand is equivalent to setting both
`vrf-import` and `vrf-export` to the same RT.  When import and
export differ, Junos uses the explicit policy-statement form:

```
set routing-instances TENANT_A vrf-import IMPORT_POLICY
set routing-instances TENANT_A vrf-export EXPORT_POLICY
set policy-options policy-statement IMPORT_POLICY term import-rt from community RT_IN
set policy-options community RT_IN members target:65001:100
```

Routing-instance types: `vrf`, `virtual-router`, `mac-vrf`, `l2vpn`,
`evpn`.

## Mapping notes

- **Pivot side.** Cisco's interface-side `vrf forwarding X` is the
  primary VRF binding; Junos's routing-instance-side `set
  routing-instances X interface ge-...` is the primary binding.
  Canonical `CanonicalInterface.vrf` (interface-side back-pointer)
  is the cross-vendor pivot.  Junos render walks
  `tree.interfaces` to synthesise the routing-instance-side
  `interface` line.
- **Instance type.** Cisco has no per-VRF instance-type
  discriminator (always `vrf` semantically); Junos models a wider
  enum (`vrf`, `virtual-router`, `mac-vrf`, `l2vpn`, `evpn`).
  Cisco source -> Junos always renders as `instance-type vrf`.
  Junos source with a non-`vrf` instance-type cannot be emitted on
  the Cisco side without information loss; canonical preserves the
  string verbatim.
- **RT shorthand vs policy.** Junos's simple `vrf-target target:...`
  maps to canonical `rt_imports` + `rt_exports` (single-RT case).
  Mixed-RT or filtered RTs require Junos's policy-statement plumbing
  which is not modelled in v1; canonical emits the simple form.
- **Multi address-family.** Cisco's `address-family ipv4 / ipv6`
  blocks under `vrf definition` carry per-AF route-targets.  Junos
  uses `rib-groups` and per-instance `protocols` blocks for the
  same semantic.  Canonical model carries a single
  `rt_imports` / `rt_exports` list (AF-agnostic); cross-vendor
  round-trip flattens the per-AF distinction.

Disposition: **unsupported** for Cisco source today (Cisco IOS-XE
codec capability matrix lists `/routing-instances/instance` under
`unsupported` with rationale "VRF declarations and per-interface
`vrf forwarding` parse-and-ignore in v1; canonical schema exists,
wire-up deferred"); **good** for Junos source.
