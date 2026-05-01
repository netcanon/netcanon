# FortiGate FortiOS CLI to Cisco IOS-XE CLI — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/fortigate_cli__cisco_iosxe_cli.yaml`
per-field expectations.  See sibling
[`README.md`](../../../tests/fixtures/cross_vendor_expectations/README.md)
for the canonical schema definition.

This is the reverse-direction sibling of
[`../cisco_iosxe_cli_to_fortigate_cli/_INDEX.md`](../cisco_iosxe_cli_to_fortigate_cli/_INDEX.md).
The vendor source URLs are identical; what differs is the
cross-vendor-migration perspective:

- **Forward** (Cisco -> FortiGate): switching features lose their
  target on FortiGate; FortiGate-only firewall semantics are absent
  from the source.
- **Reverse** (FortiGate -> Cisco): FortiGate's L3-firewall focus
  means the canonical tree never carries L2 switching intent;
  Cisco render emits routed-port-only configurations.  FortiGate's
  rich firewall / UTM surface has no Cisco analogue at all.

| Topic | Summary |
|---|---|
| [`system_services.md`](system_services.md) | Hostname / DNS / NTP / syslog / timezone — direction-asymmetric losses (FortiGate's tighter DNS / syslog schemas don't bottleneck the reverse path; canonical's per-server-options gap and timezone-format mismatch do). |
| [`interface_naming.md`](interface_naming.md) | FortiGate flat namespace (`port1`, `wan1`) -> Cisco speed-prefixed (`GigabitEthernet0/0/N`); render must invent speed prefixes (defaulting to 1G). |
| [`ip_addressing.md`](ip_addressing.md) | Both vendors use dotted-decimal masks for IPv4; FortiGate parse drops secondaries and link-local scope before they reach the canonical tree. |
| [`vlans.md`](vlans.md) | FortiGate child-interface VLAN model -> Cisco first-class `vlan` global object.  Port-membership is a model translation gap (FortiGate's parent-interface model carries no canonical port list per VLAN). |
| [`switchport.md`](switchport.md) | FortiGate has no L2 surface to populate `switchport_*` from; Cisco render emits routed ports for every interface. |
| [`static_routes.md`](static_routes.md) | FortiOS `config router static / set dst / set gateway` -> Cisco `ip route ...`.  Default routes round-trip cleanly. |
| [`snmp.md`](snmp.md) | FortiGate `config system snmp community / user` -> Cisco `snmp-server community / user`.  Multi-community FortiGate configs collapse on canonical-side. |
| [`local_users.md`](local_users.md) | FortiGate `config system admin / set accprofile / set password ENC ...` -> Cisco `username X privilege Y secret 9 $9$...`.  Hash formats are NOT cross-compatible. |
| [`aaa.md`](aaa.md) | FortiGate `config user radius` -> Cisco `radius server <name>`.  Shared-secret formats incompatible. |
| [`dhcp.md`](dhcp.md) | FortiGate's interface-bound `config system dhcp server` -> Cisco's pool-only `ip dhcp pool`.  Cisco IOS-XE codec does not advertise DHCP render in v1; cross-pair drops DHCP entirely. |
| [`lags.md`](lags.md) | FortiGate operator-named aggregates -> Cisco synthetic `Port-channel<N>` integer ID.  LACP modes preserve. |
| [`vrf.md`](vrf.md) | FortiGate VDOMs / per-interface integer VRF IDs versus Cisco named VRF model.  Both codecs parse-and-ignore VRF intent in v1. |
| [`routing_protocols.md`](routing_protocols.md) | BGP / OSPF / RIP / IS-IS — canonical-schema gap; FortiOS's FRR-based grammar shares Cisco surface form but neither codec wires through. |
| [`firewall_policy.md`](firewall_policy.md) | FortiGate's `config firewall policy / vip / address` is the primary product surface; no canonical model.  Cisco-side ACL / ZBF / NAT.  Out of scope. |

Retrieved over 2026-04-30.

See also:
- [`../README.md`](../README.md) — citation cache layout.
- [`../cisco_iosxe_cli_to_fortigate_cli/_INDEX.md`](../cisco_iosxe_cli_to_fortigate_cli/_INDEX.md)
  — forward-direction index (Cisco -> FortiGate).
- [`../arista_eos_to_juniper_junos/_INDEX.md`](../arista_eos_to_juniper_junos/_INDEX.md)
  — sibling cross-vendor pair (DC EVPN-VXLAN focus).
