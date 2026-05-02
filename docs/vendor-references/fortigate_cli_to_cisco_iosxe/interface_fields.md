# Interface canonical-core fields — `fortigate_cli` to `cisco_iosxe`

Source: [Fortinet FortiGate Administration Guide — Interface settings](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings)
Retrieved: 2026-05-01

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [openconfig-if-ip YANG schema docs (IPv4 / IPv6 augment)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

## What gets parsed on the fortigate_cli side

The FortiGate codec's `_apply_system_interface()` populates each
`CanonicalInterface` from a `config system interface / edit "<name>"`
block with:

* `name` from the edit identifier (e.g. `"port1"`, `"agg1"`,
  `"port1.100"`)
* `description` from `set alias "..."` (FortiOS caps at 25 chars
  natively)
* `enabled` from `set status up` / `set status down` (default up)
* `interface_type` inferred from `set type vlan` / `set type
  aggregate` / name shape (no IANA ifType natively in FortiOS — the
  codec maps to `iana-if-type:l2vlan`, `iana-if-type:ieee8023adLag`,
  `iana-if-type:ethernetCsmacd`, `iana-if-type:softwareLoopback`)
* `ipv4_addresses[]` from `set ip <addr> <mask>` (single address
  on FortiGate; codec produces a one-entry list)
* `ipv6_addresses[]` from `set ip6-address <addr>/<prefix>` (single
  address; defaults `scope="global"`)
* `access_vlan` for `set type vlan` interfaces (vlanid)
* `lag_member_of` set for member ports of an aggregate (back-reference)
* `dhcp_client` from `set mode dhcp`
* `vrf` from `set vrf <id>` — FortiGate codec parses but does NOT
  surface this onto canonical in v1 (deferred)

## What gets rendered on the cisco_iosxe side

The cisco_iosxe `_render_canonical()` emits:

* `<interface><name>` from `iface.name`
* `<config><name>` (duplicate, per OpenConfig convention)
* `<config><description>` if non-empty
* `<config><enabled>` always (true / false)
* `<config><type>` if `iface.interface_type` non-empty (echoed
  verbatim as IANA ident)
* `<subinterfaces><subinterface><index>0`
* `<ipv4><addresses><address>` per `iface.ipv4_addresses[]` with
  `<config><ip>` + `<config><prefix-length>`
* `<ipv6><addresses><address>` per `iface.ipv6_addresses[]` with
  same shape (no scope discriminator on the wire)

Not emitted:

* `<config><mtu>` — even though OpenConfig models it, the renderer
  walks `iface.mtu` only when set, AND the FortiGate parser doesn't
  populate `iface.mtu` in v1.
* `openconfig-vlan:switched-vlan` augment — switchport_mode /
  access_vlan / trunk_allowed_vlans / trunk_native_vlan / voice_vlan
  are not emitted as XML on cisco_iosxe render.
* `openconfig-if-aggregate:aggregate-id` leaf — `lag_member_of` is
  not emitted on cisco_iosxe render.
* DHCP-client augment — `dhcp_client` is not emitted on cisco_iosxe
  render.
* `<network-instances>` membership — `vrf` field is not emitted on
  cisco_iosxe render.

## Per-field disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `interfaces[].name` | good | FortiOS edit ID -> OpenConfig `<name>` text after rename mesh |
| `interfaces[].description` | good | FortiOS alias -> OpenConfig `<description>`; truncation already applied on parse |
| `interfaces[].enabled` | good | `set status up/down` -> YANG boolean |
| `interfaces[].interface_type` | lossy | FortiGate-inferred IANA ident emitted as authoritative — downstream OpenConfig consumers may treat the inference as fact |
| `interfaces[].mtu` | not_applicable | FortiGate parser doesn't populate; nothing to drop |
| `interfaces[].ipv4_addresses` | good | FortiOS `set ip` -> OpenConfig `<ipv4>` round-trip |
| `interfaces[].ipv6_addresses` | lossy | Link-local scope discriminator dropped on cisco_iosxe render (no scope leaf emission) |
| `interfaces[].switchport_mode` | unsupported | cisco_iosxe render doesn't emit `switched-vlan` augment |
| `interfaces[].access_vlan` | unsupported | Same render-side gap |
| `interfaces[].trunk_allowed_vlans` | unsupported | Same render-side gap (FortiGate child-interface model collapses on canonical anyway) |
| `interfaces[].trunk_native_vlan` | unsupported | Same render-side gap |
| `interfaces[].voice_vlan` | not_applicable | FortiGate has no voice-VLAN concept; canonical empty on parse |
| `interfaces[].lag_member_of` | unsupported | cisco_iosxe render doesn't emit `aggregate-id` leaf |
| `interfaces[].dhcp_client` | unsupported | cisco_iosxe render doesn't emit DHCP-client augment |
| `interfaces[].vrf` | not_applicable | FortiGate codec doesn't surface `set vrf <id>` onto canonical in v1 |
