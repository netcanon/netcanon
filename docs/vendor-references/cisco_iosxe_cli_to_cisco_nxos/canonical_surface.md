# Cisco IOS-XE (CLI) -> NX-OS: measured canonical surface

Source: `netcanon/migration/codecs/cisco_iosxe_cli/codec.py` and
`netcanon/migration/codecs/cisco_nxos/codec.py` (`CapabilityMatrix`), joined
against the committed `tools/run_full_mesh.py` pass
(`tests/fixtures/real/_cross_mesh_runs/20260820T064630Z.json`) and re-read
through `tools/run_phase4_reconciliation.py::actual_disposition` — the same
resolver the CI ratchet uses, so the per-sub-field counts below are the ones
the guard will see.
Retrieved: 2026-08-20

A Cisco-to-Cisco pair in the other direction from
`cisco_nxos__cisco_iosxe_cli`: a Catalyst / ISR / CSR running IOS-XE, captured
as CLI text, re-homed onto a Nexus. **15 fixture cells, 0 render errors, 0
re-parse errors.**

## Per-field measurement (15 cells)

`preserved` / `drifted` / `untested` are per CELL. "untested" means both sides
were in zero-state on that cell (`trivially_preserved`), so the cell could not
test any disposition claim.

| field | preserved | drifted | untested | what drifts |
|---|---:|---:|---:|---|
| `hostname` | 14 | 1 | 0 | the whole scalar, on the one source with no `hostname` line |
| `vlans` | 4 | 0 | 11 | — |
| `snmp` | 2 | 0 | 13 | — |
| `vxlan_vnis` | 1 | 0 | 14 | — |
| `domain` | 3 | 0 | 12 | — |
| `dns_servers` | 1 | 0 | 14 | — |
| `ntp_servers` | 1 | 0 | 14 | — |
| `syslog_servers` | 3 | 0 | 12 | — |
| `interfaces` | 2 | 9 | 4 | `interface_type`, `lag_member_of`, `access_vlan`, `trunk_native_vlan`, `trunk_allowed_vlans`, `voice_vlan`, `tunnel_type`, `kind`, `vrrp_groups` |
| `static_routes` | 5 | 2 | 8 | `description` only |
| `lags` | 0 | 3 | 12 | `name` only (`members` / `mode` survive) |
| `local_users` | 0 | 7 | 8 | `privilege_level` only |
| `routing_instances` | 3 | 1 | 11 | whole-record: one instance APPEARS in the target |
| `dhcp_servers` | 0 | 1 | 14 | whole record: all pools dropped |
| `radius_servers` | 0 | 1 | 14 | whole record: all servers dropped |
| `timezone` | 0 | 0 | 15 | untested |
| `evpn_type5_routes` | 0 | 0 | 15 | untested |
| `raw_sections` | 0 | 0 | 15 | untested |
| `apply_groups` | 0 | 0 | 15 | untested |
| `group_content` | 0 | 0 | 15 | untested |
| `anycast_gateway_mac` | 0 | 0 | 15 | untested |

## Sub-field drift (the authoritative view)

Resolved per YAML field key across all 15 cells. Everything NOT listed in this
table preserved on every cell that carried data for it.

| key | preserved | drifted | untested |
|---|---:|---:|---:|
| `interfaces[].interface_type` | 2 | 9 | 4 |
| `interfaces[].lag_member_of` | 0 | 3 | 12 |
| `interfaces[].access_vlan` | 2 | 1 | 12 |
| `interfaces[].trunk_native_vlan` | 2 | 1 | 12 |
| `interfaces[].trunk_allowed_vlans` | 1 | 1 | 13 |
| `interfaces[].voice_vlan` | 0 | 1 | 14 |
| `interfaces[].tunnel_type` | 1 | 1 | 13 |
| `interfaces[].kind` | 1 | 1 | 13 |
| `interfaces[].vrrp_groups` | 0 | 1 | 14 |
| `lags[].name` | 0 | 3 | 12 |
| `local_users[].privilege_level` | 0 | 7 | 8 |
| `static_routes[].description` | 0 | 2 | 13 |

