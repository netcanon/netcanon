# VRF / network-instance — IOS-XE CLI versus OpenConfig NETCONF

## CLI form

Source: [IP Routing Configuration Guide, Cisco IOS XE 17.x —
Multi-VRF Support (VRF-Lite)](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/ip-routing/b-ip-routing/m_mp-multi-vrf-vrf-lite.html)
(retrieved 2026-04-30).

```
vrf definition TENANT-A
 description Customer A
 rd 65001:100
 route-target export 65001:100
 route-target import 65001:100
 address-family ipv4
 exit-address-family
 address-family ipv6
 exit-address-family
!
interface GigabitEthernet1/0/3
 vrf forwarding TENANT-A
 ip address 10.20.0.1 255.255.255.0
!
ip route vrf TENANT-A 10.20.0.0 255.255.0.0 10.20.0.254
```

The IOS-XE native YANG (`Cisco-IOS-XE-vrf`) models this one-for-one;
the OpenConfig translation overlay maps it to `openconfig-network-
instance` with `instance-type=L3VRF`.

## OpenConfig NETCONF form

Source: [openconfig-network-instance use cases](https://openconfig.net/docs/models/network_instance/)
(retrieved 2026-04-30).

VRFs are non-default `<network-instance>` records:

```xml
<network-instances xmlns="http://openconfig.net/yang/network-instance">
  <network-instance>
    <name>TENANT-A</name>
    <config>
      <name>TENANT-A</name>
      <type>L3VRF</type>
      <description>Customer A</description>
      <route-distinguisher>65001:100</route-distinguisher>
    </config>
    <interfaces>
      <interface>
        <id>GigabitEthernet1/0/3.0</id>
        <config>
          <id>GigabitEthernet1/0/3.0</id>
          <interface>GigabitEthernet1/0/3</interface>
          <subinterface>0</subinterface>
        </config>
      </interface>
    </interfaces>
  </network-instance>
</network-instances>
```

Route-targets live under `inter-instance-policies/apply-policy` plus
the `bgp` protocol stanza inside the network-instance — a richer
scoping than the IOS-XE native grammar.

## Cross-format mapping in this repository

The CLI codec's capability matrix declares
`/routing-instances/instance` as **`unsupported`** with rationale:

> "VRF declarations (`vrf definition <name>` with `rd` +
> `address-family ipv4` + `route-target import/export`) and per-
> interface `vrf forwarding <name>` parse-and-ignore in v1.
> CanonicalRoutingInstance + CanonicalInterface.vrf schema exists;
> IOS-XE wire-up deferred."

The OpenConfig NETCONF codec doesn't model network-instances either
(its parse/render only walks `<interfaces>`).  Both codecs effectively
parse-and-ignore the entire VRF concept today.

| Direction | Disposition |
|---|---|
| CLI -> NETCONF | unsupported — both codecs leave `intent.routing_instances` empty; `interfaces[].vrf` doesn't survive. |
| NETCONF -> CLI | not_applicable — NETCONF parser never populates routing_instances. |

When the CLI codec wires VRF parsing (under the
`CanonicalRoutingInstance` + `CanonicalInterface.vrf` schema that
already exists), the same-vendor cross-pair will remain `lossy` until
the NETCONF codec also wires `openconfig-network-instance` rendering.
This is the most valuable wire-up to land for this pair — Catalyst
9300 / 9500 customer environments use VRF-Lite extensively.
