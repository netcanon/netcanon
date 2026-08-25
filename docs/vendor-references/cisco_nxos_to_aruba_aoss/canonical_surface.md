# NX-OS -> Aruba AOS-S: measured canonical surface

Source: `netcanon/migration/codecs/cisco_nxos/codec.py` and
`netcanon/migration/codecs/aruba_aoss/codec.py` (`CapabilityMatrix`), joined
against a full `tools/run_full_mesh.py` run over the committed corpus.
Retrieved: 2026-08-20

This is a *rich-source / narrow-target* pair: `cisco_nxos` is a DC leaf/spine
codec (VXLAN-EVPN, VRFs, HSRP, anycast gateway), `aruba_aoss` is a campus
L2/basic-L3 codec with a single global routing table. Everything the source
carries above the campus surface has nowhere to land.

**13 fixture cells** (12 real captures + 1 synthetic kitchen sink);
**0 render errors, 0 re-parse errors**.

## Per-field measurement (13 cells)

| field | preserved | drifted | untested | what drifts |
|---|---:|---:|---:|---|
| `hostname` | 13 | 0 | 0 | — |
| `dns_servers` | 0 | 0 | 13 | — (never populated on this pair) |
| `ntp_servers` | 1 | 0 | 12 | — |
| `timezone` | 0 | 0 | 13 | — (both matrices declare it unsupported) |
| `domain` | 0 | 2 | 11 | whole value -> `''` |
| `syslog_servers` | 0 | 1 | 12 | whole record — "all 1 dropped" |
| `anycast_gateway_mac` | 0 | 7 | 6 | whole value -> `''` |
| `interfaces` | 0 | 13 | 0 | record count + 7 sub-fields (below) |
| `vlans` | 9 | 4 | 0 | `ipv4_addresses` only |
| `static_routes` | 4 | 4 | 5 | `vrf` only |
| `snmp` | 7 | 4 | 2 | `v3_users` only |
| `lags` | 0 | 5 | 8 | `name` only |
| `local_users` | 0 | 9 | 4 | whole record — "all N dropped" |
| `vxlan_vnis` | 0 | 8 | 5 | whole record — "all N dropped" |
| `routing_instances` | 0 | 12 | 1 | whole record — "all N dropped" |
| `dhcp_servers` | 0 | 0 | 13 | — (source never populates) |
| `radius_servers` | 0 | 0 | 13 | — (source never populates) |
| `evpn_type5_routes` | 0 | 0 | 13 | — (source never populates) |
| `raw_sections` | 0 | 0 | 13 | — |
| `apply_groups` | 0 | 0 | 13 | — (Junos-only) |
| `group_content` | 0 | 0 | 13 | — (Junos-only) |

"untested" = the Phase-1 `trivially_preserved` class: both sides empty, so
the cell could not test any disposition.

## Sub-field drift, aggregated across all 13 cells

Only the sub-fields listed here drift. Every other sub-field of the same
parent is preserved on every cell where the parent list keeps its shape.

| sub-field | cells with per-record drift | observed |
|---|---:|---|
| `interfaces[].mtu` | 2 | `9216` -> `null` |
| `interfaces[].interface_type` | 2 | `ianaift:softwareLoopback` -> `ianaift:ethernetCsmacd`; `ianaift:ieee8023adLag` -> `ianaift:ethernetCsmacd` |
| `interfaces[].vrf` | 1 | `TENANT-A` -> `''`, `management` -> `''` |
| `interfaces[].description` | 1 | `PROD gateway SVI` -> `PROD` (the VLAN name overwrites it) |
| `interfaces[].lag_member_of` | 1 | `port-channel1` -> `trk1` |
| `interfaces[].vrrp_groups` | 1 | one HSRP group -> `[]` (group removed) |
| `interfaces[].ipv4_addresses` | 1 | `virtual_gateway_address` blanked; `ip` / `prefix_length` intact |
| `vlans[].ipv4_addresses` | 4 | `virtual_gateway_address` blanked; `ip` / `prefix_length` intact |
| `static_routes[].vrf` | 4 | `management` -> `''` |
| `lags[].name` | 5 | `port-channel1` -> `trk1`, `port-channel2002` -> `trk2002` |
| `snmp.v3_users` | 4 | per-user `engine_id` -> `''`; name / group / auth-protocol intact |

