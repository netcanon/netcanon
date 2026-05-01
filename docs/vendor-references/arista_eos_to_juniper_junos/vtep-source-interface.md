# VTEP source interface

How Arista EOS and Juniper Junos declare the loopback that originates
VXLAN-encapsulated traffic.

Sources:
- Arista: https://www.arista.com/en/um-eos/eos-vxlan-configuration (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn-vxlan/ovsdb-vxlan-qfx/topics/ref/statement/vtep-source-interface.html (retrieved 2026-05-01)

Citation ids: `arista-vxlan-cg`, `junos-vtep-source-iface`.

## Arista EOS form

```
interface Vxlan1
   vxlan source-interface Loopback0
   vxlan udp-port 4789
   vxlan vlan 100 vni 10100
```

`vxlan source-interface <Loopback>` lives inside the synthetic
`interface VxlanN` stanza (almost always `Vxlan1`).  The loopback is
an ordinary interface declared elsewhere (`interface Loopback0` /
`ip address X/32`).

## Junos form

```
set interfaces lo0 unit 0 family inet address 10.255.0.1/32
set switch-options vtep-source-interface lo0.0
set switch-options route-distinguisher 10.255.0.1:1
set switch-options vrf-target target:65001:1
```

`vtep-source-interface` lives under `switch-options` (default
switch-instance) or under `routing-instances <name>` (when the VTEP
is per-instance, MAC-VRF style).  The unit-form name (`lo0.0`, not
`lo0`) is required because Junos VTEPs are bound to a specific
logical unit.

## Mapping notes

- Canonical `CanonicalVxlan.source_interface` carries the
  operator-form name verbatim; the canonical port-rename mesh
  bridges `Loopback0` ↔ `lo0.0` via the standard logical-interface
  mapping (Loopback0 → lo0.0 is the documented default for this
  pair).
- The rename is symmetric and lossless when the operator hasn't
  customised the loopback name.  Operators using `Loopback42` /
  `lo0.42` get a rename suggestion in the per-pane override surface.
- Both vendors default to UDP 4789; the canonical `udp_port` field
  carries the override losslessly.
