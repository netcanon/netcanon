# Interfaces (naming, IP, MTU): MikroTik RouterOS versus Juniper Junos

How physical and logical interfaces are declared on each platform.

Sources:
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/41746442/Ethernet (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/en_US/junos12.3/topics/concept/interfaces-naming-conventions-qfx-series.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation//us/en/software/junos/interfaces-fundamentals/topics/topic-map/protocol-family-interface-address-properties.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/en_US/junos/topics/reference/configuration-statement/interfaces-edit-family-inet6.html (retrieved 2026-05-01)

Citation ids: `mikrotik-iface-naming`, `mikrotik-ip-address`,
`junos-iface-naming`, `junos-iface-fundamentals`,
`junos-family-inet6`.

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
form keeps configuration stable across renames.  Speed is not encoded
in the prefix; SFP+ ports use `sfp-sfpplus1` etc.  IPv4 / IPv6
addresses are top-level `/ip address` and `/ipv6 address` records
(NOT per-interface sub-stanzas).  RouterOS has no first-class
loopback construct — operators emulate via empty bridges or attach
addresses to other interfaces as secondaries.

## Junos form

```
set interfaces ge-0/0/0 description "Uplink to ISP"
set interfaces ge-0/0/0 mtu 9000
set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/31
set interfaces ge-0/0/0 unit 0 family inet6 address 2001:db8::1/64
set interfaces lo0 unit 0 family inet address 172.16.0.1/32
set interfaces lo0 unit 0 family inet6 address fe80::1/64
set interfaces irb unit 100 family inet address 172.16.100.1/24
```

Junos uses media-prefix interface names (`ge-` 1G, `xe-` 10G, `et-`
40/100G, `mge-` 25G, `ae` aggregated-Ethernet, `irb` integrated
routing+bridging, `lo0` loopback, `em0`/`fxp0` management).  Slot /
PIC / port indices come after the prefix.  Interface properties hang
off the parent (`mtu`, `description`); IP / family config hangs off
a unit (`unit 0 family inet address ...`).  Multi-unit interfaces
(`ge-0/0/1.100`, `irb.100`) carry per-unit VLAN tag and family config.

## Cross-vendor mapping

* Names: RouterOS flat `etherN` -> Junos speed-encoded `ge-0/0/X`
  via the rename mesh.  Default speed hint defaults to `ge-` (1G);
  `sfp-sfpplus<N>` -> `xe-` (10G); SFP28 / QSFP -> `mge-` / `et-`.
  10G+ port detection requires operator override.
* `comment=` -> `description`: free-form, both quote whitespace.
* `disabled=` -> `enabled` (inverted).  RouterOS `disabled=yes` ->
  Junos `set interfaces X disable`.  RouterOS `disabled=no` ->
  Junos `delete interfaces X disable`.
* `mtu=` -> `mtu`: integer parameter on both.
* `/ip address` records -> Junos per-unit `family inet address`.  The
  codec maps RouterOS `vlan100` interface name to Junos sub-interface
  via the `irb.100` synthesis (when the RouterOS vlan-id matches a
  canonical VLAN with an SVI).
* `/ipv6 address` -> Junos `family inet6 address`.  IPv6 link-local
  discriminator (`scope=link-local`) preserved.
* RouterOS-only: bridge interfaces (`bridge1`) have no Junos
  equivalent; on Junos, the equivalent role is the `irb` parent
  with per-VLAN units.  RouterOS's address-on-bridge model -> Junos's
  per-VLAN `irb.<N>` model is a structural transformation.
* RouterOS does NOT model loopback as a first-class interface;
  Junos's `lo0.0` has no canonical RouterOS source typically.
  Inverse direction (Junos -> RouterOS) drops `lo0` to a bridge or
  to a secondary on a physical interface.

Disposition: **good** for description / enabled / MTU / IPv4 / IPv6
addresses with documented per-name caveats; **lossy** for the
interface name (rename mesh) and for the bridge-vs-irb structural
difference.
