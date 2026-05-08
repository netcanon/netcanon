# IPv6 address forms — OpenConfig NETCONF source to Arista EOS target

Source: [openconfig-if-ip YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

Source: [Arista EOS Interface Configuration (4.35.2F)](https://www.arista.com/en/um-eos/eos-interface-configuration)
Retrieved: 2026-05-01

## Source wire format

OpenConfig models per-address records under the `openconfig-if-ip`
IPv6 augment:

```xml
<ipv6 xmlns="http://openconfig.net/yang/interfaces/ip">
  <addresses>
    <address>
      <ip>2001:db8::1</ip>
      <config>
        <ip>2001:db8::1</ip>
        <prefix-length>64</prefix-length>
      </config>
    </address>
  </addresses>
</ipv6>
```

The base `openconfig-if-ip` module has no `link-local` discriminator
— link-local treatment is inferred from the address prefix
(`fe80::/10`).  Some draft augment modules add an `address-type`
enum with values `GLOBAL_UNICAST`, `LINK_LOCAL_UNICAST`,
`UNIQUE_LOCAL_UNICAST`, etc., but they are not universally deployed
and the cisco_iosxe parser does not read them.

## What the cisco_iosxe parser does

The parser walks `<ipv6><addresses><address>` and builds
`CanonicalIPv6Address(ip=..., prefix_length=...)` records.  The
`_iface_dict_to_canonical()` body hard-codes `scope="global"` on
every record — it does not infer link-local from the prefix and
does not read any draft `address-type` augment.

```python
iface.ipv6_addresses.append(CanonicalIPv6Address(
    ip=ip,
    prefix_length=int(prefix),
    scope="global",  # hard-coded
))
```

A `fe80::/10` address in the source XML reaches the canonical tree
with `scope="global"` regardless of its actual prefix.

## Arista EOS target form

Arista EOS distinguishes link-local explicitly via the
`link-local` keyword:

```
interface Ethernet1
   ipv6 address 2001:db8::1/64
   ipv6 address fe80::1 link-local
```

A bare `ipv6 address fe80::1/64` (without the `link-local` keyword)
is REJECTED by EOS on commit — EOS requires the keyword for
`fe80::/10` addresses.

## What the Arista render does

The arista_eos codec's render walks `intent.interfaces[].ipv6_addresses`
and emits `ipv6 address X/N` (CIDR form), with the `link-local`
keyword appended only when `scope == "link-local"`.

Because the cisco_iosxe parser hard-codes `scope="global"`, the
Arista render never appends `link-local` regardless of source
content.  For a `fe80::/10` address in the source XML:

* canonical record: `CanonicalIPv6Address(ip="fe80::1", prefix_length=64, scope="global")`
* Arista output: `ipv6 address fe80::1/64`
* Arista device commit: REJECTED (`% IPv6 link-local addresses must use the link-local keyword`)

Operators see a configuration-apply failure when pushing the
rendered Arista config to the target device.

## Mitigation

If the operator-facing configuration genuinely declares only global
IPv6 addresses (no `fe80::/10` records), the round-trip succeeds
without operator intervention.  Most production NETCONF datastores
expose only explicit operator-declared addresses; auto-generated
EUI-64 link-local addresses don't surface in OpenConfig output.
The risk is real but narrow — operators that explicitly declared
link-local addresses on the Cisco source see commit failures on
the Arista target.

Long-term fix: wire the cisco_iosxe parser's link-local inference
(check if the IP starts with `fe80:` and set scope="link-local").
This is a small change but hasn't been prioritised — see
`netcanon.migration.codecs.cisco_iosxe.codec._iface_dict_to_canonical`
for the relevant code.

## Disposition

`interfaces[].ipv6_addresses`: **lossy** — global addresses
round-trip cleanly; link-local addresses break commit on the
Arista target because the source codec drops the scope discriminator
upstream of the canonical layer.
