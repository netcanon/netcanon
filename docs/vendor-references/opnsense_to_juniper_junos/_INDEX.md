# OPNsense to Juniper Junos — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/opnsense__juniper_junos.yaml`
per-field expectations.  See `tests/fixtures/cross_vendor_expectations/
README.md` for the canonical schema definition.

This is the reverse direction of `juniper_junos_to_opnsense/`.  The
dispositions are NOT symmetric: where Junos -> OPNsense degrades
because Junos models richer surface than OPNsense expresses, the
OPNsense -> Junos direction degrades because OPNsense's parse path
is incomplete on several wire-format-supported elements (DNS, NTP,
syslog, timezone, static routes), and OPNsense's source feature
footprint is much smaller than Junos accepts.

Most Junos-only L3 / DC surface (VRFs, VXLAN, EVPN, apply-groups) is
structurally absent on OPNsense parse rather than actively dropped
on render — `not_applicable` rather than `unsupported`.

| Topic | Summary |
|---|---|
| `system_services.md` | OPNsense `<system>` (hostname / domain / DNS / NTP / syslog / timezone) versus Junos `set system` directives.  Hostname / domain `good`; the rest `lossy` until OPNsense codec parse wires up the `<system>` children. |
| `interfaces.md` | OPNsense zone-label `<wan>` / `<lan>` / `<optN>` mapped to BSD `<if>` versus Junos `ge-0/0/0` / `ae0` / `irb` per-unit family hierarchy. |
| `vlans.md` | OPNsense VLAN-as-tagged-sub-interface (parent `<if>` + tag) versus Junos name-keyed VLAN with per-interface `family ethernet-switching vlan members`. |
| `static_routes.md` | OPNsense two-block `<gateways>` + `<staticroutes>` (codec wire-up incomplete) versus Junos `set routing-options static route X/N next-hop Y`. |
| `dhcp.md` | OPNsense interface-keyed `<dhcpd><zone>` pool versus Junos two-stage `dhcp-local-server` + `address-assignment pool`. |
| `snmp.md` | OPNsense `<snmpd>` round-trips v1/v2c; SNMPv3 USM is `not_applicable` on this direction (lives in plugin's snmpd.conf, never reaches canonical from OPNsense). |
| `local_users.md` | OPNsense bcrypt + group-binary versus Junos `$6$` SHA-512 + named class.  Hash format incompatibility is the principal lossy axis. |
| `radius.md` | OPNsense `<authserver>` + plaintext shared secret versus Junos `set system radius-server <ip>` (Junos auto-encrypts on commit). |
| `lags.md` | OPNsense `<laggs>` (lagg(4) driver) + comma-separated members versus Junos `ae<N>` + per-member `ether-options 802.3ad` back-pointer. |
| `vrf_unsupported.md` | OPNsense never models VRFs — `not_applicable` on the OPNsense source, Junos target receives nothing to render. |
| `vxlan_evpn_unsupported.md` | OPNsense never models VXLAN/EVPN — `not_applicable` on the OPNsense source. |
| `firewall_role_mismatch.md` | OPNsense's firewall / NAT / VPN never reach canonical; Junos target couldn't render them anyway. |

Retrieved 2026-04-30 to 2026-05-01.

## See also

- `../README.md` — citation cache layout (top-level index).
- `../juniper_junos_to_opnsense/_INDEX.md` — reverse direction.
- `../../../tests/fixtures/cross_vendor_expectations/README.md` — schema spec.
