# NX-OS -> FortiGate CLI: measured canonical surface

Source: `netcanon/migration/codecs/cisco_nxos/codec.py` and
`netcanon/migration/codecs/fortigate_cli/codec.py` (`CapabilityMatrix`), joined
against a full in-process `tools/run_full_mesh.py` run over the committed
corpus.
Retrieved: 2026-08-20

`cisco_nxos` is a DC leaf/spine switch codec (`device_classes = [switch,
router]`); `fortigate_cli` is a stateful-firewall codec with an L3-only
interface model. That role mismatch — not a codec defect — is what most of the
loss below measures. 13 fixture cells; **0 render errors, 0 re-parse errors**.

## Per-field measurement (13 cells)

| field | preserved | drifted | untested | what drifts |
|---|---:|---:|---:|---|
| `hostname` | 13 | 0 | 0 | — |
| `domain` | 2 | 0 | 11 | — |
| `ntp_servers` | 1 | 0 | 12 | — |
| `lags` | 5 | 0 | 8 | — |
| `dns_servers` | 0 | 0 | 13 | — (no fixture populates it) |
| `timezone` | 0 | 0 | 13 | — (both matrices declare it unsupported) |
| `static_routes` | 4 | 4 | 5 | `vrf` |
| `syslog_servers` | 0 | 1 | 12 | whole record dropped |
| `anycast_gateway_mac` | 0 | 7 | 6 | whole scalar dropped |
| `vxlan_vnis` | 0 | 8 | 5 | whole record dropped |
| `local_users` | 0 | 9 | 4 | `hashed_password`, `role` |
| `snmp` | 0 | 11 | 2 | `v3_users` |
| `routing_instances` | 0 | 12 | 1 | whole record dropped |
| `interfaces` | 0 | 13 | 0 | `vrf`, `switchport_mode`, `access_vlan`, `trunk_allowed_vlans`, `ipv4_addresses`, `vrrp_groups` + list-count growth |
| `vlans` | 0 | 13 | 0 | `name`, `ipv4_addresses`, `untagged_ports`, `tagged_ports` |

`dhcp_servers`, `radius_servers`, `evpn_type5_routes`, `raw_sections`,
`apply_groups` and `group_content` are untested by the corpus — the NX-OS
source never populates them on any of the 13 cells.

## Drifting sub-fields (the authoritative aggregate)

Only the sub-fields listed here drift anywhere in the pair. Every other
sub-field of the same parent is preserved on every cell that exercises it, so
`good` is the measured disposition for those.

| parent | sub-field | drifting record-occurrences |
|---|---|---:|
| `interfaces` | `vrf` | 18 |
| `interfaces` | `switchport_mode` | 17 |
| `interfaces` | `access_vlan` | 8 |
| `interfaces` | `trunk_allowed_vlans` | 6 |
| `interfaces` | `ipv4_addresses` | 5 |
| `interfaces` | `vrrp_groups` | 2 |
| `vlans` | `name` | 41 |
| `vlans` | `ipv4_addresses` | 14 |
| `vlans` | `untagged_ports` | 12 |
| `vlans` | `tagged_ports` | 8 |
| `local_users` | `hashed_password` | 10 |
| `local_users` | `role` | 9 |
| `static_routes` | `vrf` | 6 |
| `snmp` | `v3_users` | 11 cells |

## Notes grounding the dispositions

* **Anycast-gateway SVI addressing is the worst loss.** An NX-OS SVI whose
  address carries a distributed-anycast companion (`virtual_gateway_address`
  populated, i.e. `fabric forwarding mode anycast-gateway`) renders on
  FortiOS with **no `set ip` line at all** — the address is gone from both the
  interface mount and the VLAN mount. Measured on
  `akarneliuk_evpn_vxlan_mcast_leaf_c1l1_nxos939` (`Vlan10` / `Vlan20` /
  `Vlan30`) and `networklessons_clab_dag_symmetric_irb_leaf1_nxos1027`
  (`Vlan10` / `Vlan20`): the rendered stanza is `edit "Vlan10" / set type vlan
  / set vlanid 10 / set interface "Ethernet1/2" / set status up`, and nothing
  else. A plain (non-anycast) SVI keeps its address —
  `batfish_nxos_hsrp_nxos1` renders `set ip 10.10.10.1 255.255.255.0` — so
  this is specific to the anycast shape, not to SVIs in general.
* **`vlans[].ipv4_addresses` is a mount change, not always a data loss.** The
  FortiGate codec always re-parses SVI addressing onto the interface record
  (the `Vlan<id>` / `vlan<id>` child interface), never back onto the
  `CanonicalVlan`, so the VLAN-mounted copy re-parses empty on every cell that
  carries one. For a plain SVI the address itself still survives on the
  interface mount; for an anycast SVI it is lost on both (see above).
