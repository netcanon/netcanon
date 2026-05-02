# FortiGate FortiOS CLI to Juniper Junos — vendor reference index

Curated vendor-doc excerpts grounding the
[`tests/fixtures/cross_vendor_expectations/fortigate_cli__juniper_junos.yaml`](../../../tests/fixtures/cross_vendor_expectations/fortigate_cli__juniper_junos.yaml)
per-field expectations.  See sibling
[`README.md`](../../../tests/fixtures/cross_vendor_expectations/README.md)
for the canonical schema definition.

This is a firewall -> DC-class router pair.  FortiGate FortiOS is a
session-based stateful firewall + UTM appliance with a thin L2 surface
(hardware-switch only on entry-level boxes); Junos is a carrier / DC-
class router with rich EVPN-VXLAN, apply-groups, and instance-type
discriminator support.  The role mismatch concentrates the asymmetric
loss on three surfaces:

- FortiGate's primary product surface (firewall policy / NAT / VPN /
  IPsec / UTM / SD-WAN / virtual-IP) has no canonical model and no
  Junos auto-render target.
- FortiGate's VDOMs and per-interface integer VRF do not auto-project
  onto Junos's logical-systems / routing-instances.
- Junos-source-only constructs (apply-groups, EVPN-VXLAN VNI
  mappings, instance-type discriminator) are structurally absent on
  FortiGate source and not_applicable on this direction.

| Topic | Summary |
|---|---|
| [`system_services.md`](system_services.md) | Hostname / DNS / NTP / syslog / clock / domain — FortiOS DNS cap (3) doesn't bottleneck Junos's unbounded list; timezone format mismatch (FortiOS numeric index vs Olson zoneinfo) requires operator-curated lookup. |
| [`interfaces.md`](interfaces.md) | FortiGate flat namespace (`port1`, `agg1.100`) -> Junos media-prefix (`ge-0/0/0`).  Port-rename mesh required.  IP / MTU / IPv6 round-trip with documented secondary-IP and link-local-scope drift. |
| [`vlans.md`](vlans.md) | FortiGate child-interface VLAN model -> Junos first-class `vlans` object.  Port-membership is a hard model gap (FortiGate parent-interface model has no canonical port list per VLAN). |
| [`static_routes.md`](static_routes.md) | FortiOS dotted-mask + outgoing-interface -> Junos CIDR + qualified-next-hop.  Default-VRF round-trips; per-VRF unsupported (canonical schema gap). |
| [`snmp_aaa.md`](snmp_aaa.md) | FortiGate `config system snmp / config user radius` -> Junos `set snmp / set system radius-server`.  Multi-community drops to scalar; v3 USM passphrases not cross-compatible (FortiOS ENC vs Junos $9$). |
| [`local_users.md`](local_users.md) | FortiGate accprofile strings -> Junos named class.  `super_admin` -> `super-user`; others -> `operator`.  Hash formats incompatible (ENC vs $1$/$5$/$6$). |
| [`lags.md`](lags.md) | FortiGate operator-named aggregates (`agg1`) -> Junos `ae<N>` integer-keyed form.  Members preserve via rename mesh; LACP modes map cleanly. |
| [`dhcp.md`](dhcp.md) | FortiGate interface-bound pool -> Junos two-stage `dhcp-local-server` + `address-assignment pool`.  Multi-range drops to first; advanced options not modelled. |
| [`firewall_unsupported.md`](firewall_unsupported.md) | FortiGate firewall / NAT / VPN / IPsec / UTM / SD-WAN — primary product surface; no canonical model and no Junos auto-render.  Operators must keep an upstream firewall. |
| [`vrf_vdom_unsupported.md`](vrf_vdom_unsupported.md) | FortiGate VDOMs (heavyweight multi-tenancy) and per-interface integer VRF (FortiOS 7.0+) — not parsed into canonical CanonicalRoutingInstance in v1.  Junos `instance-type vrf | virtual-router | mac-vrf` lossy by structural mismatch. |
| [`vxlan_evpn_unsupported.md`](vxlan_evpn_unsupported.md) | FortiGate has no EVPN control plane and no fabric data plane; FortiGate source never populates `vxlan_vnis` / `evpn_type5_routes`.  not_applicable on this direction. |

Retrieved 2026-05-01.

See also:
- [`../README.md`](../README.md) — citation cache layout overview.
- [`../juniper_junos_to_fortigate_cli/_INDEX.md`](../juniper_junos_to_fortigate_cli/_INDEX.md)
  — reverse-direction sibling.
- [`../fortigate_cli_to_cisco_iosxe_cli/_INDEX.md`](../fortigate_cli_to_cisco_iosxe_cli/_INDEX.md)
  — sibling firewall-to-router pair (FortiGate -> Cisco IOS-XE).
- [`../arista_eos_to_juniper_junos/_INDEX.md`](../arista_eos_to_juniper_junos/_INDEX.md)
  — sibling Junos-target pair (Arista -> Junos) covering EVPN-VXLAN /
  apply-groups concepts that don't apply on FortiGate source.
