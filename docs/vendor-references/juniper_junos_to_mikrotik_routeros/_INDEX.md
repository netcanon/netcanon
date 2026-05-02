# Juniper Junos to MikroTik RouterOS — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/juniper_junos__mikrotik_routeros.yaml`
per-field expectations.  See sibling `README.md` (one level up) for
the canonical schema definition.

This is a **DC-class router to SMB/WISP router** pair.  Junos = full
DC-class router with EVPN-VXLAN, apply-groups inheritance, two-pass
parse, multi-instance routing.  MikroTik RouterOS = SMB / WISP
router-first OS with rich firewall / NAT / queue / wireless / hotspot
plumbing but no fabric overlay.  Same router-class chassis but
different feature focus and target market.

The asymmetry shapes the cross-pair:

* Junos is broader on the L2/L3/EVPN-fabric / apply-groups axis;
  RouterOS is broader on the Tier-3 firewall / NAT / scripts /
  hotspot axis.  Cross-vendor migration of canonical scope discards
  RouterOS-rich plumbing (Tier-3 by design) and discards Junos
  EVPN-fabric / apply-groups (`unsupported` on RouterOS target).
* Wire formats differ fundamentally — Junos `set ...` form with
  hierarchical inheritance and per-unit interface families;
  RouterOS `/section` + `add/set` form with flat record lists.
* Keyword-stable surface (`hostname`, `dns-server`, `ntp`,
  `static route`, `snmp community`, `radius`) round-trips through
  the canonical model despite the syntactic gap.

| Topic | Summary |
|---|---|
| `system_services.md` | Hostname / DNS / NTP / timezone / syslog mapping; Junos `set system <X>` -> RouterOS `/system <X>`.  Domain attribute scope mismatch (Junos identity vs RouterOS DNS resolver). |
| `interfaces.md` | Junos media-prefix names (`ge-0/0/0`) -> RouterOS flat names (`ether1`); per-unit family addressing -> top-level `/ip address` / `/ipv6 address`; loopback / management semantics lossy. |
| `vlans.md` | Junos named VLANs + per-interface `family ethernet-switching` -> RouterOS two-plane VLAN model (`/interface vlan` Plane 1 + `/interface bridge vlan` Plane 2); SVI absorption round-trips. |
| `static_routes.md` | Junos `set routing-options static route X/N next-hop Y` -> RouterOS `/ip route add dst-address=X/N gateway=Y`.  Per-VRF routes flatten; preference / metric drift. |
| `snmp_aaa.md` | v1/v2c clean; v3 USM algorithm overlap MD5/SHA1/SHA256 + DES/AES; engineID-salted passphrases never cross-portable; multi-target trap-host drops to first on RouterOS render. |
| `local_users.md` | Junos `class super-user`/`operator`/`read-only` -> RouterOS `full`/`write`/`read`; Junos `$6$`/`$5$`/`$1$` hashes vs RouterOS opaque internal format never cross-compatible. |
| `lags.md` | Junos `ae<N>` + per-member `ether-options 802.3ad` -> RouterOS `bond<N>` + `slaves=`; LACP `802.3ad` clean; non-LACP modes lossy; chassis device-count drops. |
| `dhcp.md` | Junos two-stage `dhcp-local-server` + `address-assignment pool` -> RouterOS three-stage `/ip pool` + `/ip dhcp-server` + `/ip dhcp-server network`; static reservations + DHCP options lossy. |
| `vxlan_evpn_unsupported.md` | Junos source carries `vxlan_vnis` / `evpn_type5_routes`; RouterOS target codec lists VXLAN unsupported.  Drop with banner. |
| `apply_groups.md` | Junos's two-pass parse (GAP 8) flattens group content into the canonical tree; group structure (apply_groups + group_content) drops on RouterOS render.  Lossy by structure preservation only. |
| `routing_instances_vrf.md` | Junos `routing-instances` with RD + vrf-target -> RouterOS `/ip vrf`; mikrotik_routeros codec wire-up gap means cross-pair currently unsupported.  RD/RT live under BGP on RouterOS. |
| `firewall_unsupported.md` | Junos `firewall family inet filter` + `policy-options policy-statement` and RouterOS `/ip firewall filter` + `/ip firewall nat` are both Tier-3 unsupported on this cross-pair.  Operator hand-translation. |

Retrieved 2026-05-01.

See also: `../README.md` (citation cache layout).