Preserved on every populated cell: `interfaces[].name` (11),
`interfaces[].enabled` (11), `interfaces[].dhcp_client` (11),
`interfaces[].ipv4_addresses` (9), `interfaces[].description` (8),
`interfaces[].switchport_mode` (5), `interfaces[].mtu` (4),
`interfaces[].vrf` (4), `interfaces[].ipv6_addresses` (3),
`interfaces[].dot1q_vlan` (1); `vlans` whole-record (4);
`static_routes[].destination` (7), `static_routes[].gateway` (7),
`static_routes[].interface` (5), `static_routes[].vrf` (2),
`static_routes[].metric` (1); `lags[].members` (3), `lags[].mode` (3);
`local_users[].name` (7), `local_users[].hashed_password` (7),
`local_users[].role` (7); `snmp.community` / `.location` / `.contact` /
`.trap_hosts` / `.v3_users` (2 each); `vxlan_vnis` whole-record (1).

## Why each drifting key drifts

**`interfaces[].interface_type`** — `ianaift:ethernetCsmacd` arrives and
re-parses as `ianaift:other`. The NX-OS parser infers ifType from a name-prefix
table (`ethernet` / `loopback` / `vlan` / `port-channel` / `nve` / `tunnel` /
`mgmt`, `cisco_nxos/parse.py::_TYPE_HINTS`), and NX-OS spells every speed with
the single `Ethernet` prefix. IOS-XE speed-prefixed names —
`GigabitEthernet0/0`, `TenGigabitEthernet1/0/1`, `FortyGigabitEthernet1/1/1` —
do not match, so the type falls to `other`. The two cells that do NOT drift
(`ciscolive_brkops1104_evpn_leaf_iosxe1715`, `cml_saumur_iosxe1712_pvrstp`) are
exactly the two whose ports are already `Ethernet<x>/<y>` / `Loopback<N>` /
`Vlan<N>` / `nve1`. Renaming to the NX-OS form restores the type.

**`interfaces[].lag_member_of` / `lags[].name`** — `Port-channel<N>` re-parses
as `port-channel<N>`. NX-OS writes the bundle lower-case. The bundle itself,
its `members` and its LACP `mode` all preserve. The reconciler's LAG-name
canonicaliser (`_LAG_NAME_RE`) accepts `Po<N>` / `Port-channel<N>` /
`Port-Channel<N>` / `ae<N>` / `trk<N>` / `agg<N>` / `bond<N>` but NOT the
lower-case NX-OS spelling, so this surfaces as drift on both keys rather than
collapsing to a vendor-correct rename.

