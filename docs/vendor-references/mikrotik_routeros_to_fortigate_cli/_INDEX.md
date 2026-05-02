# MikroTik RouterOS to FortiGate FortiOS CLI — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/mikrotik_routeros__fortigate_cli.yaml`
per-field expectations.  See sibling
[`README.md`](../../../tests/fixtures/cross_vendor_expectations/README.md)
for the canonical schema definition.

This pair is a **SMB / WISP router → firewall** migration.  MikroTik RouterOS is a router-first SMB / WISP platform with bridge-based switching as a sub-feature; FortiGate is a session-based stateful firewall with rich UTM and limited L2 switching.  Both are "router-class" but with different feature focus.  The wire formats (RouterOS `/section / add / set` /export grammar versus FortiOS `config / edit / set / next / end` 5-keyword grammar) differ enough that even concepts both vendors model end up lossy on the cross-pair.

| Topic | Summary |
|---|---|
| [`system_services.md`](system_services.md) | Hostname / DNS / NTP / timezone / syslog — RouterOS `/system identity` + `/system clock` + `/ip dns` + `/system ntp client` versus FortiOS `config system <topic>` blocks. |
| [`interfaces.md`](interfaces.md) | RouterOS flat per-product naming (`ether1` / `bond1` / `vlan100`) versus FortiGate opaque labels (`port1` / `wan1`); IP / MTU / link-local IPv6 surface. |
| [`vlans.md`](vlans.md) | RouterOS two-plane VLAN (Plane 1 `/interface vlan`, Plane 2 bridge VLAN filtering) versus FortiGate child-interface model. |
| [`static_routes.md`](static_routes.md) | RouterOS `/ip route add dst-address=CIDR` versus FortiOS `config router static / set dst NETWORK MASK`. |
| [`snmp_aaa.md`](snmp_aaa.md) | RouterOS `/snmp` + `/snmp community` + `/radius` versus FortiOS `config system snmp / community / user` and `config user radius`.  v3 USM hashes are not cross-compatible (engineID-salted). |
| [`local_users.md`](local_users.md) | RouterOS `/user add group=full/write/read` versus FortiOS `config system admin / set accprofile / set password ENC ...`.  RouterOS does NOT export hashed passwords — operators MUST set them on the FortiGate target. |
| [`lags.md`](lags.md) | RouterOS bonding (`mode=802.3ad / active-backup / balance-rr / ...`) versus FortiOS aggregate (`set type aggregate / set lacp-mode active/passive/static`).  RouterOS-unique modes lose information. |
| [`dhcp.md`](dhcp.md) | RouterOS three-section DHCP (`/ip pool` + `/ip dhcp-server` + `/ip dhcp-server network`) versus FortiOS interface-bound `config system dhcp server`. |
| [`firewall_unsupported.md`](firewall_unsupported.md) | RouterOS `/ip firewall filter / nat / mangle / queues / wireless / scripts` are RouterOS-only Tier-3 surfaces.  FortiGate's session-based firewall / UTM is also Tier 3.  Operators reconstruct manually. |
| [`routing_instances_vrf.md`](routing_instances_vrf.md) | RouterOS 7+ named `/ip vrf` versus FortiGate VDOMs (heavyweight) and FortiOS 7.x per-interface integer VRF.  Neither codec parses VRF in v1. |

Retrieved: 2026-04-30

See also:
- [`../README.md`](../README.md) — citation cache layout.
- [`../fortigate_cli_to_mikrotik_routeros/_INDEX.md`](../fortigate_cli_to_mikrotik_routeros/_INDEX.md) — reverse-direction index.
- [`../mikrotik_routeros_to_cisco_iosxe_cli/_INDEX.md`](../mikrotik_routeros_to_cisco_iosxe_cli/_INDEX.md) — sibling pair (SMB router → enterprise switch/router).
- [`../aruba_aoss_to_fortigate_cli/_INDEX.md`](../aruba_aoss_to_fortigate_cli/_INDEX.md) — sibling pair (campus switch → firewall).
