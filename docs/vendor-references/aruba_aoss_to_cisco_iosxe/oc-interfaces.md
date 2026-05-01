# OpenConfig `openconfig-interfaces` — what the cisco_iosxe target actually emits

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [openconfig-if-ip YANG schema docs (IPv4 / IPv6 augment)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

Source: [Cisco-IOS-XE-native.yang vendor model (YangModels GitHub)](https://github.com/YangModels/yang/blob/main/vendor/cisco/xe/1761/Cisco-IOS-XE-native.yang)
Retrieved: 2026-05-01

## OpenConfig interfaces — the canonical subset

The `openconfig-interfaces` model defines a list of `interface`
entries each carrying:

* `name` (key) — opaque vendor-native identifier
* `config/description` — operator free text
* `config/enabled` — YANG boolean
* `config/type` — IANA interface-type ident (`iana-if-type:ethernetCsmacd`,
  `iana-if-type:softwareLoopback`, `iana-if-type:l2vlan`,
  `iana-if-type:ieee8023adLag`, `iana-if-type:tunnel`, ...)
* `config/mtu` — single MTU leaf (link-layer)
* `subinterfaces/subinterface` — list keyed by `index`, each with
  IPv4 / IPv6 augment trees:
  * `ipv4/addresses/address/{ip, config/ip, config/prefix-length}`
  * `ipv6/addresses/address/{ip, config/ip, config/prefix-length}`

This is the entire surface area emitted by
`netconfig.migration.codecs.cisco_iosxe.codec.CiscoIOSXECodec._render_canonical()`.
The codec walks `intent.interfaces` and emits exactly the fields
above.  No other intent fields drive XML emission on the render path.

## What round-trips well from AOS-S source

The aruba_aoss parser populates the same canonical subset for every
interface-shaped object.  When the cisco_iosxe render is applied, the
following AOS-S source content survives byte-equivalently (modulo
the port-rename mesh translating bare-numeric port names to
GigabitEthernet form):

| Canonical field | Survives? | Notes |
|---|---|---|
| `interfaces[].name` | yes | After port-rename mesh translation |
| `interfaces[].description` | yes | Free-text round-trip |
| `interfaces[].enabled` | yes | YANG boolean -> CLI-equivalent |
| `interfaces[].interface_type` | partial | Inferred on AOS-S parse from name shape; emitted as IANA ident |
| `interfaces[].ipv4_addresses` | yes | Full list, including secondary addresses |
| `interfaces[].ipv6_addresses` | yes | scope=global only (link-local not yet wired through cisco_iosxe render) |
| `interfaces[].mtu` | n/a | aruba_aoss codec does not parse MTU; field is empty on parse |

## What gets dropped before reaching the render

These canonical interface-attached fields exist on the AOS-S source's
`CanonicalInterface` records but are NOT emitted by the cisco_iosxe
NETCONF render:

* `switchport_mode` / `access_vlan` / `trunk_allowed_vlans` /
  `trunk_native_vlan` / `voice_vlan` — the
  `openconfig-vlan:switched-vlan` augment is not wired on render.
* `lag_member_of` — the `openconfig-if-aggregate:aggregate-id` leaf
  is not emitted.
* `dhcp_client` — the OpenConfig DHCP-client augment is not wired.
* `vrf` — `openconfig-network-instance` is entirely out of the
  target render scope.

These fields exist on `CanonicalInterface` and are populated by the
aruba_aoss parser when source content drives them, but the
`cisco_iosxe._render_canonical()` body simply does not walk them.
This shows up as `unsupported` on the per-field expectation.

## Disposition

For the interface canonical-core fields listed in the "survives"
table above: **good** (with the `interface_type` and `ipv6` caveats
noted).  For the interface-attached fields in the "dropped" list:
**unsupported** (codec render gap).
