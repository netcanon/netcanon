# Juniper Junos -> Cisco NX-OS: measured canonical surface

Source: `netcanon/migration/codecs/juniper_junos/codec.py` and
`netcanon/migration/codecs/cisco_nxos/codec.py` (`CapabilityMatrix`), joined
against a full in-process `tools/run_full_mesh.py` run over the committed
corpus, filtered to the ordered pair `juniper_junos -> cisco_nxos`.
Retrieved: 2026-08-20

Both codecs are switch-primary (`juniper_junos` = switch/router/firewall,
`cisco_nxos` = switch/router), so the shared surface is wide: L2/L3
interfaces, VLANs + IRB/SVI addressing, VXLAN-EVPN, VRFs with L3 VNIs, LAGs,
SNMP, static routes. **11 fixture cells; 0 render errors, 0 re-parse errors.**

Fixtures: `batfish_evpntype5_router1_junos2541`, `batfish_l3vpn_pe1_junos2541`,
`buraglio_netlab_junos184`, `jnprautomate_mnha_vsrx_a_junos`,
`ksator_labmgmt_ex4550_junos151`, `ksator_labmgmt_qfx10k2_junos173`,
`ksator_labmgmt_qfx5100_junos173`, `ksator_labmgmt_qfx5110_junos173`,
`saidvandeklundert_snmpv3_junos172`, `tsg8139_evpn_leaf_dhcpv6_junos232`,
`kitchen_sink` (synthetic).

## Top-level field measurement (11 cells)

`untested` = both sides carry no data on the field (Phase 1
`trivially_preserved`), so the round-trip was never exercised.

| field | preserved | drifted | untested |
|---|---:|---:|---:|
| `hostname` | 10 | 1 | 0 |
| `domain` | 2 | 0 | 9 |
| `dns_servers` | 6 | 0 | 5 |
| `ntp_servers` | 6 | 0 | 5 |
| `timezone` | 0 | 0 | 11 |
| `syslog_servers` | 6 | 0 | 5 |
| `interfaces` | 0 | 11 | 0 |
| `vlans` | 6 | 1 | 4 |
| `static_routes` | 9 | 0 | 2 |
| `dhcp_servers` | 0 | 2 | 9 |
| `snmp` | 6 | 0 | 5 |
| `lags` | 0 | 5 | 6 |
| `local_users` | 0 | 8 | 3 |
| `radius_servers` | 0 | 0 | 11 |
| `vxlan_vnis` | 3 | 0 | 8 |
| `evpn_type5_routes` | 0 | 0 | 11 |
| `routing_instances` | 3 | 3 | 5 |
| `raw_sections` | 0 | 0 | 11 |
| `apply_groups` | 0 | 6 | 5 |
| `group_content` | 0 | 6 | 5 |
| `anycast_gateway_mac` | 0 | 0 | 11 |

## Sub-field measurement — the authoritative layer

The four list parents whose top-level row shows drift (`interfaces`, `vlans`,
`lags`, `routing_instances`) keep a STABLE row set on every cell: the identity
sub-fields (`interfaces[].name`, `vlans[].id`, `lags[].members`,
`routing_instances[].name`) never drift, so no interface, VLAN, bundle or VRF
disappears. All of their drift is attribute-level, which is why the pair YAML
declares those parents at the sub-field level and omits the top-level key.
`local_users` is the one exception — see below.

**Sub-fields that DRIFT** (everything else on the same parent is preserved on
every cell):

| sub-field | pres | drift | untested | what changes |
|---|---:|---:|---:|---|
| `interfaces[].interface_type` | 0 | 11 | 0 | `ianaift:ethernetCsmacd` -> `ianaift:other` |
| `interfaces[].ipv4_addresses` | 8 | 2 | 1 | `virtual_gateway_address` / `-mac` blanked; the IP survives |
| `interfaces[].ipv6_addresses` | 5 | 1 | 5 | same: v6 anycast companions blanked |
| `interfaces[].trunk_allowed_vlans` | 4 | 2 | 5 | list re-ordered ascending; SET identical |
| `interfaces[].lag_member_of` | 0 | 5 | 6 | `ae1` -> `port-channel1` |
| `interfaces[].tunnel_type` | 0 | 1 | 10 | `ipsec` -> `""` (vSRX `st0` units) |
| `interfaces[].dhcp_client_v6` | 0 | 1 | 10 | `dhcp6` -> `""` (`fxp0`) |
| `vlans[].ipv4_addresses` | 0 | 1 | 10 | SVI-on-VLAN address list -> `[]` |
| `lags[].name` | 0 | 5 | 6 | `ae0/ae1/ae2` -> `port-channel0/1/2` |
| `local_users[].privilege_level` | 0 | 8 | 3 | `15` -> `1` |
| `routing_instances[].instance_type` | 3 | 3 | 5 | `virtual-router` -> `vrf` |

