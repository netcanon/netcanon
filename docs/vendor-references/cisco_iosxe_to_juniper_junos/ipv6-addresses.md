# IPv6 addresses — link-local scope hard-code

Source: [openconfig-if-ip YANG schema docs (IPv4/IPv6 augment)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

Source: [Junos family inet6 statement reference](https://www.juniper.net/documentation/en_US/junos/topics/reference/configuration-statement/interfaces-edit-family-inet6.html)
Retrieved: 2026-05-01

Source: `netconfig.migration.codecs.cisco_iosxe.codec._iface_dict_to_canonical`
(in-tree code documenting the scope hard-code)
Retrieved: 2026-05-01

## What OpenConfig models

The `openconfig-if-ip` augment carries IPv6 addresses under
`/interfaces/interface/subinterfaces/subinterface/ipv6/addresses/address`
with `ip` and `prefix-length` leaves.  OpenConfig does not carry an
explicit `scope` discriminator — implementations are expected to
infer link-local from the `fe80::/10` prefix range (RFC 4291).

## What the cisco_iosxe parser does

The `_iface_dict_to_canonical()` helper hard-codes
`scope="global"` on every IPv6 address it parses, regardless of
whether the address is in the link-local range.  When the source
XML carries a `fe80::1` link-local address (legitimate per
OpenConfig and per RFC 4291), the parser miscategorises it as
global.

## What the Junos target render does

The Junos render respects whatever `scope` is on the canonical
record.  It maps `scope="link-local"` to the prefix-based
auto-detection that Junos performs natively (`fe80::/10` addresses
are inferred as link-local without a special keyword on the wire).
It maps `scope="global"` to the standard `set interfaces X unit 0
family inet6 address X/N` form.

Because the source parser hard-codes global, a `fe80::1`
link-local address in the source XML reaches the Junos render
classified as global, and the Junos render emits it under
`family inet6 address` as a global address — which Junos would
accept syntactically but would semantically misuse (the address
gets installed in the global routing table rather than as a
link-local route).

## Disposition

`interfaces[].ipv6_addresses` is **lossy** on this direction with
reason "scope discriminator hard-coded global by source parser".

The forward (cisco_iosxe_cli__juniper_junos) pair lists this field
as `good` because the CLI parser walks the explicit `link-local`
keyword from `ipv6 address fe80::1 link-local`.  The NETCONF
sibling lacks the equivalent inference and silently demotes
link-local addresses to global.

## Repair path

Two ways to close the gap:

1. **Parser-side fix.** Extend `_iface_dict_to_canonical()` to
   inspect the address bytes and set `scope="link-local"` when the
   address falls in `fe80::/10`.  Cheap; doesn't require schema
   change.
2. **Schema-side fix.** Add an OpenConfig augment for explicit
   scope on the address leaf (Cisco vendor models do carry this on
   some Catalyst trains).  Heavier; requires coordination with
   upstream OpenConfig.

Option 1 is the cheap path and would flip this disposition to
`good`.  Option 2 is the structurally clean path and would also
fix the CLI codec's GAP-CIDR-IPV6 (link-local with explicit
keyword on source CLI).
