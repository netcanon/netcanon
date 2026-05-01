# VXLAN + EVPN — IOS-XE CLI versus OpenConfig NETCONF

## CLI form

Source: [Catalyst 9000 Series EVPN-VXLAN Configuration Guide](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-15/configuration_guide/vxlan/b_1715_bgp_evpn_vxlan_9300_cg.html)
(retrieved 2026-04-30).

```
interface nve1
 no shutdown
 source-interface Loopback0
 host-reachability protocol bgp
 member vni 10100 mcast-group 239.1.1.100
 member vni 10100 associate-vrf
!
vlan configuration 100
 member vni 10100
!
```

## OpenConfig NETCONF form

OpenConfig models VXLAN / EVPN through several augments to
`openconfig-network-instance`:

* `openconfig-evpn` for the EVPN BGP address-family + per-instance
  ESI / route-target plumbing.
* `openconfig-vxlan` (where supported) for the VTEP and VLAN-to-VNI
  mappings.

Cisco's IOS-XE OpenConfig support for the VXLAN augments is partial
on Catalyst 9300 / 9500 — the native `Cisco-IOS-XE-bgp` and
`Cisco-IOS-XE-vxlan` models cover the full surface.

## Cross-format mapping in this repository

Both codecs declare every VXLAN canonical path as `unsupported`:

* `cisco_iosxe_cli` codec capability matrix:
  - `/vxlan-vnis/vni` — "IOS-XE VXLAN mappings (`interface nve1 /
    member vni <N>`) parse-and-ignore in v1."
  - `/vxlan-vnis/source-interface`, `/vxlan-vnis/udp-port` — same
    scope, same wire-up gap.
  - `/routing-instances/instance` — VRF declarations parse-and-
    ignore (which means EVPN Type-5 derivation can't happen).
  - `/evpn-type5-routes/route` — listed under `lossy` rather than
    `unsupported` because the canonical model captures Type-5 intent
    via `CanonicalRoutingInstance.l3_vni`, not per-prefix records.

* `cisco_iosxe` (NETCONF) codec capability matrix:
  - `/vxlan-vnis/vni` — "VXLAN not modelled in this NETCONF/OpenConfig
    stub codec.  CLI sibling defers VXLAN wire-up until Catalyst
    demand arrives; NETCONF stays in lockstep."
  - `/vxlan-vnis/source-interface`, `/vxlan-vnis/udp-port` — same.

| Direction | Disposition |
|---|---|
| CLI -> NETCONF | unsupported — `intent.vxlan_vnis` and `intent.evpn_type5_routes` are empty after CLI parse (parse-and-ignore). |
| NETCONF -> CLI | not_applicable — NETCONF parse never populates these. |

The canonical schema for VXLAN exists (`CanonicalVxlan`,
`CanonicalEvpnType5Route`, `CanonicalRoutingInstance.l3_vni`) — the
gating constraint is purely codec wire-up.  When demand surfaces for
Catalyst-to-Arista or Catalyst-to-NX-OS migrations, both codecs
will land VXLAN parsing at the same time and this cross-pair will
flip to `good` for the L2VNI surface and `lossy` for Type-5 (until
route-map / policy-statement parsing also lands).
