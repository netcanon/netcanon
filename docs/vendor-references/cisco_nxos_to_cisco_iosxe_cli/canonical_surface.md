# NX-OS -> Cisco IOS-XE (CLI): measured canonical surface

Source: `netcanon/migration/codecs/cisco_nxos/codec.py` and
`netcanon/migration/codecs/cisco_iosxe_cli/codec.py` (`CapabilityMatrix`),
joined against a full `tools/run_full_mesh.py` pass over the committed corpus
and re-read through `tools/run_phase4_reconciliation.py::actual_disposition`
(the same resolver the CI ratchet uses, so the sub-field counts below are the
ones the guard will see).
Retrieved: 2026-08-20

This is a Cisco-to-Cisco pair: a Nexus 9000 DC leaf re-homed onto a Catalyst
9000 / ISR running IOS-XE, captured as CLI text. 13 fixture cells;
**0 render errors, 0 re-parse errors**.

## Per-field measurement (13 cells)

| field | preserved | drifted | untested | what drifts |
|---|---:|---:|---:|---|
| `hostname` | 13 | 0 | 0 | — |
| `vlans` | 13 | 0 | 0 | — |
| `routing_instances` | 12 | 0 | 1 | — |
| `static_routes` | 8 | 0 | 5 | — |
| `vxlan_vnis` | 8 | 0 | 5 | — |
| `anycast_gateway_mac` | 7 | 0 | 6 | — |
| `domain` | 2 | 0 | 11 | — |
| `ntp_servers` | 1 | 0 | 12 | — |
| `syslog_servers` | 1 | 0 | 12 | — |
| `snmp` | 7 | 4 | 2 | `v3_users` only |
| `interfaces` | 1 | 12 | 0 | `interface_type`, `lag_member_of`, `vrrp_groups` |
| `lags` | 0 | 5 | 8 | `name` only (`members` / `mode` survive) |
| `local_users` | 0 | 9 | 4 | `role` only |

`dns_servers`, `timezone`, `dhcp_servers`, `radius_servers`,
`evpn_type5_routes`, `raw_sections`, `apply_groups` and `group_content` are
untested by the corpus — no fixture on this pair populates them on either
side, so every cell scores `trivially_preserved`.

## Sub-field drift (the authoritative view)

Resolved per sub-field key, across all 13 cells. Everything not listed here
preserved on every cell that carried data.

| key | preserved | drifted | untested |
|---|---:|---:|---:|
| `interfaces[].interface_type` | 1 | 12 | 0 |
| `interfaces[].lag_member_of` | 0 | 5 | 8 |
| `interfaces[].vrrp_groups` | 0 | 4 | 9 |
| `lags[].name` | 0 | 5 | 8 |
| `local_users[].role` | 0 | 9 | 4 |
| `snmp.v3_users` | 7 | 4 | 2 |

Preserved on every populated cell: `interfaces[].name` (13),
`interfaces[].ipv4_addresses` (13), `interfaces[].enabled` (13),
`interfaces[].dhcp_client` (13), `interfaces[].vrf` (12),
`interfaces[].description` (9), `interfaces[].access_vlan` (8),
`interfaces[].switchport_mode` (8), `interfaces[].mtu` (6),
`interfaces[].trunk_allowed_vlans` (4), `interfaces[].ipv6_addresses` (3),
`interfaces[].trunk_native_vlan` (2); `vlans[].id` (13),
`vlans[].untagged_ports` (8), `vlans[].ipv4_addresses` (6), `vlans[].name` (5),
`vlans[].tagged_ports` (4); `lags[].members` (5), `lags[].mode` (5);
`local_users[].name` / `[].hashed_password` / `[].privilege_level` (9 each);
`snmp.community` / `.location` / `.contact` / `.trap_hosts` (11 each);
`routing_instances[].name` / `[].instance_type` (12 each),
`[].route_distinguisher` / `[].rt_imports` / `[].rt_exports` / `[].l3_vni`
(6 each), `[].description` (1);
`vxlan_vnis[].vni` / `[].vlan_id` / `[].source_interface` / `[].udp_port`
(8 each), `[].mcast_group` (2);
`static_routes[].destination` / `[].gateway` (8 each), `[].vrf` (4),
`[].metric` (1).

## Notes grounding the dispositions

* **`interfaces[].vrrp_groups` — the record VANISHES.** On all 4 cells that
  carry a first-hop-redundancy group, the source holds one HSRP group on an
  SVI (`mode="hsrp"`, a virtual IP, a priority, `preempt`, and on two cells an
  authentication key) and the re-parsed target holds `[]`. The IOS-XE CLI
  matrix declares `/interfaces/interface/vrrp-groups/group/mode` lossy —
  "a cross-family source mode (HSRP / CARP) drops to a review comment on
  render" — and a review comment is not configuration, so nothing survives
  re-parse. This is `unsupported`, not `lossy`: the gateway redundancy, the
  virtual IP and the authentication key all leave the config together.
