# Arista EOS to FortiGate FortiOS CLI — vendor reference index

Curated vendor-doc excerpts grounding the
[`tests/fixtures/cross_vendor_expectations/arista_eos__fortigate_cli.yaml`](../../../tests/fixtures/cross_vendor_expectations/arista_eos__fortigate_cli.yaml)
per-field expectations.  See sibling
[`README.md`](../../../tests/fixtures/cross_vendor_expectations/README.md)
for the canonical schema definition.

This pair is a **DC-leaf -> firewall** consolidation: Arista EOS
(DC-class L2/L3 switch with EVPN-VXLAN spine-leaf fabric heritage)
to FortiGate FortiOS (session-based stateful firewall).  The two
product roles diverge sharply:

* **Arista's DC-class fabric surface loses its target.**  EVPN-VXLAN
  L2/L3 VNIs, MAC-VRF, per-interface VRF binding, BGP EVPN address-
  family, MLAG — none of these have a FortiGate analogue.
* **FortiGate's firewall + UTM product surface is structurally
  absent on Arista source.**  Firewall policy / NAT / VIP / VPN /
  UTM are FortiGate-only and the canonical model has no
  representation.
* **Foundations translate.**  Hostname / DNS / NTP / SNMP / RADIUS /
  static-routes / local-users / LAGs / IPv4-IPv6 addressing
  round-trip via the canonical tree.
* **VLANs are a hard model gap.**  Arista's VLAN-centric port-list
  re-projection (via `project_switchport_to_vlan`) cannot be
  consumed by FortiGate's child-interface VLAN model without
  synthesising one VLAN-child interface per (VLAN x parent) — a
  v1 render gap.

| Topic | Summary |
|---|---|
| [`system_services.md`](system_services.md) | Hostname / DNS / NTP / syslog / clock / domain.  Arista zoneinfo timezone vs FortiOS numeric-index table.  3-cap on FortiOS DNS + syslog. |
| [`interfaces.md`](interfaces.md) | Naming (CamelCase Ethernet/Port-Channel vs flat port1/agg1), CIDR vs dotted-mask, IPv6 link-local scope, MTU, DHCP-client. |
| [`vlans.md`](vlans.md) | Arista per-port switchport with VLAN-centric port-list reprojection vs FortiGate child-interface VLAN model.  Hard model-translation gap on multi-port VLAN membership. |
| [`static_routes.md`](static_routes.md) | Default-VRF round-trip via CIDR <-> dotted-mask conversion.  Per-VRF and IPv6 route gaps.  Metric semantic mismatch. |
| [`snmp_aaa.md`](snmp_aaa.md) | SNMP v1/v2c good; v3 USM passphrases not cross-compatible (engineID-salted; FortiOS ENC-encryption).  RADIUS shared-secret incompatible. |
| [`local_users.md`](local_users.md) | Numeric privilege (1-15) vs named accprofile (super_admin / prof_admin).  Hash families incompatible (sha512_crypt vs ENC-encryption); re-keying required. |
| [`lags.md`](lags.md) | Arista `Port-Channel<N>` vs FortiGate operator-named aggregates (`agg<N>`).  Members + LACP modes round-trip; MLAG drops. |
| [`vxlan_evpn_unsupported.md`](vxlan_evpn_unsupported.md) | EVPN-VXLAN, MAC-VRF, L3-VRF, per-interface VRF — Arista DC-fabric surface vs FortiGate firewall/NAT product.  All unsupported on this direction. |

Retrieved 2026-05-01.

See also:
- [`../README.md`](../README.md) — citation cache layout.
- [`../fortigate_cli_to_arista_eos/_INDEX.md`](../fortigate_cli_to_arista_eos/_INDEX.md)
  — reverse-direction sibling (FortiGate firewall -> Arista EOS DC switch).
- [`../arista_eos_to_juniper_junos/_INDEX.md`](../arista_eos_to_juniper_junos/_INDEX.md)
  — sibling Arista-source pair (DC-to-DC EVPN-VXLAN migration).
- [`../cisco_iosxe_cli_to_fortigate_cli/_INDEX.md`](../cisco_iosxe_cli_to_fortigate_cli/_INDEX.md)
  — sibling switch-to-firewall pair (Cisco IOS-XE -> FortiGate).
- [`../aruba_aoss_to_fortigate_cli/_INDEX.md`](../aruba_aoss_to_fortigate_cli/_INDEX.md)
  — sibling switch-to-firewall pair (Aruba AOS-S -> FortiGate).
