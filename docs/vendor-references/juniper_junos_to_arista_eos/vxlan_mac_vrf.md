# VXLAN VNI mapping + MAC-VRF / L3-VRF instance types

How VLAN-to-VNI bindings, VTEP source interface, and EVPN MAC-VRF /
L3-VRF instance types are configured on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn/topics/example/evpn-vxlan-irb-within-data-center.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn-vxlan/topics/concept/evpn-vxlan-data-center-overview.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn-vxlan/ovsdb-vxlan-qfx/topics/ref/statement/vtep-source-interface.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/instance-type-edit-routing-instances.html (retrieved 2026-05-01)
- Arista: https://www.arista.com/en/um-eos/eos-vxlan-configuration (retrieved 2026-05-01)
- Arista: https://www.arista.com/en/um-eos/eos-configuring-evpn (retrieved 2026-05-01)

Citation ids: `junos-evpn-irb-example`, `junos-evpn-overview`,
`junos-vtep-source-iface`, `junos-instance-type`, `arista-vxlan-cg`,
`arista-evpn-cg`.

## Junos form

```
set switch-options vtep-source-interface lo0.0
set switch-options route-distinguisher 10.255.255.1:1
set switch-options vrf-target target:65000:1

set vlans v100 vlan-id 100
set vlans v100 vxlan vni 10100
set vlans v200 vlan-id 200
set vlans v200 vxlan vni 10200

set routing-instances TENANT-A instance-type vrf
set routing-instances TENANT-A interface irb.100
set routing-instances TENANT-A route-distinguisher 10.255.255.1:100
set routing-instances TENANT-A vrf-target target:65000:100
set routing-instances TENANT-A protocols evpn ip-prefix-routes vni 99100
set routing-instances TENANT-A protocols evpn ip-prefix-routes encapsulation vxlan

set routing-instances MACVRF-A instance-type mac-vrf
set routing-instances MACVRF-A vtep-source-interface lo0.0
set routing-instances MACVRF-A vlans v100
```

Junos has multiple instance-type discriminators:
- `vrf` — L3-VRF (RFC 4364 style with RD + RT).
- `virtual-router` — L3 isolation without RD/RT (CE-LAN).
- `mac-vrf` — MAC-VRF for EVPN-VXLAN (per-tenant MAC table).
- `l2vpn` — point-to-point pseudo-wire L2VPN.

VTEP source interface is declared once at the global
`switch-options` level (default switch) or per-MAC-VRF on
`set routing-instances NAME vtep-source-interface lo0.0`.

## Arista form

```
interface Loopback0
   ip address 10.255.255.1/32

interface Vxlan1
   vxlan source-interface Loopback0
   vxlan udp-port 4789
   vxlan vlan 100 vni 10100
   vxlan vlan 200 vni 10200
   vxlan vrf TENANT-A vni 99100

vrf instance TENANT-A
   rd 10.255.255.1:100
   route-target import evpn 65000:100
   route-target export evpn 65000:100

ip routing vrf TENANT-A

router bgp 65000
   vrf TENANT-A
      rd 10.255.255.1:100
      route-target import evpn 65000:100
      route-target export evpn 65000:100

! MAC-VRF (Arista 4.27+ explicit MAC-VRF feature)
router bgp 65000
   vlan-aware-bundle TENANT-MACVRF
      rd 10.255.255.1:1
      route-target both 65000:1
      vlan 100,200
```

Arista has a single VTEP per device (the `interface Vxlan1` stanza),
with VLAN-to-VNI bindings declared as `vxlan vlan <id> vni <vni>`
lines.  L3-VNI for EVPN Type-5 routing is declared as
`vxlan vrf <name> vni <vni>`.  Per-VRF RD/RT live under
`vrf instance` + `router bgp / vrf X`.

## Mapping notes

- **VTEP source interface.** Junos `lo0.0` <-> Arista `Loopback0`
  via the port-rename mesh.  Canonical preserves the operator-form
  string; render emits the platform-form name.
- **VLAN-to-VNI binding.** Direct one-to-one mapping (Junos
  `set vlans NAME vxlan vni N` -> Arista `vxlan vlan <id> vni N`).
  Canonical `CanonicalVxlanVni{vlan_id, vni}` carries losslessly.
- **L3-VNI.** Junos `set routing-instances NAME protocols evpn
  ip-prefix-routes vni N` -> Arista `vxlan vrf NAME vni N`.
  Canonical `CanonicalRoutingInstance.l3_vni` carries the binding.
- **Instance-type discriminator.**
  - `vrf` -> Arista `vrf instance` (lossless).
  - `mac-vrf` -> Arista's vlan-aware-bundle MAC-VRF feature
    (lossless on 4.27+, lossy banner on earlier).
  - `virtual-router` -> **unsupported** on Arista (no analogue;
    Arista has no L3-isolation-without-RT primitive).  Canonical
    field carries the discriminator; render emits a `!` comment.
  - `l2vpn` -> not in canonical scope (out of band).
- **RD / RT.** Both accept `<asn>:<nn>` and `<ip>:<nn>` forms.
  Direct one-to-one.
- **UDP port.** Both default to 4789 (IANA).  Junos QFX is not
  commonly tunable; Arista's `vxlan udp-port N` is — canonical
  preserves the value, lossless on default.
- **Multicast group / flood list.** Junos's BGP-EVPN-signalled
  ingress replication is the default; explicit static flood lists
  (`set vlans NAME vxlan static-remote-vtep-list`) translate
  loosely to Arista's `vxlan flood vtep` head-end-replication form.
  `mcast_group` not commonly used on Junos; canonical carries it
  for completeness.
