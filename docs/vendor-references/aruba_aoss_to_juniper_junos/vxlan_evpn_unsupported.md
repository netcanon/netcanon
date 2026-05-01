# VXLAN / EVPN: Aruba AOS-S versus Juniper Junos

Why VXLAN VNI mappings and EVPN Type-5 routes do not cross from
Aruba AOS-S source to Juniper Junos target.

Sources:
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn-vxlan/topics/concept/evpn-vxlan-data-center-overview.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn/topics/example/evpn-vxlan-irb-within-data-center.html (retrieved 2026-05-01)

Citation ids: `aruba-vxlan-unsupported`, `junos-evpn-overview`,
`junos-evpn-irb-example`.

## Aruba AOS-S form

AOS-S is a campus L2 / L3 access platform.  It does **not model
VXLAN, EVPN, or any overlay-fabric primitives**.  The aruba_aoss
codec capability matrix lists every overlay path under
`unsupported` with rationale "VXLAN not modelled — AOS-S is a
campus L2/L3 codec":

* `/vxlan-vnis/vni`
* `/vxlan-vnis/source-interface`
* `/vxlan-vnis/udp-port`

The newer Aruba CX (AOS-CX) firmware family supports VXLAN; AOS-S
on ProCurve heritage hardware does not.

## Junos form

Junos QFX / EX / MX support full EVPN-VXLAN with per-VLAN VNI
bindings, switch-options-level VTEP plumbing, and Type-5 IP-prefix
routes via L3 VNIs:

```
set switch-options vtep-source-interface lo0.0
set switch-options route-distinguisher 172.16.0.1:1
set switch-options vrf-target target:65000:9999
set switch-options vxlan-port 4789

set vlans USERS vlan-id 10
set vlans USERS vxlan vni 10010
set vlans TENANT_A_DATA vxlan vni 10100
set vlans TENANT_A_DATA l3-interface irb.100

set routing-instances TENANT_A instance-type vrf
set routing-instances TENANT_A protocols evpn ip-prefix-routes vni 50100
```

The juniper_junos codec capability matrix lists `/vxlan-vnis/vni`,
`/vxlan-vnis/source-interface`, and `/vxlan-vnis/udp-port` under
`supported` (GAP-EVPN-2 wired).

## Cross-vendor mapping

* Aruba source -> Junos render:
  `CanonicalIntent.vxlan_vnis` is always empty on Aruba parse, so
  Junos render emits no `set vlans <name> vxlan vni <N>` lines and
  no `set switch-options` plumbing.
* `CanonicalIntent.evpn_type5_routes` and the
  `CanonicalRoutingInstance.l3_vni` field are also always empty on
  Aruba parse.

The cross-pair is structurally empty rather than lossy or
unsupported on this direction — there is no source data to lose.

Disposition: **not_applicable** for `vxlan_vnis` and
`evpn_type5_routes` (Aruba lacks the concept).
