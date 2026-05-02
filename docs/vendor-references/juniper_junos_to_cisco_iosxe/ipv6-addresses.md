# IPv6 addresses — link-local on render

Source: [Junos family inet6 statement reference](https://www.juniper.net/documentation/en_US/junos/topics/reference/configuration-statement/interfaces-edit-family-inet6.html)
Retrieved: 2026-05-01

Source: [openconfig-if-ip YANG schema docs (IPv4/IPv6 augment)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

Source: `netconfig.migration.codecs.cisco_iosxe.codec._render_canonical`
(in-tree code documenting the IPv6 emit path)
Retrieved: 2026-05-01

## What the Junos parser produces

The juniper_junos codec populates IPv6 addresses from
`set interfaces X unit 0 family inet6 address X/N`.  Junos infers
link-local from the prefix range natively; the codec preserves
the scope distinction by setting `scope="link-local"` on canonical
records whose address falls in `fe80::/10`, and `scope="global"`
otherwise.

## What the cisco_iosxe render emits

The `_render_canonical` walks `intent.interfaces[].ipv6_addresses`
and emits:

```xml
<subinterface>
  <index>0</index>
  <ipv6 xmlns="http://openconfig.net/yang/interfaces/ip">
    <addresses>
      <address>
        <ip>fe80::1</ip>
        <config>
          <ip>fe80::1</ip>
          <prefix-length>64</prefix-length>
        </config>
      </address>
    </addresses>
  </ipv6>
</subinterface>
```

There is no scope discriminator in the output.  OpenConfig's
`openconfig-if-ip` model carries IP and prefix-length leaves but
not an explicit `scope` field — implementations are expected to
infer link-local from the `fe80::/10` prefix range (RFC 4291).

## Asymmetry on round-trip

The Junos parser preserves the scope distinction on parse.  The
cisco_iosxe render drops it on emit.  A downstream OpenConfig
consumer must perform its own inference from the address bytes.
This is a structural property of OpenConfig (no explicit scope
leaf) rather than a wire-up gap on the render path.

## Disposition

`interfaces[].ipv6_addresses` is **lossy** on this direction with
reason "scope discriminator collapses on render (OpenConfig
schema has no explicit scope leaf; downstream consumer must infer
from prefix bytes)".

The forward direction (cisco_iosxe -> juniper_junos) lists this
field as `lossy` for a different reason: the source parser hard-
codes `scope="global"` on every address.  Two different lossy
mechanisms on the same field, one per direction.

## Repair path

To make scope round-trip cleanly:

1. **Schema-side.** Extend `CanonicalIPv6Address` with the existing
   `scope` field — already present.  The cisco_iosxe render could
   emit a vendor-augment leaf (e.g. `cisco-if-ip:scope`) on the
   address config.  This would require the downstream consumer to
   recognise the augment.
2. **Inference-side.** Document that downstream consumers MUST
   infer scope from prefix bytes per RFC 4291.  Cheap, doesn't
   require schema change, but pushes the cost onto every consumer.
3. **OpenConfig contribution.** Propose a scope leaf on
   `openconfig-if-ip` upstream.  Heaviest path; benefits the whole
   ecosystem.

Option 2 is the cheap path but accepts the lossy classification.
Options 1 and 3 close the gap; both are more work than the
disposition warrants for a Phase-0.5 stub codec.
