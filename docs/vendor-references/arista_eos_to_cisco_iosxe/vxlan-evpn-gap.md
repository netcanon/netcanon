# VXLAN, EVPN, and MAC-VRF — Arista source to OpenConfig NETCONF target

Source: [Arista EOS VXLAN Configuration Guide (4.36.0F)](https://www.arista.com/en/um-eos/eos-vxlan-configuration)
Retrieved: 2026-05-01

Source: [Arista EOS Configuring EVPN (4.35.2F)](https://www.arista.com/en/um-eos/eos-configuring-evpn)
Retrieved: 2026-05-01

Source: [openconfig-evpn YANG model (GitHub)](https://github.com/openconfig/public/tree/master/release/models/evpn)
Retrieved: 2026-05-01

Source: [OpenConfig network-instance use cases](https://openconfig.net/docs/models/network_instance/)
Retrieved: 2026-05-01

## Arista source surface (rich)

Arista EOS is the most VXLAN/EVPN-mature codec in the suite.  The
parser populates from grammar like:

```
interface Vxlan1
   vxlan source-interface Loopback0
   vxlan udp-port 4789
   vxlan vlan 10 vni 10010
   vxlan vlan 100 vni 10100
   vxlan vrf TENANT_A vni 50100
!
router bgp 65001
   vlan 100
      rd 10.255.0.1:100
      route-target both 65000:100
      redistribute learned
   !
   vrf TENANT_A
      rd 10.255.0.1:50100
      route-target import evpn 65000:50100
      route-target export evpn 65000:50100
   !
   address-family evpn
      neighbor 10.0.0.0 activate
```

Populated canonical fields:

* `intent.vxlan_vnis[]` — full VLAN-to-VNI mappings (vlan_id, vni,
  source_interface, udp_port, mcast_group, flood_list).
* `intent.routing_instances[]` — VRF + MAC-VRF records (the
  per-VLAN BGP `rd` / `route-target` blocks become `mac-vrf`
  instance_type records; the `vrf TENANT_A` block becomes a `vrf`
  instance_type record).
* `intent.routing_instances[].l3_vni` — L3 VNI for symmetric IRB
  Type-5 routing, populated from `vxlan vrf <name> vni N`.

The arista_eos CapabilityMatrix declares `/vxlan-vnis/vni`,
`/vxlan-vnis/source-interface`, `/vxlan-vnis/udp-port`, and
`/routing-instances/instance` under `supported`.

## OpenConfig target surface

OpenConfig models EVPN-VXLAN via:

* `openconfig-network-instance` for VRFs / routing-instances
  (`<network-instances><network-instance>` list with type
  `L3VRF`, `L2VSI`, `L2L3`, etc).
* `openconfig-evpn` for EVPN-specific state (Type-2/3/5 controls,
  EVI bindings) — published at
  `https://github.com/openconfig/public/tree/master/release/models/evpn`.
* Per-VLAN VNI binding via the `openconfig-vlan` augment under
  `openconfig-network-instance` paths.

## What the cisco_iosxe codec emits

`_render_canonical()` does not walk `intent.vxlan_vnis`,
`intent.routing_instances`, or `intent.evpn_type5_routes`.  No
`<network-instances>` element appears in the output XML.  No
`openconfig-evpn` content is emitted.

The capability matrix declares `/vxlan-vnis/vni`,
`/vxlan-vnis/source-interface`, `/vxlan-vnis/udp-port` under
`unsupported` explicitly, with the reason: "VXLAN not modelled in
this NETCONF/OpenConfig stub codec.  CLI sibling defers VXLAN
wire-up until Catalyst demand arrives; NETCONF stays in lockstep."

## Concrete demonstration

For an Arista source with the Vxlan1 + router-bgp blocks above:

* The cisco_iosxe NETCONF output contains the `Vxlan1` interface
  entry as a generic interface with `<type>` set to whatever IANA
  ident the Arista codec inferred (likely `other` for `Vxlan*`
  prefixed names) — but no VXLAN-specific configuration on it.
* No top-level `<network-instances>` block.
* No EVPN BGP signalling state.
* No `<vlans>` block (already gone for non-EVPN reasons; see
  `vlan-render-gap.md`).

A downstream OpenConfig consumer trying to bring up an EVPN-VXLAN
fabric from this output would have nothing to consume.

## Operator implication

For DC EVPN-VXLAN spine-leaf migrations from Arista to Cisco, this
NETCONF target is unusable.  Route through `cisco_iosxe_cli`
instead — that codec's render also currently lacks VXLAN/EVPN
emission (Catalyst-VXLAN demand has been deferred), so even the
CLI target is lossy on these fields.  For Arista -> NX-OS or
Arista -> Junos EVPN-VXLAN flows, use the appropriate target codec
(both have richer EVPN/VXLAN support).

## Disposition

| Field | Disposition | Reason |
|---|---|---|
| `vxlan_vnis` | unsupported | Source parses fully; target matrix declares `/vxlan-vnis/*` `unsupported` AND render-side gap |
| `vxlan_vnis[].vlan_id` | unsupported | Same |
| `vxlan_vnis[].vni` | unsupported | Same |
| `vxlan_vnis[].source_interface` | unsupported | Same |
| `vxlan_vnis[].udp_port` | unsupported | Same |
| `vxlan_vnis[].mcast_group` | unsupported | Same |
| `vxlan_vnis[].flood_list` | unsupported | Same |
| `evpn_type5_routes` | unsupported | Per-prefix records not populated by either codec; matrix-level unsupported on target |
