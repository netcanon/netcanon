# Cisco IOS-XE CLI to Arista EOS — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/cisco_iosxe_cli__arista_eos.yaml`
per-field expectations.  See sibling `README.md` (authored by Agent A)
for the canonical schema definition.

This pair is a high-feature-overlap DC migration: both vendors share
the same Cisco-family CLI lineage (Arista EOS deliberately mirrors
IOS for low-friction onboarding), so most translations are a direct
keyword swap or trivial rewrite.

| Topic | Summary |
|---|---|
| `vlans.md` | VLAN creation `vlan N / name X` is identical on both vendors. |
| `switchport.md` | Access / trunk syntax is identical: `switchport mode {access\|trunk}`, `switchport access vlan`, `switchport trunk allowed vlan`, `switchport trunk native vlan`. |
| `interface_naming.md` | Cisco `GigabitEthernet1/0/1` versus Arista `Ethernet1` — port-rename mesh handles. |
| `ip_addressing.md` | Cisco `ip address A.B.C.D MASK` (dotted-mask) versus Arista `ip address A.B.C.D/N` (CIDR).  Codecs convert; canonical stores prefix-length. |
| `static_routes.md` | Cisco `ip route DEST MASK GW` versus Arista `ip route DEST/N GW`.  Equivalent. |
| `vrf.md` | Cisco `vrf definition <name>` versus Arista `vrf instance <name>`.  Sub-stanzas (`rd`, `route-target`) are nearly identical. |
| `snmp.md` | `snmp-server` family is identical for v1/v2c.  v3 user grammar diverges on encryption-keyword forms. |
| `local_users.md` | Cisco `username X privilege Y secret 9 $9$...` versus Arista `username X role <name> secret sha512 $6$...`.  Hash formats are NOT cross-compatible. |
| `aaa.md` | TACACS+ / RADIUS server config.  Server-host syntax differs slightly; canonical captures the cross-vendor surface. |
| `spanning_tree.md` | Cisco default `pvst`; Arista default `mstp`.  Both support `rapid-pvst`.  Tier-3 informational. |
| `routing_protocols.md` | BGP / OSPF / EIGRP — all currently parse-and-ignore in both codecs. |
| `system_services.md` | Hostname / NTP / DNS / logging / clock — small surface, mostly identical. |

Retrieved over 2026-04-30 to 2026-05-01.

See also: `../README.md` (schema overview, owned by Agent A).
