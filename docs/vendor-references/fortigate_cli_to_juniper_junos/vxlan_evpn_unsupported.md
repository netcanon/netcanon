# VXLAN / EVPN — not_applicable on FortiGate -> Juniper Junos in v1

## Why this is not_applicable from FortiGate source

FortiGate is a firewall codec (capability matrix declares device
classes `firewall` + `router`).  The FortiGate codec capability
matrix lists the canonical VXLAN paths under unsupported:

- `/vxlan-vnis/vni` — "VXLAN not modelled — FortiGate is a firewall codec."
- `/vxlan-vnis/source-interface` — "VXLAN not modelled (see /vxlan-vnis/vni)."
- `/vxlan-vnis/udp-port` — "VXLAN not modelled (see /vxlan-vnis/vni)."

FortiOS does support VXLAN tunnel interfaces for limited scenarios
(VXLAN-over-IPsec for SD-WAN overlays, point-to-point L2 stretch over
WAN), but no EVPN control plane.  The FortiGate codec deliberately
does not model VXLAN VNI mappings or EVPN advertisements.

## Junos EVPN-VXLAN target

Source: [Junos EVPN-VXLAN data-center overview](https://www.juniper.net/documentation/us/en/software/junos/evpn-vxlan/topics/concept/evpn-vxlan-data-center-overview.html).
Retrieved: 2026-05-01.

Junos has rich EVPN-VXLAN fabric support on QFX / EX / MX:

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

The Junos codec capability matrix lists the VXLAN paths under
supported (GAP 6 + GAP-EVPN-2 wired):

- `/vxlan-vnis/vni`
- `/vxlan-vnis/source-interface`
- `/vxlan-vnis/udp-port`

## Disposition

- **vxlan_vnis** — `not_applicable`.  FortiGate source never
  populates the canonical list; Junos target receives an empty
  list and emits no `vxlan vni` mappings.  Marked `not_applicable`
  rather than `unsupported` because the canonical schema and the
  Junos render IS wired — the cross-pair simply has no source
  intent to translate.
- **evpn_type5_routes** — `not_applicable` for the same reason.

## What this means in practice

Operators wanting to retain EVPN-VXLAN fabric data plane should
not attempt to project it onto FortiGate-as-edge.  The reverse
direction (Junos -> FortiGate) is `unsupported` (FortiGate has no
fabric data plane to land it on); this forward direction is
`not_applicable` (FortiGate has no source intent).
