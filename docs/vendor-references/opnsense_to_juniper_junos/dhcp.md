# DHCP server: OPNsense versus Junos

## OPNsense

Source: [OPNsense ISC DHCPv4 manual](https://docs.opnsense.org/manual/isc.html)
Retrieved: 2026-04-30

```xml
<dhcpd>
  <lan>
    <enable/>
    <range>
      <from>192.168.10.100</from>
      <to>192.168.10.199</to>
    </range>
    <gateway>192.168.10.1</gateway>
    <dnsserver>1.1.1.1,9.9.9.9</dnsserver>
    <domain>lan.example.net</domain>
    <defaultleasetime>7200</defaultleasetime>
    <maxleasetime>86400</maxleasetime>
  </lan>
</dhcpd>
```

OPNsense DHCP notes:

- Pool key is the zone label (`<lan>`, `<opt1>`, ...) — there is
  NO named pool concept.
- Network + mask come from the zone's `<ipaddr>` + `<subnet>`; the
  pool record carries only the range / gateway / options.
- DNS list is a COMMA-SEPARATED string.
- Lease time scalars (`<defaultleasetime>` / `<maxleasetime>`) in
  seconds.

## Junos

Source: [Junos DHCP server topic-map](https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/topic-map/dhcp-server.html)
Source: [Junos DHCP local-server overview](https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/concept/dhcp-local-server-overview.html)
Retrieved: 2026-05-01

Junos uses a TWO-STAGE DHCP server model:

```
set system services dhcp-local-server group LAN_GROUP interface irb.100

set access address-assignment pool LAN_POOL family inet network 192.168.10.0/24
set access address-assignment pool LAN_POOL family inet range R1 low 192.168.10.100
set access address-assignment pool LAN_POOL family inet range R1 high 192.168.10.199
set access address-assignment pool LAN_POOL family inet dhcp-attributes router 192.168.10.1
set access address-assignment pool LAN_POOL family inet dhcp-attributes name-server 1.1.1.1
set access address-assignment pool LAN_POOL family inet dhcp-attributes maximum-lease-time 86400
```

Junos DHCP notes:

- `dhcp-local-server` declares which interfaces serve DHCP.
- `address-assignment pool` carries the network / range / gateway /
  DNS / lease parameters.
- Two-stage model is mandatory.

## Cross-vendor mapping

OPNsense -> Junos:

- `dhcp_servers`: **lossy** — OPNsense's zone-keyed pool
  (`<dhcpd><lan>`) maps to Junos's named pool.  The canonical
  `CanonicalDHCPPool.interface` carries the zone binding; pool name
  must be synthesised on Junos render (typically derived from the
  zone label, e.g. `lan_pool`).  Network + mask must be reconstructed
  on Junos render from the pool's start_ip / end_ip plus a /24
  default (or looked up from the canonical interface's IP).  DNS
  list flattens from OPNsense's comma-separated string to Junos's
  per-line `name-server`.
- The juniper_junos codec does not currently advertise `/dhcp/pool`
  in its capability matrix; cross-pair render is partial pending
  wire-up.  The opnsense codec DOES populate
  `CanonicalDHCPPool` from `<dhcpd>` so source side is healthy.

Disposition: **lossy** — Junos render wire-up gap plus structural
two-stage versus zone-keyed divergence.