* **VLAN port membership does not survive.** FortiOS binds a VLAN to exactly
  one parent via `set interface "<parent>"`, so the canonical
  `tagged_ports` / `untagged_ports` lists have nowhere to go and re-parse
  empty. The parent the render picks is inferred and is not always a real
  trunk — `batfish_nxos_hsrp_nxos1` binds `Vlan10` and `Vlan2000` to
  `loopback123`, while `busterswt_spine_leaf_xk32_1_nxos9312` binds `vlan999`
  to `port-channel10`.
* **`vlans[].name` is replaced, not carried.** The FortiOS VLAN child
  interface's edit key becomes the canonical VLAN name on re-parse, so
  `user_svi_1_vrf_service_cust_1` comes back as `Vlan10` and an unnamed VLAN
  comes back as `vlan1`. Every operator-authored VLAN name is lost.
* **The interface list GROWS, it does not shrink.** Seven cells show a
  list-count drift (e.g. 129 -> 130, 67 -> 113) and it is always the target
  gaining rows: the render materialises a `vlan<id>` child interface for each
  canonical VLAN that has no matching SVI in the source. No source interface
  is ever dropped. Because Phase 1 encodes a list-count drift as a summary
  string rather than a per-record diff, Phase 4 marks *every* `interfaces[]`
  sub-field as drifted on those cells and collapses all but the first to
  `STRUCTURAL_ONLY`; the expectation YAML therefore lists the drifting
  interface sub-fields before the preserved ones so the structural signal is
  claimed by a key that genuinely declares a loss.
* **`local_users[].hashed_password` never survives.** The render emits no
  password line at all, only a review comment
  (`# password manager user-name "admin" -- review: 5 hash from source vendor
  cannot be re-used on FortiOS; reset this user password manually`). Shape of
  the loss: `5 $5$<salt>$<digest>` -> `""`. Every migrated admin account lands
  on the FortiGate with no credential.
* **`local_users[].role` is remapped, and only partly.** `network-admin`
  becomes the FortiOS built-in accprofile `super_admin`; a role with no
  mapping is passed through verbatim (`network-operator` -> `network-operator`
  on the kitchen-sink fixture), which is not a FortiOS built-in accprofile.
  `privilege_level` round-trips unchanged.
* **`snmp.v3_users` survives with the VACM group dropped.** Measured on the
  kitchen-sink cell: `name`, `auth_protocol` and `priv_protocol` round-trip;
  `group` goes `network-admin` -> `""`; the passphrase blob is re-tagged
  `0x<localized-key>` -> `ENC 0x<localized-key>`. The passphrase re-tag is
  blanked by the comparator's cosmetic-hash rule, so the measured drift is the
  group. v1/v2c (`community` / `location` / `contact` / `trap_hosts`) is
  preserved on every cell.
* **`interfaces[].vrrp_groups` does not survive.** The NX-OS corpus only ever
  carries `mode="hsrp"` groups. The render emits an empty `config vrrp` block
  plus `# review: vrrp_groups[10] mode='hsrp' has no FortiOS equivalent —
  VRRP is the only L3 redundancy protocol on FortiOS`, so the group re-parses
  as an empty list.
* **Whole-record drops.** `vxlan_vnis`, `routing_instances`, `syslog_servers`
  and `anycast_gateway_mac` all go to zero records / empty on every cell that
  populates them, matching the fortigate_cli matrix's `unsupported`
  declarations (`/vxlan-vnis/vni` "VXLAN not modelled — FortiGate is a
  firewall codec"; `/routing-instances/instance` "Render emits no
  VRF/routing-instance construct (VDOMs not modelled)";
  `/system/syslog-server`; `/anycast-gateway-mac`).
* **`lags` round-trips intact.** Name, members and LACP mode all survive
  verbatim (`port-channel1` with members `Ethernet1/5` / `Ethernet1/6`, mode
  `active`) on all 5 cells that populate LAGs — no rename mesh needed on this
  direction, because the FortiGate codec carries the source-native bundle name
  through.
* **`interfaces[].trunk_native_vlan`** has data on only two cells
  (`busterswt_spine_leaf_xk32_1_nxos9312`, `kitchen_sink`) and both are
  list-count-drift cells, so the corpus never isolates its behaviour. It is
  declared `unsupported` on the fortigate_cli matrix's own account
  ("FortiOS has no native-VLAN on a routed port"), not on measurement.
  `voice_vlan` and `dot1q_vlan` are declared unsupported by the same matrix
  and are never populated by the NX-OS source at all.
* **`timezone` / `dns_servers`** are untested by the corpus.
  `/system/timezone` is declared unsupported on BOTH matrices with the same
  reason ("Render emits no clock/timezone stanza"), so it is a target-side
  drop regardless. `/system/dns-server` is declared supported on both, so
  `good` rests on the declarations rather than an observed round-trip.
