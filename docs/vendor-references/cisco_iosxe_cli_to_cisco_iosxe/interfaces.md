# Interfaces — IOS-XE CLI versus OpenConfig NETCONF

## CLI form (`cisco_iosxe_cli`)

Source: [Cisco IOS XE 17 Interface and Hardware Component Configuration
Guide](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/int-hw/b-int-hw.html)
(retrieved 2026-04-30).

```
interface GigabitEthernet1/0/1
 description Uplink to spine-1
 mtu 9216
 ip address 10.0.0.1 255.255.255.252
 ipv6 address 2001:db8::1/64
 no shutdown
!
interface Loopback0
 description Router-ID
 ip address 10.255.0.1 255.255.255.255
!
```

Notes:

* Interface name encodes hardware speed (`FastEthernet`,
  `GigabitEthernet`, `TenGigabitEthernet`, `TwentyFiveGigE`,
  `HundredGigE`).
* IPv4 mask is dotted-decimal; the CLI parser converts to / from
  prefix-length canonically.
* `no shutdown` is the default; the absence of `shutdown` is
  semantically `enabled=true`.

## OpenConfig NETCONF form (`cisco_iosxe`)

Source: [openconfig-interfaces YANG model schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
(retrieved 2026-04-30).

```xml
<interfaces xmlns="http://openconfig.net/yang/interfaces">
  <interface>
    <name>GigabitEthernet1/0/1</name>
    <config>
      <name>GigabitEthernet1/0/1</name>
      <description>Uplink to spine-1</description>
      <enabled>true</enabled>
      <type xmlns:ianaift="urn:ietf:params:xml:ns:yang:iana-if-type">ianaift:ethernetCsmacd</type>
      <mtu>9216</mtu>
    </config>
    <subinterfaces>
      <subinterface>
        <index>0</index>
        <ipv4 xmlns="http://openconfig.net/yang/interfaces/ip">
          <addresses><address>
            <ip>10.0.0.1</ip>
            <config><ip>10.0.0.1</ip><prefix-length>30</prefix-length></config>
          </address></addresses>
        </ipv4>
        <ipv6 xmlns="http://openconfig.net/yang/interfaces/ip">
          <addresses><address>
            <ip>2001:db8::1</ip>
            <config><ip>2001:db8::1</ip><prefix-length>64</prefix-length></config>
          </address></addresses>
        </ipv6>
      </subinterface>
    </subinterfaces>
  </interface>
</interfaces>
```

Notes:

* Same vendor-native interface name on the wire — the rename mesh is
  a no-op for this same-vendor pair.
* `type` leaf is an IANA interface-type ident (`ethernetCsmacd`,
  `softwareLoopback`, `ieee8023adLag`).  CLI source codec infers
  this from the name prefix.
* Subinterfaces always present (index=0 = main interface).  IPv4
  and IPv6 are siblings under the same subinterface.
* `enabled` is YANG boolean (`"true"` / `"false"` lower-case strict).

## Cross-format mapping

| Canonical field | CLI -> NETCONF | NETCONF -> CLI |
|---|---|---|
| `interfaces[].name` | good (verbatim) | good (verbatim) |
| `interfaces[].description` | good | good |
| `interfaces[].enabled` | good (no shutdown -> `enabled:true`) | good |
| `interfaces[].interface_type` | lossy (CLI infers from name prefix; not all IANA types detectable) | good (NETCONF carries the IANA ident verbatim) |
| `interfaces[].mtu` | lossy (IOS native distinguishes `mtu` (link) vs `ip mtu`; OpenConfig collapses to a single `mtu` leaf) | lossy (same) |
| `interfaces[].ipv4_addresses` | good | good |
| `interfaces[].ipv6_addresses` | good (CLI parser supports IPv6 since GAP-EVPN-3) | good |
| `interfaces[].switchport_mode` | unsupported (this repo's NETCONF codec does not wire `openconfig-vlan` switched-vlan) | not_applicable (NETCONF source never populates) |
| `interfaces[].access_vlan` | unsupported (same) | not_applicable |
| `interfaces[].trunk_allowed_vlans` | unsupported (same) | not_applicable |
| `interfaces[].trunk_native_vlan` | unsupported (same) | not_applicable |
| `interfaces[].voice_vlan` | unsupported (same) | not_applicable |
| `interfaces[].lag_member_of` | unsupported (NETCONF codec does not model `Port-channel` membership via `openconfig-if-aggregate`) | not_applicable |
| `interfaces[].dhcp_client` | unsupported (no OpenConfig leaf wired) | not_applicable |
| `interfaces[].vrf` | unsupported (NETCONF codec does not parse `network-instance` VRF membership) | not_applicable |

The key drift is **switchport state** — the OpenConfig codec doesn't
wire the `switched-vlan` augment, so any CLI source with switchport
configuration loses the L2 mode + VLAN membership on render.  This is
documented in the codec's capability matrix as part of the broader
"VXLAN / VRF / LAG not yet wired" Phase-0.5 stub framing.

## MTU note (lossy in both directions)

IOS-XE native CLI distinguishes:

* `mtu N` — Layer-2 (link / system) MTU
* `ip mtu N` — Layer-3 IPv4 MTU
* `ipv6 mtu N` — Layer-3 IPv6 MTU
* `mpls mtu N` — Layer-2.5 MPLS MTU

OpenConfig `openconfig-interfaces` models a single `mtu` leaf at the
interface level; per-protocol layer MTU lives on the IP-augment but
real Cisco devices typically only honour one.  Cross-format round-
trip collapses any non-link-MTU value back to `mtu N`, which the
operator must review.  The CLI codec lists this as `LossyPath` in
its capability matrix:

> `"YANG-only round-trip loses the distinction"` — `cisco_iosxe`
> `CapabilityMatrix.lossy[/interfaces/interface/config/mtu]`.
