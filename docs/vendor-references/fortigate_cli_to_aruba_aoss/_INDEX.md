# FortiGate FortiOS CLI to Aruba AOS-S — vendor reference index

Curated vendor-doc excerpts grounding the
[`tests/fixtures/cross_vendor_expectations/fortigate_cli__aruba_aoss.yaml`](../../../tests/fixtures/cross_vendor_expectations/fortigate_cli__aruba_aoss.yaml)
per-field expectations.  See sibling
[`README.md`](../../../tests/fixtures/cross_vendor_expectations/README.md)
for the canonical schema definition.

This is the reverse-direction sibling of
[`../aruba_aoss_to_fortigate_cli/_INDEX.md`](../aruba_aoss_to_fortigate_cli/_INDEX.md).
The vendor source URLs are identical; what differs is the
cross-vendor-migration perspective:

- **Forward** (Aruba -> FortiGate): Aruba's L2 surface loses its
  target on FortiGate; FortiGate's firewall surface is structurally
  absent on Aruba source.
- **Reverse** (FortiGate -> Aruba): FortiGate's L3-firewall focus
  means the canonical tree never carries L2 switching intent;
  Aruba render emits VLAN stanzas with empty port-membership
  lists.  FortiGate's firewall / NAT / VPN / UTM / VDOM product
  surface has no Aruba analogue at all and is lost on migration.

| Topic | Summary |
|---|---|
| [`system_services.md`](system_services.md) | Hostname / DNS / NTP-vs-SNTP / syslog / clock — direction-asymmetric losses (FortiGate's tighter DNS / syslog schemas don't bottleneck the reverse path; canonical's domain render gap and timezone format mismatch do). |
| [`interface_naming.md`](interface_naming.md) | FortiGate flat namespace (`port1`, `wan1`) -> Aruba bare-numeric (`1`, `A1`).  Port-rename mesh required (Aruba `_IFACE_HEADER_RE` rejects FortiGate names verbatim). |
| [`ip_addressing.md`](ip_addressing.md) | FortiOS dotted-only -> Aruba CIDR via the codec helpers.  IPv6 link-local scope discriminator lossy on this direction (FortiGate parse drops it). |
| [`vlans.md`](vlans.md) | FortiGate child-interface VLAN model -> Aruba first-class `vlan` global object.  Port-membership is a hard model-translation gap (FortiGate parent-interface model carries no canonical port list per VLAN). |
| [`switchport.md`](switchport.md) | FortiGate has no L2 surface to populate switchport_*; Aruba target receives empty switchport / VLAN-port-list canonical fields. |
| [`static_routes.md`](static_routes.md) | FortiOS `config router static` -> Aruba `ip route ...`.  Default routes round-trip cleanly; outgoing-interface lossy (Aruba has no field). |
| [`snmp.md`](snmp.md) | FortiGate `config system snmp community / user` -> Aruba `snmp-server community / snmpv3 user ...`.  Multi-community configs collapse on canonical-side; v3 USM passphrases not cross-compatible (engineID-salting). |
| [`local_users.md`](local_users.md) | FortiGate accprofile strings -> Aruba two-role model (super_admin -> manager; others -> operator).  Hash formats incompatible (FortiOS ENC vs Aruba sha1/bcrypt). |
| [`radius.md`](radius.md) | FortiGate edit-table -> Aruba flat host-keyed form.  Shared-secret format incompatible. |
| [`dhcp.md`](dhcp.md) | FortiGate first-class DHCP-server pools have NO Aruba target — AOS-S is relay-only and the codec doesn't render pools.  **Unsupported** on this direction. |
| [`lags.md`](lags.md) | FortiGate operator-named aggregates -> Aruba `Trk<N>` synthesised integer ID.  Mode coercion loses FortiGate `passive` distinction. |
| [`vrf.md`](vrf.md) | FortiGate VDOMs / per-interface integer VRF unmodelled in canonical v1; Aruba has no VRF concept.  Unsupported. |
| [`routing_protocols.md`](routing_protocols.md) | FortiOS BGP / OSPF / IS-IS / RIP not in canonical model; Aruba has no BGP / IS-IS at all. |
| [`firewall_policy.md`](firewall_policy.md) | FortiGate's primary product surface; no canonical model and no Aruba analogue.  Operators must keep an upstream firewall. |
| [`spanning_tree.md`](spanning_tree.md) | FortiGate carries no STP intent; Aruba target requires STP but operators configure manually post-migration. |

Retrieved over 2026-04-30 to 2026-05-01.

See also:
- [`../README.md`](../README.md) — citation cache layout.
- [`../aruba_aoss_to_fortigate_cli/_INDEX.md`](../aruba_aoss_to_fortigate_cli/_INDEX.md)
  — forward-direction sibling (Aruba switch -> FortiGate firewall).
- [`../fortigate_cli_to_cisco_iosxe_cli/_INDEX.md`](../fortigate_cli_to_cisco_iosxe_cli/_INDEX.md)
  — sibling firewall-to-router pair (FortiGate -> Cisco IOS-XE).
- [`../aruba_aoss_to_cisco_iosxe_cli/_INDEX.md`](../aruba_aoss_to_cisco_iosxe_cli/_INDEX.md)
  — sibling Aruba-target pair (Aruba -> Cisco IOS-XE).
