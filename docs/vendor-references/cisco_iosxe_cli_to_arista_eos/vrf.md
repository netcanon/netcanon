# VRF / routing-instance: Cisco IOS-XE versus Arista EOS

## Cisco IOS-XE

Source: [Cisco IOS XE Catalyst SD-WAN Qualified Command Reference — VRF Commands](https://www.cisco.com/c/en/us/td/docs/routers/sdwan/command/iosxe/qualified-cli-command-reference-guide/m-vrf-commands.html)
Source: [IP Routing Configuration Guide, Cisco IOS XE Cupertino 17.9.x — Configuring VRF-lite (Catalyst 9400)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-9/configuration_guide/rtng/b_179_rtng_9400_cg/configuring_vrf_lite.html)
Source: [MPLS Layer 3 VPNs Configuration Guide, Cisco IOS XE Release 3S — MPLS VPN VRF CLI](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/mp_l3_vpns/configuration/xe-3s/mp-l3-vpns-xe-3s-book/mp-vpn-ipv4-ipv6.html)

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

Both codecs ship the schema but neither wires it up in v1:

- Cisco IOS-XE codec capability matrix lists
  `/routing-instances/instance` as **unsupported**:
  "VRF declarations (`vrf definition <name>` with `rd` +
  `address-family ipv4` + `route-target import/export`) and per-
  interface `vrf forwarding <name>` parse-and-ignore in v1."

- Arista EOS codec capability matrix lists
  `/routing-instances/instance` as **supported** (GAP 6 demoted),
  but actual parse / render is in scope only for the `vrf instance`
  shell — RD and RT extraction from `router bgp / vrf` is partial.

Cross-pair disposition: VRF data largely silently drops on Cisco-side
parse, so a round-trip Cisco -> Arista emits no `vrf instance` blocks.
This is a known asymmetry; flagged as a deferred audit-pass item.

Disposition: **unsupported** (Cisco parse-and-ignore; pending GAP 6 wire-up).
