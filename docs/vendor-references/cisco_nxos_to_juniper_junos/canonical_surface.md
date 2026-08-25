# NX-OS -> Juniper Junos: measured canonical surface

Source: `netcanon/migration/codecs/cisco_nxos/codec.py` and
`netcanon/migration/codecs/juniper_junos/codec.py` (`CapabilityMatrix`), joined
against a full in-process `tools/run_full_mesh.py` run over the committed
corpus, filtered to the `cisco_nxos -> juniper_junos` cells.
Retrieved: 2026-08-20

13 fixture cells (12 real captures + the synthetic kitchen-sink);
**0 render errors, 0 re-parse errors**.

Both codecs are switch-primary (`cisco_nxos` = switch/router, `juniper_junos` =
switch/router/firewall), so the shared surface is wide: L2/L3 interfaces,
VLANs + SVIs, VXLAN-EVPN, VRFs with L3 VNIs, LAGs, SNMP, static routes. The
realistic migration is a Nexus 9000 leaf replaced by a QFX leaf in the same
EVPN-VXLAN fabric role.

## Per-field measurement (13 cells)

`untested` = both sides in their zero state on that cell, so the round-trip
was never exercised there (Phase 1 `trivially_preserved`).

| field | preserved | drifted | untested | what drifts |
|---|---:|---:|---:|---|
| `hostname` | 13 | 0 | 0 | — |
| `vlans` | 0 | 13 | 0 | `name` only — synthesised `VLAN-<id>` |
| `interfaces` | 0 | 13 | 0 | row count + `interface_type` / `lag_member_of` / `vrrp_groups` |
| `routing_instances` | 12 | 0 | 1 | — |
| `snmp` | 7 | 4 | 2 | `v3_users` (per-user engineID) |
| `static_routes` | 7 | 1 | 5 | `metric` |
| `vxlan_vnis` | 6 | 2 | 5 | `mcast_group` |
| `domain` | 2 | 0 | 11 | — |
| `ntp_servers` | 1 | 0 | 12 | — |
| `syslog_servers` | 1 | 0 | 12 | — |
| `lags` | 0 | 5 | 8 | `name` (`port-channel<N>` -> `ae<N>`) |
| `local_users` | 0 | 9 | 4 | whole record — every user dropped |
| `anycast_gateway_mac` | 0 | 7 | 6 | whole scalar — dropped to `""` |
| `dns_servers` | 0 | 0 | 13 | — |
| `timezone` | 0 | 0 | 13 | — |
| `dhcp_servers` | 0 | 0 | 13 | — |
| `radius_servers` | 0 | 0 | 13 | — |
| `evpn_type5_routes` | 0 | 0 | 13 | — |
| `raw_sections` | 0 | 0 | 13 | — |
| `apply_groups` | 0 | 0 | 13 | — |
| `group_content` | 0 | 0 | 13 | — |

## Sub-field drift aggregate — the authoritative list

Every sub-field NOT named here is preserved on every cell where its parent's
per-record drill-down exists, so declaring it `good` is safe; declaring one of
THESE `good` manufactures a false `CODEC_BUG`.

| sub-field | drifts on | direction |
|---|---|---|
| `interfaces` (whole list) | 11 cells | row count, e.g. `134 -> 9` |
| `interfaces[].interface_type` | 13 cells | `ianaift:ethernetCsmacd` -> `""` |
| `interfaces[].lag_member_of` | 1 cell (per-record) | `port-channel1` -> `ae1` |
| `interfaces[].vrrp_groups` | 1 cell (per-record) | one `mode="hsrp"` group -> `[]` |
| `vlans[].name` | 13 cells / 23 records | `""` -> `VLAN-<id>` |
| `lags[].name` | 5 cells | `port-channel<N>` -> `ae<N>` |
| `local_users` (whole list) | 9 cells | `all N local_users dropped` |
| `snmp.v3_users` | 4 cells | per-user `engine_id` -> `""` |
| `static_routes[].metric` | 1 cell | `200` -> `0` |
| `vxlan_vnis[].mcast_group` | 2 cells | `239.11.11.10` -> `""` |
| `anycast_gateway_mac` | 7 cells | populated MAC -> `""` |

## Notes grounding the dispositions

* **`local_users` — the pair's headline loss.** Not a nuance drop: the Junos
  render emits NO login user for an NX-OS source. NX-OS stores
  `username <name> password 5 $5$<salt>$<digest>` (SHA-256 crypt); Junos's
  accepted hash set is `{plaintext, junos:<crypt>, $6$ SHA-512, $1$ md5crypt}`
  (`netcanon/migration/_user_secrets.py::_TARGET_ACCEPTS["juniper_junos"]`), so
  every user fails the migratability gate in
  `codecs/juniper_junos/render.py`. The render deliberately `continue`s past
  the whole user rather than emitting a bare
  `set system login user <name> class <role>` line, because that form commits
  as a PASSWORDLESS account on Junos — strictly worse than the source. What
  the operator gets instead is a review comment naming the account. Measured:
  9 of 9 populated cells, every user, dropped. `unsupported`, not `lossy` —
  the record does not survive in any form.
