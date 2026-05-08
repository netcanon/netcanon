# Interface canonical-core fields — Junos source to Cisco NETCONF target

Source: [Junos Protocol Family and Interface Address Properties](https://www.juniper.net/documentation//us/en/software/junos/interfaces-fundamentals/topics/topic-map/protocol-family-interface-address-properties.html)
Retrieved: 2026-05-01

Source: [Junos Understanding Interface Naming Conventions (QFX)](https://www.juniper.net/documentation/en_US/junos12.3/topics/concept/interfaces-naming-conventions-qfx-series.html)
Retrieved: 2026-05-01

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: `netcanon.migration.codecs.cisco_iosxe.codec._render_canonical`
(in-tree code documenting what the render emits)
Retrieved: 2026-05-01

## What the Junos parser populates

The juniper_junos codec walks `set interfaces ...` and populates
`CanonicalInterface` records with these fields:

| Canonical field | Populated? | Source set-form lines |
|---|---|---|
| `name` | yes | `set interfaces ge-0/0/0 ...` |
| `description` | yes | `set interfaces X description "..."` |
| `enabled` | yes | `set interfaces X disable` (default true) |
| `interface_type` | yes | inferred from name prefix (ge-/xe-/et-/lo/ae) |
| `mtu` | yes | `set interfaces X mtu N` |
| `ipv4_addresses` | yes | `set interfaces X unit 0 family inet address X/N` |
| `ipv6_addresses` | yes | `set interfaces X unit 0 family inet6 address X/N` |
| `switchport_mode` | yes | `family ethernet-switching interface-mode {access | trunk}` |
| `access_vlan` | yes | `family ethernet-switching vlan members <name>` (single) |
| `trunk_allowed_vlans` | yes | `family ethernet-switching vlan members [list]` |
| `trunk_native_vlan` | yes | `set interfaces X native-vlan-id N` |
| `voice_vlan` | NO | Junos has no first-class voice-VLAN |
| `lag_member_of` | yes | `set interfaces X gigether-options 802.3ad ae<N>` |
| `dhcp_client` | yes | `set interfaces X unit 0 family inet dhcp` |
| `vrf` | yes | `set routing-instances X interface ge-0/0/0.0` (GAP 6) |

## What the cisco_iosxe NETCONF render emits

The cisco_iosxe `_render_canonical` walks `intent.interfaces` and
emits `<interface>` records.  Only a subset of CanonicalInterface
fields make it to the output XML:

| Canonical field | Rendered? | Output XML element |
|---|---|---|
| `name` | yes | `<interface><name>` |
| `description` | yes (if non-empty) | `<config><description>` |
| `enabled` | yes | `<config><enabled>` (true/false) |
| `interface_type` | yes (if non-empty) | `<config><type>` |
| `mtu` | NO | render does NOT emit `<config><mtu>` |
| `ipv4_addresses` | yes | `<subinterface index=0><ipv4><addresses>` |
| `ipv6_addresses` | yes | `<subinterface index=0><ipv6><addresses>` |
| `switchport_mode` | NO | render doesn't walk `openconfig-vlan:switched-vlan` |
| `access_vlan` | NO | render doesn't walk |
| `trunk_allowed_vlans` | NO | render doesn't walk |
| `trunk_native_vlan` | NO | render doesn't walk |
| `voice_vlan` | NO | (Junos doesn't populate either) |
| `lag_member_of` | NO | render doesn't walk `openconfig-if-aggregate` |
| `dhcp_client` | NO | render doesn't walk OpenConfig DHCP-client augment |
| `vrf` | NO | render doesn't walk `<network-instances>` |

## Per-field disposition

| Field | Disposition | Reason |
|---|---|---|
| `interfaces[].name` | good | round-trips through rename mesh |
| `interfaces[].description` | good | free-text |
| `interfaces[].enabled` | good | YANG bool form |
| `interfaces[].interface_type` | lossy | inference asymmetry — Junos infers from name shape |
| `interfaces[].mtu` | unsupported | render-side gap (parsed but not emitted) |
| `interfaces[].ipv4_addresses` | good | OpenConfig prefix-length form |
| `interfaces[].ipv6_addresses` | lossy | scope discriminator collapses on render (no scope leaf in OpenConfig output) |
| `interfaces[].switchport_mode` | unsupported | render-side gap |
| `interfaces[].access_vlan` | unsupported | render-side gap |
| `interfaces[].trunk_allowed_vlans` | unsupported | render-side gap |
| `interfaces[].trunk_native_vlan` | unsupported | render-side gap |
| `interfaces[].voice_vlan` | not_applicable | Junos source has no voice-VLAN |
| `interfaces[].lag_member_of` | unsupported | render-side gap on aggregate augment |
| `interfaces[].dhcp_client` | unsupported | render-side gap on DHCP-client augment |
| `interfaces[].vrf` | unsupported | render-side gap on `<network-instances>` |

## MTU asymmetry

The Junos parser populates `CanonicalInterface.mtu` from
`set interfaces X mtu N`.  The cisco_iosxe render's
`_render_canonical` does not emit `<config><mtu>` even when
present on the canonical record.  Disposition: `unsupported`
(render-side gap) with reason citing the matrix's `lossy`
classification of `/interfaces/interface/config/mtu` ("YANG-only
round-trip loses the link/IP-MTU distinction") — but the
operational truth is that the render doesn't emit at all, not
that it loses the distinction.

## IPv6 scope collapse

The Junos parser populates IPv6 with explicit scope when the
address is in the link-local range (`fe80::/10`).  The cisco_iosxe
render emits `<ipv6><addresses><address>` with `<ip>` and
`<prefix-length>` — but no scope discriminator.  A downstream
OpenConfig consumer must infer scope from the prefix bytes.
Disposition: `lossy` with reason "scope discriminator collapses
on render".
