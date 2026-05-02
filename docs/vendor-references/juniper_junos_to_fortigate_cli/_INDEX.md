# Juniper Junos to FortiGate FortiOS CLI — vendor reference index

Curated vendor-doc excerpts grounding the
[`tests/fixtures/cross_vendor_expectations/juniper_junos__fortigate_cli.yaml`](../../../tests/fixtures/cross_vendor_expectations/juniper_junos__fortigate_cli.yaml)
per-field expectations.  See sibling
[`README.md`](../../../tests/fixtures/cross_vendor_expectations/README.md)
for the canonical schema definition.

This is a DC-class router -> firewall pair.  Junos models richer
per-instance detail (instance-type discriminator, apply-groups
inheritance, EVPN-VXLAN VNI mappings, MAC-VRF, L3 VNI for IRB) that
FortiGate's firewall-centric model has no target for.  The asymmetric
loss concentrates on:

- Junos's EVPN-VXLAN fabric data plane (VNI mappings, Type-5 routes,
  MAC-VRF, L3 VNI, switch-options globals) — `unsupported` on
  FortiGate target.
- Junos's apply-groups inheritance — `lossy` (group-shape drops on
  FortiGate render; flattened content survives via two-pass parse).
- Junos's firewall filters / policy-statements / BGP / OSPF / MPLS
  — Tier-3 informational-only; drops on FortiGate render.
- Junos's switching surface (`family ethernet-switching`) is
  populated in canonical but FortiGate has no canonical render path.

| Topic | Summary |
|---|---|
| [`system_services.md`](system_services.md) | Hostname / DNS / NTP / syslog / clock / domain — FortiOS DNS cap (3) + syslog cap (3) bottleneck Junos's unbounded lists.  Timezone format mismatch (Olson zoneinfo vs FortiOS numeric index) requires operator-curated lookup. |
| [`interfaces.md`](interfaces.md) | Junos media-prefix names (`ge-0/0/0`) -> FortiGate flat namespace (`port1`).  Slashes need rename-mesh sanitisation.  Stacked addresses + IPv6 link-local scope drift on FortiGate render. |
| [`vlans.md`](vlans.md) | Junos first-class `vlans` object -> FortiGate child-interface model.  Port-membership is a hard model gap (canonical port list per VLAN cannot project onto FortiGate without synthesising multiple VLAN-child interfaces). |
| [`static_routes.md`](static_routes.md) | Junos CIDR + qualified-next-hop -> FortiGate dotted-mask + outgoing-interface.  Default-VRF round-trips; per-VRF unsupported (canonical schema gap). |
| [`snmp_aaa.md`](snmp_aaa.md) | Junos `set snmp / set system radius-server` -> FortiGate `config system snmp / config user radius`.  IP-keyed RADIUS -> FortiGate render synthesises name.  v3 USM passphrases not cross-compatible. |
| [`local_users.md`](local_users.md) | Junos named class -> FortiGate accprofile.  `super-user` -> `super_admin`; others -> `prof_admin`.  Hash formats incompatible ($1$/$5$/$6$/$9$ vs ENC).  SSH-key auth drops (canonical gap). |
| [`lags.md`](lags.md) | Junos `ae<N>` integer-keyed -> FortiGate operator-named edit-ID.  Members declare-on-self -> FortiGate `set member` list.  Chassis device-count drops on FortiGate render. |
| [`dhcp.md`](dhcp.md) | Junos two-stage `dhcp-local-server` + `address-assignment pool` -> FortiGate interface-bound.  Multi-range drops to first; FortiGate must synthesise interface binding. |
| [`vrf_unsupported.md`](vrf_unsupported.md) | Junos `routing-instances` (rich `instance-type vrf | mac-vrf | virtual-router | l2vpn | evpn`) -> FortiGate has no VRF render in v1.  VDOMs / per-interface integer VRF (FortiOS 7.0+) are not wired. |
| [`vxlan_evpn_unsupported.md`](vxlan_evpn_unsupported.md) | Junos EVPN-VXLAN fabric (VNI mappings, Type-5, MAC-VRF, L3 VNI, switch-options) -> FortiGate has no fabric data plane.  FortiOS supports VXLAN tunnels for SD-WAN only, no EVPN control plane. |
| [`apply_groups.md`](apply_groups.md) | Junos apply-groups configuration inheritance (per GAP 9b two-pass parse) — group-shape drops on FortiGate render; flattened content survives. |
| [`firewall_filters_unsupported.md`](firewall_filters_unsupported.md) | Junos firewall filters / policy-statements / BGP / OSPF / MPLS — Tier-3 raw_sections.  Drops on FortiGate render; operators reconstruct routing-policy + firewall semantics manually. |

Retrieved 2026-05-01.

See also:
- [`../README.md`](../README.md) — citation cache layout overview.
- [`../fortigate_cli_to_juniper_junos/_INDEX.md`](../fortigate_cli_to_juniper_junos/_INDEX.md)
  — forward-direction sibling.
- [`../juniper_junos_to_cisco_iosxe_cli/_INDEX.md`](../juniper_junos_to_cisco_iosxe_cli/_INDEX.md)
  — sibling Junos-source pair (Junos -> Cisco IOS-XE) covering the
  same EVPN-VXLAN / apply-groups / instance-type concepts at a
  router target.
- [`../arista_eos_to_fortigate_cli/_INDEX.md`](../arista_eos_to_fortigate_cli/_INDEX.md)
  — sibling FortiGate-target pair (Arista -> FortiGate) covering
  the role-mismatch loss surface.