* **`interfaces` row count** — 11 of 13 cells shrink (worst: `134 -> 9`). The
  cause is an artefact of the source capture, not lost configuration: an NX-OS
  `show running-config` materialises every chassis port plus the default
  `Vlan1` SVI at factory state, and the Junos render emits no `set interfaces`
  line for a record carrying no configuration, so those rows do not re-appear
  on re-parse. Counted across the corpus: **1001 rows dropped, 0 of which
  carried ANY configuration** (description, address, MTU, switchport mode,
  trunk list, LAG membership, VRF, or a non-default admin state). What is lost
  is the port INVENTORY, not operator intent.
* **`interfaces[].vrrp_groups`** — the cisco_nxos parser produces FHRP groups
  only from `hsrp <N>` blocks, so `mode` is always `"hsrp"` on this ordered
  pair. The Junos matrix declares
  `/interfaces/interface/vrrp-groups/group/mode` lossy ("a cross-family source
  mode (HSRP / CARP) is skipped on render"), and the observed effect is that
  the group vanishes entirely — the kitchen-sink `Vlan10` HSRP group renders
  to no VRRP stanza at all. Whole record gone, hence `unsupported` for this
  direction.
* **`lags[].name` / `interfaces[].lag_member_of`** — vendor-correct rename
  (`port-channel1` -> `ae1`), and `members` + `mode` round-trip intact on all
  5 cells that carry a bundle. The Phase-4 LAG-name equivalence
  (`_canonical_lag_name`) does NOT absorb it here: its table matches
  `Port-channel<N>` / `Po<N>`, not the lower-case `port-channel<N>` the NX-OS
  parser emits. Real drift at the string level, a rename at the semantic one.
* **`vlans[].name`** — always the same direction: an NX-OS VLAN declared with
  no `name` carries an empty canonical name; Junos keys VLANs BY name, so the
  render synthesises `VLAN-<id>` and that placeholder re-parses. Operator-named
  VLANs survive verbatim — on `busterswt_spine_leaf_xk32_1` only ids 1 and 999
  (both unnamed) gain a name while the named VLANs round-trip.
* **`snmp.v3_users`** — the USM user survives (name, group, auth protocol all
  round-trip); the per-user engineID drops, because Junos treats engineIDs as
  device-assigned and emits no per-user value (its matrix declares
  `/snmp/v3-user/engine-id` lossy). Auth/priv passphrases are excluded from the
  Phase-1 comparison by design (opaque per-vendor localized keys), so plan on
  re-keying v3 users regardless.
* **`anycast_gateway_mac`** — Junos declares `/anycast-gateway-mac`
  unsupported and models the equivalent per IRB unit
  (`set interfaces irb unit <vid> virtual-gateway-v4-mac`). The chassis-wide
  MAC an NX-OS fabric sets once with `fabric forwarding anycast-gateway-mac`
  drops to `""` on all 7 cells that populate it. Note the per-address anycast
  companions (`virtual_gateway_address` / `virtual_gateway_mac` on
  `CanonicalIPv4Address`) ARE declared supported by Junos and DO survive — the
  two surfaces are independent.
* **`domain` / `dns_servers` / `ntp_servers`** — the Junos matrix does not
  ENUMERATE `/system/domain`, `/system/dns-server` or `/system/ntp-server`.
  That is a matrix enumeration gap, not a declared unsupported: the render
  emits `set system domain-name` / `set system name-server` /
  `set system ntp server` and the parser reads all three back, and `domain`
  (2 cells) and `ntp_servers` (1 cell) are observed preserved through exactly
  that un-enumerated path. `dns_servers` is untested only because no fixture
  on this pair carries one.
* **`timezone`** — both matrices declare `/system/timezone` unsupported with
  the identical reason ("Render emits no clock/timezone stanza"), so this is a
  symmetric gap in the pair rather than a Junos limitation.
* **`dhcp_servers` / `radius_servers`** — the gap is SOURCE-side. The NX-OS
  matrix declares `/dhcp-servers/pool`, `/radius-servers/server/host` and
  `/radius-servers/server/key` unsupported, so the codec never populates
  either field (0 of 13 cells) and there is nothing for Junos to lose. Junos
  *can* render DHCP pools (`/dhcp-servers/pool` supported on its side), so
  closing the NX-OS parse side would move `dhcp_servers` off
  `not_applicable`. `radius_servers` compounds the `local_users` gap: with
  neither RADIUS nor local accounts arriving, the migrated config has no
  authentication source at all.
* **`evpn_type5_routes`** — not populated on this pair (0 of 13 cells). Both
  codecs model Type-5 IP-prefix advertisement as a VRF property via
  `CanonicalRoutingInstance.l3_vni` (both matrices declare
  `/evpn-type5-routes/route` lossy with that rationale), so the surface is
  carried under `routing_instances[].l3_vni` — preserved on all 6 cells that
  populate it — not here.
* **`raw_sections` / `apply_groups` / `group_content`** — untested on this
  pair. `raw_sections` is Tier 3 by design (vendor-private, never auto-rendered
  cross-vendor); `apply_groups` and `group_content` are Junos-native concepts
  populated on PARSE, so an NX-OS source never fills them.

## Reproducing the measurement

```
python tools/run_full_mesh.py            # writes tests/fixtures/real/_cross_mesh_runs/<ts>.json
python tools/run_phase4_reconciliation.py
```

Filter the mesh JSON's `cells` to
`source_codec == "cisco_nxos" and target_codec == "juniper_junos"` and read
each cell's `field_disposition` block; `preserved` / `trivially_preserved` /
`drift` on each field are the three columns of the table above.
