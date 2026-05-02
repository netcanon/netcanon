# VXLAN / EVPN — Cisco NETCONF source to OPNsense target

Source: [OpenConfig network-instance use cases](https://openconfig.net/docs/models/network_instance/)
Retrieved: 2026-05-01

Source: [openconfig-evpn YANG model (GitHub)](https://github.com/openconfig/public/tree/master/release/models/evpn)
Retrieved: 2026-05-01

Source: [Catalyst 9000 Series EVPN-VXLAN Configuration Guide](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-15/configuration_guide/vxlan/b_1715_bgp_evpn_vxlan_9300_cg.html)
Retrieved: 2026-05-01

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-05-01

## Both ends decline

VXLAN and EVPN are out of scope on BOTH sides of this pair:

### cisco_iosxe (source)

The codec's `CapabilityMatrix._CAPS` declares these paths under
`unsupported`:

- `/vxlan-vnis/vni` — "VXLAN not modelled in this NETCONF/OpenConfig
  stub codec.  CLI sibling defers VXLAN wire-up until Catalyst
  demand arrives; NETCONF stays in lockstep."
- `/vxlan-vnis/source-interface`
- `/vxlan-vnis/udp-port`

The parser also doesn't walk `<network-instances>` (where EVPN
lives in OpenConfig), so `intent.evpn_type5_routes` and
`intent.routing_instances` stay empty regardless.

### opnsense (target)

The OPNsense codec's `CapabilityMatrix._CAPS` lists `/vxlan-vnis/vni`
under `unsupported` with rationale "VXLAN not modelled — OPNsense
is a firewall codec."  OPNsense is FreeBSD-based; the underlying
OS supports VXLAN at the driver layer (`ifconfig vxlan0 create
...`) but `config.xml` carries no VXLAN configuration.  EVPN has no
OPNsense surface at all — there's no BGP / EVPN control-plane.

## Cross-pair disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `vxlan_vnis` | unsupported | source matrix declares `/vxlan-vnis/vni` unsupported; target also declares unsupported |
| `evpn_type5_routes` | unsupported | both sides decline; no canonical-stable surface |
| `routing_instances` | unsupported | OPNsense has no VRF model; source parser doesn't walk `<network-instances>` either |

These dispositions are stable across parser wire-up — even if the
cisco_iosxe parser learned to read VXLAN/EVPN/VRF subtrees, the
OPNsense target couldn't accept them.  Operator-level redesign
required for any L2VPN / fabric migration that touches an OPNsense
node.
