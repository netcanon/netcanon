# OPNsense to Aruba AOS-S — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/opnsense__aruba_aoss.yaml`
per-field expectations.  See `tests/fixtures/cross_vendor_expectations/
README.md` for the canonical schema definition.

This pair is a firewall-to-switch translation — the reverse of the
`aruba_aoss_to_opnsense/` direction.  OPNsense source carries
firewall-shape state (zones, gateways, dhcpd interface-keyed pools)
that has no first-class destination on an Aruba campus switch.
Aruba's switching state (per-VLAN tagged/untagged port lists,
spanning-tree, voice-VLAN) is structurally absent on OPNsense parse
because OPNsense never models those concepts to begin with.

| Topic | Summary |
|---|---|
| `system_services.md` | OPNsense `<system>` (hostname / domain / DNS / NTP / syslog / timezone) versus Aruba bare directives. |
| `interfaces.md` | OPNsense zone-label `<wan>` / `<lan>` / `<optN>` mapped to BSD `<if>` versus Aruba bare-numeric / letter-uplink port names. |
| `vlans.md` | OPNsense VLAN-as-tagged-sub-interface versus Aruba VLAN-centric port-membership. |
| `static_routes.md` | OPNsense two-block `<gateways>` + `<staticroutes>` model versus Aruba CIDR `ip route`. |
| `dhcp_relay_versus_pool.md` | OPNsense `<dhcpd>` interface-keyed pool versus Aruba relay-only platform. |
| `snmp.md` | OPNsense `<snmpd>` round-trips v1/v2c; SNMPv3 USM lives in plugin's snmpd.conf and is unsupported. |
| `local_users.md` | OPNsense bcrypt versus Aruba SHA-1 / bcrypt / plaintext; hash compatibility is partial at best. |
| `radius.md` | OPNsense `<authserver>` versus Aruba flat `radius-server host` form. |
| `lags.md` | OPNsense `<laggs>` (lagg(4) driver) versus Aruba `Trk<N>`. |
| `switchport_unsupported.md` | OPNsense has no switching state to lose; the direction never carries switchport intent. |
| `vrf_unsupported.md` | Neither vendor models VRFs — structurally absent on both ends. |
| `firewall_natively_unsupported.md` | OPNsense firewall / NAT / VPN / captive-portal stay in `raw_sections`; Aruba target couldn't render them anyway. |

Retrieved over 2026-04-30 to 2026-05-01.

## See also

- `../README.md` — citation cache layout (top-level index).
- `../aruba_aoss_to_opnsense/_INDEX.md` — reverse direction.
- `../../../tests/fixtures/cross_vendor_expectations/README.md` — schema spec.
