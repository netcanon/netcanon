# NX-OS -> MikroTik RouterOS: measured canonical surface

Source: `netcanon/migration/codecs/cisco_nxos/codec.py` and
`netcanon/migration/codecs/mikrotik_routeros/codec.py` (`CapabilityMatrix`),
joined against a full `tools/run_full_mesh.py` run over the committed corpus.
Retrieved: 2026-08-20

This is a **class-crossing** pair, not a like-for-like one. `cisco_nxos`
declares `device_classes = [switch, router]` and its fixtures are DC leaves and
spines (EVPN-VXLAN, VRFs, SVIs, HSRP, port-channels). `mikrotik_routeros`
models L2 as *bridge VLAN filtering* rather than switchport, has no VRF /
routing-instance construct, and does not model VXLAN. The realistic migration
is a small edge or branch box replacing a Nexus in a much simpler role — a lot
of fabric surface has nowhere to land.

13 fixture cells; **0 render errors, 0 re-parse errors**.

## Per-field measurement (13 cells)

| field | preserved | drifted | trivially empty | what drifts |
|---|---:|---:|---:|---|
| `hostname` | 13 | 0 | 0 | — |
| `domain` | 0 | 2 | 11 | whole value -> `''` |
| `dns_servers` | 0 | 0 | 13 | untested by the corpus |
| `ntp_servers` | 1 | 0 | 12 | — |
| `timezone` | 0 | 0 | 13 | untested by the corpus |
| `syslog_servers` | 0 | 1 | 12 | `all 1 syslog_servers dropped` |
| `interfaces` | 0 | 13 | 0 | record COUNT only — see below |
| `vlans` | 0 | 13 | 0 | `name`, `description`, `ipv4_addresses`, `untagged_ports`, `tagged_ports` |
| `static_routes` | 4 | 4 | 5 | `vrf` |
| `dhcp_servers` | 0 | 0 | 13 | source never populates |
| `snmp` | 0 | 11 | 2 | `v3_users` — the sole `value_drift_keys` entry on all 11 cells |
| `lags` | 5 | 0 | 8 | — |
| `local_users` | 0 | 9 | 4 | `hashed_password`, `role` |
| `radius_servers` | 0 | 0 | 13 | source never populates |
| `vxlan_vnis` | 0 | 8 | 5 | whole record — `all N vxlan_vnis dropped` |
| `evpn_type5_routes` | 0 | 0 | 13 | source never populates |
| `routing_instances` | 0 | 12 | 1 | whole record — `all N routing_instances dropped` |
| `raw_sections` | 0 | 0 | 13 | untested by the corpus |
| `apply_groups` | 0 | 0 | 13 | Junos-only; never populated |
| `group_content` | 0 | 0 | 13 | Junos-only; never populated |
| `anycast_gateway_mac` | 0 | 7 | 6 | whole value -> `''` |

Sub-field drift totals across all cells (per-record counts, not cell counts):
`vlans.name` 41, `vlans.ipv4_addresses` 14, `vlans.untagged_ports` 12,
`vlans.description` 9, `vlans.tagged_ports` 8, `local_users.hashed_password` 10,
`local_users.role` 10, `static_routes.vrf` 6. **No other sub-field of any of
those parents drifts on any cell.**

## Why `interfaces` drifts on all 13 cells

Phase 1 records a *count* drift, never a per-record diff:

```
count drift: 19 -> 20      count drift: 129 -> 131    count drift: 67 -> 114
count drift: 4  -> 7       count drift: 132 -> 133    count drift: 12 -> 15
```

Nothing is lost. A name-set diff of source vs re-parsed target on every cell
gives `lost: []` and `added: ['bridge1', 'vlan1', 'vlan10', 'vlan100', ...]`.
RouterOS's VLAN model *requires* a parent bridge, so the render synthesises
`bridge1` plus one `/interface vlan` per canonical VLAN; both re-parse as extra
`CanonicalInterface` records. The 67 -> 114 cell is simply a spine with 47
VLANs.

This has a consequence the YAML has to respect. Because the Phase-1 drift
summary for `interfaces` is a STRING rather than a per-record diff,
`run_phase4_reconciliation.actual_disposition` grades **every** `interfaces[].*`
sub-field as drifted — it will not claim a sub-field survived while records are
missing wholesale. A `good` disposition on any `interfaces[]` sub-field would
therefore manufacture a false `CODEC_BUG`. The YAML keeps the top-level
`interfaces` key and adds sub-field keys only for attributes an independent
name-matched probe confirms really do drop.

### Name-matched per-interface probe (1102 records over the 13 cells)

Byte-identical on **every** record: `name`, `default_name`, `description`,
`enabled`, `ipv6_addresses`, `lag_member_of`, `dhcp_client`, `dhcp_client_v6`,
`dot1q_vlan`, `voice_vlan`, `kind`, `tunnel_type`.

Differing:

