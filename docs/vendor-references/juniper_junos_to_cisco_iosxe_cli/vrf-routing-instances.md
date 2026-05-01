# Routing-instances / VRF: Juniper Junos versus Cisco IOS-XE

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/vpn-l3/topics/topic-map/l3vpns-overview.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/instance-type-edit-routing-instances.html (retrieved 2026-04-30)
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/mp_l3_vpns/configuration/xe-3s/mp-l3-vpns-xe-3s-book/mp-vpn-ipv4-ipv6.html (retrieved 2026-04-30)
- Cisco: https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-9/configuration_guide/rtng/b_179_rtng_9400_cg/configuring_vrf_lite.html (retrieved 2026-04-30)

Citation ids: `junos-l3vpn`, `junos-instance-type`, `cisco-vrf-cli`, `cisco-vrf-lite-cg`.

## Junos form

```
set routing-instances TENANT_A instance-type vrf
set routing-instances TENANT_A description "Tenant A"
set routing-instances TENANT_A route-distinguisher 65001:100
set routing-instances TENANT_A vrf-target target:65001:100
set routing-instances TENANT_A interface ge-0/0/0.0
set routing-instances TENANT_A interface ge-0/0/0.100
```

Routing-instance types include `vrf`, `virtual-router`, `mac-vrf`,
`l2vpn`, `evpn`.  The `vrf-target` shorthand is equivalent to
identical `vrf-import` + `vrf-export` policies.  Asymmetric
import/export requires explicit `policy-options` plumbing.

## Cisco IOS-XE form

```
vrf definition TENANT_A
 description "Tenant A"
 rd 65001:100
 address-family ipv4
  route-target export 65001:100
  route-target import 65001:100
 exit-address-family
!
interface GigabitEthernet1/0/1
 vrf forwarding TENANT_A
 ip address 10.1.0.1 255.255.255.0
```

The legacy `ip vrf X` form is deprecated.  Modern multi-AF
`vrf definition` is the IOS-XE convention.

## Mapping notes

- **Pivot side.** Canonical `CanonicalInterface.vrf` (interface-
  side back-pointer) is the cross-vendor pivot.  Junos source has
  the binding routing-instance-side; Cisco source has the binding
  interface-side; canonical normalises to the interface-side form.
- **Instance type.** Junos's `instance-type` enum (`vrf`,
  `virtual-router`, `mac-vrf`, `l2vpn`, `evpn`) collapses to
  Cisco's implicit `vrf` semantic.  Junos source with a
  non-`vrf` instance-type cannot be represented faithfully on
  Cisco; canonical preserves the string but cross-vendor render
  emits a comment for non-`vrf` types.
- **RT shorthand vs explicit.** Junos's `vrf-target target:...`
  maps to canonical `rt_imports` + `rt_exports` (single-RT case)
  -> Cisco emits matching `route-target export` / `import` lines.
  Asymmetric import/export configured via Junos
  `policy-statement` is not modelled canonically.
- **Per-AF route-targets.** Cisco's `address-family ipv4 / ipv6`
  blocks with per-AF route-targets are richer than Junos's
  per-instance `vrf-target`.  Canonical carries a single
  `rt_imports` / `rt_exports` list (AF-agnostic); cross-vendor
  round-trip flattens.
- **L3 VNI for EVPN Type-5.** Junos's `protocols evpn
  ip-prefix-routes vni N` under the routing-instance maps to
  canonical `CanonicalRoutingInstance.l3_vni`; Cisco
  IOS-XE's per-VRF `member vni N vrf X` (under `interface nve1`)
  is the equivalent.  Both depend on per-codec wire-up status.

## Capability matrix status

- Junos codec capability matrix lists `/routing-instances/instance`
  under `supported` (GAP 6 wired).
- Cisco IOS-XE codec capability matrix lists
  `/routing-instances/instance` under `unsupported` with rationale
  "VRF declarations and per-interface `vrf forwarding`
  parse-and-ignore in v1; canonical schema exists, wire-up
  deferred."

Disposition: **lossy** on Junos -> Cisco render (canonical
intent intact, but Cisco render is parse-only on the receiving
side, so a Junos source -> Cisco render produces no `vrf
definition` blocks today).  Marked unsupported pending Cisco
wire-up.
