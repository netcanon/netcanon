# Cisco IOS-XE CLI to Juniper Junos — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/cisco_iosxe_cli__juniper_junos.yaml`
per-field expectations.  See sibling `README.md` (in
`tests/fixtures/cross_vendor_expectations/`) for the canonical schema
definition.

This pair is one of the most-likely-real-world DC migrations:
Cisco's stanza-form CLI versus Junos's hierarchical set-form requires
substantial structural transformation, but both platforms model the
same set of L2/L3 / overlay primitives.  The keyword-stable surface
(hostname / DNS / NTP / static routes / SNMP v1+v2c / VLANs) round-
trips cleanly; semantic-divergent surfaces (interface naming, VRF /
routing-instances, password hash formats, EVPN-VXLAN) are flagged
lossy or unsupported.

| File | Topic | Citation ids |
|---|---|---|
| `interface-naming.md` | Physical/logical interface naming (`GigabitEthernet1/0/1` vs `ge-0/0/0`) | `cisco-interface-cli`, `junos-iface-naming` |
| `vlans.md` | VLAN declaration + per-port membership (`switchport` vs `family ethernet-switching`) | `cisco-vlan-cg`, `junos-vlans-statement`, `junos-bridging-overview` |
| `ip-addressing.md` | IPv4 / IPv6 address forms (dotted-mask vs CIDR, link-local discrimination) | `cisco-ip-cg`, `cisco-ipv6-cg`, `junos-iface-fundamentals`, `junos-family-inet6` |
| `static-routes.md` | Global + per-VRF static route declarations | `cisco-static-routes`, `junos-static-routing` |
| `vrf-routing-instances.md` | VRF (`vrf definition`) versus routing-instance (`set routing-instances`) | `cisco-vrf-cli`, `cisco-vrf-lite-cg`, `junos-l3vpn`, `junos-instance-type` |
| `snmp.md` | v1 / v2c communities + v3 USM users | `cisco-snmp-cg`, `junos-snmp-overview`, `junos-snmpv3-cg` |
| `local-users.md` | Local user accounts + password hash formats (`secret 9` vs `$6$`) | `cisco-username-cli`, `cisco-password-types`, `junos-password-cli`, `junos-kb-password-format` |
| `system-services.md` | Hostname / domain / DNS / NTP / syslog / timezone | `cisco-fundamentals`, `junos-initial-config`, `junos-syslog-overview` |
| `vxlan-evpn.md` | VXLAN VTEP + VLAN-to-VNI bindings + EVPN overlay | `cisco-evpn-vxlan-cg`, `junos-evpn-overview`, `junos-evpn-irb-example` |
| `lags.md` | Port-channels (Cisco) versus aggregated-Ethernet (Junos `ae<N>`) | `cisco-etherchannel`, `junos-lag-overview`, `junos-ae-example` |
| `routing-protocols.md` | BGP / OSPF / EIGRP / IS-IS / MPLS — out of canonical scope | `cisco-bgp-cg`, `cisco-ospf-cg`, `junos-bgp-overview`, `junos-ospf-overview` |
| `aaa.md` | RADIUS / TACACS+ servers | `cisco-aaa-cli`, `junos-radius-cli`, `junos-tacplus-cli` |
| `dhcp-server.md` | On-device DHCP server pools | `cisco-dhcp-cg`, `junos-dhcp-server`, `junos-dhcp-local-server` |

Retrieved 2026-04-30.

See also: `../README.md` (cache layout overview);
`../arista_eos_to_juniper_junos/_INDEX.md` (Junos-side primitives
shared with the Arista pair).
