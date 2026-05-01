# VLAN-to-VNI mapping

How a Layer-2 VLAN gets bound to its 24-bit VXLAN Network Identifier
on each platform.

Sources:
- Arista: https://www.arista.com/en/um-eos/eos-vxlan-configuration (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn/topics/example/evpn-vxlan-irb-within-data-center.html (retrieved 2026-05-01)

Citation ids: `arista-vxlan-cg`, `junos-evpn-irb-example`.

## Arista EOS form

```
interface Vxlan1
   vxlan source-interface Loopback0
   vxlan vlan 100 vni 10100
   vxlan vlan 200 vni 10200
   vxlan vlan 101-102 flood vtep 11.1.1.1 11.1.1.2
```

`vxlan vlan <id> vni <vni>` — single-line declarative association.
Arista flood-list syntax uses `vxlan vlan <range> flood vtep <ip>...`
for head-end replication; multicast declared via `vxlan vlan <id>
multicast-group <mcast>`.

## Junos form

```
set vlans v100 vlan-id 100
set vlans v100 vxlan vni 10100
set vlans v200 vlan-id 200
set vlans v200 vxlan vni 10200
```

VLANs in Junos are always named (`v100`, not bare `100`), and the
VNI binding lives under the `vlans <name> vxlan vni <vni>` hierarchy.
The VLAN name is operator-chosen; `set vlans <name> vlan-id <N>` is
the bridge-id binding.

## Mapping notes

- Canonical `CanonicalVxlan{vlan_id, vni}` carries the binding
  losslessly.  Arista's anonymous-VLAN model (id only, no name
  required) maps cleanly to Junos's name-required model when the
  Junos render path synthesises a deterministic name (`v<id>` is
  the documented convention).
- Multicast / flood-list semantics are also carried by
  `CanonicalVxlan{mcast_group, flood_list}`; Junos's per-VNI
  ingress-replication is defaulted by EVPN signaling and rarely
  declared explicitly.