`interfaces` additionally drifts *structurally* on 11 of 13 cells — the list
loses records rather than attributes:

```
129 -> 3     131 -> 5     132 -> 4     132 -> 4     134 -> 8     134 -> 7
 66 -> 3      72 -> 13     67 -> 7      70 -> 7      19 -> 16
```

Direct probe (`cisco_nxos.parse` -> `aruba_aoss.render` -> `aruba_aoss.parse`)
shows what is lost: NX-OS `show running-config` emits a stanza for every
physical port on the chassis, including ports in pure default state, and the
AOS-S render only emits ports that carry configuration. Default-state
`Ethernet1/N` records therefore do not survive. Alongside them, SVIs with no
IPv4 address — `Vlan1`, and the L3VNI-only `Vlan100` — drop, because AOS-S has
no way to express a VLAN interface that exists solely to host a VRF/VNI
binding. Configured ports, configured SVIs, `loopback0`, `mgmt0` and
`port-channel1` all survive by name.

## Notes grounding the dispositions

* **`local_users`** — the whole record vanishes on all 9 cells that populate
  it ("all N local_users dropped"). The `aruba_aoss` matrix declares no
  `/local-users/...` path at all, so its render emits nothing: the account
  name, its role, and its NX-OS type-5 hash (shape `5 $5$<salt>$<digest>`) go
  together. Marked `unsupported`, not `lossy` — nothing survives to be lossy
  about. This is the single most operator-significant loss on the pair: the
  rendered config would bring the target up with no local credentials.
* **`routing_instances`** — same shape, 12 of 13 cells: "all N dropped". AOS-S
  has one global routing table. Combined with `interfaces[].vrf` and
  `static_routes[].vrf` (both of which blank on render), every tenant VRF's
  interfaces and routes land in the global table together.
* **`vxlan_vnis`** — "all N dropped" on 8 cells; the target matrix declares
  every `/vxlan-vnis/*` path unsupported ("VXLAN not modelled — AOS-S is a
  campus L2/L3 codec").
* **`anycast_gateway_mac` / `*[].ipv4_addresses`** — the same v1 gap seen from
  two sides. `aruba_aoss` declares `/anycast-gateway-mac` and both
  `/…/address/virtual-gateway-address` paths unsupported, so the chassis-wide
  MAC blanks entirely while the per-address companion blanks but leaves the
  real `ip` / `prefix_length` intact.
* **`lags`** — members and LACP mode are preserved on every populated cell;
  only the bundle NAME changes (`port-channel<N>` -> `trk<N>`). Lossy, not
  unsupported — the aggregation itself lands.
* **`static_routes[].metric`** — the target matrix declares the administrative
  distance lossy, but the measurement disagrees: the one fixture carrying a
  non-default distance (`10.100.0.0/16`, metric 200) round-trips it intact, so
  the field is recorded `good` on this pair.
* **`snmp`** — v1/v2c (`community` / `location` / `contact` / `trap_hosts`) is
  preserved on all 11 populated cells. Only the per-user SNMPv3 `engine_id`
  blanks, matching the target matrix's own `/snmp/v3-user/engine-id`
  declaration ("engineIDs are device-assigned / global").
* **`timezone`** — untested by the corpus, but BOTH matrices declare
  `/system/timezone` unsupported, so it is a target-side drop regardless.
* **`dns_servers`** — untested by the corpus; both matrices declare
  `/system/dns-server` supported, so it is recorded `good` on the
  declarations rather than on an observed round-trip.
* **`dhcp_servers` / `radius_servers` / `evpn_type5_routes`** — source-side
  absence. The `cisco_nxos` codec never populates them (0 of 13 cells), so
  there is nothing for the AOS-S target to lose.
