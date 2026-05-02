# Cisco IOS-XE OpenConfig NETCONF to Juniper Junos — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/cisco_iosxe__juniper_junos.yaml`
per-field expectations.  See sibling `README.md` (one level up) for the
canonical schema definition.

This is the **Cisco OpenConfig NETCONF source -> Juniper Junos source-rich
target** direction.  Distinct from the sibling pair
`../cisco_iosxe_cli_to_juniper_junos/`: the source codec here is the
`cisco_iosxe` codec (NETCONF/OpenConfig YANG XML), NOT `cisco_iosxe_cli`
(operator-paste running-config).

The two Cisco codecs target the same device family but the parse
surface is sharply different:

| Source codec | Wire format | Parse coverage |
|---|---|---|
| `cisco_iosxe_cli` | `show running-config` text | Full canonical surface (certified) |
| `cisco_iosxe` | OpenConfig NETCONF YANG XML | `<interfaces>` only (best_effort stub) |

## Direction-specific framing

The dominant fact for this pair is that the `cisco_iosxe` SOURCE
codec's `parse()` only walks `<interfaces>`.  Even when a real
device's `<get-config>` reply carries `<system>`, `<vlans>`,
`<network-instances>`, `<snmp>`, the parser ignores those subtrees
entirely.  `intent.hostname`, `intent.dns_servers`, `intent.snmp`,
`intent.vlans`, `intent.local_users`, `intent.radius_servers`,
`intent.lags`, `intent.routing_instances`, `intent.static_routes`
are all empty / None after parse, regardless of input content.

The Junos target codec is among the richest in the repo: it advertises
support for hostname, DNS, NTP, syslog, VLANs, VXLAN VNIs, MAC-VRF and
L3-VRF instance types, full SNMPv1/v2c + v3 USM, local users, static
routes, and apply-groups inheritance.  But on this direction, the
canonical input the Junos target consumes is overwhelmingly empty
because the source parser never populated the data.  Almost every
non-interface field is `not_applicable` (source parser never produced
data) rather than `lossy` (would be data loss) or `unsupported`
(target can't accept) — same labelling pattern as the sibling
`cisco_iosxe_to_aruba_aoss/` audit.

This is structurally different from cross-VENDOR pairs where both
codecs are full-feature (cisco_iosxe_cli__juniper_junos): there the
loss happens at vendor-feature mismatch.  Here the loss happens at
the codec parse boundary, well before any vendor decision.

## Topics

| File | Topic | Direction notes |
|---|---|---|
| `openconfig-yang-scope.md` | What the cisco_iosxe parser actually populates | `<interfaces>` only; `<system>`/`<vlans>`/`<network-instances>` ignored |
| `interface-fields.md` | Per-field disposition for the canonical interface core | The only fields with `good` disposition |
| `ipv6-addresses.md` | IPv6 link-local scope hard-code | Source parser hard-codes `scope="global"` |
| `vlan-render-gap.md` | VLANs and SVIs | `not_applicable` (parser never reads `<vlans>`) |
| `snmp-render-gap.md` | SNMP v1/v2c + v3 USM | `not_applicable` (parser never reads `<snmp>`) |
| `vxlan-evpn-gap.md` | VXLAN, EVPN-VXLAN | `not_applicable` (parser + Cisco target both blocked) |
| `vrf-render-gap.md` | VRF / routing-instances | `not_applicable` (parser never reads `<network-instances>`) |
| `interface-naming.md` | Cisco GigabitEthernet to Junos `ge-`/`xe-`/`et-` form | Port-rename mesh handles cross-vendor mapping |

## Re-fetch notes

OpenConfig models cited live at `https://openconfig.net/projects/models/`
and `https://github.com/openconfig/public/`.  Juniper TechLibrary docs
live at `https://www.juniper.net/documentation/`.

See also: `../juniper_junos_to_cisco_iosxe/_INDEX.md` (reverse direction)
and `../README.md` (citation cache layout).
