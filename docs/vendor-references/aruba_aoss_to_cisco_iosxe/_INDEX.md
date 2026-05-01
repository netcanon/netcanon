# Aruba AOS-S to Cisco IOS-XE OpenConfig NETCONF — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/aruba_aoss__cisco_iosxe.yaml`
per-field expectations.  See sibling `README.md` (one level up) for the
canonical schema definition.

This is the **AOS-S CLI source -> Cisco OpenConfig NETCONF target**
direction.  Distinct from the sibling pair
`../aruba_aoss_to_cisco_iosxe_cli/`: the target codec here is the
`cisco_iosxe` codec, NOT `cisco_iosxe_cli`.  The two Cisco codecs
target the same device family (Catalyst 9K / ISR / ASR) but different
wire formats:

| Target codec | Wire format | Certification |
|---|---|---|
| `cisco_iosxe_cli` | `show running-config` text | `certified` |
| `cisco_iosxe` | OpenConfig NETCONF YANG XML | `best_effort` (Phase-0.5 stub) |

## Direction-specific framing

The dominant fact for this pair is that the `cisco_iosxe` target
codec's `render()` only emits a NARROW subset of OpenConfig YANG —
the `openconfig-interfaces` subtree with IPv4 + IPv6 addresses, MTU,
description, enable state, and IANA interface-type.  Everything
else the AOS-S source CLI carries (VLANs, SNMP, RADIUS, local users,
LAGs, static routes, system services like DNS/NTP/syslog/hostname)
falls into one of two buckets:

1. **`unsupported`** — the target codec's CapabilityMatrix lists the
   path under `unsupported` (e.g. `/snmp/v3-user`, `/vxlan-vnis/*`).
2. **Aspirational `supported`** — the matrix lists the path under
   `supported` for cross-codec orchestration friendliness, but the
   actual `_render_canonical()` method NEVER emits XML for that
   subtree.  These show as `lossy` or `unsupported` here with an
   honest reason citing the parse/render gap.

The result: the AOS-S source typically carries 5-10x more content
than the cisco_iosxe target can re-emit.  Operators using this pair
for backup / orchestration need to understand they're getting a
lossy projection of the AOS-S running-config — anything not in the
narrow OpenConfig interfaces subtree must be re-applied separately
(typically via the device's CLI directly, or by routing the
migration through `cisco_iosxe_cli` first).

## Topics

| File | Topic | Direction notes |
|---|---|---|
| `oc-interfaces.md` | OpenConfig `openconfig-interfaces` YANG model — what NETCONF actually emits | The narrow subset that does survive the round-trip |
| `aoss-out-of-scope.md` | AOS-S features NOT carried through the OpenConfig render | Hostname / VLAN / SNMP / RADIUS / users / LAGs / static-routes |
| `port-naming.md` | AOS-S bare-numeric -> Cisco GigabitEthernet/.../... | Same name-shape mapping as `aruba_aoss_to_cisco_iosxe_cli` |
| `interface-fields.md` | Per-field disposition for the interface canonical core | The only fields with `good` disposition on this direction |
| `vlan-svi-loss.md` | AOS-S VLAN-centric model -> OpenConfig render gap | VLAN definitions and SVIs both drop entirely |
| `system-services.md` | hostname / DNS / NTP / syslog / timezone | All `unsupported` in target render path |
| `vxlan-evpn-vrf.md` | VXLAN, EVPN, VRF | All target-side `unsupported` (matrix-declared) |
| `snmp-and-aaa.md` | SNMP v1/v2c/v3 + RADIUS + local users | All drop on target render |

## Re-fetch notes

OpenConfig models cited here live at `https://openconfig.net/projects/models/`;
specific YANG modules are mirrored on GitHub at
`https://github.com/openconfig/public/tree/master/release/models`.
Aruba AOS-S manuals are sourced from
`https://www.arubanetworks.com/techdocs/AOS-S/` (16.10 / 16.11 train).

See also: `../cisco_iosxe_to_aruba_aoss/_INDEX.md` (reverse direction)
and `../README.md` (citation cache layout).