**`interfaces[].access_vlan` / `[].trunk_native_vlan` /
`[].trunk_allowed_vlans`** — one cell
(`user_contrib_cat9300_iosxe1712`), and the pattern is mode-directed: the NX-OS
render emits only the switchport attributes that apply to the port's ACTIVE
mode. On `switchport mode trunk` ports the source's `switchport access vlan
150` is dropped (`access_vlan: 150 -> null`); on `switchport mode access` ports
the source's `switchport trunk native vlan` / `trunk allowed vlan` are dropped
(`trunk_native_vlan: 100 -> null`, `trunk_allowed_vlans: [100] -> []`). Ports
whose configured attributes match their mode round-trip intact — that is why
the other two cells carrying these sub-fields preserve them.

**`interfaces[].voice_vlan`** — `30 -> null`. The `cisco_nxos` matrix declares
`/interfaces/interface/voice-vlan` **unsupported**: "This codec does not model
NX-OS per-port voice VLAN; dropped on render (blind-audit 65f9c01 #11)." The
attribute does not survive in any form.

**`interfaces[].tunnel_type`** — `ipsec -> ""`. The matrix declares
`/interfaces/interface/tunnel-type` lossy: `gre` and `ipip` round-trip via
`tunnel mode gre ip` / `tunnel mode ipip`, while `ipsec` / `vxlan` / `eoip`
have no NX-OS interface-encap equivalent. The interface record survives; only
its encapsulation type is erased.

**`interfaces[].kind`** — `mgmt -> ""` on the Catalyst's `GigabitEthernet0/0`.
`kind` is the logical-role override; empty means "infer from the name". The
NX-OS parser re-promotes a port to `kind="mgmt"` only when it is named `mgmt*`
or sits in a `management` / `mgmt` VRF (`cisco_nxos/parse.py::_is_mgmt_vrf`),
neither of which is true of a port that keeps its IOS-XE name in the default
VRF.

**`interfaces[].vrrp_groups`** — the group survives with the same `group_id`,
`virtual_ips`, `priority` and `preempt`; `mode` changes `vrrp -> hsrp`. The
NX-OS matrix declares `/interfaces/interface/vrrp-groups/group` and
`.../group/mode` lossy: the codec renders EVERY `CanonicalVRRPGroup` as an
`hsrp` block regardless of the source mode. It also declares
`advertisement-interval`, `virtual-ipv6s` and the group `description` lossy —
no cell in this corpus populates those, so only the protocol swap is observed.

**`local_users[].privilege_level`** — `15 -> 1` and `5 -> 1`, on every cell with
local accounts. Mechanism, end to end: the IOS-XE CLI parser derives a canonical
`role` from the numeric privilege (`15 -> "admin"`, else `"operator"`,
`cisco_iosxe_cli/parse.py`); the NX-OS renderer emits `user.role` VERBATIM when
set, so it writes `username <name> ... role admin`; the NX-OS parser then maps
only `network-admin` / `vdc-admin` back to privilege 15 (`_NXOS_ADMIN_ROLES`)
and everything else to 1. `role` therefore round-trips unchanged (`admin`
in, `admin` out) while the privilege collapses. `admin` is not an NX-OS
built-in role, so the rendered config also references a role the target device
does not define until the operator creates it.

**`static_routes[].description`** — the route name is dropped
(`"boppety" -> ""`, `"UMBRELLA_SIG" -> ""`). Both matrices declare
`/routing/static-route/description` lossy: the NX-OS render emits destination +
next-hop + metric only. The route itself, its VRF and its metric all survive.

**`hostname`** — one cell (`ntc_carrier_interfaces`), whose source config
carries no `hostname` line at all. `cisco_nxos/render.py` line 93 is
`hostname = tree.hostname or "switch"`, so the target comes up named `switch`.
Every other cell preserves the hostname verbatim.

**`routing_instances`** — one cell (`batfish_cisco_ip_route`), and the drift is
an APPEARANCE, not a loss: `0 -> 1`. The source declares no `vrf definition`,
only VRF-scoped statics (`ip route vrf myvrf 0.0.0.0 0.0.0.0 5.6.7.8 ...`).
NX-OS cannot host a VRF-scoped route without the VRF existing, so the render
materialises `vrf context myvrf` and the re-parse returns a routing instance
the source never had. The synthesised context carries `name` +
`instance_type` only — no RD, no route-targets. On the other 3 populated cells
the VRFs (with RD, RT imports/exports and `l3_vni`) preserve exactly.

**`dhcp_servers` / `radius_servers`** — whole-record drops, both on
`kitchen_sink` ("all 2 dhcp_servers dropped", "all 2 radius_servers dropped").
The `cisco_nxos` matrix declares `/dhcp-servers/pool`,
`/radius-servers/server/host` and `/radius-servers/server/key` **unsupported**:
the render emits no DHCP pool and no `aaa` / `radius-server` configuration at
all. Nothing survives to re-parse.

## Untested by this corpus

`timezone`, `evpn_type5_routes`, `raw_sections`, `apply_groups`,
`group_content` and `anycast_gateway_mac` score `trivially_preserved` on all 15
cells — no fixture on this pair populates them on either side.

* `timezone`: BOTH matrices declare `/system/timezone` unsupported ("Render
  emits no clock/timezone stanza; intent.timezone is dropped on migration"), so
  the gap is certain regardless of coverage.
* `anycast_gateway_mac`: both matrices declare it supported; no fixture
  exercises it.
* `evpn_type5_routes`: both codecs model EVPN Type-5 IP-prefix advertisement as
  a VRF property via `CanonicalRoutingInstance.l3_vni`, not as standalone route
  records, and both declare `/evpn-type5-routes/route` lossy for that reason.
  The `cisco_iosxe_cli` source never populates it.
* `raw_sections`: the `cisco_iosxe_cli` source never populates it. (The NX-OS
  target declares `vdc` and `features` raw-sections lossy, but nothing on this
  pair reaches those paths.)
* `apply_groups` / `group_content`: Junos-only concepts.

## Reproducing

```
py tools/run_full_mesh.py                     # writes tests/fixtures/real/_cross_mesh_runs/<ts>.json
py tools/run_phase4_reconciliation.py         # re-reads it against the pair YAMLs
py tools/load_cross_vendor_expectations.py    # schema gate for the YAML itself
```