**Sub-fields the SOURCE never populates** (Junos parser writes no value, so
the pair YAML calls them `not_applicable` rather than blaming the target):
`static_routes[].metric` / `.interface` / `.description` (the Junos parser
builds `CanonicalStaticRoute(destination, gateway, interface="", vrf)` and
nothing else), `vlans[].description` (it builds `CanonicalVlan(id, name)`),
`vxlan_vnis[].mcast_group` / `.flood_list` (absent from the codec entirely),
`radius_servers` (`set system radius-server` is parse-and-ignore),
`anycast_gateway_mac` (Junos models the equivalent per IRB unit).

## Notes grounding the dispositions

* **`interfaces[].ipv4_addresses` / `ipv6_addresses` — the headline loss.**
  Drift is confined to the anycast companions. On
  `ksator_labmgmt_qfx10k2_junos173` five IRB units carry
  `ip=10.22N.0.5/16` + `virtual_gateway_address=10.22N.0.1` +
  `virtual_gateway_mac`; the target returns the same IP and prefix with both
  companions empty. Same shape on `batfish_evpntype5_router1_junos2541`
  (four `irb.N` units, VGA `172.16.N.100`). NX-OS models IPv4 distributed
  anycast gateway ONLY as `fabric forwarding mode anycast-gateway`, where the
  virtual IP *equals* the SVI's own primary address; a Junos
  `virtual-gateway-address` that DIFFERS from the unit address has no NX-OS
  equivalent. Its matrix declares
  `/interfaces/interface/ipv4/address/virtual-gateway-address` lossy and
  `/interfaces/interface/ipv6/address/virtual-gateway-address` unsupported.
* **`interfaces[].trunk_allowed_vlans` — ordering only.** On
  `ksator_labmgmt_qfx5100_junos173` `xe-0/0/2` goes
  `[3006..3010, 2030, 2031, 2050, 2051]` -> `[2030, 2031, 2050, 2051,
  3006..3010]`; on `saidvandeklundert_snmpv3_junos172` the 85-VLAN list on
  `ae1`..`ae202` comes back identical but sorted. No VLAN is added or removed
  on any record.
* **`local_users` — the one parent kept at top level.** `kitchen_sink` loses a
  whole record (3 -> 2): the Junos `readonly` user has no password, the NX-OS
  render emits `username readonly role read-only`, and the NX-OS parser skips
  a `username` line carrying no password, so the account never re-appears.
  Separately, `privilege_level` drops `15 -> 1` on all 8 populated cells —
  the NX-OS codec maps `network-admin` / `vdc-admin` to 15 and everything else
  to 1, and Junos classes (`super-user`) are neither.
* **`local_users[].hashed_password` — preserved, but read the shape.** The
  string round-trips verbatim, because the NX-OS render emits it as
  `username <name> password 0 junos:$6$<salt>$<digest>` and type-`0` is the
  NX-OS *cleartext* marker, which the parser strips again on re-parse. The
  canonical value survives; what would land on a real Nexus is a cleartext
  password equal to the Junos hash string.
* **`hostname`.** One cell drifts, and it is an ADDITION:
  `tsg8139_evpn_leaf_dhcpv6_junos232` sets no `system host-name`, and the
  NX-OS render opens with `hostname switch` + `vdc switch id 1` because its
  VDC scaffold needs a name.
* **`apply_groups` / `group_content`.** Populated on 6 cells and dropped
  wholesale ("all N apply_groups dropped"). The Junos parser applies group
  CONTENT into the canonical tree first (two-pass parse) and keeps the group
  names + bodies alongside as provenance, so the inherited VALUES do arrive
  flattened; the inheritance STRUCTURE does not. NX-OS has no configuration-
  inheritance grammar and both matrices declare zero support.
* **`snmp.v3_users` — preserved, including on the SNMPv3 fixture.** Note the
  mesh blanks `auth_passphrase` / `priv_passphrase` before comparing (they are
  opaque per-vendor localized digests), so "preserved" covers user name,
  group, protocols and engineID, not the keys.
* **`vxlan_vnis[].vni` / `.udp_port` — preserved, with untested edges.** The
  NX-OS matrix declares both lossy (per-VNI `suppress-arp` /
  `ingress-replication` sub-flags; a non-default `vxlan udp-port` override).
  Neither edge is exercised: all three populated cells use the IANA default
  4789 and carry no per-VNI sub-flags, and the round-trip preserves them.
* **`routing_instances[].instance_type`.** Junos `virtual-router` (a routing
  instance with no RD/RT) has no NX-OS form; `vrf context <name>` is the only
  shape the render emits, so the discriminator downgrades to `vrf` on 3 cells.
  Instances that were already `vrf` round-trip untouched, and RD, RT imports,
  RT exports, description and `l3_vni` are preserved everywhere.
* **`dhcp_servers`.** The Junos source DOES populate pools (4 on
  `jnprautomate_mnha_vsrx_a_junos`, 1 on `kitchen_sink`) and the NX-OS matrix
  declares `/dhcp-servers/pool` unsupported — "Render emits no DHCP server
  pool" — so the whole record vanishes. Unsupported, not lossy.
* **`timezone`.** Both matrices declare `/system/timezone` unsupported with
  the identical reason, so it is a symmetric gap in the pair; no fixture
  populates it.
