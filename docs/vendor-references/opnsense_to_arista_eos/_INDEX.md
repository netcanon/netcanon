# OPNsense to Arista EOS — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/opnsense__arista_eos.yaml`
per-field expectations.  See `tests/fixtures/cross_vendor_expectations/
README.md` for the canonical schema definition.

This pair is a firewall-to-DC-switch translation — the reverse of
the `arista_eos_to_opnsense/` direction.  OPNsense source carries
firewall-shape state (zones, gateways, dhcpd interface-keyed pools,
authservers) that has no first-class destination on an Arista DC
switch.  Arista's DC switching state (per-port switchport modes,
spanning-tree, voice-VLAN), VRF / EVPN-VXLAN fabric, and BGP
control-plane are structurally absent on OPNsense parse because
OPNsense never models those concepts to begin with.

The asymmetry from the forward direction:

- Switching state: not_applicable here (OPNsense never carries it),
  was unsupported on the forward direction (Arista carried it,
  OPNsense couldn't render).
- VRF / EVPN-VXLAN: not_applicable here (OPNsense never carries
  them), was unsupported on the forward direction.
- DHCP server pools: lossy here (OPNsense has them, Arista accepts
  them with codec wire-up gap), was lossy on the forward direction
  too.

| Topic | Summary |
|---|---|
| `system_services.md` | OPNsense `<system>` (hostname / domain / DNS / NTP / syslog / timezone) versus Arista bare directives. |
| `interfaces.md` | OPNsense zone-label `<wan>` / `<lan>` / `<optN>` mapped to BSD `<if>` versus Arista flat `Ethernet<N>` / `Vlan<N>` / `Loopback<N>` / `Port-Channel<N>`. |
| `vlans.md` | OPNsense VLAN-as-tagged-sub-interface versus Arista per-port `switchport` (transposed onto `CanonicalVlan` lists). |
| `static_routes.md` | OPNsense two-block `<gateways>` + `<staticroutes>` model versus Arista flat `ip route`. |
| `dhcp.md` | OPNsense `<dhcpd>` interface-keyed pool versus Arista named `ip dhcp pool`. |
| `snmp.md` | OPNsense `<snmpd>` round-trips v1/v2c; SNMPv3 USM lives in plugin's snmpd.conf and is not_applicable here. |
| `local_users.md` | OPNsense bcrypt versus Arista `$1$` / `$6$` crypt forms; cross-vendor hash incompatibility. |
| `radius.md` | OPNsense `<authserver>` versus Arista flat `radius-server host` form. |
| `lags.md` | OPNsense `<laggs>` (lagg(4) driver, zero-based) versus Arista `Port-Channel<N>` (one-based). |
| `switching_not_modeled.md` | OPNsense has no switching state to lose; the direction never carries switchport intent. |
| `vrf_unsupported.md` | OPNsense `config.xml` has no VRF / EVPN-VXLAN schema — Arista's overlay surface is structurally absent on parse. |
| `firewall_drops_on_render.md` | OPNsense firewall / NAT / VPN / captive-portal stay in `raw_sections`; Arista target couldn't render them as ACLs anyway. |

Retrieved over 2026-04-30 to 2026-05-01.

## See also

- `../README.md` — citation cache layout (top-level index).
- `../arista_eos_to_opnsense/_INDEX.md` — reverse direction.
- `../opnsense_to_aruba_aoss/_INDEX.md` — sister OPNsense-source pair (firewall-to-campus).
- `../opnsense_to_cisco_iosxe_cli/_INDEX.md` — sister OPNsense-source pair (firewall-to-IOS-XE).
- `../../../tests/fixtures/cross_vendor_expectations/README.md` — schema spec.
