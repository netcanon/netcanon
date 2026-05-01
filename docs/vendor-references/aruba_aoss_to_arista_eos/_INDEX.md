# Aruba AOS-S to Arista EOS — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/aruba_aoss__arista_eos.yaml`
per-field expectations.  See sibling
`tests/fixtures/cross_vendor_expectations/README.md` for the
canonical schema definition.

This pair is part of the **aruba_aoss mesh sweep**.  Aruba AOS-S
(ProCurve heritage L2/basic-L3 campus switch) is a strict subset
of Arista EOS's feature surface — the asymmetry is "source has
fewer features than target accepts", so Cisco-style rich-target
losses (VRF, VXLAN, EVPN, BGP) don't apply on this direction (the
fields are structurally empty on the Aruba source).

The good news: Arista EOS deliberately mirrors Cisco IOS CLI
grammar, and Aruba ProCurve's lineage is also Cisco-CLI-flavoured,
so the keyword-stable surface (`hostname`, `vlan N`, `snmp-server`,
`radius-server`, CIDR addressing) tracks cleanly.

| Topic | Summary |
|---|---|
| `vlans.md` | Aruba VLAN-centric `untagged 1-24 / ip address X/N` -> Arista port-centric `switchport access vlan N` + separate `interface Vlan<N>`.  CIDR form preserved on both sides. |
| `port_naming.md` | Aruba bare-numeric `1` / `A1` / `1/1` -> Arista `Ethernet1` (no speed token); Aruba `Trk<N>` -> Arista `Port-Channel<N>` (capital 'C'). |
| `ip_addressing.md` | Both vendors accept CIDR natively; no dotted-mask conversion noise.  IPv6 `link-local` discriminator preserved. |
| `static_routes.md` | Aruba CIDR `ip route X/N <gw>` -> Arista CIDR `ip route X/N <gw>`.  `ip default-gateway` legacy form normalises.  Aruba never carries per-VRF routes. |
| `snmp.md` | v1/v2c quoted-community + Operator/Manager mapping; v3 USM passphrases not cross-compatible. |
| `local_users.md` | Aruba two-role (manager/operator) -> Arista `privilege + role`; SHA-1 / bcrypt hashes Aruba-only. |
| `lags.md` | Aruba `Trk<N>` -> Arista `Port-Channel<N>` (capital 'C'); `dt-lacp` / `fec` modes lossy. |
| `system_services.md` | Hostname (quoted -> bare) / DNS (priority-ordered -> flat) / SNTP -> NTP keyword change / minute-offset timezone -> zoneinfo timezone. |
| `vrf_unsupported.md` | Aruba has no VRF concept; field always empty on this direction. |
| `vxlan_unsupported.md` | Aruba has no VXLAN/EVPN concept; field always empty on this direction. |
| `radius.md` | Both vendors share Cisco-derived `radius-server host` + global key form; round-trips cleanly. |

Retrieved 2026-04-30 to 2026-05-01.

See also: `../README.md` (citation cache layout),
`../arista_eos_to_aruba_aoss/_INDEX.md` (the inverse pair).
