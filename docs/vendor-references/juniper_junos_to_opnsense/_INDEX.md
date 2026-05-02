# Juniper Junos to OPNsense — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/juniper_junos__opnsense.yaml`
per-field expectations.  See `tests/fixtures/cross_vendor_expectations/
README.md` for the canonical schema definition.

This is a **DC-class router → FreeBSD-firewall** pair.  Junos is a
full DC-class router with rich EVPN-VXLAN, apply-groups inheritance,
two-pass parse, and per-instance VRF surface.  OPNsense is a FreeBSD-
based open-source router/firewall (pfSense fork).  Two very different
roles meet over a small shared canonical surface:

* hostname / domain — good
* DNS / NTP / syslog / timezone — lossy until OPNsense parse + render
  wires up the corresponding `<system>` children
* interfaces (IP, MTU, enable, descr) — good
* VLANs — id good; name/description collapse; port-membership and
  SVI sub-fields unsupported (OPNsense has no VLAN-centric port
  lists, no first-class SVI)
* Static routes — lossy (OPNsense `<gateways>` + `<staticroutes>`
  model is two-stage, codec doesn't currently render either)
* DHCP server scopes — lossy (Junos two-stage `dhcp-local-server`
  versus OPNsense interface-keyed pool, plus codec wire-up gaps)
* SNMP v1/v2c — good; SNMPv3 USM unsupported (lives in OPNsense
  plugin's snmpd.conf, not config.xml)
* Local users — lossy (Junos `$6$` SHA-512 / ssh-rsa versus OPNsense
  bcrypt; class versus group-binary)
* RADIUS — good for host/port; lossy on shared-secret encryption
* LAGs — lossy (`ae<N>` ↔ `lagg<N>` rename, LACP-mode collapse)
* VRFs / routing-instances — unsupported on OPNsense (no model)
* VXLAN / EVPN — unsupported on OPNsense (no model)
* apply-groups — Junos-only inheritance; flattens on parse, group
  structure drops on OPNsense render

| Topic | Summary |
|---|---|
| `system_services.md` | hostname / domain / DNS / NTP / syslog / timezone — close structural match; OPNsense codec wire-up gaps drive several to lossy. |
| `interfaces.md` | Junos `ge-/xe-/et-` versus OPNsense `<wan>`/`<lan>`/`<optN>` zone tags; per-unit family hierarchy versus flat `<ipaddr>`+`<subnet>`. |
| `vlans.md` | Junos VLAN-centric `set vlans NAME vlan-id N` + `family ethernet-switching vlan members` versus OPNsense VLAN-as-tagged-sub-interface. |
| `static_routes.md` | Junos `set routing-options static route X/N next-hop Y` versus OPNsense two-block `<gateways>` + `<staticroutes>`. |
| `dhcp.md` | Junos two-stage `dhcp-local-server` + `address-assignment pool` versus OPNsense interface-keyed `<dhcpd><zone>` pool. |
| `snmp.md` | v1/v2c surface round-trips; SNMPv3 USM lives in OPNsense plugin's snmpd.conf, not config.xml. |
| `local_users.md` | Junos `class super-user / operator` + `$6$` SHA-512 versus OPNsense `<groupname>admins/users</groupname>` + bcrypt. |
| `radius.md` | Junos `set system radius-server <ip>` + `$9$...` versus OPNsense `<authserver>` + plaintext shared secret. |
| `lags.md` | Junos `ae<N>` + `aggregated-ether-options lacp` versus OPNsense `lagg<N>` + `<proto>lacp</proto>`. |
| `apply_groups.md` | Junos-only configuration inheritance (`set groups` + `set apply-groups`); flattens on parse, group structure drops on OPNsense render. |
| `vrf_routing_instances.md` | Junos `routing-instances` versus OPNsense single global routing table; structurally unsupported on OPNsense. |
| `vrf_unsupported.md` | Compact unsupported summary referenced by VRF / routing-instance fields. |
| `vxlan_evpn_unsupported.md` | Junos EVPN-VXLAN overlay (per-VLAN VNI, switch-options VTEP, Type-5 L3 VNI) — OPNsense has none. |
| `firewall_role_mismatch.md` | Junos firewall filters / policy-statements and OPNsense firewall / NAT / VPN are mutually out of scope for canonical translation. |

Retrieved 2026-04-30 to 2026-05-01.

## See also

- `../README.md` — citation cache layout (top-level index).
- `../opnsense_to_juniper_junos/_INDEX.md` — reverse direction.
- `../../../tests/fixtures/cross_vendor_expectations/README.md` — schema spec.
