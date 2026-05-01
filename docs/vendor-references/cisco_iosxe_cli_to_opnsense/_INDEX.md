# Cisco IOS-XE CLI to OPNsense — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/cisco_iosxe_cli__opnsense.yaml`
per-field expectations.  See `tests/fixtures/cross_vendor_expectations/
README.md` for the canonical schema definition.

This pair is a switch/router-to-firewall translation.  Cisco IOS-XE
is a switching-and-routing platform; OPNsense is a FreeBSD-based
router/firewall (pfSense fork).  The shared surface is small but
clean (hostname / domain / DNS / NTP / interface IPs / VLAN tags /
basic SNMP / local users / RADIUS).  Switching constructs (switchport
modes, spanning-tree, VTP) and Cisco multi-VRF / multi-protocol
routing are firmly out of scope on the OPNsense side.  OPNsense's
firewall / NAT / VPN feature set is firmly out of scope on the Cisco
side.

| Topic | Summary |
|---|---|
| `system_services.md` | Hostname / domain / DNS / NTP / syslog / timezone — small canonical surface. |
| `interfaces.md` | Cisco speed-encoded port names versus OPNsense BSD device names + zone labels (`<wan>` / `<lan>` / `<optN>`). |
| `vlans.md` | Cisco VLAN-with-port-membership versus OPNsense VLAN-as-tagged-sub-interface. |
| `static_routes.md` | Cisco `ip route` versus OPNsense's two-block `<gateways>` + `<staticroutes>` model. |
| `dhcp.md` | Cisco `ip dhcp pool` versus OPNsense interface-keyed `<dhcpd>` block. |
| `snmp.md` | v1/v2c surface round-trips; SNMPv3 USM lives in OPNsense plugin's snmpd.conf, not config.xml. |
| `local_users.md` | Cisco type-9 scrypt versus OPNsense bcrypt; hash formats are NOT cross-compatible. |
| `radius.md` | RADIUS server config — round-trips host / port pair; type-7 obfuscated keys are lossy. |
| `lags.md` | Cisco `Port-channel<N>` versus OPNsense `lagg(4)` driver naming + LACP-mode collapse. |
| `switchport_unsupported.md` | OPNsense has no switching fabric — switchport modes / STP / VTP are all unsupported. |
| `vrf_unsupported.md` | OPNsense has no VRF model — Cisco multi-VRF migrations need redesign. |
| `firewall_natively_unsupported.md` | Cisco IOS-XE ACL / NAT / crypto surfaces never reach canonical; OPNsense firewall rules are out of scope. |

Retrieved over 2026-04-30 to 2026-04-30.

## See also

- `../README.md` — citation cache layout (top-level index).
- `../opnsense_to_cisco_iosxe_cli/_INDEX.md` — reverse direction.
- `../../../tests/fixtures/cross_vendor_expectations/README.md` — schema spec.
