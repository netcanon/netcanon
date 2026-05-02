# VXLAN / EVPN: unsupported on OPNsense target

Why Junos EVPN-VXLAN overlay primitives do not cross to OPNsense
target.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn-vxlan/topics/concept/evpn-vxlan-data-center-overview.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn/topics/example/evpn-vxlan-irb-within-data-center.html (retrieved 2026-05-01)
- OPNsense: https://docs.opnsense.org/manual/interfaces.html (retrieved 2026-04-30)

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
set vlans TENANT_A_DATA vlan-id 100
set vlans TENANT_A_DATA vxlan vni 10100
set vlans TENANT_A_DATA l3-interface irb.100

set protocols evpn vni-options vni 10100 vrf-target target:64500:10100
set protocols evpn encapsulation vxlan
set protocols evpn extended-vni-list all

set routing-instances TENANT_A protocols evpn ip-prefix-routes vni 50100
```

The juniper_junos codec capability matrix lists `/vxlan-vnis/vni`,
`/vxlan-vnis/source-interface`, and `/vxlan-vnis/udp-port` under
`supported`.

## OPNsense form

OPNsense is a FreeBSD-based firewall codec.  It does **not model
VXLAN, EVPN, or any overlay-fabric primitives**.  The opnsense
codec capability matrix lists every VXLAN path under `unsupported`
with rationale "VXLAN not modelled — OPNsense is a firewall codec":

* `/vxlan-vnis/vni`
* `/vxlan-vnis/source-interface`
* `/vxlan-vnis/udp-port`

FreeBSD's `if_vxlan(4)` driver exists at the OS level, but OPNsense
does not surface VXLAN configuration through `config.xml` / the
operator UI.

## Cross-vendor mapping

* Junos source -> OPNsense render:
  `CanonicalIntent.vxlan_vnis` is populated by the Junos parse with
  per-VLAN VNI mappings, source-interface (`lo0.0`), and UDP port.
  The opnsense codec's render path emits NOTHING for these — the
  entire list drops on OPNsense render.
* `CanonicalIntent.evpn_type5_routes` is not populated by the Junos
  codec today (Type-5 routes use the
  `CanonicalRoutingInstance.l3_vni` VRF-property model instead);
  the field is empty regardless of source.
* `CanonicalRoutingInstance.l3_vni` populated by the Junos parser
  drops on OPNsense render alongside the parent routing-instance.

The cross-pair flags this as `unsupported` because Junos source
actively populates the canonical fields; the loss is real (the
operator's overlay-fabric configuration does not survive), not just
structurally empty.

Disposition: **unsupported** for `vxlan_vnis`, `evpn_type5_routes`,
and the `l3_vni` field on routing-instances.
