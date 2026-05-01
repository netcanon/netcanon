# IPv4 / IPv6 addressing: Juniper Junos versus Cisco IOS-XE

Sources:
- Juniper: https://www.juniper.net/documentation//us/en/software/junos/interfaces-fundamentals/topics/topic-map/protocol-family-interface-address-properties.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/en_US/junos/topics/reference/configuration-statement/interfaces-edit-family-inet6.html (retrieved 2026-04-30)
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipaddr/configuration/xe-3se/3850/iadi-xe-3se-3850-book.html (retrieved 2026-04-30)
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipv6/configuration/xe-17/ipv6-xe-17-book.html (retrieved 2026-04-30)

Citation ids: `junos-iface-fundamentals`, `junos-family-inet6`, `cisco-ip-cg`, `cisco-ipv6-cg`.

## Junos form

```
set interfaces ge-0/0/0 unit 0 family inet address 10.1.0.1/24
set interfaces ge-0/0/0 unit 0 family inet address 10.1.0.2/24
set interfaces ge-0/0/0 unit 0 family inet6 address 2001:db8:1::1/64
set interfaces ge-0/0/0 unit 0 family inet6 address fe80::1/64
set interfaces ge-0/0/0 unit 0 family inet dhcp
```

Junos uses CIDR for all addresses (inet and inet6).  Multiple
addresses per family stack as additional `set` lines.  Link-local
is auto-detected by the `fe80::/10` prefix — there's no explicit
keyword.

## Cisco IOS-XE form

```
interface GigabitEthernet1/0/1
 ip address 10.1.0.1 255.255.255.0
 ip address 10.1.0.2 255.255.255.0 secondary
 ipv6 address 2001:db8:1::1/64
 ipv6 address fe80::1 link-local
 ipv6 enable
 ip address dhcp
```

Cisco uses dotted-decimal mask for IPv4; IPv6 uses CIDR.  A
`secondary` keyword distinguishes secondary IPs.  IPv6 link-local
requires the explicit `link-local` keyword.

## Mapping notes

- **Mask form.** Both vendors normalise to canonical
  `CanonicalIPv4Address{ip, prefix_length}`.  Round-trip is
  lossless on the integer prefix-length.
- **Multiple addresses per family.** Junos's "stack additional
  set lines" maps to Cisco's first-address + N-secondary
  structure on render; canonical model is a list, no
  primary/secondary discriminator preserved.
- **Link-local auto-detect.** Junos infers from the `fe80::/10`
  prefix; Cisco requires the `link-local` keyword.  Canonical
  `CanonicalIPv6Address.scope` carries the discriminator;
  round-trip preserves it but the on-wire form differs.
- **DHCP client.** Both forms map to
  `CanonicalInterface.dhcp_client = True`.
- **Per-unit address scoping.** Junos addresses live under
  `unit <N>` (per logical sub-interface); Cisco addresses live
  on the bare interface or on `<iface>.<N>` sub-interfaces.
  Canonical model carries per-interface (or per-canonical-
  interface-unit) addresses; the unit hierarchy is flattened.

Disposition: **good** on the address list / prefix-length / scope.
