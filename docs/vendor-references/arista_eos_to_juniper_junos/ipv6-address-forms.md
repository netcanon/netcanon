# IPv6 address forms

Per-interface IPv6 address declaration including link-local handling.

Sources:
- Arista: https://www.arista.com/en/um-eos/eos-interface-configuration (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/interfaces-fundamentals/topics/topic-map/protocol-family-interface-address-properties.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/en_US/junos/topics/reference/configuration-statement/interfaces-edit-family-inet6.html (retrieved 2026-05-01)

Citation ids: `arista-iface-cg`, `junos-iface-fundamentals`, `junos-family-inet6`.

## Arista EOS form

```
interface Ethernet1
   ipv6 address 2001:db8::1/64
   ipv6 address fe80::1/64 link-local
```

Link-local addresses are explicit via the `link-local` keyword;
omitting it makes the address global-scope.  Arista emits at most
one link-local per interface.

## Junos form

```
set interfaces ge-0/0/0 unit 0 family inet6 address 2001:db8::1/64
set interfaces ge-0/0/0 unit 0 family inet6 address fe80::1/64
```

Junos has no `link-local` keyword — the prefix itself
(`fe80::/10`) discriminates.  Junos auto-generates a link-local
EUI-64 address on every IPv6-enabled interface; explicit
declarations override the auto-generated value.

## Mapping notes

- Canonical `CanonicalIPv6Address.scope` ∈ {`global`, `link-local`}
  normalises the discriminator.  Arista's explicit `link-local`
  keyword and Junos's address-prefix-derived scope both round-trip
  through this discriminator.
- Junos auto-generates a link-local address even when no explicit
  fe80::/10 declaration exists.  The canonical parse currently does
  not synthesise an implicit link-local record from "interface has
  IPv6 enabled" — only explicit declarations populate the list.  An
  operator migrating Arista → Junos with explicit `fe80::1/64
  link-local` will see the address render correctly; one migrating
  Junos → Arista with NO explicit link-local will produce an Arista
  config that lacks the EUI-64 address Junos auto-generated.
- Address `family inet6` requires the `unit 0` (or other unit
  number) wrapper on Junos; Arista's flat `interface Ethernet1`
  form maps to Junos `ge-X/Y/Z` + `unit 0`.
