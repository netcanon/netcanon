# MikroTik RouterOS to Cisco IOS-XE NETCONF/OpenConfig — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/mikrotik_routeros__cisco_iosxe.yaml`
per-field expectations.  See sibling
`tests/fixtures/cross_vendor_expectations/README.md` for the canonical
schema definition.

This is the **MikroTik RouterOS source -> Cisco IOS-XE OpenConfig
NETCONF target** direction.  Distinct from the sibling pair
`../mikrotik_routeros_to_cisco_iosxe_cli/`: the target codec here is
the `cisco_iosxe` codec, NOT `cisco_iosxe_cli`.  The two Cisco codecs
target the same device family (Catalyst 9K / ISR / ASR) but emit
different wire formats:

| Target codec | Wire format | Certification |
|---|---|---|
| `cisco_iosxe_cli` | `show running-config` text | `certified` |
| `cisco_iosxe` | OpenConfig NETCONF YANG XML (Phase-0.5 stub) | `best_effort` |

## Direction-specific framing

The dominant fact for this pair is that the cisco_iosxe NETCONF target
codec's `render()` only emits a NARROW subset of OpenConfig YANG —
the `openconfig-interfaces` subtree with IPv4 + IPv6 addresses,
description, enable state, and IANA interface-type.  Everything else
the RouterOS source carries (hostname / DNS / NTP / syslog / VLANs /
SNMP / static-routes / DHCP / LAGs / local users / RADIUS) reaches
the canonical tree but is silently dropped by the target render.

For this cross-pair this means:

* **Heavy `unsupported`** for non-interface fields, because the source
  side populates them but the target render does not walk them.  The
  CapabilityMatrix lists `/system/hostname` and friends under
  `supported` aspirationally; honest classification beats matrix-
  deference.
* **`good` / `lossy` for the interface canonical-core** — the same
  surface the sibling `mikrotik_routeros__cisco_iosxe_cli` pair
  classifies.
* **`unsupported`** for paths where BOTH codecs declare the path
  unsupported (VXLAN VNIs, EVPN routes).
* **`not_applicable`** for fields neither side carries (apply_groups,
  group_content, voice_vlan).

The contrast with the sibling `mikrotik_routeros__cisco_iosxe_cli`
pair is sharp: that pair classifies most surfaces as `lossy` because
the cisco_iosxe_cli render walks the full canonical tree.  The NETCONF
stub's narrow render scope is the single biggest factor making this
pair lossier.

For a real RouterOS-to-Cisco migration with hostname / DNS / NTP /
syslog / VLAN / SNMP / static-route content, route through
`cisco_iosxe_cli` first — that codec is `certified` and emits the full
canonical surface.

## Topics

| File | Topic | Direction notes |
|---|---|---|
| `openconfig_yang_scope.md` | What the cisco_iosxe NETCONF target actually emits | `<interfaces>`-only render; rationale for `unsupported` on non-interface fields |
| `interface_fields.md` | Per-field disposition for the interface canonical core | The only category with `good` / `lossy` rather than `unsupported` |
| `ipv6_addresses.md` | RouterOS link-local handling vs OpenConfig render | `link-local=yes` flag dropped on render; lossy for explicit `fe80::` |
| `vlan_render_gap.md` | RouterOS VLAN modelling vs OpenConfig render | Plane-1 SVIs survive as interfaces; top-level `<vlans>` not emitted |
| `snmp_render_gap.md` | RouterOS SNMP source vs OpenConfig render | Source carries v1/v2c+v3; render emits nothing.  v3 doubly unsupported |
| `dhcp_render_gap.md` | RouterOS DHCP server source vs render | Three-section RouterOS form; render has no OpenConfig DHCP model |
| `lag_render_gap.md` | RouterOS bonding source vs render | `bondN` interfaces survive; aggregator records and member back-pointers dropped |

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
* `../cisco_iosxe_to_mikrotik_routeros/_INDEX.md` — the inverse pair
* `../mikrotik_routeros_to_cisco_iosxe_cli/_INDEX.md` — sibling Cisco-
  target pair (CLI variant) with full canonical surface coverage
* `../aruba_aoss_to_cisco_iosxe/_INDEX.md` — sibling pair targeting the
  same NETCONF stub codec (target-side gap discussion)
