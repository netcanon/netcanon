# Cisco IOS-XE CLI to FortiGate FortiOS CLI — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/cisco_iosxe_cli__fortigate_cli.yaml`
per-field expectations.  See sibling
[`README.md`](../../../tests/fixtures/cross_vendor_expectations/README.md)
for the canonical schema definition.

This pair is a **switch/router -> firewall** migration.  Cisco IOS-XE
covers L2 switching, L3 routing, and basic NAT/ACL, while FortiGate
is a session-based stateful firewall with rich UTM integration and
limited L2 switching.  Cross-vendor mapping is genuinely partial —
the foundations (hostname, NTP, DNS, SNMP, static routes, basic IP
addressing) carry across, but switching features lose their target
and firewall policies don't have a canonical model to land on.

| Topic | Summary |
|---|---|
| [`system_services.md`](system_services.md) | Hostname / DNS / NTP / syslog / timezone — Cisco globals versus FortiOS `config system <topic>` blocks. |
| [`interface_naming.md`](interface_naming.md) | Cisco `GigabitEthernet0/0/0` (speed-encoded) versus FortiOS `port1` / `wan1` / `internal` (opaque labels). |
| [`ip_addressing.md`](ip_addressing.md) | Both vendors use dotted-decimal masks; FortiOS schemas only first-record per-interface (Cisco secondaries lost). |
| [`vlans.md`](vlans.md) | Cisco's first-class `vlan <N>` global object versus FortiOS's child-interface model (`set type vlan / set vlanid`). |
| [`switchport.md`](switchport.md) | Cisco access/trunk/voice-VLAN versus FortiGate's flat L3 firewall model (no L2 switching). |
| [`static_routes.md`](static_routes.md) | Cisco `ip route` versus FortiOS `config router static / set dst / set gateway`.  Default routes round-trip cleanly. |
| [`snmp.md`](snmp.md) | Cisco `snmp-server community / host` versus FortiOS `config system snmp community / user`.  v3 USM hashes are not cross-compatible (engineID salting). |
| [`local_users.md`](local_users.md) | Cisco `username X privilege Y secret 9 $9$...` versus FortiOS `config system admin / set accprofile / set password ENC ...`.  Hash formats are NOT cross-compatible. |
| [`aaa.md`](aaa.md) | Cisco `radius server <name> / address ipv4 ... / key ...` versus FortiOS `config user radius / edit / set server / set secret ENC ...`. |
| [`dhcp.md`](dhcp.md) | Cisco's `ip dhcp pool <name>` versus FortiOS interface-bound `config system dhcp server`.  Range vs exclusion semantic divergence. |
| [`lags.md`](lags.md) | Cisco `Port-channel<N>` plus per-member `channel-group` versus FortiOS aggregate-side `set type aggregate / set member`. |
| [`vrf.md`](vrf.md) | Cisco named VRFs (`vrf definition / rd / rt`) versus FortiGate VDOMs (heavyweight) versus FortiOS 7.x per-interface integer VRF IDs. |
| [`routing_protocols.md`](routing_protocols.md) | BGP / OSPF / EIGRP / RIP — all canonical-schema gaps; both codecs Tier-3 parse-and-ignore. |
| [`firewall_policy.md`](firewall_policy.md) | FortiGate `config firewall policy / vip / address` is the primary product surface; Cisco ACL / ZBF / NAT.  No canonical model — out of scope. |

Retrieved over 2026-04-30.

See also:
- [`../README.md`](../README.md) — citation cache layout.
- [`../fortigate_cli_to_cisco_iosxe_cli/_INDEX.md`](../fortigate_cli_to_cisco_iosxe_cli/_INDEX.md)
  — reverse-direction index.
- [`../cisco_iosxe_cli_to_arista_eos/_INDEX.md`](../cisco_iosxe_cli_to_arista_eos/_INDEX.md)
  — sibling Cisco-source pair (high-overlap DC migration).
