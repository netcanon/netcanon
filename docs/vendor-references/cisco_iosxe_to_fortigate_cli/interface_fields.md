# Interface canonical-core fields — `cisco_iosxe` to `fortigate_cli`

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [openconfig-if-ip YANG schema docs (IPv4 / IPv6 augment)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

Source: [Fortinet FortiGate Administration Guide — Interface settings](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings)
Retrieved: 2026-05-01

## What gets parsed on the cisco_iosxe side

The `cisco_iosxe` codec's `_iface_dict_to_canonical()` populates each
`CanonicalInterface` from the OpenConfig `<interface>` element with:

* `name` from `<name>` text
* `description` from `<config><description>` text
* `enabled` from `<config><enabled>` (strict YANG boolean — `"true"` /
  `"false"` only)
* `interface_type` from `<config><type>` IANA ifType ident (e.g.
  `iana-if-type:ethernetCsmacd`)
* `ipv4_addresses[]` from `<subinterfaces><subinterface><ipv4>
  <addresses><address>` with `<config><prefix-length>` (validated
  range 0-32)
* `ipv6_addresses[]` from same shape under `<ipv6>` (range 0-128;
  hard-coded `scope="global"`)

NOT populated from parse:

* `mtu` — even though OpenConfig models `<config><mtu>`, the codec's
  `_parse_config()` reads `mtu` into the raw dict but
  `_iface_dict_to_canonical()` does not project it onto the
  `CanonicalInterface.mtu` field.
* `switchport_mode` / `access_vlan` / `trunk_allowed_vlans` /
  `trunk_native_vlan` / `voice_vlan` — the
  `openconfig-vlan:switched-vlan` augment is not walked.
* `lag_member_of` — the `openconfig-if-aggregate:aggregate-id` leaf
  is not read.
* `dhcp_client` — the OpenConfig DHCP-client augment is not walked.
* `vrf` — `<network-instances>` is entirely out of parse scope.

## What gets rendered on the fortigate_cli side

The FortiGate render walks `intent.interfaces` and emits per-interface:

* `edit "<name>"` — interface identity (after rename mesh maps Cisco
  `GigabitEthernet0/0/0` to FortiOS `port1` form)
* `set alias "<description>"` — capped at 25 characters (FortiOS limit)
* `set status up` / `set status down` from `enabled`
* `set ip <addr> <mask>` — primary IPv4 address only; secondary
  addresses are dropped on render today (FortiGate codec render path
  emits the first address and a banner for any tail)
* `set ip6-address <addr>/<prefix>` from `ipv6_addresses[0]`
* No emission for `interface_type` — FortiOS infers from name shape
  / `set type vlan` / `set type aggregate` rather than carrying an
  IANA ident
* No emission for `set mode dhcp` from `dhcp_client` (render-side gap)
* `set member ...` for LAG aggregates (when `intent.lags` carries
  records — but cisco_iosxe parse never populates `intent.lags`)

## Per-field disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `interfaces[].name` | good | Verbatim text via OpenConfig `<name>` -> FortiOS `edit` ID; rename mesh applies |
| `interfaces[].description` | good | OpenConfig `<description>` -> FortiOS alias; truncates at 25 chars |
| `interfaces[].enabled` | good | YANG boolean -> `set status up/down` |
| `interfaces[].interface_type` | lossy | Cisco-source IANA ident not emitted by FortiGate (inferred) |
| `interfaces[].mtu` | not_applicable | cisco_iosxe parser doesn't project mtu onto canonical |
| `interfaces[].ipv4_addresses` | lossy | Primary good; secondaries drop on FortiGate render |
| `interfaces[].ipv6_addresses` | lossy | Link-local scope discriminator hard-coded global on parse |
| `interfaces[].switchport_mode` | not_applicable | NETCONF parser doesn't walk switched-vlan augment |
| `interfaces[].access_vlan` | not_applicable | Same parse-side gap |
| `interfaces[].trunk_allowed_vlans` | not_applicable | Same parse-side gap |
| `interfaces[].trunk_native_vlan` | not_applicable | Same parse-side gap |
| `interfaces[].voice_vlan` | not_applicable | Same parse-side gap (plus FortiGate has no voice-VLAN concept) |
| `interfaces[].lag_member_of` | not_applicable | NETCONF parser doesn't walk aggregate augment |
| `interfaces[].dhcp_client` | not_applicable | NETCONF parser doesn't walk DHCP-client augment |
| `interfaces[].vrf` | not_applicable | NETCONF parser doesn't walk `<network-instances>` |
