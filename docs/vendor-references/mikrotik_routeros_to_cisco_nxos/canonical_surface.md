# RouterOS -> NX-OS: measured canonical surface

Source: `netcanon/migration/codecs/mikrotik_routeros/codec.py` and
`netcanon/migration/codecs/cisco_nxos/codec.py` (`CapabilityMatrix`), joined
against a full `tools/run_full_mesh.py` pass over the committed corpus.
Retrieved: 2026-08-20

This is a class-crossing pair: `mikrotik_routeros` is an SMB / WISP / branch
router-and-bridge codec, `cisco_nxos` is a DC leaf/spine switch codec. The
realistic migration is a RouterOS edge or lab box being replaced by a Nexus.
The shared surface is therefore narrow — L3 addressing, VLANs, static routes,
SNMP, LAG bundles — and the two ends of the canonical model that each vendor
owns exclusively (RouterOS DHCP/AAA services; NX-OS EVPN-VXLAN fabric) are
empty or dropped in this direction.

**5 fixture cells; 0 render errors, 0 re-parse errors.**

## Per-field measurement (5 cells)

| field | preserved | drifted | trivially empty | what drifts |
|---|---:|---:|---:|---|
| `hostname` | 2 | 3 | 0 | empty source identity -> literal `switch` |
| `domain` | 0 | 0 | 5 | — (source never populates) |
| `dns_servers` | 1 | 0 | 4 | — |
| `ntp_servers` | 3 | 0 | 2 | — |
| `timezone` | 0 | 0 | 5 | — (both matrices declare it unsupported) |
| `syslog_servers` | 0 | 0 | 5 | — (source never populates) |
| `interfaces` | 0 | 5 | 0 | `interface_type`, `default_name`, `lag_member_of` |
| `vlans` | 1 | 2 | 2 | `description`, `ipv4_addresses` |
| `static_routes` | 0 | 1 | 4 | `description`, `gateway`, `interface` |
| `dhcp_servers` | 0 | 3 | 2 | whole record — "all N dhcp_servers dropped" |
| `snmp` | 1 | 2 | 2 | `v3_users` |
| `lags` | 0 | 1 | 4 | `name` |
| `local_users` | 0 | 1 | 4 | whole record — "all 3 local_users dropped" |
| `radius_servers` | 0 | 1 | 4 | whole record — "all 2 radius_servers dropped" |
| `vxlan_vnis` | 0 | 0 | 5 | — (source never populates) |
| `evpn_type5_routes` | 0 | 0 | 5 | — (source never populates) |
| `routing_instances` | 0 | 0 | 5 | — (source never populates) |
| `raw_sections` | 0 | 0 | 5 | — (empty on both sides on every cell) |
| `apply_groups` | 0 | 0 | 5 | — (Junos-only) |
| `group_content` | 0 | 0 | 5 | — (Junos-only) |
| `anycast_gateway_mac` | 0 | 0 | 5 | — (source never populates) |

## Sub-field drift aggregate (across ALL cells)

Only the sub-fields below drift. Every other sub-field of the same parent is
preserved on every cell, which is what makes a `good` disposition safe for
them and what makes a `good` disposition on one of these a manufactured
`CODEC_BUG`. Counts are per-record drift occurrences, not per-cell.

| sub-field | occurrences | observed shape |
|---|---:|---|
| `interfaces[].interface_type` | 43 | `""` -> `ianaift:other` |
| `interfaces[].default_name` | 27 | `ether2` -> `""` |
| `interfaces[].lag_member_of` | 4 | `bond1` -> `port-channel1` |
| `vlans[].description` | 8 | `User` -> `""` |
| `vlans[].ipv4_addresses` | 2 | `[]` -> `[{ip: 10.100.0.1/24, ...}]` |
| `static_routes[].description` | 4 | `Default route to ISP` -> `""` |
| `static_routes[].gateway` | 1 | `bridge1` -> `""` |
| `static_routes[].interface` | 1 | `""` -> `bridge1` |
| `lags[].name` | 2 | `bond1` -> `port-channel1` |
| `snmp.v3_users` | 2 cells | sole entry in Phase-1 `value_drift_keys` |
| `hostname` (whole) | 3 cells | `""` -> `switch` |
| `dhcp_servers` (whole) | 3 cells | all pools dropped |
| `local_users` (whole) | 1 cell | all users dropped |
| `radius_servers` (whole) | 1 cell | all servers dropped |

## Mechanism notes grounding the dispositions

* **`local_users` — the headline loss.** RouterOS `/export` never surfaces
  `/user` password material, so `CanonicalLocalUser.hashed_password` arrives
  empty. `cisco_nxos/render.py` then takes the no-password branch
  (`if not user.hashed_password: return f"username {name} role {role}"`), and
  the NX-OS parser's `_USERNAME_RE`
  (`^username\s+(\S+)\s+password\s+(\d+)\s+(\S+)\s+role\s+(\S+)`) requires the
  `password <type> <hash>` clause, so the emitted line is not recovered. Every
  local account disappears across the round trip. Combined with
  `radius_servers` (below) the migrated device is left with no local and no
  remote authentication source.