| sub-field | records differing | what happens |
|---|---:|---|
| `interface_type` | 1065 / 1102 | `ianaift:ethernetCsmacd` -> `''`; RouterOS exposes no IANA ifType and re-infers it from the name prefix |
| `switchport_mode` | 29 | `trunk` / `access` -> `null` |
| `vrf` | 28 | `VRF_SERVICE_CUST_1` -> `''`; no VRF construct on the target |
| `access_vlan` | 13 | `10` -> `null` |
| `trunk_allowed_vlans` | 10 | `[10, 2000]` -> `[]` |
| `ipv4_addresses` | 9 | address kept; the anycast `virtual_gateway_address` companion is dropped |
| `trunk_native_vlan` | 4 | `999` -> `null` |
| `vrrp_groups` | 4 | `[{group_id: 10, mode: hsrp, ...}]` -> `[]` |
| `mtu` | 3 | SVI `9216` -> `null` |

## Notes grounding the dispositions

* **L2 membership disappears from both sides.** The port-side attributes
  (`switchport_mode`, `access_vlan`, `trunk_allowed_vlans`,
  `trunk_native_vlan`) and the VLAN-centric twin (`vlans[].tagged_ports`,
  `vlans[].untagged_ports`) all render empty, and the target matrix declares
  each of those six paths `unsupported` for the same reason: RouterOS carries
  membership in the bridge VLAN table, which this codec does not render. VLAN
  IDs survive and ports survive; the mapping between them does not.

* **VRF scoping collapses into the global table.** `routing_instances` drops
  wholesale on 12 of 13 cells, `interfaces[].vrf` blanks on 28 records, and
  `static_routes[].vrf` blanks on 6 — the route itself survives, in the
  *global* table. A `management`-VRF route silently becomes a global-table
  route.

* **`vrrp_groups` does not survive at all — it is not merely lossy here.**
  Rendering `batfish_nxos_hsrp_nxos1.txt` emits the `/interface vrrp` section
  header and then only
  `# review: vrrp_groups[10] on 'Vlan10' has mode='hsrp' which RouterOS does
  not natively support` — no `add` line. The SVI keeps its own address; the
  virtual gateway is gone.

* **`vlans[].name` is replaced, not just dropped.**
  `user_svi_1_vrf_service_cust_1` comes back as `Vlan10`: RouterOS stores a
  VLAN's name *as* the L3 interface name, so the re-parse recovers the
  interface name rather than the operator's descriptive name. On the same
  records `vlans[].description` moves the other way — source `''` re-parses as
  `IBGP connection`, the SVI description arriving through RouterOS's single
  per-VLAN `comment` field.

* **`vlans[].ipv4_addresses` empties but the address is not lost.** The SVI L3
  address is carried on the sibling `interfaces[]` record and survives there
  (only the anycast companion drops). It is the VLAN-record mount of the same
  address that does not round-trip.

* **`local_users`.** `hashed_password` is dropped deliberately, not by
  oversight: `mikrotik_routeros/render.py` gates password emission on
  `is_migratable(...)`, RouterOS accepts plaintext only, and emitting a foreign
  hash literal as `password=` would set the password *to the hash string*. An
  NX-OS `5 $5$<salt>$<digest>` therefore renders as a
  `# password manager ... -- review:` comment above a password-less
  `/user add`, and RouterOS `/export` omits hashes so the re-parse yields `''`.
  `role` collapses onto RouterOS's built-in group vocabulary
  (`network-admin` -> group `full` -> `admin`); `privilege_level` survives
  intact on all 9 populated cells, so the account keeps equivalent rights under
  a different name.

* **`snmp`.** On all 11 populated cells the Phase-1 dict diff is
  `{"only_in_source": [], "only_in_target": [], "value_drift_keys":
  ["v3_users"]}` — `community`, `location`, `contact` and `trap_hosts` are
  preserved verbatim. Inside `v3_users` the observed loss is the VACM `group`
  binding (`network-admin` -> `''`); the target matrix additionally declares
  auth/priv-algorithm substitution lossy, which this corpus does not exercise
  (every fixture user is `md5` with no privacy).

* **`lags` is `good`, and that is measured.** 5 populated cells, 0 drifted:
  name, members and mode all round-trip. The target matrix declares
  `/lags/lag/mode` lossy because RouterOS `mode=802.3ad` has no passive
  variant, but no NX-OS fixture carries a passive bundle, so declaring the
  field lossy would be an unevidenced claim.

* **`timezone` / `dns_servers`.** Untested by the corpus, so the disposition
  follows the matrices rather than a measurement: both codecs declare
  `/system/timezone` unsupported ("Render emits no clock/timezone stanza"),
  while both declare `/system/dns-server` supported.

* **`dhcp_servers` / `radius_servers` / `evpn_type5_routes`.** The gap is
  SOURCE-side — the cisco_nxos codec never populates them (0 of 13 cells), so
  there is nothing for the RouterOS target to lose. RouterOS itself renders
  DHCP pools and RADIUS servers, so closing the NX-OS parse side would move
  these off `not_applicable`.
