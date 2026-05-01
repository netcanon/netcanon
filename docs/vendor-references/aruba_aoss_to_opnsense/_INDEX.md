# Aruba AOS-S to OPNsense — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/aruba_aoss__opnsense.yaml`
per-field expectations.  See `tests/fixtures/cross_vendor_expectations/
README.md` for the canonical schema definition.

This pair is a switch-to-firewall translation.  Aruba AOS-S is an
enterprise campus L2/basic-L3 switch (ProCurve heritage); OPNsense is
a FreeBSD-based router/firewall (pfSense fork).  The two vendor roles
barely overlap.  The shared canonical surface is small: hostname /
DNS / interface IPs / VLAN tags / SNMP v1/v2c / local users / RADIUS
/ LAGs.  Aruba's switching state (switchport-mode-equivalent
`tagged` / `untagged` port lists, spanning-tree, dhcp-snooping,
LLDP-MED voice VLAN) is firmly out of scope on the OPNsense side, and
OPNsense's firewall / NAT / VPN / captive-portal / plugin surface is
firmly out of scope on the Aruba side.

| Topic | Summary |
|---|---|
| `system_services.md` | Hostname / DNS / SNTP / syslog / timezone — small canonical surface; Aruba has no domain directive. |
| `interfaces.md` | Aruba bare-numeric ports (`1`, `A1`) versus OPNsense BSD device names + zone labels (`<wan>` / `<lan>` / `<optN>`). |
| `vlans.md` | Aruba VLAN-centric port-membership versus OPNsense VLAN-as-tagged-sub-interface. |
| `static_routes.md` | Aruba CIDR `ip route` versus OPNsense's two-block `<gateways>` + `<staticroutes>` model. |
| `dhcp_relay_versus_pool.md` | Aruba is relay-only; canonical `dhcp_servers` always empty on this direction. |
| `snmp.md` | v1/v2c surface round-trips; SNMPv3 USM lives in OPNsense plugin's snmpd.conf, not config.xml. |
| `local_users.md` | Aruba SHA-1 / bcrypt / plaintext versus OPNsense bcrypt; hash formats are not cross-compatible. |
| `radius.md` | RADIUS server config — round-trips host / port pair / shared key. |
| `lags.md` | Aruba `Trk<N>` versus OPNsense `lagg(4)` driver naming + LACP-mode collapse. |
| `switchport_unsupported.md` | OPNsense has no switching fabric — tagged/untagged port lists, spanning-tree, voice VLAN are all unsupported. |
| `vrf_unsupported.md` | Neither vendor models VRFs — structurally absent on both ends. |
| `firewall_natively_unsupported.md` | OPNsense firewall / NAT / VPN never reach canonical from an Aruba source; informational only. |

Retrieved over 2026-04-30 to 2026-05-01.

## See also

- `../README.md` — citation cache layout (top-level index).
- `../opnsense_to_aruba_aoss/_INDEX.md` — reverse direction.
- `../../../tests/fixtures/cross_vendor_expectations/README.md` — schema spec.