* **`interfaces[].interface_type`** — drifts on 12 of 13 cells, always on the
  management port: source `ianaift:ethernetCsmacd` on `mgmt0`, target
  `ianaift:other`. The IOS-XE CLI parser infers the IANA type from the name
  prefix (its matrix says so at `/interfaces/interface/config/type`) and
  `mgmt0` is not an IOS-XE name, so the type degrades. The interface itself,
  its addressing and its state survive.
* **`lags[].name` / `interfaces[].lag_member_of`** — the bundle survives:
  `lags[].members` and `lags[].mode` preserve on all 5 populated cells. What
  changes is the spelling — NX-OS writes `port-channel1`, IOS-XE re-parses
  `Port-channel1`. The reconciler's LAG-name canonicaliser
  (`_canonical_lag_name`) accepts `Po<N>` / `Port-channel<N>` /
  `Port-Channel<N>` but NOT the lower-case NX-OS form, so this surfaces as
  drift rather than collapsing to a vendor-correct rename.
* **`local_users[].role`** — NX-OS RBAC role names do not cross.
  `network-admin` re-parses as `admin` and `network-operator` as `operator`.
  The render deliberately suppresses the `role <name>` line
  (`render.py`: emitted only when the role is not `admin` / `operator`, and
  that branch is a `pass`), and `parse.py::_parse_local_users` re-derives the
  role from the privilege number (`admin` at privilege 15, else `operator`).
  The account, its privilege level and its password hash survive — the hash
  is Cisco-family on both ends, `5 $5$<salt>$<digest>` in, `secret 5
  $5$<salt>$<digest>` out — so only the role label is lost.
* **`snmp.v3_users`** — the sole SNMP attribute that drifts (4 of 11 populated
  cells; community, location, contact and trap hosts preserve on all 11). Two
  changes: the per-user engineID the NX-OS source carries is dropped (the
  IOS-XE CLI matrix declares `/snmp/v3-user/engine-id` lossy — engineIDs are
  device-assigned), and a user with no NX-OS group is placed in a synthesised
  `v3group` on render (`snmp-server user <name> {group or 'v3group'} v3`).
  The NX-OS matrix separately declares `/snmp/v3-user/auth-passphrase` and
  `/snmp/v3-user/priv-passphrase` lossy, so the USM key material never enters
  the canonical model in the first place.
* **`vlans`** — preserved on all 13 cells, including the L3 address carried on
  the VLAN record itself. This is the pair's clearest win over
  `cisco_nxos__arista_eos`, where the same SVI-on-VLAN shape drops. The
  IOS-XE CLI matrix declares `/vlans/vlan/description` and the VLAN-record
  anycast companions lossy, but no fixture on this pair populates them, so
  nothing drifts.
* **`vxlan_vnis`** — VNI, VLAN binding, VTEP source interface, UDP port and
  multicast group all preserve. The target matrix declares
  `/vxlan-vnis/udp-port` lossy (no `vxlan udp-port` override on render) and
  `/vxlan-vnis/flood-list` lossy, but every fixture uses the default 4789 and
  none carries a static flood list, so the declared losses are never reached.
* **`routing_instances`** — VRF name, RD, RT import/export, L3 VNI, the
  instance-type discriminator and even the VRF description all preserve. The
  target matrix declares `/routing-instances/instance` and
  `.../instance-type` lossy; the corpus does not exercise the shapes those
  declarations describe (no mac-vrf instances on this pair).
* **`dns_servers`** — untested and undeclared. The `cisco_iosxe_cli` matrix
  enumerates no `/system/dns-server` path, but `parse.py` and `render.py`
  both implement `ip name-server` end to end, and the two sibling scalars
  that are equally undeclared (`domain`, `ntp_servers`) measurably preserve
  on every cell that populates them. Recorded `good` on that basis.
* **`timezone`** — both matrices declare `/system/timezone` unsupported with
  the same reason ("Render emits no clock/timezone stanza"), so this is a
  target-side drop independent of fixture coverage.
* **`dhcp_servers` / `radius_servers`** — the gap is SOURCE-side: the NX-OS
  codec declares `/dhcp-servers/pool`, `/radius-servers/server/host` and
  `/radius-servers/server/key` unsupported and never populates them, so there
  is nothing for the IOS-XE target to lose.
