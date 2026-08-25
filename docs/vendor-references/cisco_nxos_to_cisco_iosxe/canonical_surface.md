# NX-OS -> Cisco IOS-XE (NETCONF/OpenConfig): measured canonical surface

Source: `netcanon/migration/codecs/cisco_nxos/codec.py` and
`netcanon/migration/codecs/cisco_iosxe/codec.py` (`CapabilityMatrix`), joined
against a full `tools/run_full_mesh.py` pass over the committed corpus
(`tests/fixtures/real/_cross_mesh_runs/20260820T064630Z.json`).
Retrieved: 2026-08-20

13 fixture cells; **0 render errors, 0 re-parse errors**.

## Read this first: which IOS-XE codec this is

`cisco_iosxe` is the **NETCONF / OpenConfig** codec, not the operator-paste
CLI sibling `cisco_iosxe_cli`. Its `render()` is a Phase-0.5 stub that emits
**only the `openconfig-interfaces` subtree** — name, `enabled`, IANA `type`,
`description`, and the IPv4/IPv6 address augments. It emits no `<system>`, no
`<vlans>`, no `<network-instances>`, no `<snmp>`, no aggregation augment and no
VXLAN model. Everything the NX-OS parser puts on the canonical tree outside
interfaces therefore lands on the tree and is silently dropped on render.

That single fact explains almost every row below, and it is why this pair is
mostly `unsupported` rather than `lossy`: the records do not survive at all.
For a real Nexus-to-Catalyst migration, route through `cisco_iosxe_cli`.

## Per-field measurement (13 cells)

Counts are per CELL. "trivial" = both sides empty (Wave 10alpha
`trivially_preserved`), i.e. no fixture on this pair exercises the field.

| field | preserved | drifted | trivial | what drifts |
|---|---:|---:|---:|---|
| `hostname` | 0 | 13 | 0 | whole value -> `""` |
| `domain` | 0 | 2 | 11 | whole value -> `""` |
| `dns_servers` | 0 | 0 | 13 | — (untested) |
| `ntp_servers` | 0 | 1 | 12 | all servers dropped |
| `timezone` | 0 | 0 | 13 | — (untested; NX-OS never parses it) |
| `syslog_servers` | 0 | 1 | 12 | all servers dropped |
| `interfaces` | 0 | 13 | 0 | 9 sub-fields — see table below |
| `vlans` | 2 | 11 | 0 | 7 cells lose the whole list; 4 lose sub-fields |
| `static_routes` | 0 | 8 | 5 | whole list ("all N static_routes dropped") |
| `dhcp_servers` | 0 | 0 | 13 | — (untested; NX-OS never parses it) |
| `snmp` | 0 | 11 | 2 | whole object -> `None` |
| `lags` | 0 | 5 | 8 | whole list ("all N lags dropped") |
| `local_users` | 0 | 9 | 4 | whole list ("all N local_users dropped") |
| `radius_servers` | 0 | 0 | 13 | — (untested; NX-OS never parses it) |
| `vxlan_vnis` | 0 | 8 | 5 | whole list |
| `evpn_type5_routes` | 0 | 0 | 13 | — (untested) |
| `routing_instances` | 0 | 12 | 1 | whole list ("all N routing_instances dropped") |
| `raw_sections` | 0 | 0 | 13 | — (untested) |
| `apply_groups` | 0 | 0 | 13 | — (Junos-only; NX-OS never populates) |
| `group_content` | 0 | 0 | 13 | — (Junos-only; NX-OS never populates) |
| `anycast_gateway_mac` | 0 | 7 | 6 | whole value -> `""` |

## Interface sub-field measurement (per CELL)

The `interfaces` list itself never collapses — on all 13 cells the Phase-1
drift is a per-record dict, never a "list dropped" / count-drift string. So
the interface RECORD survives everywhere and only these sub-fields move:

| sub-field | cells drifting | shape of the drift |
|---|---:|---|
| `vrf` | 12 | `"VRF_SERVICE_CUST_1"` -> `""` |
| `switchport_mode` | 8 | `"trunk"` / `"access"` -> `null` |
| `access_vlan` | 8 | `10` -> `null` |
| `mtu` | 6 | `9216` -> `null` |
| `lag_member_of` | 5 | `"port-channel1"` -> `null` |
| `ipv4_addresses` | 4 | see below — two distinct causes |
| `vrrp_groups` | 4 | whole HSRP/VRRP group list dropped |
| `trunk_allowed_vlans` | 4 | `[10, 2000]` -> `[]` |
| `trunk_native_vlan` | 2 | `999` -> `null` |

