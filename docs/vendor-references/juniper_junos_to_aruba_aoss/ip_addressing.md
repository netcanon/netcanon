# IPv4 / IPv6 addressing: Juniper Junos versus Aruba AOS-S

How IP addresses are bound to interfaces and SVIs on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation//us/en/software/junos/interfaces-fundamentals/topics/topic-map/protocol-family-interface-address-properties.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/en_US/junos/topics/reference/configuration-statement/interfaces-edit-family-inet6.html (retrieved 2026-05-01)
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv6/2930F-3810-5400/index.htm (retrieved 2026-05-01)

Citation ids: `junos-iface-fundamentals`, `junos-family-inet6`,
`aruba-ip-addressing`.

## Junos form

```
set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/31
set interfaces ge-0/0/0 unit 0 family inet6 address 2001:db8::1/64
set interfaces lo0 unit 0 family inet6 address fe80::1/64
set interfaces irb unit 100 family inet address 192.168.10.1/24
```

Junos uses the per-unit `family inet` / `family inet6` surface.
IPv6 link-local addresses do not require an explicit keyword;
auto-detection by prefix (`fe80::/10`).  Multiple addresses per
unit are accepted natively (`set address X/N` repeated).

## Aruba AOS-S form

CIDR prefix-length notation for both v4 and v6.  SVI L3 absorbed
into the VLAN stanza:

```
vlan 100
   ip address 192.168.10.1/24
   ipv6 address 2001:db8::1/64
   ipv6 address fe80::1/64 link-local
   exit

interface 25
   routing
   ip address 198.51.100.1/30
```

Per-routed-port (3810 / 5400R via the `routing` directive).

## Cross-vendor mapping

The canonical model normalises both sides to CIDR / prefix-length
form.

Specifics:

* Junos's per-unit `family inet address X/N` lands on
  `CanonicalInterface.ipv4_addresses`; Aruba render emits
  `ip address X/N` directly inside the renamed interface stanza
  (with `routing` keyword to enable L3 on the port).
* Junos's `irb` sub-interface family addresses transpose to the
  `CanonicalVlan.ipv4_addresses` list via the `set vlans NAME
  l3-interface irb.<id>` binding; Aruba render emits the address
  inline inside the VLAN stanza.
* IPv6 link-local: Junos's prefix-detected scope -> Aruba's explicit
  `link-local` keyword.  `CanonicalIPv6Address.scope = "link-local"`
  preserves the discriminator.
* Junos's multiple-address-per-unit (e.g. dual `set address` lines)
  flattens to a list of `CanonicalIPv4Address` records; Aruba
  emits each as a separate `ip address` line inside the same
  interface stanza.
* Junos-only address-family attributes (`primary`, `preferred`,
  `master-only`) drop on canonical (not modelled).

Disposition: **good** for the address itself with the link-local
discriminator preserved.
