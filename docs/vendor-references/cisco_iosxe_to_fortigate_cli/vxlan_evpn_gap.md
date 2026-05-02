# VXLAN, EVPN, and VRF — `cisco_iosxe` source to `fortigate_cli` target

Source: [openconfig-evpn YANG model (GitHub)](https://github.com/openconfig/public/tree/master/release/models/evpn)
Retrieved: 2026-05-01

Source: [OpenConfig network-instance use cases](https://openconfig.net/docs/models/network_instance/)
Retrieved: 2026-05-01

Source: [Catalyst 9000 Series EVPN-VXLAN Configuration Guide (IOS-XE 17.15)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-15/configuration_guide/vxlan/b_1715_bgp_evpn_vxlan_9300_cg.html)
Retrieved: 2026-05-01

Source: [Fortinet FortiGate Administration Guide — VRF / VDOM](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/)
Retrieved: 2026-05-01

## VXLAN

The `cisco_iosxe` codec's CapabilityMatrix lists `/vxlan-vnis/vni`,
`/vxlan-vnis/source-interface`, and `/vxlan-vnis/udp-port` under
`unsupported` with rationale:

> "VXLAN not modelled in this NETCONF/OpenConfig stub codec.  CLI
> sibling defers VXLAN wire-up until Catalyst demand arrives;
> NETCONF stays in lockstep."

The `fortigate_cli` codec also lists `/vxlan-vnis/vni` and the
sibling source-interface / udp-port paths under `unsupported`
with rationale:

> "VXLAN not modelled — FortiGate is a firewall codec."

Both codecs decline.  `intent.vxlan_vnis` is empty after
`cisco_iosxe` parse and would not render on FortiGate regardless.

## EVPN Type-5 routes

Same situation.  `cisco_iosxe` parse never populates
`intent.evpn_type5_routes`; FortiGate codec never emits EVPN
because its product surface has no EVPN data plane (firewall,
not BGP-EVPN router).

## VRF / routing-instances

The `cisco_iosxe` codec doesn't walk `<network-instances>` —
neither for VLANs nor for VRFs.  `intent.routing_instances` is
empty after parse.  Even if populated, the FortiGate codec does
not parse `set vrf <id>` (per-interface integer VRF, FortiOS
7.x) nor VDOMs as canonical
`CanonicalRoutingInstance` records in v1 — the FortiGate
parse / render path treats VRF as out-of-scope.

FortiGate's VDOM (Virtual Domain) is structurally distinct from
Cisco-style named VRF + RD + RT: VDOMs carry independent firewall
policy tables, address objects, admin sessions, and routing
tables.  They are a heavier multi-tenancy primitive that requires
per-VDOM canonical-tree splitting (out of v1 pipeline scope).
The newer per-interface integer VRF (`set vrf 5`) is closer in
spirit to Cisco VRF-Lite but the FortiGate codec doesn't parse
or render it in v1.

## Disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `vxlan_vnis` | not_applicable | cisco_iosxe parser doesn't populate; matrix-declared unsupported on both sides |
| `evpn_type5_routes` | not_applicable | Same — both codecs decline |
| `routing_instances` | not_applicable | cisco_iosxe parser doesn't walk `<network-instances>`; FortiGate codec doesn't parse VRF in v1 |
| `interfaces[].vrf` | not_applicable | Same parser-side gap |

These are `not_applicable` rather than `unsupported` because the
source codec never populates the canonical fields — there is no
data on the cross-pair to drop.  When the cisco_iosxe parser
wires `<network-instances>`, the disposition flips to
`unsupported` (FortiGate render-side gap remains).
