# VRF / routing-instances: Aruba AOS-S versus Juniper Junos

Why VRFs do not cross from Aruba AOS-S source to Juniper Junos target.

Sources:
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/instance-type-edit-routing-instances.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/vpn-l3/topics/topic-map/l3vpns-overview.html (retrieved 2026-05-01)

Citation ids: `aruba-vrf-unsupported`, `junos-instance-type`,
`junos-l3vpn`.

## Aruba AOS-S form

AOS-S is a campus L2 / basic-L3 platform with a single global
routing table.  There is **no VRF / routing-instance concept** —
the platform does not expose multi-tenant L3 isolation beyond
VLAN-level segmentation with a shared default routing context.

Some Aruba AOS-CX (the newer cloud-native firmware family) supports
VRFs, but AOS-S (ProCurve heritage on 2930F / 2930M / 3810 / 5400R)
does not.  The aruba_aoss codec models AOS-S only.

The aruba_aoss codec capability matrix does not advertise
`/routing-instances/instance` on either the supported or lossy
sides.

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
set routing-instances RTR_C instance-type virtual-router
```

Instance types include `vrf`, `virtual-router`, `mac-vrf`, `l2vpn`,
`evpn` — distinct semantics for L3-VPN, lightweight router, EVPN
overlay, and L2-VPN deployments.

The juniper_junos codec capability matrix lists
`/routing-instances/instance` under `supported` (GAP 6 wired).

## Cross-vendor mapping

* Aruba source -> Junos render: `CanonicalIntent.routing_instances`
  is always empty on Aruba parse (the field is structurally absent
  on the wire format), so Junos render emits no
  `set routing-instances` blocks.  The cross-pair is structurally
  empty rather than lossy or unsupported on this direction.
* `CanonicalInterface.vrf` is also always empty on Aruba source
  (no per-interface VRF binding on the platform).

Disposition: **not_applicable** (Aruba lacks the concept; the
canonical fields are always empty on this direction so nothing is
lost on render).