* **`radius_servers`.** The NX-OS matrix declares `/radius-servers/server/host`
  and `/radius-servers/server/key` unsupported — "Render emits no AAA
  radius-server config". The RouterOS `/radius` entries are parsed, carried
  canonically, and then dropped whole on render.
* **`dhcp_servers`.** The NX-OS matrix declares `/dhcp-servers/pool`
  unsupported — "Render emits no DHCP server pool". RouterOS is very often the
  DHCP server for the subnets it routes (`/ip pool` + `/ip dhcp-server network`
  + `/ip dhcp-server` join to one `CanonicalDHCPPool` per network); none of it
  reaches the Nexus.
* **`hostname`.** `cisco_nxos/render.py` uses `tree.hostname or "switch"`, so a
  capture with no `/system identity` comes back named `switch` rather than
  un-named. When the source does carry an identity it round-trips verbatim
  (2 of 5 cells).
* **`interfaces[].interface_type`.** NX-OS infers the IANA ifType from the name
  prefix (`Ethernet` -> `ethernetCsmacd`, `Vlan` -> `l3ipvlan`, `port-channel`
  -> `ieee8023adLag`, ...). This path carries RouterOS-native names verbatim —
  port renaming belongs to the orchestrator's rename layer, not the audit — so
  `ether2` / `bridge1` match no prefix and re-parse as `ianaift:other`.
* **`interfaces[].default_name`.** RouterOS's factory port binding
  (`default-name=ether2`, distinct from an operator-renamed `name=`) has no
  NX-OS grammar and is dropped.
* **`lags[].name` / `interfaces[].lag_member_of`.** The bundle itself survives:
  members and LACP mode are preserved, and only the operator-facing token is
  re-spelled `bond1` -> `port-channel1` (NX-OS renders and re-parses the
  lowercase `port-channel<N>` form, `cisco_nxos/parse.py`). Note the
  reconciler's LAG-name equivalence (`_canonical_lag_name`, accepting
  `ae|Po|Port-channel|Port-Channel|trk|Trk|agg|bond`) does NOT collapse this
  pair, because NX-OS's lowercase `port-channel` is outside that regex — so the
  rename surfaces as real drift on this pair and the honest disposition is
  `lossy`, not `good`.
* **`vlans[].ipv4_addresses`.** The drift direction is a re-mount, not a loss:
  the source VLAN record carries no L3 address (RouterOS holds SVI addressing
  on `/interface vlan` + `/ip address`, which canonicalises onto the interface
  record) while the NX-OS render emits `interface Vlan<N>` and its re-parse
  folds the address back onto the VLAN record too.
  `interfaces[].ipv4_addresses` is preserved on every cell, so nothing is
  dropped — the mount point changes.
* **`static_routes[].gateway` / `[].interface`.** Also a re-mount: RouterOS's
  interface-as-gateway form (`gateway=bridge1`) lands in
  `CanonicalStaticRoute.gateway`, and the NX-OS render/re-parse pair moves the
  same token into `.interface`. The route survives; the slot changes.
* **`static_routes[].description`.** The NX-OS matrix is explicit — "Render
  emits destination + next-hop + metric only; the static-route name /
  description is dropped".
* **`vlans[].description`.** The NX-OS matrix is explicit — render emits the
  VLAN name but no separate description line.
* **`snmp.v3_users`.** The sole value-drift key on the two cells where `snmp`
  drifts; `community` / `location` / `contact` / `trap_hosts` are equal on both
  sides everywhere. The NX-OS matrix declares the v3 auth passphrase, priv
  passphrase and engine-id lossy: NX-OS normalises USM key material to the
  older `localizedkey` digest form and spells engineID colon-decimal
  (`128:0:0:9:...`) where other vendors use hex. v1/v2c is unaffected.
* **`raw_sections`.** Empty on both sides on all 5 cells. The
  `mikrotik_routeros` codec routes RouterOS-only Tier-3 grammar (firewall, NAT,
  queues, wireless, hotspot, scripts, IPsec, PPP) to
  `intent.dropped_tier3_sections` via `detect_tier3_sections_routeros`, not to
  `raw_sections`, so nothing travels through this field on this pair. That
  Tier-3 material is still lost on migration — it is simply not measured here.
* **Source-side structural absence.** The `mikrotik_routeros` matrix declares
  `/system/domain`, `/system/syslog-server`, `/system/timezone`, the
  per-interface switchport family (`switchport-mode`, `access-vlan`,
  `dot1q-vlan`, `trunk-allowed-vlans`, `trunk-native-vlan`, `voice-vlan`),
  `/vlans/vlan/tagged-ports`, `/vlans/vlan/untagged-ports`,
  `/routing/static-route/vrf`, `/routing-instances/instance`, the
  `/vxlan-vnis/*` family and `/anycast-gateway-mac` unsupported. Those fields
  are empty after every RouterOS parse, which is why the measurement shows them
  trivially empty rather than drifted, and why they are `not_applicable` rather
  than a target-side gap.
* **`timezone` is the exception in that list.** The NX-OS matrix ALSO declares
  `/system/timezone` unsupported — "Render emits no clock/timezone stanza;
  intent.timezone is dropped on migration" — so even after the RouterOS parse
  side is wired up the value would not survive. Recorded as `unsupported`
  (target-side hard drop) rather than `not_applicable`.
