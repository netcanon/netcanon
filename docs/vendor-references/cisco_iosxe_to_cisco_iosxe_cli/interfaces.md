# Interfaces — OpenConfig NETCONF source rendered to IOS-XE CLI

For full bidirectional content (CLI form, NETCONF XML form, MTU
discussion) see the sibling file
`../cisco_iosxe_cli_to_cisco_iosxe/interfaces.md`.  This file
captures direction-specific notes.

## Direction-specific disposition

The NETCONF parser in this repository walks `<interfaces>` and
populates each `CanonicalInterface` with `name`, `description`,
`enabled`, `interface_type`, IPv4 addresses, and IPv6 addresses
(GAP-EVPN-3).  Switchport / VLAN / LAG / VRF / DHCP-client fields
are not parsed.

| Canonical field | NETCONF -> CLI |
|---|---|
| `interfaces[].name` | good — verbatim same-vendor name (`GigabitEthernet1/0/1`) |
| `interfaces[].description` | good |
| `interfaces[].enabled` | good (YANG bool -> `no shutdown` / `shutdown`) |
| `interfaces[].interface_type` | good — NETCONF carries the IANA ident, CLI render is a no-op (the type is implicit in the name) |
| `interfaces[].mtu` | lossy — same `mtu` vs `ip mtu` ambiguity as the CLI->NETCONF direction; CLI render emits `mtu N` (link MTU) which may not match the original CLI's `ip mtu N` |
| `interfaces[].ipv4_addresses` | good |
| `interfaces[].ipv6_addresses` | good |
| `interfaces[].switchport_mode` | not_applicable — NETCONF parser never populates |
| `interfaces[].access_vlan` | not_applicable |
| `interfaces[].trunk_allowed_vlans` | not_applicable |
| `interfaces[].trunk_native_vlan` | not_applicable |
| `interfaces[].voice_vlan` | not_applicable |
| `interfaces[].lag_member_of` | not_applicable |
| `interfaces[].dhcp_client` | not_applicable |
| `interfaces[].vrf` | not_applicable |

The `not_applicable` rows reflect that the NETCONF parser's input
(the device's `<get-config>` reply) IS structurally richer than what
the parser currently extracts — so on a real device, switchport state
DOES exist in the XML, the parser just doesn't read it.  An operator
running the NETCONF -> CLI cross-pair on a Catalyst 9300 will get a
CLI render with no `switchport` / `channel-group` / `vrf forwarding`
lines, which is materially incomplete.  The validation report
should surface the input XML's switched-vlan / aggregate / network-
instance subtrees as `raw_sections` Tier-3 content for operator
review.
