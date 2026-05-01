# Cisco IOS-XE OpenConfig NETCONF to Aruba AOS-S — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/cisco_iosxe__aruba_aoss.yaml`
per-field expectations.  See sibling `README.md` (one level up) for the
canonical schema definition.

This is the **Cisco OpenConfig NETCONF source -> Aruba AOS-S CLI
target** direction.  Distinct from the sibling pair
`../cisco_iosxe_cli_to_aruba_aoss/`: the source codec here is the
`cisco_iosxe` codec (NETCONF), NOT `cisco_iosxe_cli` (CLI).

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

So when the AOS-S CLI render runs, there's nothing to drop —
there's nothing in the canonical tree to begin with.  Almost every
non-interface field on this direction is `not_applicable` (source
parser never produced data) rather than `lossy` (would be data
loss) or `unsupported` (target can't accept).

This is structurally different from cross-VENDOR pairs: the loss
happens at the codec parse boundary, not at the target render
boundary or at vendor-feature mismatch.

## Topics

| File | Topic | Direction notes |
|---|---|---|
| `oc-parse-narrow.md` | What the cisco_iosxe parser actually populates | Subset of openconfig-interfaces; ignores everything else |
| `interface-fields.md` | Per-field disposition for the canonical interface core | The only fields with `good` disposition |
| `aoss-target-coverage.md` | What the AOS-S target codec accepts vs what arrives | Most AOS-S `supported` paths get nothing to render |
| `port-naming.md` | Cisco GigabitEthernet to AOS-S bare-numeric | Same name-shape mapping as cisco_iosxe_cli sibling pair |
| `system-services.md` | hostname / DNS / NTP / syslog / timezone | All `not_applicable` (parser never reads `<system>`) |
| `vlan-and-svi.md` | VLANs and SVIs | `not_applicable` (parser never reads `<vlans>`) |
| `snmp-and-aaa.md` | SNMP / RADIUS / local users | All `not_applicable` |
| `vxlan-evpn-vrf.md` | VXLAN, EVPN, VRF | All `not_applicable` (parser + target both blocked) |

## Re-fetch notes

OpenConfig models cited live at `https://openconfig.net/projects/models/`
and `https://github.com/openconfig/public/`.  Aruba AOS-S manuals are
at `https://www.arubanetworks.com/techdocs/AOS-S/` (16.10 / 16.11 train).

See also: `../aruba_aoss_to_cisco_iosxe/_INDEX.md` (reverse direction)
and `../README.md` (citation cache layout).
