# Juniper Junos to Cisco IOS-XE CLI — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/juniper_junos__cisco_iosxe_cli.yaml`
per-field expectations.  See sibling `README.md` (in
`tests/fixtures/cross_vendor_expectations/`) for the canonical schema
definition.

This is the reverse of `cisco_iosxe_cli_to_juniper_junos/`; the
dispositions are NOT symmetric.  Junos models richer per-instance
detail (instance-type discriminator, apply-groups inheritance,
per-VRF policy-statements) that Cisco's stanza model doesn't
express; the asymmetry is documented per-field.

| File | Topic | Citation ids |
|---|---|---|
| `interface-naming.md` | Junos `ge-/xe-/et-` versus Cisco speed-encoded names | `junos-iface-naming`, `cisco-interface-cli` |
| `vlans.md` | `set vlans NAME vlan-id N` versus Cisco `vlan N / switchport` | `junos-vlans-statement`, `junos-bridging-overview`, `cisco-vlan-cg` |
| `ip-addressing.md` | Junos `family inet/inet6 address` (CIDR) versus Cisco dotted-mask | `junos-iface-fundamentals`, `junos-family-inet6`, `cisco-ip-cg`, `cisco-ipv6-cg` |
| `static-routes.md` | `routing-options static route` versus `ip route` | `junos-static-routing`, `cisco-static-routes` |
| `vrf-routing-instances.md` | `routing-instances` versus `vrf definition` | `junos-l3vpn`, `junos-instance-type`, `cisco-vrf-cli`, `cisco-vrf-lite-cg` |
| `snmp.md` | v1/v2c communities + v3 USM (split hierarchy) | `junos-snmp-overview`, `junos-snmpv3-cg`, `cisco-snmp-cg` |
| `local-users.md` | Junos `class` (named role) + `encrypted-password` versus Cisco `privilege` + `secret <N>` | `junos-password-cli`, `junos-kb-password-format`, `cisco-username-cli`, `cisco-password-types` |
| `system-services.md` | Hostname / domain / DNS / NTP / syslog / timezone | `junos-initial-config`, `junos-syslog-overview`, `cisco-fundamentals` |
| `vxlan-evpn.md` | `set vlans NAME vxlan vni N` + `protocols evpn` versus `interface nve1` | `junos-evpn-overview`, `junos-evpn-irb-example`, `cisco-evpn-vxlan-cg` |
| `lags.md` | `ae<N>` + `aggregated-ether-options lacp` versus Cisco `Port-channel<N>` | `junos-lag-overview`, `junos-ae-example`, `cisco-etherchannel` |
| `routing-protocols.md` | `protocols bgp / ospf` (set form) versus `router bgp / ospf` (stanza) | `junos-bgp-overview`, `junos-ospf-overview`, `cisco-bgp-cg`, `cisco-ospf-cg` |
| `aaa.md` | RADIUS / TACACS+ servers (IP-keyed Junos vs named-server Cisco) | `junos-radius-cli`, `junos-tacplus-cli`, `cisco-aaa-cli` |
| `dhcp-server.md` | Junos two-stage `dhcp-local-server` + `address-assignment pool` versus Cisco `ip dhcp pool` | `junos-dhcp-server`, `junos-dhcp-local-server`, `cisco-dhcp-cg` |
| `apply-groups.md` | Junos-only configuration inheritance (`set groups` + `set apply-groups`) | `junos-groups-statement`, `junos-config-groups-overview` |

Retrieved 2026-04-30.

See also: `../README.md` (cache layout overview);
`../arista_eos_to_juniper_junos/_INDEX.md` (Junos primitives also
seen on Arista source); `../cisco_iosxe_cli_to_juniper_junos/_INDEX.md`
(reverse direction).
