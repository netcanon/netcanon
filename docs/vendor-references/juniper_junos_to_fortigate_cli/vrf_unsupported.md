# VRF / routing-instances — unsupported on Juniper Junos -> FortiGate in v1

## Junos model: routing-instances with rich instance-type discriminator

Source: [Junos `instance-type` statement reference](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/instance-type-edit-routing-instances.html).
Source: [Junos L3 VPN topic-map](https://www.juniper.net/documentation/us/en/software/junos/vpn-l3/topics/topic-map/l3vpns-overview.html).
Retrieved: 2026-05-01.

Junos models VRF and tenant separation under `set routing-instances
<name> ...` with a rich `instance-type` discriminator:

```
set routing-instances TENANT_A instance-type vrf
set routing-instances TENANT_A description "Tenant A L3 VRF"
set routing-instances TENANT_A route-distinguisher 172.16.0.1:10000
set routing-instances TENANT_A vrf-target target:65000:10000
set routing-instances TENANT_A interface irb.100
set routing-instances TENANT_A protocols evpn ip-prefix-routes vni 50100
#
set routing-instances TENANT_B instance-type mac-vrf
set routing-instances TENANT_B route-distinguisher 172.16.0.1:20000
set routing-instances TENANT_B vrf-target import target:65000:20000
set routing-instances TENANT_B vrf-target export target:65000:20001
#
set routing-instances RTR_C instance-type virtual-router
set routing-instances RTR_C interface ge-0/0/0.0
```

The Junos codec capability matrix advertises
`/routing-instances/instance` under supported (GAP 6 wired).
Canonical CanonicalRoutingInstance records ARE populated from
Junos source.

## FortiGate model: VDOMs + per-interface integer VRF (unparsed)

Source: [FortiGate / FortiOS Administration Guide — Virtual Domains (VDOMs)](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-05-01.

FortiGate has two distinct multi-tenancy primitives:

1. **VDOMs** — heavyweight multi-tenancy with independent firewall
   policy tables, address objects, admin sessions, and routing
   tables.  Configured under `config vdom / edit <name>`.
2. **Per-interface integer VRF** — FortiOS 7.0+ supports `set vrf
   <id>` (range 0-251).

Neither is wired into canonical render in v1:

- VDOMs would require per-VDOM canonical-tree splitting (the
  migration model is one CanonicalIntent per device).
- Per-interface integer VRF is parse-and-render-ignore in v1
  (FortiGate codec capability matrix does not advertise it).

## Disposition on cross-vendor migration

- **routing_instances** — `unsupported`.  Junos populates
  CanonicalRoutingInstance with name / instance-type / RD / RT /
  interface bindings; FortiGate render emits no VRF binding.
- **routing_instances[].instance_type** — `unsupported`.  FortiGate
  has no per-VRF instance-type discriminator; even when v2 wires
  the FortiGate render, the integer VRF model has no analogue for
  non-`vrf` types (mac-vrf, l2vpn, evpn — L2-fabric constructs
  FortiGate doesn't model).
- **routing_instances[].route_distinguisher / rt_imports /
  rt_exports / l3_vni / description** — `unsupported`.  Same
  underlying gap.
- **interfaces[].vrf** — `unsupported`.  Junos GAP 6 source-side
  populates this; FortiGate render-side unwired.

## Lands when …

The FortiGate codec gains VRF render wire-up:

1. Per-interface `set vrf <id>` render synthesis from
   CanonicalRoutingInstance bindings (with operator-curated lookup
   tables for name -> integer-id mapping).
2. (Optional, longer-term) per-VDOM canonical-tree projection.

Both are deferred to subsequent audit passes.
