# VRF / routing-instances: Junos versus OPNsense

Why Junos routing-instances do not cross to OPNsense target.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/instance-type-edit-routing-instances.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/vpn-l3/topics/topic-map/l3vpns-overview.html (retrieved 2026-05-01)
- OPNsense: https://docs.opnsense.org/manual/interfaces.html (retrieved 2026-04-30)

## Junos form

Junos models VRFs as routing-instances with a typed `instance-type`:

```
set routing-instances TENANT_A instance-type vrf
set routing-instances TENANT_A description "Tenant A L3 VRF"
set routing-instances TENANT_A route-distinguisher 172.16.0.1:10000
set routing-instances TENANT_A vrf-target target:65000:10000
set routing-instances TENANT_A interface irb.100
set routing-instances TENANT_A protocols evpn ip-prefix-routes vni 50100

set routing-instances TENANT_B instance-type mac-vrf
set routing-instances TENANT_B vrf-target import target:65000:20000
set routing-instances TENANT_B vrf-target export target:65000:20001

set routing-instances RTR_C instance-type virtual-router
```

Instance types: `vrf`, `virtual-router`, `mac-vrf`, `l2vpn`, `evpn`.

The juniper_junos codec capability matrix lists
`/routing-instances/instance` under `supported` (GAP 6 wired); the
`CanonicalRoutingInstance.l3_vni` field is populated for Type-5
EVPN routing.

## OPNsense form

OPNsense is a FreeBSD-based router/firewall with a single global
routing table.  There is **no VRF / routing-instance concept in
config.xml** — FreeBSD's FIB-based per-jail routing is a kernel
feature, not exposed via the OPNsense canonical wire format.

The opnsense codec capability matrix does not advertise
`/routing-instances/instance` (neither supported, lossy, nor
unsupported — structurally absent on this codec).

## Cross-vendor mapping

* Junos source -> OPNsense render:
  `CanonicalIntent.routing_instances` is populated from the Junos
  parse (with each instance's name, type, RD, route-targets,
  description, and L3 VNI).  The opnsense codec's render path
  emits no VRF directive (no construct on the platform); the entire
  routing-instance list drops on OPNsense render.
* `CanonicalInterface.vrf` back-pointers populated by the Junos
  parser drop on OPNsense render — interfaces lose their VRF
  membership and revert to the implicit global routing context.
* `CanonicalRoutingInstance.l3_vni` (used for EVPN Type-5 routing)
  is also dropped — OPNsense has no EVPN.
* `mac-vrf` and `virtual-router` instance types are even less
  expressible — OPNsense has neither L2VPN nor multi-router
  primitives.

The cross-pair flags this as `unsupported` rather than
`not_applicable` because Junos source actively populates the
canonical fields; the loss is real (the operator's tenant
isolation does not survive the migration), not just structurally
empty.

Disposition: **unsupported** (Junos source populates the canonical
fields; OPNsense target has no construct to render them).
