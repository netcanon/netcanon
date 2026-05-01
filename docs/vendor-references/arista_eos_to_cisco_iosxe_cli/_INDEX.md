# Arista EOS to Cisco IOS-XE CLI — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/arista_eos__cisco_iosxe_cli.yaml`
per-field expectations.  See sibling
`tests/fixtures/cross_vendor_expectations/README.md` for the canonical
schema definition.

This pair is the **inverse** of `cisco_iosxe_cli_to_arista_eos/`.  The
keyword-stable surface (vlans / switchport / static routes / SNMP v1/v2c
/ hostname / DNS / NTP / logging) round-trips cleanly because Arista EOS
deliberately mirrors Cisco IOS CLI grammar.  The asymmetries are
**richer-source-than-target** ones: the Arista parser populates VRF and
EVPN MAC-VRF and VXLAN data that the Cisco IOS-XE codec does not always
have a render path for (VXLAN especially — IOS-XE's `interface NVE`
form is a NX-OS construct, not standard IOS-XE CLI).

| Topic | Summary |
|---|---|
| `vlans.md` | VLAN creation `vlan N / name X` is identical on both vendors. |
| `switchport.md` | Access / trunk syntax is byte-identical: `switchport mode {access\|trunk}`, `switchport access vlan`, `switchport trunk allowed vlan`, `switchport trunk native vlan`. |
| `interface_naming.md` | Arista `Ethernet1` (flat) versus Cisco `GigabitEthernet1/0/1` (speed-encoded) — port-rename mesh handles. |
| `ip_addressing.md` | Arista `ip address A.B.C.D/N` (CIDR) versus Cisco `ip address A.B.C.D MASK` (dotted-mask).  Codecs convert; canonical stores prefix-length. |
| `static_routes.md` | Arista `ip route DEST/N GW` versus Cisco `ip route DEST MASK GW`.  Equivalent. |
| `vrf.md` | Arista `vrf instance <name>` versus Cisco `vrf definition <name>`.  Sub-stanzas (`rd`, `route-target`) are nearly identical; the Cisco render path emits the canonical L3 VRF cleanly so this direction is good for the standard surface. |
| `mac_vrf.md` | Arista's `router bgp / vlan N / rd ... / route-target ...` per-VLAN EVPN MAC-VRF binding has no clean IOS-XE equivalent.  Documented lossy. |
| `vxlan.md` | Arista's `interface Vxlan1` with `vxlan vlan X vni Y` mappings has no auto-renderable IOS-XE form (Cisco's NVE syntax is NX-OS lineage).  Documented unsupported. |
| `snmp.md` | `snmp-server` family is identical for v1/v2c.  v3 USM passphrases are not cross-compatible (engineID-derived salt). |
| `local_users.md` | Arista `username X role <name> secret sha512 $6$...` versus Cisco `username X privilege Y secret 9 $9$...`.  Hash formats are NOT cross-compatible. |
| `aaa.md` | TACACS+ / RADIUS server config.  Server-host syntax differs slightly; canonical captures the cross-vendor surface. |
| `spanning_tree.md` | Arista default `mstp`; Cisco default `pvst`.  Both support `rapid-pvst`.  Tier-3 informational. |
| `routing_protocols.md` | BGP / OSPF / EIGRP — all currently parse-and-ignore on both codecs.  EIGRP is Cisco-only on the WIRE (Arista has no EIGRP), but irrelevant since the canonical model has no routing-protocol surface. |
| `system_services.md` | Hostname / NTP / DNS / logging / clock — small surface, mostly identical. |

Retrieved over 2026-04-30.

See also: `../README.md` (citation cache layout),
`../cisco_iosxe_cli_to_arista_eos/_INDEX.md` (the inverse pair).
