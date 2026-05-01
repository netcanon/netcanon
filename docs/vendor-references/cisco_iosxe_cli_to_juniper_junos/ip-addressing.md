# IPv4 / IPv6 addressing: Cisco IOS-XE versus Juniper Junos

How interface IPv4 and IPv6 addresses are declared.

Sources:
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipaddr/configuration/xe-3se/3850/iadi-xe-3se-3850-book.html (retrieved 2026-04-30)
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipv6/configuration/xe-17/ipv6-xe-17-book.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation//us/en/software/junos/interfaces-fundamentals/topics/topic-map/protocol-family-interface-address-properties.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/en_US/junos/topics/reference/configuration-statement/interfaces-edit-family-inet6.html (retrieved 2026-04-30)

Citation ids: `cisco-ip-cg`, `cisco-ipv6-cg`, `junos-iface-fundamentals`, `junos-family-inet6`.

## Cisco IOS-XE form

```
interface GigabitEthernet1/0/1
 ip address 10.1.0.1 255.255.255.0
 ip address 10.1.0.2 255.255.255.0 secondary
 ipv6 address 2001:db8:1::1/64
 ipv6 address fe80::1 link-local
 ipv6 enable
```

Cisco's IPv4 syntax uses dotted-decimal mask (`A.B.C.D MASK`); the
`secondary` keyword adds additional IPs.  IPv6 uses CIDR form
(`/<prefix>`) and an explicit `link-local` keyword for fe80::/10
addresses.

DHCP client form:

```
interface GigabitEthernet1/0/1
 ip address dhcp
```

## Junos form

```
set interfaces ge-0/0/0 unit 0 family inet address 10.1.0.1/24
set interfaces ge-0/0/0 unit 0 family inet address 10.1.0.2/24
set interfaces ge-0/0/0 unit 0 family inet6 address 2001:db8:1::1/64
set interfaces ge-0/0/0 unit 0 family inet6 address fe80::1/64
```

Junos uses CIDR for both inet and inet6.  Multiple addresses on the
same family stack as additional `set` lines.  Junos auto-detects
link-local addresses by prefix (`fe80::/10`) — there's no explicit
keyword.

DHCP client form:

```
set interfaces ge-0/0/0 unit 0 family inet dhcp
```

## Mapping notes

- **Mask form.** Cisco's dotted-decimal mask parses into the same
  canonical `CanonicalIPv4Address{ip, prefix_length}` shape as
  Junos's CIDR; the codec parsers normalise.  Round-trip is
  lossless on the integer prefix-length.
- **Secondary IPs.** Cisco's `secondary` keyword maps to additional
  `CanonicalIPv4Address` entries on the same interface; Junos
  emits each as a separate `set ... address` line.  Order is not
  semantically preserved (canonical model is a list, but no
  vendor-side primary/secondary discriminator).
- **IPv6 link-local.** The canonical `CanonicalIPv6Address.scope`
  field discriminates `"global"` vs `"link-local"`; Cisco emits
  `link-local` as a keyword while Junos infers from the `fe80::/10`
  prefix.  Round-trip preserves the scope but the on-wire form
  differs.
- **DHCP client.** Cisco's `ip address dhcp` and Junos's `family
  inet dhcp` map to `CanonicalInterface.dhcp_client = True`.
  Round-trip is lossless.
- **IPv6 enable without address.** Cisco's bare `ipv6 enable`
  (which auto-derives a link-local) has no direct Junos equivalent;
  Junos auto-enables IPv6 the moment a `family inet6` clause exists.
  No canonical primitive for "enable without explicit address" — the
  codec parsers ignore the bare `ipv6 enable` directive.

Disposition: **good** on the address list / prefix-length / scope.
The `ipv6 enable`-without-address Cisco quirk is parse-and-ignore,
flagged in the codec capability matrices.
