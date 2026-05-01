# VRF / routing-instance: Arista EOS versus Cisco IOS-XE

## Arista EOS

Source: [EOS 4.36.0F — Static Inter-VRF Route](https://www.arista.com/en/um-eos/eos-static-inter-vrf-route)
Source: [Arista EOS Central — Virtual Routing and Forwarding (VRF) Fundamentals](https://eos.arista.com/virtual-routing-and-forwarding-vrf-fundamentals/)
Retrieved: 2026-04-30

Arista uses `vrf instance <name>` (modern; the older `vrf definition`
form is deprecated since EOS 4.20):

```
vrf instance TENANT_A
 rd 65001:100
 description "Tenant A"
!
ip routing vrf TENANT_A
```

Route-targets live under the BGP address-family per-VRF, NOT under the
`vrf instance` block (a structural difference from Cisco):

```
router bgp 65001
 vrf TENANT_A
  rd 65001:100
  route-target import evpn 65001:100
  route-target export evpn 65001:100
```

Per-interface VRF binding (different keyword from Cisco):

```
interface Ethernet1
 vrf TENANT_A
 ip address 10.1.0.1/24
```

## Cisco IOS-XE

Source: [Cisco IOS XE Catalyst SD-WAN Qualified Command Reference — VRF Commands](https://www.cisco.com/c/en/us/td/docs/routers/sdwan/command/iosxe/qualified-cli-command-reference-guide/m-vrf-commands.html)
Source: [IP Routing Configuration Guide, Cisco IOS XE Cupertino 17.9.x — Configuring VRF-lite (Catalyst 9400)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-9/configuration_guide/rtng/b_179_rtng_9400_cg/configuring_vrf_lite.html)
Source: [MPLS Layer 3 VPNs Configuration Guide, Cisco IOS XE Release 3S — MPLS VPN VRF CLI](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/mp_l3_vpns/configuration/xe-3s/mp-l3-vpns-xe-3s-book/mp-vpn-ipv4-ipv6.html)
Retrieved: 2026-04-30

Cisco uses `vrf definition <name>` (the modern multi-AF form;
deprecates the older `ip vrf <name>` syntax):

```
vrf definition TENANT_A
 rd 65001:100
 address-family ipv4
  route-target export 65001:100
  route-target import 65001:100
 exit-address-family
 address-family ipv6
  route-target export 65001:100
  route-target import 65001:100
 exit-address-family
```

Per-interface VRF binding:

```
interface GigabitEthernet1/0/1
 vrf forwarding TENANT_A
 ip address 10.1.0.1 255.255.255.0
```

## Cross-vendor mapping

The canonical model is `CanonicalRoutingInstance` plus per-interface
`CanonicalInterface.vrf`.  Schema documented in
`netconfig/migration/canonical/intent.py`:

```
class CanonicalRoutingInstance(BaseModel):
    name: str
    instance_type: str = "vrf"
    route_distinguisher: str = ""
    rt_imports: list[str] = Field(default_factory=list)
    rt_exports: list[str] = Field(default_factory=list)
    description: str = ""
    l3_vni: int | None = None
```

This direction is the **easier** asymmetry of the pair: the Arista
codec parses `vrf instance` blocks AND walks `router bgp / vrf <name>`
sub-stanzas to extract RD + RT communities (see
`netconfig/migration/codecs/arista_eos/parse.py` `_parse_router_bgp_vrf_routing_instances`
function).  The Cisco IOS-XE codec render path emits `vrf definition`
blocks with the canonical RD + RT data via `address-family ipv4 /
route-target import|export` — see
`netconfig/migration/codecs/cisco_iosxe_cli/render.py` `_render_vrfs`
section.

Per-interface `vrf` field renders as Cisco's `vrf forwarding <name>`
sub-line on each interface stanza.

Note the structural asymmetry on the Cisco PARSE side: Cisco IOS-XE
codec capability matrix lists `/routing-instances/instance` as
**unsupported** ("VRF declarations and per-interface vrf forwarding
parse-and-ignore in v1").  This means a round-trip Cisco→Arista→Cisco
would lose VRF data on the second Cisco parse, but the
Arista→Cisco direction (this file) is asymmetrically better because
the Cisco RENDER path is wired even though the PARSE path is not.

Limitation: Arista's `route-target import evpn 65001:100` form (with
the `evpn ` prefix denoting the L2VPN-EVPN address-family) gets
parsed as a plain RT after stripping the keyword.  Cisco IOS-XE
re-emits as a generic `route-target import` under the IPv4 AF; the
EVPN-specific AF context is lost.  This is fine for plain L3VPN use
but loses fidelity for EVPN deployments.

Disposition: **good** for the standard L3 VRF surface (name, RD, RTs,
description, per-interface membership); **lossy** for EVPN-specific
RT semantics (`route-target import evpn` collapses to plain RT).