Every OTHER interface sub-field the corpus populates is preserved on every
cell it appears on: `name`, `description`, `enabled`, `interface_type`,
`dhcp_client`, `ipv6_addresses`. `voice_vlan`, `tunnel_type`, `default_name`
and `kind` are never populated by any fixture on this pair.

### `interfaces[].ipv4_addresses` — two causes, one of them substantive

Of the four drifting cells, two (`networklessons_clab_dag_symmetric_irb`,
`kitchen_sink.cfg`) are pure anycast-companion blanking: the target keeps
`ip` and `prefix_length` and clears `virtual_gateway_address`, which the
target matrix already declares `unsupported` at
`/interfaces/interface/ipv4/address/virtual-gateway-address`.

The other two (`akarneliuk_evpn_vxlan_mcast_leaf_c1`,
`busterswt_spine_leaf_xk32_1_nxos931`) carry a **real** loss on `loopback0`:
a second address parsed with `is_secondary: true` re-parses from the render as
`is_secondary: false`. Both addresses survive as values, but the
primary/secondary discriminator is gone, so the pair re-renders as two primary
addresses on one loopback — which on a real box means the second overwrites
the first. This is the reason `interfaces[].ipv4_addresses` is `lossy` here
and not `good`.

## `vlans` — why the top-level key, not sub-field keys

`vlans` splits three ways across the 13 cells:

* 2 cells preserved.
* 7 cells lose the record wholesale — "all N vlans dropped" or a count drift
  (`47 -> 1`, `5 -> 4`, `4 -> 2`, `3 -> 1`). When the Phase-1 drift is a
  structural string every sub-field is drifted by construction, so no
  `vlans[].<x>` key can honestly be called `good`.
* 4 cells keep a record but lose `name` (4), `untagged_ports` (4),
  `ipv4_addresses` (2), `tagged_ports` (2). `id` survives on those four.

The survivors are an artefact, not VLAN support: the stub renders no
`<vlans>` subtree, and the target matrix says so directly for
`/vlans/vlan/id` ("Phase 0.5 stub render does not walk intent.vlans"). The
VLAN rows that come back are re-derived on re-parse from the synthesised
`interface VlanN` SVIs that DO survive through the interfaces subtree. So the
disposition applies to the whole record and the key stays top-level.

## Capability-matrix cross-check

Where the target matrix has an opinion, the measurement agrees with it:

* `/system/hostname`, `/system/domain`, `/system/dns-server`,
  `/system/ntp-server`, `/system/timezone`, `/system/syslog-server` — all
  `unsupported` ("Phase 0.5 stub render emits only the openconfig-interfaces
  subtree").
* `/vlans/vlan/id`, `/vlans/vlan/name`, `/routing/static-route`,
  `/routing-instances/instance`, `/snmp`, `/vxlan-vnis/vni`,
  `/evpn-type5-routes/route`, `/dhcp-servers/pool`,
  `/radius-servers/server/host`, `/anycast-gateway-mac` — `unsupported`.
* `/interfaces/interface/switchport-mode`, `/access-vlan`,
  `/trunk-allowed-vlans`, `/trunk-native-vlan`, `/voice-vlan`,
  `/vrrp-groups/group` (and every leaf under it) — `unsupported`.
* `/interfaces/interface/config/mtu` and `/interfaces/interface/tunnel-type`
  — `lossy`.

Two places where the matrix is SILENT and the measurement is the only
evidence:

* **`lags`** — `cisco_iosxe` declares no `/lags/lag` path at all, neither
  supported nor unsupported. The corpus shows the whole record dropped on all
  5 populated cells. The declaration gap is worth closing on the codec side;
  the behaviour is not in doubt.
* **`local_users`** — same shape: no `/local-users/user` declaration, whole
  record dropped on all 9 populated cells.

`/interfaces/interface/config/mtu` is declared `lossy` with a nuance reason
("platform-specific MTU tweaks ... only representable in CLI"), but the
measurement is blunter than the declaration: the value goes to `null`, it is
not degraded. The YAML keeps `lossy` to stay in step with the matrix and
states the measured outcome in the reason.

## Secrets

`snmp` and `local_users` both drop wholesale, and both carry credential
material on the source side — SNMPv3 USM localized keys in `0x<hex>` form and
NX-OS local-user hashes in `5 $5$<salt>$<digest>` form. Neither this note nor
the YAML reproduces any real salt, digest or key; shapes only.
