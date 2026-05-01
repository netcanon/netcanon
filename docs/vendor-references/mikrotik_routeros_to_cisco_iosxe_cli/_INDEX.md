# MikroTik RouterOS to Cisco IOS-XE CLI — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/mikrotik_routeros__cisco_iosxe_cli.yaml`
per-field expectations.  See sibling
`tests/fixtures/cross_vendor_expectations/README.md` for the
canonical schema definition.

This is the **inverse** of `cisco_iosxe_cli_to_mikrotik_routeros/`.
Wire-format mismatch matters more than syntax similarity — RouterOS
`/export` form has no structural overlap with Cisco IOS-XE stanza
configuration.  RouterOS-side richness in firewall, queues,
wireless, scripting falls outside the canonical scope and lands in
`raw_sections` for operator review.

| Topic | Summary |
|---|---|
| `system_services.md` | Hostname / DNS / NTP / timezone / syslog.  RouterOS `/system clock set time-zone-name=America/Los_Angeles` (TZ database) versus Cisco `clock timezone PST -8 0` (offset+name).  RouterOS source rarely populates `domain`. |
| `interface_naming.md` | RouterOS's flat `etherN` / operator-renamed `WAN uplink` versus Cisco's hardware-fixed `GigabitEthernet0/0/1`.  Operator-form name lands in Cisco `description` field. |
| `ip_addressing.md` | RouterOS `/ip address add address=X/N interface=etherN` (CIDR) versus Cisco `ip address X.X.X.X MASK` (dotted-mask).  Multi-address per interface -> primary + secondary on Cisco. |
| `vlans.md` | RouterOS two-plane model versus Cisco interface-centric switchport.  Plane 1 -> Cisco sub-interfaces or SVIs; Plane 2 -> Cisco access/trunk. |
| `switching_model.md` | Philosophy difference — RouterOS router-first, Cisco port-mode-discriminated.  Tier-3 RouterOS surfaces (firewall, queues, wireless, scripts) noted for operator review. |
| `static_routes.md` | RouterOS `/ip route add dst-address=X/N gateway=Y` versus Cisco `ip route DEST MASK GW`.  RouterOS `blackhole=yes` -> Cisco `Null0` next-hop.  Per-VRF (`routing-table=`) deferred. |
| `dhcp_server.md` | RouterOS three-section split versus Cisco bundled `ip dhcp pool`.  Static reservations / multi-range pools lossy. |
| `snmp.md` | RouterOS `/snmp community` (overloaded for v1/v2c + v3) versus Cisco `snmp-server community` + `snmp-server user`.  Single-target trap collapses cleanly to one Cisco `snmp-server host`.  USM passphrases re-key required. |
| `local_users.md` | RouterOS `/user add name=X group=full password=...` (export hides hash) versus Cisco `username X privilege Y secret 9 $9$...`.  Password export gap means Cisco render emits no `secret` line — operator must re-enter. |
| `radius_aaa.md` | RouterOS `/radius` (service-binding) versus Cisco `radius server` + `aaa group server` + method-list.  Shared-secret encoding pass-through. |
| `lags.md` | RouterOS `/interface bonding` modes — only `802.3ad` round-trips cleanly to Cisco LACP.  Active-backup / balance-* modes have no Cisco equivalent. |
| `routing_instances_vrf.md` | RouterOS `/ip vrf` versus Cisco `vrf definition`.  Both codecs parse-and-ignore VRF declarations in v1 — whole surface unsupported. |

Retrieved over 2026-04-30.

See also:
- `../README.md` (citation cache layout)
- `../cisco_iosxe_cli_to_mikrotik_routeros/_INDEX.md` (the inverse pair)
