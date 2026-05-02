# VXLAN / EVPN — unsupported on Juniper Junos -> FortiGate in v1

## Junos EVPN-VXLAN source

Source: [Junos EVPN-VXLAN data-center overview](https://www.juniper.net/documentation/us/en/software/junos/evpn-vxlan/topics/concept/evpn-vxlan-data-center-overview.html).
Source: [Junos EVPN-VXLAN Centrally-Routed Bridging Fabric example](https://www.juniper.net/documentation/us/en/software/junos/evpn/topics/example/evpn-vxlan-irb-within-data-center.html).
Retrieved: 2026-05-01.

Junos has rich EVPN-VXLAN fabric support on QFX / EX / MX, with the
canonical `vxlan_vnis`, `evpn_type5_routes`, and `routing_instances
.l3_vni` paths all wired (GAP 6 + GAP-EVPN-2):

```
set switch-options vtep-source-interface lo0.0
set switch-options route-distinguisher 172.16.0.1:1
set switch-options vrf-target target:65000:9999
set switch-options vxlan-port 4789
#
set vlans TENANT_A_DATA vlan-id 100
set vlans TENANT_A_DATA vxlan vni 10100
set vlans TENANT_A_DATA l3-interface irb.100
#
set protocols evpn vni-options vni 10100 vrf-target target:65000:10100
set protocols evpn extended-vni-list 10100
#
set routing-instances TENANT_A protocols evpn ip-prefix-routes vni 50100
```

Junos source populates:

- `vxlan_vnis[].vlan_id`, `vni`, `mcast_group`, `flood_list`,
  `source_interface`, `udp_port`.
- `routing_instances[].l3_vni` (Type-5 advertisements).

## FortiGate target: no fabric data plane

Source: FortiGate codec capability matrix.

FortiGate is a firewall codec; the FortiGate codec capability matrix
lists VXLAN paths under unsupported:

- `/vxlan-vnis/vni` — "VXLAN not modelled — FortiGate is a firewall codec."
- `/vxlan-vnis/source-interface` — "VXLAN not modelled."
- `/vxlan-vnis/udp-port` — "VXLAN not modelled."

FortiOS does support VXLAN tunnel interfaces for limited SD-WAN
overlay scenarios (point-to-point L2 stretch over WAN, VXLAN-over-
IPsec) but no EVPN control plane and no per-VLAN VNI binding render.

## Disposition on cross-vendor migration

- **vxlan_vnis** — `unsupported`.  Junos populates the canonical
  list (GAP-EVPN-2 wired); FortiGate render emits nothing.
- **vxlan_vnis[].*** — `unsupported` (each sub-field).
- **evpn_type5_routes** — `unsupported`.  FortiGate has no EVPN
  data plane.
- **routing_instances[].l3_vni** — `unsupported`.  Even if VRF
  render were wired, FortiGate has no L3 VNI / Type-5 surface.

## What this means in practice

Operators wanting to retain EVPN-VXLAN fabric data plane should not
attempt to project Junos source intent onto a FortiGate target.  The
forward direction (FortiGate -> Junos) is `not_applicable` (FortiGate
source has no VXLAN intent); this reverse direction is `unsupported`
(FortiGate target has no fabric data plane).
