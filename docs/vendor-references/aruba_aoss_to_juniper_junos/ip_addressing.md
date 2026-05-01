# IPv4 / IPv6 addressing: Aruba AOS-S versus Juniper Junos

How IP addresses are bound to interfaces and SVIs on each platform.

Sources:
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv6/2930F-3810-5400/index.htm (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation//us/en/software/junos/interfaces-fundamentals/topics/topic-map/protocol-family-interface-address-properties.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/en_US/junos/topics/reference/configuration-statement/interfaces-edit-family-inet6.html (retrieved 2026-05-01)

Citation ids: `aruba-ip-addressing`, `junos-iface-fundamentals`,
`junos-family-inet6`.

## Aruba AOS-S form

CIDR prefix-length notation for both v4 and v6.  SVI L3 absorbed
into the VLAN stanza:

```
vlan 100
   ip address 192.168.10.1/24
   ipv6 address 2001:db8::1/64
   ipv6 address fe80::1/64 link-local
   exit
```

Per-routed-port (3810 / 5400R via the `routing` directive — bare
numeric port becomes L3):

```
interface 25
   routing
   ip address 198.51.100.1/30
   ipv6 address 2001:db8:0:25::1/64
```

The codec parses the AOS-S form into
`CanonicalInterface.ipv4_addresses[0] = CanonicalIPv4Address(...)`
or `CanonicalVlan.ipv4_addresses[0] = ...` depending on whether the
address lives on a routed port or absorbed inside a VLAN stanza.

Optional `link-local` keyword flips
`CanonicalIPv6Address.scope = "link-local"`.

## Junos form

Junos uses the per-unit `family inet` / `family inet6` surface:

```
set interfaces ge-0/0/24 unit 0 family inet address 198.51.100.1/30
set interfaces ge-0/0/24 unit 0 family inet6 address 2001:db8:0:25::1/64
```

For an SVI the parent is `irb` and each VLAN gets its own unit:

```
set interfaces irb unit 100 family inet address 192.168.10.1/24
set interfaces irb unit 100 family inet6 address 2001:db8::1/64
set vlans USERS l3-interface irb.100
```

IPv6 link-local addresses do not require an explicit keyword on
Junos; auto-detection by prefix (`fe80::/10`).  The codec normalises
the discriminator on parse.

## Cross-vendor mapping

The canonical model normalises both sides to CIDR / prefix-length
form.  Disposition is `good` on the address itself; the structural
transformation is internal to each codec's render path.

Specifics:

* Aruba VLAN-absorbed SVI -> Junos `irb.<id>` unit.  Aruba's
  `vlan 100 / ip address X/N` lands on `CanonicalVlan.ipv4_addresses`;
  Junos render emits both `set interfaces irb unit 100 family inet
  address X/N` and `set vlans <name> l3-interface irb.100`.
* Routed-port `interface 25 / routing / ip address` lands on
  `CanonicalInterface.ipv4_addresses` and renders as `set interfaces
  <renamed> unit 0 family inet address X/N`.
* The `link-local` discriminator round-trips via
  `CanonicalIPv6Address.scope`.  Aruba's explicit keyword maps to
  Junos's prefix-based auto-detection.
* Aruba's `ipv6 address dhcp full` (DHCPv6 client) has no canonical
  equivalent — the parser drops the directive on parse.  Junos's
  `family inet6 dhcp` is also not modelled canonically.
* Aruba does not parse `secondary` addresses (none in the codec
  surface today); Junos accepts multiple `address` entries per unit
  natively.

Disposition: **good** for the primary v4 / v6 address with the
link-local discriminator preserved.
