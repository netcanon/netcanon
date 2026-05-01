# DHCP server pools: Cisco IOS-XE versus Juniper Junos

How on-device DHCP-server pools are declared.

Sources:
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipaddr_dhcp/configuration/xe-17/dhcp-xe-17-book.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/topic-map/dhcp-server.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/concept/dhcp-local-server-overview.html (retrieved 2026-04-30)

Citation ids: `cisco-dhcp-cg`, `junos-dhcp-server`, `junos-dhcp-local-server`.

## Cisco IOS-XE form

```
ip dhcp pool LAN_USERS
 network 10.10.10.0 255.255.255.0
 default-router 10.10.10.1
 dns-server 10.0.0.53 10.0.0.54
 lease 7

ip dhcp excluded-address 10.10.10.1 10.10.10.10
```

Single-stanza per pool; lease is days/hours/minutes (default 1
day).  Excluded-address blocks live separately.

## Junos form

Two-stage model: `dhcp-local-server` (which interfaces serve the
protocol) plus `access address-assignment pool` (which addresses
get assigned):

```
set system services dhcp-local-server group LAN_GROUP interface ge-0/0/0.100

set access address-assignment pool LAN_USERS family inet network 10.10.10.0/24
set access address-assignment pool LAN_USERS family inet range LAN_USERS-range low 10.10.10.20 high 10.10.10.250
set access address-assignment pool LAN_USERS family inet dhcp-attributes router 10.10.10.1
set access address-assignment pool LAN_USERS family inet dhcp-attributes name-server 10.0.0.53
set access address-assignment pool LAN_USERS family inet dhcp-attributes name-server 10.0.0.54
set access address-assignment pool LAN_USERS family inet dhcp-attributes maximum-lease-time 604800
```

## Mapping notes

- **Canonical surface.** `CanonicalDHCPPool{interface, network,
  start_ip, end_ip, gateway, dns_servers, lease_time,
  domain_name}` flattens both vendor forms.  Round-trip is
  lossless on the basic fields.
- **Pool versus split model.** Cisco's single `ip dhcp pool`
  stanza maps to Junos's split `dhcp-local-server` /
  `address-assignment pool` pair on render; canonical model is
  pool-centric, so the codec render-path synthesises both
  Junos hierarchies.
- **Lease-time units.** Cisco's `lease <days> <hours> <minutes>`
  vs Junos's `maximum-lease-time <seconds>`.  Canonical
  `lease_time: int` is in seconds; codecs convert.
- **Excluded ranges.** Cisco's separate `ip dhcp excluded-address`
  stanza has no Junos equivalent — Junos achieves the same
  semantic by setting the `range` low/high to exclude the
  reserved block.  Canonical model carries `start_ip` /
  `end_ip` only; cross-vendor round-trip can lose the
  excluded-block discriminator if the operator used multiple
  ranges.
- **Option set richness.** Cisco's wide DHCP-options surface
  (option 43 / 60 / 66 / 150 / etc) is not modelled canonically.
  Operators relying on advanced options see a parse-and-ignore
  banner.

Disposition: **lossy** — basic pool round-trip works; advanced
options drift.
