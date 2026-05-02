# Cisco IOS-XE OpenConfig NETCONF to Arista EOS — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/cisco_iosxe__arista_eos.yaml`
per-field expectations.  See sibling
`tests/fixtures/cross_vendor_expectations/README.md` for the canonical
schema definition.

This is the **Cisco IOS-XE OpenConfig NETCONF source -> Arista EOS CLI
target** direction.  Distinct from the sibling pair
`../cisco_iosxe_cli_to_arista_eos/`: the source codec here is the
`cisco_iosxe` codec, NOT `cisco_iosxe_cli`.  Both Cisco codecs target
the same Catalyst 9K / ISR4K / ASR1K device family but parse different
wire formats:

| Source codec | Wire format | Certification |
|---|---|---|
| `cisco_iosxe_cli` | `show running-config` text | `certified` |
| `cisco_iosxe` | OpenConfig NETCONF YANG XML | `best_effort` (Phase-0.5 stub) |

## Direction-specific framing

The dominant asymmetry on this direction is **opposite** to the
forward (`arista_eos -> cisco_iosxe`) pair.  Forward: rich Arista
source produces a populated canonical tree, target NETCONF render
silently drops most of it.  Reverse (this pair): the cisco_iosxe
**parse** path walks `<interfaces>` only and never populates
`hostname`, `domain`, `dns_servers`, `ntp_servers`, `vlans`,
`static_routes`, `routing_instances`, `lags`, `local_users`,
`radius_servers`, or `snmp` from the source XML.  These fields are
empty on the canonical tree input to the Arista render — there is no
data to drop.

For these fields the disposition is `not_applicable` (parser never
produces; nothing reaches render to lose) rather than `unsupported`
(codec semantically declines to handle declared canonical data).
Same operational meaning — the operator gets nothing on the wire —
but a structurally different schema label that distinguishes "data
loss happened upstream" from "the target codec declined to emit
declared data".

The Arista EOS target codec is by contrast `certified` and
emits the full canonical surface: a hypothetical fully-wired
cisco_iosxe parser would round-trip through this pair cleanly.  The
limitation is purely on the source-codec parse-side — once the
cisco_iosxe parser walks `<system>`, `<vlans>`, `<network-instances>`,
`<snmp>`, etc., this YAML's `not_applicable` rows flip to `good`
or `lossy` per the underlying canonical-model fidelity.

## Topics

| File | Topic | Direction notes |
|---|---|---|
| `openconfig-yang-scope.md` | Why the cisco_iosxe parser walks `<interfaces>` only | OpenConfig vs Cisco-IOS-XE-native YANG modules |
| `interface-fields.md` | Per-field disposition for the interface canonical core | The only fields with `good` or `lossy` disposition on this direction |
| `ipv6-addresses.md` | IPv6 address forms and link-local handling | cisco_iosxe parser hard-codes scope=global; Arista renders link-local explicitly |
| `vlan-render-gap.md` | VLAN definitions never reach the canonical tree | Source parse-side gap; Arista render is empty |
| `snmp-render-gap.md` | SNMP v1/v2c + v3 USM users never reach the canonical tree | Source parse-side gap |
| `vxlan-evpn-gap.md` | VXLAN VNIs + EVPN Type-5 never reach the canonical tree | Source matrix declares `/vxlan-vnis/*` `unsupported`; Arista target is fully wired |
| `vrf-render-gap.md` | VRFs / routing-instances never reach the canonical tree | Source parse-side gap; Arista target is fully wired |

## Re-fetch notes

OpenConfig models cited here live at
`https://openconfig.net/projects/models/`; specific YANG modules are
mirrored on GitHub at
`https://github.com/openconfig/public/tree/master/release/models`.
Cisco IOS-XE programmability guides at
`https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/prog/configuration/`.
Arista TechHub manuals at `https://www.arista.com/en/um-eos/`
(EOS 4.27.0F / 4.35.2F / 4.36.0F trains).

See also: `../README.md` (citation cache layout),
`../arista_eos_to_cisco_iosxe/_INDEX.md` (forward direction),
`../cisco_iosxe_cli_to_arista_eos/_INDEX.md` (sibling CLI source).
