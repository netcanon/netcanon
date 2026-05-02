# VXLAN / EVPN — OPNsense source to Cisco NETCONF target

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-05-01

Source: [openconfig-evpn YANG model (GitHub)](https://github.com/openconfig/public/tree/master/release/models/evpn)
Retrieved: 2026-05-01

Source: [Catalyst 9000 Series EVPN-VXLAN Configuration Guide](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-15/configuration_guide/vxlan/b_1715_bgp_evpn_vxlan_9300_cg.html)
Retrieved: 2026-05-01

## Both ends decline

VXLAN and EVPN are out of scope on BOTH sides of this pair:

### opnsense (source)

OPNsense's codec `CapabilityMatrix._CAPS` declares `/vxlan-vnis/vni`,
`/vxlan-vnis/source-interface`, `/vxlan-vnis/udp-port` under
`unsupported` with rationale "VXLAN not modelled — OPNsense is a
firewall codec."  EVPN has no OPNsense surface — there's no BGP /
EVPN control-plane.  `intent.vxlan_vnis`, `intent.evpn_type5_routes`
are always empty from this source.

### cisco_iosxe (target)

The codec's `CapabilityMatrix._CAPS` declares these paths under
`unsupported`:

- `/vxlan-vnis/vni` — "VXLAN not modelled in this NETCONF/OpenConfig
  stub codec.  CLI sibling defers VXLAN wire-up until Catalyst
  demand arrives; NETCONF stays in lockstep."
- `/vxlan-vnis/source-interface`
- `/vxlan-vnis/udp-port`

The renderer also doesn't emit `<network-instances>` (where EVPN
and VRF live in OpenConfig), so even if the canonical tree carried
EVPN Type-5 routes or routing-instances, the render would drop
them.

## Cross-pair disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `vxlan_vnis` | not_applicable | OPNsense source never populates (matrix declares unsupported); target also declares unsupported |
| `evpn_type5_routes` | not_applicable | both sides decline |
| `routing_instances` | not_applicable | OPNsense has no VRF model regardless |

These dispositions are stable across render wire-up — even if the
cisco_iosxe renderer learned to emit VXLAN/EVPN/VRF subtrees, the
OPNsense source has nothing to feed them.  Operator-level redesign
required for any L2VPN / fabric migration that touches an OPNsense
node.

`not_applicable` rather than `unsupported` here because the source
doesn't populate the canonical fields (per the schema-README
definition: "the field is structurally absent on the source
vendor's wire format").  The target's `unsupported` matrix entry
is moot — there's no data to fail to render.
