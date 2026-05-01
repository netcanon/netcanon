# OPNsense to Cisco IOS-XE CLI — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/opnsense__cisco_iosxe_cli.yaml`
per-field expectations.  See `tests/fixtures/cross_vendor_expectations/
README.md` for the canonical schema definition.

This pair is the reverse of `cisco_iosxe_cli_to_opnsense/`.  OPNsense
is a FreeBSD-based router/firewall; Cisco IOS-XE is a switching-and-
routing platform.  The asymmetry from the forward direction is
sharp:

- Cisco-source fields like switchport state and VRF membership
  marked `unsupported` on the OPNsense target are
  `not_applicable` on the OPNsense source — OPNsense's parser
  never populates those fields, so there's nothing to lose.
- OPNsense-source fields like firewall rules / NAT / VPN
  (which the OPNsense codec marks unsupported on parse) are
  similarly `unsupported` on the Cisco target.

| Topic | Summary |
|---|---|
| `system_services.md` | Hostname / domain are good; DNS / NTP / syslog / timezone are lossy pending OPNsense parse wire-up. |
| `interfaces.md` | OPNsense zone labels (`<wan>` / `<lan>` / `<optN>`) versus Cisco speed-encoded port names. |
| `vlans.md` | OPNsense VLAN-as-tagged-sub-interface versus Cisco VLAN-with-port-membership; tagged_ports / SVI lossy on this direction. |
| `static_routes.md` | OPNsense's two-block `<gateways>` + `<staticroutes>` model versus Cisco bare-next-hop `ip route`; not currently parsed by OPNsense codec. |
| `dhcp.md` | OPNsense interface-keyed `<dhcpd>` versus Cisco named `ip dhcp pool`; lease-time units conversion. |
| `snmp.md` | v1/v2c surface round-trips; SNMPv3 is not_applicable from OPNsense source (lives in plugin's snmpd.conf). |
| `local_users.md` | bcrypt (`$2y$`) hashes don't apply on Cisco; password authentication fails post-migration. |
| `radius.md` | Host / port / shared-secret round-trip cleanly; RADIUS protocol selection is OPNsense-specific. |
| `lags.md` | OPNsense `lagg<N>` versus Cisco `Port-channel<N>`; non-LACP modes degrade. |
| `switching_not_modeled.md` | OPNsense never populates switchport / spanning-tree / VTP — not_applicable from this source. |
| `vrf_not_modeled.md` | OPNsense has no VRF model — not_applicable from this source. |
| `firewall_drops_on_render.md` | OPNsense filter / NAT / VPN never reach canonical; Cisco render emits nothing for those surfaces. |

Retrieved over 2026-04-30 to 2026-04-30.

## See also

- `../README.md` — citation cache layout (top-level index).
- `../cisco_iosxe_cli_to_opnsense/_INDEX.md` — forward direction.
- `../../../tests/fixtures/cross_vendor_expectations/README.md` — schema spec.
