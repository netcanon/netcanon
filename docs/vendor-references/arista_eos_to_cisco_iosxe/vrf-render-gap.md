# VRFs / routing-instances — Arista source to OpenConfig NETCONF render gap

Source: [Arista EOS Configuring EVPN (4.35.2F)](https://www.arista.com/en/um-eos/eos-configuring-evpn)
Retrieved: 2026-05-01

Source: [OpenConfig network-instance use cases](https://openconfig.net/docs/models/network_instance/)
Retrieved: 2026-05-01

## Arista source surface

Arista EOS uses `vrf instance <name>` to declare a VRF, with
per-VRF address-family enablement via `ip routing vrf <name>` and
the per-interface assignment via `vrf <name>` inside the interface
stanza.  Per-VRF BGP RD + RTs live under `router bgp / vrf <name>`:

```
vrf instance TENANT_A
!
ip routing vrf TENANT_A
!
interface Vlan100
   vrf TENANT_A
   ip address 10.100.0.1/24
!
router bgp 65001
   vrf TENANT_A
      rd 10.255.0.1:50100
      route-target import evpn 65000:50100
      route-target export evpn 65000:50100
```

The arista_eos parser populates:

* `intent.routing_instances[]` — list of CanonicalRoutingInstance
  records (name, instance_type=`vrf`, route_distinguisher,
  rt_imports, rt_exports, l3_vni when set via `vxlan vrf X vni N`).
* `intent.interfaces[].vrf` — per-interface back-pointer to the
  VRF name.

The arista_eos CapabilityMatrix declares `/routing-instances/instance`
and `/interfaces/interface/config/vrf` under `supported`.

## OpenConfig target surface

OpenConfig models VRFs under `openconfig-network-instance`:

```xml
<network-instances xmlns="http://openconfig.net/yang/network-instance">
  <network-instance>
    <name>TENANT_A</name>
    <config>
      <name>TENANT_A</name>
      <type>L3VRF</type>
      <route-distinguisher>10.255.0.1:50100</route-distinguisher>
    </config>
    <interfaces>
      <interface>
        <id>Vlan100.0</id>
      </interface>
    </interfaces>
    <inter-instance-policies>
      <import-export-policy>
        ...
      </import-export-policy>
    </inter-instance-policies>
  </network-instance>
</network-instances>
```

Cisco IOS-XE NETCONF agents expose this subtree, but the cisco_iosxe
codec in Netcanon does not yet wire it up.

## What the cisco_iosxe codec emits

`_render_canonical()` does not walk `intent.routing_instances` or
`intent.interfaces[].vrf`.  No `<network-instances>` element
appears in the output XML.

The codec capability matrix does NOT declare
`/routing-instances/instance` or `/interfaces/interface/config/vrf`
explicitly under either `supported` or `unsupported` — those paths
are absent from the matrix entirely on the cisco_iosxe (NETCONF)
side, while the CLI sibling lists `/routing-instances/instance`
under `unsupported`.  In practice both codecs treat VRFs as a gap;
the disposition on this cross-pair is `unsupported` because the
Arista source has rich data for the target render to drop.

## Concrete demonstration

For the Arista source above, the cisco_iosxe NETCONF output
contains the `Vlan100` interface entry with name / enabled / type
(`l2vlan`) and the IPv4 address `10.100.0.1/24` — but NO VRF
binding.  A downstream OpenConfig consumer sees an SVI in the
default VRF that should be in TENANT_A.  L3 isolation is silently
broken.

## Operator implication

For Arista sources with any VRF state, this NETCONF target is
unusable.  Route through `cisco_iosxe_cli` instead.  The CLI
sibling codec also currently treats `/routing-instances/instance`
as `unsupported` on the render side, so VRF declarations don't
auto-emit there either — but the CLI codec's lossy classification
is mechanically different from this NETCONF codec's silent drop:
operators see a banner flagging the unsupported VRF data and can
manually reconstruct the `vrf definition` blocks.

## Disposition

| Field | Disposition | Reason |
|---|---|---|
| `routing_instances` | unsupported | Render-side wire-up gap; no `<network-instances>` emitted |
| `routing_instances[].name` | unsupported | Same |
| `routing_instances[].instance_type` | unsupported | Same |
| `routing_instances[].route_distinguisher` | unsupported | Same |
| `routing_instances[].rt_imports` | unsupported | Same |
| `routing_instances[].rt_exports` | unsupported | Same |
| `routing_instances[].description` | unsupported | Same |
| `routing_instances[].l3_vni` | unsupported | Doubly: VRF gap PLUS VXLAN gap (matrix `/vxlan-vnis/*` unsupported) |
| `interfaces[].vrf` | unsupported | Render-side gap; per-interface VRF binding not emitted |

Note: `static_routes` is also affected by the same render-side
`<network-instances>` gap (since OpenConfig models static routes as
a per-instance protocol under `<network-instances>`); see the
top-level `static_routes` disposition in the YAML for this pair.
