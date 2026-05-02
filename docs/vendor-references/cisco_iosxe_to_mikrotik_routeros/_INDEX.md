# Cisco IOS-XE NETCONF/OpenConfig to MikroTik RouterOS — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/cisco_iosxe__mikrotik_routeros.yaml`
per-field expectations.  See sibling
`tests/fixtures/cross_vendor_expectations/README.md` for the canonical
schema definition.

This is the **cisco_iosxe (NETCONF/OpenConfig stub) source -> MikroTik
RouterOS target** direction.  Distinct from the sibling pair
`../cisco_iosxe_cli_to_mikrotik_routeros/`: the source codec here is the
`cisco_iosxe` codec, NOT `cisco_iosxe_cli`.  The two Cisco codecs target
the same device family (Catalyst 9K / ISR / ASR) but consume different
wire formats:

| Source codec | Wire format | Certification |
|---|---|---|
| `cisco_iosxe_cli` | `show running-config` text | `certified` |
| `cisco_iosxe` | OpenConfig NETCONF YANG XML (Phase-0.5 stub) | `best_effort` |

## Direction-specific framing

The dominant fact for this pair is that the cisco_iosxe NETCONF source
codec is interface-only on parse.  Its `parse()` walks
`<interfaces>/<interface>` in the input XML and produces
`CanonicalInterface` records; every other OpenConfig namespace
(`<system>`, `<vlans>`, `<network-instances>`, `<lacp>`, `<snmp>`,
`<routing>`, ...) is silently ignored.

The CapabilityMatrix lists paths like `/system/hostname`,
`/system/dns-server`, `/system/ntp-server`, `/vlans/vlan/id`,
`/routing/static-route`, `/snmp/community` under `supported` to keep
cross-codec orchestration friendly, but those declarations are
aspirational — the codec's `parse()` does not read those subtrees.
This is documented in the codec's module docstring: "first real adapter
... Phase-0.5 stub".

The result for this cross-pair:

* **Heavy `not_applicable`** for non-interface fields, because the
  source codec produces no data for them (the structural absence is
  on the source side, not a target render-side gap).
* **`good` / `lossy` for the interface canonical-core** — the same
  surface the sibling `cisco_iosxe_cli__mikrotik_routeros` pair
  classifies as `good` for ipv4 / `lossy` for ipv6 (link-local) and
  `interface_type` (IANA ident asymmetry).
* **`unsupported`** only for paths where BOTH codecs declare the path
  unsupported (VXLAN VNIs, EVPN routes).

For a real Cisco-to-MikroTik migration with hostname / DNS / NTP /
syslog / VLAN / SNMP / static-route content, route through
`cisco_iosxe_cli` first — that codec's parse coverage is full and the
sibling pair (`cisco_iosxe_cli__mikrotik_routeros`) covers the wider
canonical surface.

## Topics

| File | Topic | Direction notes |
|---|---|---|
| `openconfig_yang_scope.md` | What the cisco_iosxe NETCONF source actually parses | `<interfaces>`-only stub; rationale for `not_applicable` on non-interface fields |
| `interface_fields.md` | Per-field disposition for the interface canonical core | The only category with `good` / `lossy` rather than `not_applicable` |
| `ipv6_addresses.md` | OpenConfig IPv6 augment parsing and link-local handling | Scope hard-coded `global` on parse; lossy for explicit `fe80::` addresses |
| `vlan_render_gap.md` | OpenConfig VLAN model (top-level + `switched-vlan` augment) | Source codec ignores both; SVI interfaces survive but no top-level vlans |
| `snmp_render_gap.md` | OpenConfig `<system><snmp>` model | Source codec ignores; v3 also matrix-declared `unsupported` |
| `dhcp_render_gap.md` | DHCP server scope (Cisco-IOS-XE-dhcp.yang native) | OpenConfig has no DHCP-server model; source codec is OpenConfig-only |
| `lag_render_gap.md` | OpenConfig LAG augments (`if-aggregate`, `lacp`) | Port-channel-named interfaces survive; member-relationship lost |

## Re-fetch notes

* OpenConfig models cited here live at
  `https://openconfig.net/projects/models/`; specific YANG modules are
  mirrored on GitHub at
  `https://github.com/openconfig/public/tree/master/release/models`.
* MikroTik RouterOS docs are sourced from
  `https://help.mikrotik.com/docs/spaces/ROS/`.

Retrieved 2026-05-01.

## See also

* `../README.md` — citation cache layout
* `../mikrotik_routeros_to_cisco_iosxe/_INDEX.md` — the inverse pair
* `../cisco_iosxe_cli_to_mikrotik_routeros/_INDEX.md` — sibling Cisco-
  source pair (CLI variant) with full canonical surface coverage
* `../aruba_aoss_to_cisco_iosxe/_INDEX.md` — sibling pair targeting the
  same NETCONF stub codec (target-side gap discussion)
