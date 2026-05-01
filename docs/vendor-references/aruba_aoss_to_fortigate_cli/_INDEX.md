# Aruba AOS-S to FortiGate FortiOS CLI — vendor reference index

Curated vendor-doc excerpts grounding the
[`tests/fixtures/cross_vendor_expectations/aruba_aoss__fortigate_cli.yaml`](../../../tests/fixtures/cross_vendor_expectations/aruba_aoss__fortigate_cli.yaml)
per-field expectations.  See sibling
[`README.md`](../../../tests/fixtures/cross_vendor_expectations/README.md)
for the canonical schema definition.

This pair is a **switch -> firewall** edge consolidation: Aruba
AOS-S (campus L2/L3 access switch, ProCurve heritage) to FortiGate
FortiOS (session-based stateful firewall with limited L2 hardware-
switch surface).  The two product roles diverge sharply:

* **Aruba's L2 surface loses its target.**  VLAN-centric port
  lists (`tagged 1-24` / `untagged 25-26`), spanning-tree (MSTP /
  RPVST+), DHCP-snooping, IGMP-snooping, voice-VLAN-via-LLDP-MED
  — none of these have a FortiGate analogue beyond the hardware-
  switch sub-feature on a few low-end models.
* **FortiGate's firewall surface is structurally absent on Aruba
  source.**  Firewall policy / NAT / VPN / UTM / VDOM are the
  primary FortiGate product but the canonical model has no
  representation, so the cross-pair drops the lot.
* **Foundations translate.**  Hostname / DNS / SNMP v1+v2c /
  RADIUS / static-routes / local-users / LAGs round-trip via the
  canonical tree.

| Topic | Summary |
|---|---|
| [`system_services.md`](system_services.md) | Hostname / DNS / SNTP-vs-NTP / syslog / clock.  AOS-S uses SNTP and minute-offset timezones; FortiOS uses NTP and a numeric-index timezone table. |
| [`interface_naming.md`](interface_naming.md) | Aruba bare-numeric (`1` / `A1`) vs FortiGate flat namespace (`port1` / `wan1`).  Port-rename mesh required. |
| [`ip_addressing.md`](ip_addressing.md) | IPv4 mixed-mask (Aruba accepts CIDR + dotted) vs FortiOS dotted-only.  IPv6 link-local scope discriminator lossy on this direction. |
| [`vlans.md`](vlans.md) | Aruba VLAN-centric port lists vs FortiGate child-interface VLAN model.  Hard model-translation gap on multi-port VLAN membership. |
| [`switchport.md`](switchport.md) | Aruba's L2 surface (switchport / spanning-tree / dhcp-snooping / voice-LLDP) is unsupported on FortiGate (L3-only product). |
| [`static_routes.md`](static_routes.md) | Default-VRF static routes round-trip cleanly via CIDR <-> dotted-mask conversion.  Per-route metadata gaps (description / metric semantics). |
| [`snmp.md`](snmp.md) | v1/v2c surface good (Operator/Manager collapses to single canonical scalar); v3 USM passphrases not cross-compatible (engineID-salted). |
| [`local_users.md`](local_users.md) | Aruba two-role model (manager/operator) -> FortiGate accprofile strings (super_admin/prof_admin).  Hash formats incompatible. |
| [`radius.md`](radius.md) | Aruba flat host-keyed form -> FortiGate edit-table.  Shared-secret format incompatible (FortiOS ENC encryption). |
| [`dhcp.md`](dhcp.md) | Aruba is relay-only (codec doesn't parse pools); not_applicable on this direction.  helper-address relay intent unmodelled. |
| [`lags.md`](lags.md) | Aruba `Trk<N>` -> FortiGate operator-named aggregates.  Members + LACP modes round-trip; HP-proprietary `dt-lacp` / `fec` lossy. |
| [`vrf.md`](vrf.md) | Aruba has no VRF concept; FortiGate VDOMs / per-interface integer VRF unmodelled in canonical v1.  Not applicable. |
| [`routing_protocols.md`](routing_protocols.md) | OSPF / RIP / BGP not in canonical model; both codecs parse-and-ignore. |
| [`firewall_policy.md`](firewall_policy.md) | FortiGate's primary product surface; no canonical model.  Not applicable on this direction. |
| [`spanning_tree.md`](spanning_tree.md) | Aruba MSTP / RPVST+ has no FortiGate target; firewall is L3-only. |

Retrieved 2026-04-30 to 2026-05-01.

See also:
- [`../README.md`](../README.md) — citation cache layout.
- [`../fortigate_cli_to_aruba_aoss/_INDEX.md`](../fortigate_cli_to_aruba_aoss/_INDEX.md)
  — reverse-direction sibling (FortiGate firewall -> Aruba switch).
- [`../cisco_iosxe_cli_to_fortigate_cli/_INDEX.md`](../cisco_iosxe_cli_to_fortigate_cli/_INDEX.md)
  — sibling switch-to-firewall pair (Cisco IOS-XE -> FortiGate).
- [`../cisco_iosxe_cli_to_aruba_aoss/_INDEX.md`](../cisco_iosxe_cli_to_aruba_aoss/_INDEX.md)
  — sibling Aruba pair (Cisco IOS-XE -> Aruba AOS-S).
