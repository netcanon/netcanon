# DHCP server: Junos versus OPNsense

## Junos

Source: [Junos DHCP server topic-map](https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/topic-map/dhcp-server.html)
Source: [Junos DHCP local-server overview](https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/concept/dhcp-local-server-overview.html)
Retrieved: 2026-05-01

Junos uses a TWO-STAGE DHCP server model:

```
set system services dhcp-local-server group LAN_GROUP interface irb.100

set access address-assignment pool LAN_POOL family inet network 192.168.10.0/24
set access address-assignment pool LAN_POOL family inet range LAN_RANGE low 192.168.10.100
set access address-assignment pool LAN_POOL family inet range LAN_RANGE high 192.168.10.199
set access address-assignment pool LAN_POOL family inet dhcp-attributes router 192.168.10.1
set access address-assignment pool LAN_POOL family inet dhcp-attributes name-server 1.1.1.1
set access address-assignment pool LAN_POOL family inet dhcp-attributes maximum-lease-time 86400
set access address-assignment pool LAN_POOL family inet dhcp-attributes domain-name lan.example.net
```

Junos DHCP notes:

- `dhcp-local-server` declares which interfaces serve DHCP.
- `address-assignment pool` carries the network / range / gateway
  / DNS / lease parameters.
- The two-stage model is mandatory — there's no single-stanza form.
- Vendor options (option 43, 60, 66, 150) extend the
  `dhcp-attributes` hierarchy with codec-specific keywords.

## OPNsense

Source: [OPNsense ISC DHCPv4 manual](https://docs.opnsense.org/manual/isc.html)
Retrieved: 2026-04-30

OPNsense's DHCP server is INTERFACE-KEYED — pools are scoped to a
zone label, and the network/mask is INFERRED from the zone's
interface address:

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

- Pool key is the zone label (`<lan>`, `<opt1>`, ...) — there is NO
  named pool concept.
- Network + mask come from the zone's `<ipaddr>` + `<subnet>`; the
  pool record carries only the range / gateway / options.
- DNS list is a COMMA-SEPARATED string (not repeated elements).
- Lease time is a single integer in seconds (`<defaultleasetime>`).

## Cross-vendor mapping

Junos -> OPNsense:

- `dhcp_servers`: **lossy** — Junos's named pool collapses to OPNsense's
  zone-keyed pool.  Pool name drops on render (canonical
  `CanonicalDHCPPool.interface` carries the zone binding).  Network
  and mask round-trip via the zone's interface address.  Lease time
  scalar round-trips.  DNS list flattens from canonical
  `dns_servers: list[str]` to OPNsense comma-separated string.
  Vendor-option / DHCP-attributes-hierarchy fidelity is unsupported
  — canonical model carries only `network / start_ip / end_ip /
  gateway / dns_servers / lease_time / domain_name`.
- The juniper_junos codec does not currently advertise
  `/dhcp/pool` in its `supported` capability matrix; cross-pair
  parse path may be empty (no canonical pool entries derived).
  Mark `lossy` rather than `unsupported` because the structural
  mapping is sound — wire-up gap is the principal blocker.

Disposition: **lossy** — codec wire-up gap on Junos parse plus
two-stage / zone-keyed structural divergence; round-trip of basic
pool parameters survives if both sides wire up.
