# DHCP server pools: Juniper Junos versus Cisco IOS-XE

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/topic-map/dhcp-server.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/concept/dhcp-local-server-overview.html (retrieved 2026-04-30)
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipaddr_dhcp/configuration/xe-17/dhcp-xe-17-book.html (retrieved 2026-04-30)

Citation ids: `junos-dhcp-server`, `junos-dhcp-local-server`, `cisco-dhcp-cg`.

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

## Cisco IOS-XE form

```
ip dhcp pool LAN_USERS
 network 10.10.10.0 255.255.255.0
 default-router 10.10.10.1
 dns-server 10.0.0.53 10.0.0.54
 lease 7

ip dhcp excluded-address 10.10.10.1 10.10.10.10
```

## Mapping notes

- **Canonical surface.** `CanonicalDHCPPool{interface, network,
  start_ip, end_ip, gateway, dns_servers, lease_time,
  domain_name}` flattens both vendor forms.
- **Split versus single-stanza.** Junos's split
  `dhcp-local-server` + `address-assignment pool` pair flattens
  on parse to a single `CanonicalDHCPPool`; Cisco's single
  `ip dhcp pool` stanza maps directly.  Cross-vendor render
  re-synthesises the appropriate vendor structure.
- **Lease-time units.** Junos's `maximum-lease-time <seconds>` vs
  Cisco's `lease <days> <hours> <minutes>`.  Canonical
  `lease_time: int` is in seconds; codecs convert.
- **Excluded ranges.** Cisco's separate `ip dhcp excluded-address`
  has no Junos analogue (Junos uses `range low/high` to bracket);
  on Junos -> Cisco render, the excluded-block is reconstructed
  by inverting the range against the network — losing this
  information when multiple ranges existed in the source.
- **Option set richness.** Cisco's wide DHCP-options surface
  (option 43 / 60 / 66 / 150 / etc) is not modelled canonically.
  Operators relying on advanced options see a parse-and-ignore
  banner.

Disposition: **lossy** — basic pool round-trip works; advanced
options drift.
