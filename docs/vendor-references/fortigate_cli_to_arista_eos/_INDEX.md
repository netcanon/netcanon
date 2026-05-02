# FortiGate FortiOS CLI to Arista EOS — vendor reference index

Curated vendor-doc excerpts grounding the
[`tests/fixtures/cross_vendor_expectations/fortigate_cli__arista_eos.yaml`](../../../tests/fixtures/cross_vendor_expectations/fortigate_cli__arista_eos.yaml)
per-field expectations.  See sibling
[`README.md`](../../../tests/fixtures/cross_vendor_expectations/README.md)
for the canonical schema definition.

This pair is a **firewall -> DC-switch** demotion: FortiGate FortiOS
(session-based stateful firewall + UTM) to Arista EOS (DC-class L2/L3
switch with EVPN-VXLAN heritage).  Less common than the reverse
direction (consolidating an Arista leaf into a FortiGate edge is the
typical pattern); fortigate -> arista surfaces when an operator
demotes a FortiGate to a pure L2/L3 routing role and offloads the
security duties to a separate appliance.

* **FortiGate's firewall + UTM product surface drops entirely.**
  Firewall policy / NAT / VIP / VPN / IPsec / UTM are FortiGate-
  only and the canonical model has no representation.  Tier-3
  raw_sections content drops with banners.
* **VDOMs and per-interface integer VRF lose their target.**
  Arista has named-VRF + RD + RT (structurally different); even if
  the FortiGate codec wired through `set vrf <id>` parse, the
  integer wouldn't carry the RD/RT semantics Arista needs.
* **VLAN port-membership is the inverse model gap.**  FortiGate's
  child-interface VLAN model never populates canonical
  tagged_ports / untagged_ports, so Arista render emits VLAN
  stanzas with empty port lists — operator must reconstruct
  per-port switchport state.
* **Foundations translate.**  Hostname / DNS / NTP / SNMP / RADIUS /
  static-routes / local-users / LAGs / IPv4 + IPv6 (global)
  round-trip via the canonical tree.

| Topic | Summary |
|---|---|
| [`system_services.md`](system_services.md) | Hostname / DNS / NTP / syslog / clock / domain.  FortiOS-source list lengths fit comfortably in Arista's unbounded targets. |
| [`interfaces.md`](interfaces.md) | Naming (flat port1/agg1 vs CamelCase Ethernet/Port-Channel), dotted-mask vs CIDR, IPv6 link-local n/a, MTU, type-discriminator. |
| [`vlans.md`](vlans.md) | FortiGate child-interface VLAN model yields empty canonical port-lists; Arista render needs them — operator must reconstruct switchport state. |
| [`static_routes.md`](static_routes.md) | Default-VRF round-trip via dotted-mask <-> CIDR conversion.  Per-VRF / IPv6 / per-comment gaps. |
| [`snmp_aaa.md`](snmp_aaa.md) | SNMP scalars good; multi-community collapses; v3 USM passphrases not cross-compatible.  RADIUS shared-secret incompatible (FortiOS ENC). |
| [`local_users.md`](local_users.md) | Named accprofile (super_admin/prof_admin/custom) -> numeric privilege + role string flattening.  Hashes incompatible (ENC vs sha512_crypt). |
| [`lags.md`](lags.md) | FortiGate operator-named aggregates (agg<N>) -> Arista mandated `Port-Channel<N>` form.  LACP modes round-trip. |
| [`firewall_unsupported.md`](firewall_unsupported.md) | Firewall policy / NAT / VIP / VPN / IPsec / VDOMs / per-interface integer VRF — FortiGate's primary product surface, no Arista target. |

Retrieved 2026-05-01.

See also:
- [`../README.md`](../README.md) — citation cache layout.
- [`../arista_eos_to_fortigate_cli/_INDEX.md`](../arista_eos_to_fortigate_cli/_INDEX.md)
  — reverse-direction sibling (Arista DC-leaf -> FortiGate firewall).
- [`../fortigate_cli_to_aruba_aoss/_INDEX.md`](../fortigate_cli_to_aruba_aoss/_INDEX.md)
  — sibling FortiGate-source pair (FortiGate -> Aruba AOS-S campus switch).
- [`../fortigate_cli_to_cisco_iosxe_cli/_INDEX.md`](../fortigate_cli_to_cisco_iosxe_cli/_INDEX.md)
  — sibling FortiGate-source pair (FortiGate -> Cisco IOS-XE).
