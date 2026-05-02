# IPv6 address forms — Arista EOS source to OpenConfig NETCONF target

Source: [Arista EOS Interface Configuration (4.35.2F)](https://www.arista.com/en/um-eos/eos-interface-configuration)
Retrieved: 2026-05-01

Source: [openconfig-if-ip YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

## Arista EOS form

Arista EOS distinguishes link-local addresses explicitly via the
`link-local` keyword:

```
interface Ethernet1
   ipv6 address 2001:db8:0:1::1/64
   ipv6 address fe80::1 link-local
```

A bare `ipv6 address fe80::1/64` (without the `link-local` keyword)
is treated as a global address by EOS; the keyword is the
discriminator.  Multiple link-local addresses per interface are
rejected by EOS — at most one explicit link-local declaration.

EOS also auto-generates a link-local EUI-64 address on every
IPv6-enabled interface; the explicit declaration overrides the
auto-generated value.

## OpenConfig NETCONF target form

The `openconfig-if-ip` IPv6 augment models per-address records:

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
on the address record — link-local treatment is inferred from the
address prefix (`fe80::/10`).  Some draft augment modules add an
`address-type` enum, but they aren't universally deployed and the
cisco_iosxe codec doesn't emit them.

## What the cisco_iosxe codec does

The codec's `_iface_dict_to_canonical()` body hard-codes
`scope="global"` on every parsed IPv6 address it builds from the
NETCONF wire (see
`netconfig.migration.codecs.cisco_iosxe.codec._iface_dict_to_canonical`).

When this codec is the **render** target (this pair), the render
side emits the address with no scope hint regardless of what the
canonical record carries.  Concretely:

* Arista source declares `ipv6 address fe80::1 link-local`.
* Arista codec parses this with
  `CanonicalIPv6Address(ip="fe80::1", prefix_length=64, scope="link-local")`.
* cisco_iosxe codec `_render_canonical()` walks the record and emits
  a normal `<address><ip>fe80::1</ip><config><prefix-length>64</prefix-length></config></address>`
  with no link-local indicator.
* A downstream OpenConfig consumer cannot distinguish the address
  from an unintentionally-routable global address.

Operationally this typically isn't catastrophic — devices receiving
an OpenConfig NETCONF edit-config with an `fe80::/10` address apply
it as link-local based on the prefix — but the canonical-model
discriminator is dropped on the wire.

## Mapping notes

* Canonical `CanonicalIPv6Address.scope` ∈ {`global`, `link-local`}
  preserves the discriminator on the canonical layer but the
  cisco_iosxe render path doesn't carry it through to the wire.
* Multiple global IPv6 addresses round-trip cleanly (Arista source
  with two `ipv6 address X/N` lines emits two `<address>` records
  in the OpenConfig output).
* Single explicit Arista link-local declarations preserve the
  address bytes but lose the `link-local` flag on the OpenConfig
  output.
* Auto-generated EUI-64 link-local addresses are not parsed by
  the Arista codec (they don't appear in `running-config` text);
  this aspect is invisible to NetConfig regardless of target codec.

## Disposition

`interfaces[].ipv6_addresses`: **lossy** — the addresses round-trip
in shape and bytes; the link-local scope discriminator is dropped
on the OpenConfig wire format.
