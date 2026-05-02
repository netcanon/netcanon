# Interfaces (naming, IP, MTU): Juniper Junos versus MikroTik RouterOS

How physical and logical interfaces are declared on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/en_US/junos12.3/topics/concept/interfaces-naming-conventions-qfx-series.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation//us/en/software/junos/interfaces-fundamentals/topics/topic-map/protocol-family-interface-address-properties.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/en_US/junos/topics/reference/configuration-statement/interfaces-edit-family-inet6.html (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/41746442/Ethernet (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing (retrieved 2026-05-01)

Citation ids: `junos-iface-naming`, `junos-iface-fundamentals`,
`junos-family-inet6`, `mikrotik-iface-naming`, `mikrotik-ip-address`.

## Junos form

```
set interfaces ge-0/0/0 description "Uplink to ISP"
set interfaces ge-0/0/0 mtu 9000
set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/31
set interfaces ge-0/0/0 unit 0 family inet6 address 2001:db8::1/64
set interfaces lo0 unit 0 family inet address 172.16.0.1/32
set interfaces lo0 unit 0 family inet6 address fe80::1/64
set interfaces irb unit 100 family inet address 172.16.100.1/24
set interfaces ge-0/0/9 disable
```

Junos uses media-prefix interface names (`ge-` 1G, `xe-` 10G, `et-`
40/100G, `mge-` 25G, `ae` aggregated-Ethernet, `irb` integrated
routing+bridging, `lo0` loopback, `em0`/`fxp0` management).  Slot /
PIC / port indices come after the prefix (`ge-0/0/0`).  Interface
properties hang off the parent (`mtu`, `description`); IP / family
config hangs off a unit (`unit 0 family inet address ...`).  Multi-
unit interfaces (`ge-0/0/1.100`, `irb.100`) carry per-unit VLAN tag
and family config.

## RouterOS form

```
/interface ethernet
set [ find default-name=ether1 ] comment="WAN uplink to ISP" disabled=no mtu=1500
set [ find default-name=ether2 ] comment="LAN trunk - bridge member" disabled=no mtu=1500

/interface vlan
add interface=bridge1 name=vlan100 vlan-id=100
add interface=bridge1 name=vlan200 vlan-id=200

/ip address
add address=198.51.100.2/30 interface=ether1
add address=10.100.0.1/24 interface=vlan100

/ipv6 address
add address=2001:db8:0:1::2/64 interface=ether1
add address=fe80::1/64 interface=ether1 advertise=no
```

RouterOS uses flat factory-default names (`ether1` / `ether2` / ...,
`sfp1`, `sfp-sfpplus1`, `wlan1`).  The `set [ find default-name=X ]`
form keeps configuration stable across renames.  Speed is not
encoded in the prefix.  IPv4 / IPv6 addresses are top-level
`/ip address` and `/ipv6 address` records (NOT per-interface
sub-stanzas).  RouterOS has no first-class loopback construct —
operators emulate via empty bridges or via addresses on a virtual
interface.  IPv6 link-local addresses are auto-detected from prefix
(`fe80::/10`); explicit declaration is uncommon.

## Cross-vendor mapping

* Names: speed-encoded Junos prefix vs flat RouterOS name.  Port-
  rename mesh maps `ge-0/0/0` -> `ether1` / `etherN` based on slot
  ordering; 10G+ ports may need operator override (`xe-` / `et-`
  -> `sfp-sfpplus<N>`).
* `description` -> `comment=`: free-form, both quote whitespace.
* `enabled` -> `disabled=`: inverted boolean; Junos `set ... disable`
  vs `delete ... disable` -> RouterOS `disabled=yes` vs `disabled=no`.
* `mtu` -> `mtu=`: integer parameter on both.
* IPv4 / IPv6 addresses with prefix-length: round-trip cleanly via
  CIDR.  Junos's per-unit addressing materialises as separate
  `/ip address` records per unit; the codec's `vlan100` interface
  name discriminates between parent (`ge-0/0/0`) and sub-unit
  (`ge-0/0/0.100` / `irb.100` -> `vlan100`).
* IPv6 `scope=link-local` discriminator preserved.
* Loopback (`lo0`): no first-class RouterOS equivalent; cross-pair
  drops to lossy (RouterOS render emulates via an empty bridge with
  a /32 address, or attaches the address to an existing physical
  interface as a secondary).
* Management interfaces (`em0` / `fxp0`): no RouterOS equivalent
  (RouterOS has no out-of-band / management VRF distinction); fall
  back to a regular `/interface ethernet` record.

Disposition: **good** for description / enabled / MTU / IPv4 / IPv6
addresses with documented per-name caveats; **lossy** for the
interface name (rename-mesh mapping required) and for loopback /
management semantics.
