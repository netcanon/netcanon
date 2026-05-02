# FortiGate FortiOS CLI to MikroTik RouterOS — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/fortigate_cli__mikrotik_routeros.yaml`
per-field expectations.  See sibling
[`README.md`](../../../tests/fixtures/cross_vendor_expectations/README.md)
for the canonical schema definition.

This pair is a **firewall → SMB / WISP router** migration.  FortiGate is a session-based stateful firewall with rich UTM and limited L2 switching; MikroTik RouterOS is a router-first SMB / WISP platform with bridge-based switching as a sub-feature.  Both are "router-class" but with different feature focus, and the two vendor wire formats (FortiOS `config / edit / set / next / end` 5-keyword grammar versus RouterOS `/section / add / set` /export grammar) differ enough that even concepts both vendors model end up lossy on the cross-pair.

| Topic | Summary |
|---|---|
| [`system_services.md`](system_services.md) | Hostname / DNS / NTP / timezone / syslog — FortiOS `config system <topic>` blocks versus RouterOS `/system identity` + `/system clock` + `/ip dns` + `/system ntp client` + `/system logging`. |
| [`interfaces.md`](interfaces.md) | FortiGate opaque labels (`port1` / `wan1`) versus RouterOS flat per-product naming (`ether1` / `bond1` / `vlan100`); IP / MTU / status surface. |
| [`vlans.md`](vlans.md) | FortiGate child-interface VLAN model versus RouterOS two-plane (Plane 1 `/interface vlan` for L3, Plane 2 bridge VLAN filtering for L2 switching). |
| [`static_routes.md`](static_routes.md) | FortiOS `config router static / set dst NETWORK MASK` (dotted-mask) versus RouterOS `/ip route add dst-address=CIDR`. |
| [`snmp_aaa.md`](snmp_aaa.md) | FortiOS `config system snmp / community / user` and `config user radius` versus RouterOS `/snmp` and `/radius`.  v3 USM hashes are not cross-compatible (engineID-salted; FortiOS uses ENC-prefixed proprietary form). |
| [`local_users.md`](local_users.md) | FortiOS `config system admin / set accprofile / set password ENC ...` versus RouterOS `/user add group=full/write/read`.  RouterOS does NOT export hashed passwords — operators must re-set them. |
| [`lags.md`](lags.md) | FortiOS aggregate parent (`set type aggregate / set member / set lacp-mode`) versus RouterOS bonding (`/interface bonding add slaves= mode=802.3ad`).  RouterOS does not distinguish active/passive LACP. |
| [`dhcp.md`](dhcp.md) | FortiOS interface-bound `config system dhcp server` versus RouterOS three-section form (`/ip pool` + `/ip dhcp-server` + `/ip dhcp-server network`). |
| [`firewall_unsupported.md`](firewall_unsupported.md) | FortiGate `config firewall policy / vip / ippool` and VDOMs / IPsec / UTM are FortiGate-only product surfaces with no canonical model.  RouterOS firewall is Tier 3.  Operators reconstruct security policy manually. |
| [`routing_instances_vrf.md`](routing_instances_vrf.md) | FortiGate VDOMs (heavyweight) and FortiOS 7.x per-interface integer VRF versus RouterOS 7+ named `/ip vrf`.  Neither codec parses VRF in v1; cross-pair is unsupported. |

Retrieved: 2026-04-30

See also:
- [`../README.md`](../README.md) — citation cache layout.
- [`../mikrotik_routeros_to_fortigate_cli/_INDEX.md`](../mikrotik_routeros_to_fortigate_cli/_INDEX.md) — reverse-direction index.
- [`../cisco_iosxe_cli_to_fortigate_cli/_INDEX.md`](../cisco_iosxe_cli_to_fortigate_cli/_INDEX.md) — sibling pair (router/switch → firewall).
- [`../cisco_iosxe_cli_to_mikrotik_routeros/_INDEX.md`](../cisco_iosxe_cli_to_mikrotik_routeros/_INDEX.md) — sibling pair (enterprise → SMB router).
