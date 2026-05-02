# VXLAN, EVPN, and VRF — `fortigate_cli` source to `cisco_iosxe` target

Source: [openconfig-evpn YANG model (GitHub)](https://github.com/openconfig/public/tree/master/release/models/evpn)
Retrieved: 2026-05-01

Source: [OpenConfig network-instance use cases](https://openconfig.net/docs/models/network_instance/)
Retrieved: 2026-05-01

Source: [Catalyst 9000 Series EVPN-VXLAN Configuration Guide (IOS-XE 17.15)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-15/configuration_guide/vxlan/b_1715_bgp_evpn_vxlan_9300_cg.html)
Retrieved: 2026-05-01

Source: [Fortinet FortiGate Administration Guide — VRF / VDOM](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/)
Retrieved: 2026-05-01

## VXLAN

The `fortigate_cli` codec's CapabilityMatrix lists `/vxlan-vnis/vni`,
`/vxlan-vnis/source-interface`, and `/vxlan-vnis/udp-port` under
`unsupported` with rationale:

> "VXLAN not modelled — FortiGate is a firewall codec."

The `cisco_iosxe` codec also lists `/vxlan-vnis/vni` and the
sibling source-interface / udp-port paths under `unsupported`
with rationale:

> "VXLAN not modelled in this NETCONF/OpenConfig stub codec.  CLI
> sibling defers VXLAN wire-up until Catalyst demand arrives;
> NETCONF stays in lockstep."

Both codecs decline.  `intent.vxlan_vnis` is empty after FortiGate
parse and would not render on cisco_iosxe regardless.

## EVPN Type-5 routes

Same situation.  FortiGate as a firewall has no EVPN data plane
(it's not a BGP-EVPN router); FortiGate parser never populates
`intent.evpn_type5_routes`.  cisco_iosxe codec doesn't emit EVPN
because v1 NETCONF stub doesn't wire `<network-instances>` /
`<protocols>` walking.

## VRF / routing-instances

The FortiGate codec parses `set vrf <id>` per-interface in the
codec internals but does NOT surface it onto
`CanonicalRoutingInstance` records — the canonical field is empty
on parse.  FortiGate's per-interface integer VRF (FortiOS 7.x) is
closer in spirit to Cisco VRF-Lite but the codec defers parsing
in v1.

cisco_iosxe codec's CapabilityMatrix doesn't enumerate
`/routing-instances/instance` explicitly, but the render path
doesn't walk `<network-instances>` at all — VRF declarations would
not survive.

FortiGate's heavier multi-tenancy primitive — VDOMs (Virtual
Domains) — carries independent firewall policy tables, address
objects, admin sessions, and routing tables.  VDOMs require
per-VDOM canonical-tree splitting (out of v1 pipeline scope) and
have no Cisco-OpenConfig analogue (Cisco's MDT / multi-instance
VRF semantics are different).

## Disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `vxlan_vnis` | not_applicable | FortiGate codec never populates; matrix-declared unsupported on both sides |
| `evpn_type5_routes` | not_applicable | Same — both codecs decline |
| `routing_instances` | not_applicable | FortiGate codec doesn't surface `set vrf <id>` onto canonical in v1 |
| `interfaces[].vrf` | not_applicable | Same — codec doesn't populate canonical field |

These are `not_applicable` because the FortiGate source codec
never populates the canonical fields in v1, regardless of
whether the FortiOS source had `set vrf` directives on individual
interfaces.  When the codec wires VRF parsing, the disposition
flips to `unsupported` (cisco_iosxe render-side gap remains).
