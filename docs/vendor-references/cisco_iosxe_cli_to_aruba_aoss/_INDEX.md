# Cisco IOS-XE CLI to Aruba AOS-S — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/cisco_iosxe_cli__aruba_aoss.yaml`
per-field expectations.  See sibling `README.md` (one level up) for the
canonical schema definition.

This pair is a **CLI-family campus migration**: Cisco IOS-XE
(Catalyst-class L2/L3 switching) to Aruba AOS-S (ProCurve heritage,
2930F/2930M/3810/5400R class).  Both vendors share a Cisco-derived
CLI lineage but diverge on:

* Membership model (Cisco port-centric `switchport access vlan` vs
  Aruba VLAN-centric `untagged 1-24`).
* Mask format (Cisco dotted decimal vs Aruba CIDR).
* Hash formats (Cisco type-9 scrypt vs Aruba SHA-1 / bcrypt; not
  cross-compatible).
* Feature surface (Cisco supports VRF / BGP / EIGRP — Aruba AOS-S
  is L2/basic-L3 with no VRF concept and no BGP).

| Topic | Summary |
|---|---|
| `vlans.md` | VLAN definition (Cisco `vlan N / name X`, Aruba `vlan N / name "X" / untagged 1-24 / ip address X/N`) and the canonical VLAN-centric model. |
| `port_naming.md` | Cisco `GigabitEthernet1/0/1` (speed prefix) vs Aruba `1/1`/`A1` (bare numeric).  Speed hint lossy. |
| `ip_addressing.md` | IPv4 dotted-mask vs CIDR; IPv6 link-local discriminator. |
| `static_routes.md` | Default-VRF routes round-trip cleanly; per-VRF routes lossy (no canonical VRF field on `CanonicalStaticRoute`). |
| `snmp.md` | v1/v2c surface good; v3 USM passphrases not cross-compatible (engineID-salted). |
| `local_users.md` | Cisco `privilege N` (1-15) vs Aruba `manager`/`operator` two-role; hash formats incompatible. |
| `lags.md` | Cisco `Port-channel<N>` vs Aruba `Trk<N>`; LAG members + LACP mode round-trip; PAgP/dt-lacp lossy. |
| `system_services.md` | Hostname / DNS / NTP-vs-SNTP / timezone / syslog. |
| `vrf_unsupported.md` | Cisco VRFs parse-and-ignore on Cisco codec; Aruba AOS-S has no VRF concept. |
| `routing_protocols_unsupported.md` | BGP / OSPF / EIGRP — all parse-and-ignore on both codecs. |
| `radius.md` | RADIUS host + key + auth/acct ports round-trip. |
| `dhcp_relay_versus_pool.md` | Cisco's `ip dhcp pool` server config has no Aruba target (AOS-S is relay-only). |
| `spanning_tree.md` | Cisco PVST+ / rapid-pvst vs Aruba MSTP; canonical field not modelled, Tier 3. |

Retrieved 2026-04-30 to 2026-05-01.

See also: `../README.md` (citation cache layout).
