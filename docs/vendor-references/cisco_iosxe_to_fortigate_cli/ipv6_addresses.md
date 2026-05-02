# IPv6 addresses — `cisco_iosxe` source to `fortigate_cli` target

Source: [openconfig-if-ip YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

Source: [Fortinet FortiGate Administration Guide — Interface settings (IPv6 addressing)](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings)
Retrieved: 2026-05-01

## OpenConfig IPv6 augment

The `openconfig-if-ip` module models IPv6 addresses on a subinterface
identical to IPv4 — a list of `<address>` records keyed by `<ip>`,
each carrying `<config><ip>` + `<config><prefix-length>` (0-128).
OpenConfig also carries an explicit `<config><type>` leaf for
distinguishing **global** / **link-local** scope, but the
`netconfig.migration.codecs.cisco_iosxe` codec does NOT read this
leaf — `_parse_ipv6()` hard-codes `scope="global"` on every
`CanonicalIPv6Address` it produces:

```python
iface.ipv6_addresses.append(CanonicalIPv6Address(
    ip=ip,
    prefix_length=int(prefix),
    scope="global",
))
```

This is a documented codec limitation (parser comment in
`_parse_ipv6`: "Link-local scope is not yet inferred from the wire
here").  Real-world OpenConfig replies from a Catalyst 9K that
include `fe80::/10` link-local addresses will have those addresses
mis-categorised as `scope="global"` on parse.

## FortiGate IPv6 emission

The FortiGate render emits IPv6 addresses via `set ip6-address
<addr>/<prefix>` under `config system interface` -> `config ipv6`.
The FortiOS form has no explicit scope keyword on `set ip6-address`
— FortiOS infers link-local from the address prefix (anything
matching `fe80::/10`) and treats global / link-local distinctly
internally.  Cross-vendor migration from a global-tagged canonical
record to FortiOS works correctly; from a link-local source, the
canonical record (mis-tagged as global on cisco_iosxe parse) emits
correctly because FortiOS infers from the prefix anyway.

## Disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `interfaces[].ipv6_addresses[].ip` | good | Round-trips via OpenConfig `<ip>` -> FortiOS `set ip6-address` |
| `interfaces[].ipv6_addresses[].prefix_length` | good | Round-trips via OpenConfig `<prefix-length>` -> FortiOS `/prefix` suffix |
| `interfaces[].ipv6_addresses[].scope` | lossy | Hard-coded `global` on parse (canonical-model gap, not introduced by this pair) |

The lossy classification is upstream of this codec pair — both
sides agree on the canonical form but the cisco_iosxe parser
discards the scope discriminator before reaching the canonical
layer.  Promotes to `good` when the `cisco_iosxe` codec wires
link-local inference (or reads the explicit OpenConfig
`<type>` leaf).
