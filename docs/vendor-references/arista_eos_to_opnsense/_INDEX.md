# Arista EOS to OPNsense — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/arista_eos__opnsense.yaml`
per-field expectations.  See `tests/fixtures/cross_vendor_expectations/
README.md` for the canonical schema definition.

This pair is a DC-switch-to-firewall translation.  Arista EOS is a
DC-class L2/L3 switch deployed as the leaf in EVPN-VXLAN spine-leaf
fabrics; OPNsense is a FreeBSD-based router/firewall (pfSense fork).
The wire-format mismatch is severe — Arista stanza CLI versus
OPNsense `config.xml` — and the role mismatch is even sharper.  The
shared canonical surface is small: hostname / domain / DNS / NTP /
syslog / interface IPs / VLAN tags / SNMP v1/v2c / RADIUS / local
users / LAGs.  Arista's EVPN-VXLAN fabric (vxlan_vnis,
evpn_type5_routes, routing_instances, per-interface VRF), all
switching state (switchport modes, spanning-tree, voice-VLAN), and
spine-leaf BGP control-plane are firmly out of scope on the OPNsense
side.  OPNsense's firewall / NAT / VPN / captive-portal / plugin
surface is firmly out of scope on the Arista side.

| Topic | Summary |
|---|---|
| `system_services.md` | Hostname / domain / DNS / NTP / syslog / timezone — small canonical surface; OPNsense `<system>` parser wire-up is incomplete on several children. |
| `interfaces.md` | Arista flat `Ethernet<N>` / `Port-Channel<N>` / `Vlan<N>` / `Loopback<N>` versus OPNsense BSD device names + zone labels (`<wan>` / `<lan>` / `<optN>`). |
| `vlans.md` | Arista per-port `switchport access/trunk` (transposed onto `CanonicalVlan` lists) versus OPNsense VLAN-as-tagged-sub-interface. |
| `static_routes.md` | Arista flat `ip route` versus OPNsense's two-block `<gateways>` + `<staticroutes>` model. |
| `dhcp.md` | Arista named `ip dhcp pool` versus OPNsense interface-keyed `<dhcpd>` blocks; codec wire-up partial on OPNsense side. |
| `snmp.md` | v1/v2c surface round-trips; SNMPv3 USM lives in OPNsense plugin's snmpd.conf, not config.xml. |
| `local_users.md` | Arista `$1$` MD5-crypt / `$6$` SHA-512-crypt versus OPNsense bcrypt-only; hash formats are not cross-compatible. |
| `radius.md` | RADIUS server config — round-trips host / port pair / shared key. |
| `lags.md` | Arista `Port-Channel<N>` versus OPNsense `lagg(4)` driver naming + LACP-mode collapse. |
| `switchport_unsupported.md` | OPNsense has no switching fabric — switchport modes, spanning-tree, voice-VLAN are all unsupported. |
| `vxlan_evpn_unsupported.md` | Arista EVPN-VXLAN fabric (VNI bindings, L3 VNI, VRFs, BGP RD/RT) has no destination on OPNsense. |
| `firewall_natively_unsupported.md` | Arista ACLs stay in `raw_sections`; OPNsense firewall surface is structurally absent on the canonical tree. |

Retrieved over 2026-04-30 to 2026-05-01.

## See also

- `../README.md` — citation cache layout (top-level index).
- `../opnsense_to_arista_eos/_INDEX.md` — reverse direction.
- `../arista_eos_to_juniper_junos/_INDEX.md` — sister Arista-source pair (DC-to-DC).
- `../../../tests/fixtures/cross_vendor_expectations/README.md` — schema spec.
